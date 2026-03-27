import base64
import mimetypes
import os
from pathlib import Path
from openai import OpenAI
from config import PROVIDERS, DEFAULT_PROVIDER

VALID_REASONING_EFFORTS = {"minimal", "low", "medium", "high"}


def _get_field(data, key, default=None):
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _extract_responses_text(data) -> str:
    text = _get_field(data, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts = []
    for item in _get_field(data, "output", []) or []:
        if _get_field(item, "type", "") != "message":
            continue
        for content in _get_field(item, "content", []) or []:
            if _get_field(content, "type", "") not in {"output_text", "text"}:
                continue
            value = _get_field(content, "text", "")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    if parts:
        return "\n".join(parts).strip()

    if hasattr(data, "model_dump"):
        return _extract_responses_text(data.model_dump())
    return ""


def _extract_chat_text(data) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        if isinstance(data.get("content"), str) and data["content"].strip():
            return data["content"].strip()
        if isinstance(data.get("text"), str) and data["text"].strip():
            return data["text"].strip()
        data = data.get("content", data)
    if not isinstance(data, list):
        return str(data).strip() if data else ""

    parts = []
    for item in data:
        if isinstance(item, dict):
            value = item.get("text", "")
            if not value and isinstance(item.get("content"), str):
                value = item.get("content", "")
        else:
            value = getattr(item, "text", "") or getattr(item, "content", "")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts).strip()


def _stream_chat_text(stream) -> str:
    parts = []
    for chunk in stream:
        for choice in getattr(chunk, "choices", []) or []:
            delta = getattr(choice, "delta", None)
            if not delta:
                continue
            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                parts.append(content)
                continue
            if isinstance(content, list):
                for item in content:
                    value = _get_field(item, "text", "")
                    if isinstance(value, str) and value:
                        parts.append(value)
    return "".join(parts).strip()


def _stream_responses_text(stream) -> str:
    parts = []
    for event in stream:
        event_type = _get_field(event, "type", "")
        if event_type in {"response.output_text.delta", "response.output_text.annotation.added"}:
            delta = _get_field(event, "delta", "") or _get_field(event, "text", "")
            if isinstance(delta, str) and delta:
                parts.append(delta)
        elif event_type == "response.completed":
            response = _get_field(event, "response", None)
            text = _extract_responses_text(response)
            if text:
                return text
    return "".join(parts).strip()


def _file_to_data_uri(image_path: str | Path) -> str:
    path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


def _normalize_reasoning_effort(reasoning_effort: str | None) -> str:
    if not reasoning_effort:
        return "high"
    if reasoning_effort not in VALID_REASONING_EFFORTS:
        options = ", ".join(sorted(VALID_REASONING_EFFORTS))
        raise ValueError(f"Invalid reasoning_effort: {reasoning_effort}. Expected one of: {options}")
    return reasoning_effort


def _should_fallback_to_chat(exc: Exception) -> bool:
    text = str(exc).lower()
    fallback_signals = [
        "responses api 未返回可解析文本",
        "request was blocked",
        "permissiondenied",
        "524",
        "502",
        "timeout",
        "html>",
        "cf-wrapper",
        "bad gateway",
        "connection error",
        "remoteprotocolerror",
        "server disconnected without sending a response",
        "incomplete chunked read",
    ]
    return any(signal in text for signal in fallback_signals)


def _should_fallback_to_responses(exc: Exception) -> bool:
    text = str(exc).lower()
    fallback_signals = [
        "chat completions api 未返回可解析文本",
        "request was blocked",
        "permissiondenied",
        "524",
        "502",
        "timeout",
        "html>",
        "cf-wrapper",
        "bad gateway",
        "connection error",
        "remoteprotocolerror",
        "server disconnected without sending a response",
        "incomplete chunked read",
    ]
    return any(signal in text for signal in fallback_signals)


def _should_retry_request(exc: Exception) -> bool:
    text = str(exc).lower()
    signals = [
        "connection error",
        "remoteprotocolerror",
        "server disconnected without sending a response",
        "incomplete chunked read",
        "timeout",
        "timed out",
        "bad gateway",
        "502",
        "524",
    ]
    return any(signal in text for signal in signals)


def _call_with_one_retry(func):
    last_exc = None
    for attempt in range(2):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _should_retry_request(exc):
                continue
            raise
    raise last_exc


