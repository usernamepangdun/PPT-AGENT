import argparse
import os
import sys
import time
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError

from ai_client import AIClient
from config import PROVIDERS

load_dotenv()

VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high")


def _preview(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def _extract_responses_text(resp) -> str:
    text = getattr(resp, "output_text", None)
    if text:
        return text.strip()

    parts = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", "") in {"output_text", "text"}:
                value = getattr(content, "text", "")
                if value:
                    parts.append(value)
    return "\n".join(parts).strip()


def _extract_chat_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return str(content).strip() if content else ""

    parts = []
    for item in content:
        if isinstance(item, dict):
            value = item.get("text", "")
        else:
            value = getattr(item, "text", "")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts).strip()


def _exception_chain(exc: Exception) -> str:
    parts = []
    current = exc.__cause__ or exc.__context__
    seen = set()
    while current and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        parts.append(f"{type(current).__name__}: {text}" if text else type(current).__name__)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


def _format_exception(exc: Exception) -> str:
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None) or getattr(exc.response, "status_code", None)
        try:
            body = (exc.response.text or "").strip() if exc.response else ""
        except Exception:
            body = ""
        detail = f"{type(exc).__name__}: status={status}"
        if body:
            detail += f", body={_preview(body, 240)}"
        return detail

    if isinstance(exc, APIConnectionError):
        chain = _exception_chain(exc)
        if chain:
            return f"{type(exc).__name__}: {chain}"

    return f"{type(exc).__name__}: {exc}"


def probe_chat(client: AIClient, prompt: str) -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        resp = client.client.chat.completions.create(
            model=client.model,
            temperature=0,
            messages=[
                {"role": "system", "content": "你是接口连通性测试助手。请简短回答：CHAT_OK"},
                {"role": "user", "content": prompt},
            ],
        )
        content = _extract_chat_text(resp.choices[0].message.content or "")
        elapsed = time.perf_counter() - started
        return True, elapsed, _preview(content or "<empty>")
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return False, elapsed, _format_exception(exc)


def probe_responses(client: AIClient, prompt: str, reasoning_effort: str) -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        resp = client.client.responses.create(
            model=client.model,
            instructions="你是接口连通性测试助手。请简短回答：RESPONSES_OK",
            input=prompt,
            reasoning={"effort": reasoning_effort},
        )
        content = _extract_responses_text(resp)
        elapsed = time.perf_counter() - started
        return True, elapsed, _preview(content or "<empty>")
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return False, elapsed, _format_exception(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="验证当前 provider 的接口可用性")
    parser.add_argument("--provider", "-m", choices=["openai", "claude", "domestic"], default=None,
                        help="要测试的 provider，默认读取 .env DEFAULT_PROVIDER")
    parser.add_argument("--mode", choices=["chat", "responses", "both"], default="both",
                        help="要测试的接口模式")
    parser.add_argument("--prompt", default="请只返回 OK，用于验证接口可用性。",
                        help="测试 prompt")
    parser.add_argument("--reasoning-effort", choices=VALID_REASONING_EFFORTS,
                        default=os.getenv("OPENAI_REASONING_EFFORT", "high"),
                        help="responses 模式下使用的 reasoning effort")
    args = parser.parse_args()

    try:
        client = AIClient(args.provider)
    except Exception as exc:
        print(f"[FAIL] client init: {type(exc).__name__}: {exc}")
        return 2

    cfg = PROVIDERS[client.provider]
    print(f"Provider: {client.provider}")
    print(f"Model: {client.model}")
    print(f"Base URL: {cfg['base_url']}")
    print(f"Reasoning effort: {args.reasoning_effort}")
    print(f"Mode: {args.mode}")
    print("-" * 40)

    results = []
    if args.mode in {"chat", "both"}:
        ok, elapsed, detail = probe_chat(client, args.prompt)
        print(f"[{'PASS' if ok else 'FAIL'}] chat ({elapsed:.2f}s)")
        print(detail)
        print("-" * 40)
        results.append(ok)

    if args.mode in {"responses", "both"}:
        ok, elapsed, detail = probe_responses(client, args.prompt, args.reasoning_effort)
        print(f"[{'PASS' if ok else 'FAIL'}] responses ({elapsed:.2f}s)")
        print(detail)
        print("-" * 40)
        results.append(ok)

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
