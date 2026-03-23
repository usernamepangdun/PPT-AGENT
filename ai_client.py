import os
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
    if not isinstance(data, list):
        return str(data).strip() if data else ""

    parts = []
    for item in data:
        value = _get_field(item, "text", "")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts).strip()


def _normalize_reasoning_effort(reasoning_effort: str | None) -> str:
    if not reasoning_effort:
        return "high"
    if reasoning_effort not in VALID_REASONING_EFFORTS:
        options = ", ".join(sorted(VALID_REASONING_EFFORTS))
        raise ValueError(f"Invalid reasoning_effort: {reasoning_effort}. Expected one of: {options}")
    return reasoning_effort


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
                  tools: list | None = None) -> str:
        try:
            kwargs = {
                "model": self.model,
                "instructions": instructions,
                "input": user,
                "reasoning": {"effort": _normalize_reasoning_effort(reasoning_effort or self.reasoning_effort)},
            }
            if tools:
                kwargs["tools"] = tools
            resp = self.client.responses.create(**kwargs)
            text = _extract_responses_text(resp)
            if text:
                return text
            raise RuntimeError("Responses API 未返回可解析文本")
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"[{self.provider}/{self.model}] API调用失败: {e}") from e

    def chat(self, system: str, user: str, temperature: float = 0.7) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            text = _extract_chat_text(resp.choices[0].message.content)
            if text:
                return text
            raise RuntimeError("Chat Completions API 未返回可解析文本")
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"[{self.provider}/{self.model}] API调用失败: {e}") from e
