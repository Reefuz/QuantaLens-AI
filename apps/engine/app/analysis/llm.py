"""OpenAI-compatible chat client (Gemini by default) with retry, backoff and model fallback."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("quantalens.llm")
RETRYABLE = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """A failure with a message that is safe to show the user."""


class LLMNotConfigured(LLMError):
    pass


class LLMClient:
    # Quota is per API key, so a model that is rate limited stays skipped for a while across every run.
    _blocked_until: dict[str, float] = {}

    def __init__(self, settings: Settings | None = None, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 http: httpx.Client | None = None, timeout: float = 75.0) -> None:
        self.s = settings or get_settings()
        self.sleep = sleep
        self.clock = clock
        self.http = http or httpx.Client(timeout=timeout)

    @property
    def configured(self) -> bool:
        return self.s.ai_configured

    def _post(self, model: str, messages: list[dict], tools: list[dict] | None, tool_choice: Any) -> httpx.Response:
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        return self.http.post(
            self.s.ai_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {self.s.ai_provider_api_key.get_secret_value()}"}, json=body,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, tool_choice: Any = None,
             notify: Callable[[str], None] | None = None) -> tuple[dict[str, Any], str]:
        """Return (assistant message exactly as the provider sent it, model used).

        The raw message is returned so it can be sent back unchanged: Gemini attaches thought signatures to tool
        calls and rejects follow-up turns that drop them.
        """
        if not self.configured:
            raise LLMNotConfigured("The AI provider is not configured. Set AI_PROVIDER_API_KEY on the engine.")
        plan = [(self.s.ai_model, 3)]
        if self.s.ai_fallback_model and self.s.ai_fallback_model != self.s.ai_model:
            plan.append((self.s.ai_fallback_model, 2))
        now = self.clock()
        available = [p for p in plan if self._blocked_until.get(p[0], 0) <= now]
        if available and len(available) < len(plan):
            plan = available  # skip a model that was recently rate limited
        last = "The AI provider did not respond."
        for mi, (model, attempts) in enumerate(plan):
            for attempt in range(attempts):
                try:
                    resp = self._post(model, messages, tools, tool_choice)
                except (httpx.TimeoutException, httpx.TransportError):
                    last = "The AI provider timed out."
                    status = 0
                else:
                    status = resp.status_code
                    if resp.is_success:
                        msg = (resp.json().get("choices") or [{}])[0].get("message")
                        if msg:
                            return msg, model
                        last = "The AI provider returned an empty response."
                    elif status in (401, 403):
                        raise LLMError("The AI provider rejected the API key. Check AI_PROVIDER_API_KEY.")
                    elif status == 404 or status == 400 and "model" in resp.text[:300].lower():
                        last = "The configured AI model is not available."
                        break  # try the fallback model immediately
                    elif status in RETRYABLE:
                        last = "The AI provider is busy." if status != 429 else "The AI provider's rate limit was reached."
                    else:
                        logger.error("LLM request failed with status %s", status)
                        raise LLMError(f"The AI provider returned an error ({status}).")
                is_last_attempt = attempt == attempts - 1
                if not is_last_attempt:
                    delay = 2.0 * (2 ** attempt)
                    if status == 429:
                        try:
                            delay = min(20.0, max(delay, float(resp.headers.get("retry-after", delay))))
                        except (ValueError, UnboundLocalError):
                            pass
                    if notify:
                        notify(f"{last} Retrying in {delay:.0f}s.")
                    self.sleep(delay)
            if status in (429, 503) or status == 0:
                self._blocked_until[model] = self.clock() + (90 if status == 429 else 30)
            if mi < len(plan) - 1 and notify:
                notify(f"{last} Switching to the fallback model.")
        raise LLMError(f"{last} Please try again in a minute.")


def parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise tool calls: [{id, name, arguments(dict), parse_error}]."""
    calls = []
    for i, c in enumerate(message.get("tool_calls") or []):
        fn = c.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args, err = (json.loads(raw) if isinstance(raw, str) else dict(raw)), None
        except (ValueError, TypeError):
            args, err = {}, "The arguments were not valid JSON."
        calls.append({"id": c.get("id") or f"call_{i}", "name": fn.get("name", ""), "arguments": args, "parse_error": err})
    return calls