class AIClient:
    def __init__(self, provider: str | None = None):
        name = provider or DEFAULT_PROVIDER
        cfg = PROVIDERS.get(name)
        if not cfg:
            raise ValueError(f"Unknown provider: {name}")
        if not cfg["api_key"]:
            raise ValueError(f"API key not set for provider: {name}")
        self.model = cfg["model"]
        self.reasoning_effort = _normalize_reasoning_effort(cfg.get("reasoning_effort"))
        self.provider = name
        extra = {}
        if name == "claude":
            extra["default_headers"] = {"anthropic-version": "2023-06-01"}
        # 非官方 OpenAI 接口不走代理
        import httpx
        no_proxy_hosts = os.getenv("NO_PROXY", "")
        proxies = None
        if os.getenv("HTTPS_PROXY") and not any(
            h in cfg["base_url"] for h in no_proxy_hosts.split(",")
        ):
            proxies = os.getenv("HTTPS_PROXY")
        timeout = httpx.Timeout(connect=30, read=300, write=30, pool=30)
        http_client = httpx.Client(proxy=proxies, timeout=timeout) if proxies else httpx.Client(timeout=timeout)
        self.client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            http_client=http_client,
            **extra,
        )

    def responses(self, instructions: str, user: str, reasoning_effort: str | None = None,
                  tools: list | None = None, allow_chat_fallback: bool = True) -> str:
        kwargs = {
            "model": self.model,
            "instructions": instructions,
            "input": user,
            "reasoning": {"effort": _normalize_reasoning_effort(reasoning_effort or self.reasoning_effort)},
        }
        if tools:
            kwargs["tools"] = tools
        try:
            if tools:
                resp = _call_with_one_retry(lambda: self.client.responses.create(**kwargs))
                text = _extract_responses_text(resp)
            else:
                try:
                    def _stream_call():
                        with self.client.responses.stream(**kwargs) as stream:
                            return _stream_responses_text(stream)
                    text = _call_with_one_retry(_stream_call)
                except Exception:
                    resp = _call_with_one_retry(lambda: self.client.responses.create(**kwargs))
                    text = _extract_responses_text(resp)
            if text:
                return text
            raise RuntimeError("Responses API 未返回可解析文本")
        except Exception as e:
            if allow_chat_fallback and not tools and _should_fallback_to_chat(e):
                try:
                    return self.chat(instructions, user, temperature=0.3, allow_responses_fallback=False)
                except Exception:
                    pass
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"[{self.provider}/{self.model}] API调用失败: {e}") from e

    def review_image(self, instructions: str, user: str, image_path: str | Path,
                     reasoning_effort: str | None = None) -> str:
        image_uri = _file_to_data_uri(image_path)
        kwargs = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user},
                        {"type": "input_image", "image_url": image_uri},
                    ],
                }
            ],
        }
        if instructions:
            kwargs["instructions"] = instructions
        if self.provider == "openai":
            kwargs["reasoning"] = {"effort": _normalize_reasoning_effort(reasoning_effort or self.reasoning_effort)}
        try:
            resp = _call_with_one_retry(lambda: self.client.responses.create(**kwargs))
            text = _extract_responses_text(resp)
            if text:
                return text
            raise RuntimeError("Review API 未返回可解析文本")
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"[{self.provider}/{self.model}] 截图审查失败: {e}") from e

    def chat(self, system: str, user: str, temperature: float = 0.7,
             allow_responses_fallback: bool = True) -> str:
        try:
            try:
                def _stream_call():
                    with self.client.chat.completions.stream(
                        model=self.model,
                        temperature=temperature,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    ) as stream:
                        return _stream_chat_text(stream)
                text = _call_with_one_retry(_stream_call)
            except Exception:
                resp = _call_with_one_retry(lambda: self.client.chat.completions.create(
                    model=self.model,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                ))
                text = _extract_chat_text(resp.choices[0].message.content)
            if text:
                return text
            raise RuntimeError("Chat Completions API 未返回可解析文本")
        except Exception as e:
            if allow_responses_fallback and _should_fallback_to_responses(e):
                try:
                    return self.responses(system, user, allow_chat_fallback=False)
                except Exception:
                    pass
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"[{self.provider}/{self.model}] API调用失败: {e}") from e
