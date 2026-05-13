from __future__ import annotations

import json
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Iterator, List, Optional

from langchain_openai import ChatOpenAI

from app.config import get_settings


def selected_provider() -> str:
    return get_settings().model_provider.strip().lower()


@lru_cache
def get_deepseek_chat() -> Optional[ChatOpenAI]:
    settings = get_settings()
    if selected_provider() != "deepseek" or not settings.deepseek_api_key:
        return None

    return ChatOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        temperature=settings.deepseek_temperature,
        streaming=True,
    )


def is_ark_enabled() -> bool:
    settings = get_settings()
    return selected_provider() == "ark" and bool(settings.ark_api_key)


def invoke_text(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Call the configured LLM and return full text. Returns None when no provider is configured."""
    deepseek = get_deepseek_chat()
    if deepseek is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = deepseek.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        return str(response.content).strip()

    if is_ark_enabled():
        return _ark_invoke(system_prompt, user_prompt)

    return None


def stream_text(system_prompt: str, user_prompt: str) -> Iterator[str]:
    """Stream text from providers that expose streaming. Currently used for Ark chat."""
    if is_ark_enabled():
        yield from _ark_stream(system_prompt, user_prompt)
        return

    full_text = invoke_text(system_prompt, user_prompt)
    if full_text:
        yield full_text


def _ark_payload(system_prompt: str, user_prompt: str, stream: bool, use_web_search: bool = True) -> dict:
    settings = get_settings()
    input_messages = []
    if system_prompt.strip():
        input_messages.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            }
        )
    input_messages.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": user_prompt}],
        }
    )

    payload = {
        "model": settings.ark_model,
        "stream": stream,
        "temperature": settings.ark_temperature,
        "input": input_messages,
    }
    if settings.ark_enable_web_search and use_web_search:
        payload["tools"] = [
            {
                "type": "web_search",
                "max_keyword": settings.ark_web_search_max_keyword,
            }
        ]
    return payload


def _ark_request(payload: dict, timeout: int = 120) -> urllib.request.Request:
    settings = get_settings()
    return urllib.request.Request(
        settings.ark_base_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.ark_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if payload.get("stream") else "application/json",
        },
        method="POST",
    )


def _ark_invoke(system_prompt: str, user_prompt: str) -> str:
    settings = get_settings()
    payload = _ark_payload(system_prompt, user_prompt, stream=False)
    try:
        with urllib.request.urlopen(_ark_request(payload), timeout=settings.ark_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if _should_retry_without_web_search(payload, body):
            fallback_payload = _ark_payload(system_prompt, user_prompt, stream=False, use_web_search=False)
            with urllib.request.urlopen(_ark_request(fallback_payload), timeout=settings.ark_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            return _extract_response_text(data).strip()
        raise RuntimeError(f"Ark request failed: HTTP {exc.code} {body}") from exc
    return _extract_response_text(data).strip()


def _ark_stream(system_prompt: str, user_prompt: str) -> Iterator[str]:
    settings = get_settings()
    payload = _ark_payload(system_prompt, user_prompt, stream=True)
    try:
        yield from _read_ark_stream(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if _should_retry_without_web_search(payload, body):
            yield from _read_ark_stream(_ark_payload(system_prompt, user_prompt, stream=True, use_web_search=False))
            return
        raise RuntimeError(f"Ark stream failed: HTTP {exc.code} {body}") from exc


def _read_ark_stream(payload: dict) -> Iterator[str]:
    settings = get_settings()
    with urllib.request.urlopen(_ark_request(payload), timeout=settings.ark_timeout_seconds) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            data_text = line[5:].strip()
            if data_text == "[DONE]":
                break
            try:
                event = json.loads(data_text)
            except json.JSONDecodeError:
                continue
            chunk = _extract_stream_delta(event)
            if chunk:
                yield chunk


def _should_retry_without_web_search(payload: dict, response_body: str) -> bool:
    return bool(payload.get("tools")) and (
        "ToolNotOpen" in response_body
        or "web search" in response_body.lower()
        or "content_plugin" in response_body.lower()
    )


def _extract_stream_delta(event: dict) -> str:
    event_type = str(event.get("type") or "")
    if event_type and "delta" not in event_type:
        return ""

    for key in ("delta", "text", "output_text"):
        value = event.get(key)
        if isinstance(value, str):
            return value

    item = event.get("item") or event.get("response") or {}
    if isinstance(item, dict):
        text = _extract_response_text(item)
        if text:
            return text

    content = event.get("content")
    if isinstance(content, list):
        return _extract_content_text(content)
    return ""


def _extract_response_text(data: dict) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output = data.get("output")
    if isinstance(output, list):
        pieces: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                pieces.append(_extract_content_text(content))
        return "".join(pieces)

    choices = data.get("choices")
    if isinstance(choices, list):
        pieces = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                pieces.append(message["content"])
        return "".join(pieces)

    return ""


def _extract_content_text(content: list) -> str:
    pieces: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            pieces.append(text)
            continue
        if block.get("type") in {"output_text", "input_text"} and isinstance(block.get("content"), str):
            pieces.append(block["content"])
    return "".join(pieces)
