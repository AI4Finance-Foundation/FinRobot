"""Tiny live LLM probe shared by Settings test-provider and the run-spend gates.

One place owns "make the cheapest possible real call and classify the failure":

- ``POST /api/settings/test-provider`` — config-time ✗ with a reason the UI
  localizes (the auto-test fired after the user saves a key).
- ``POST /api/runs`` — submit-time gate. The
  ``is_model_configured`` guard only proves a key EXISTS; a key that cannot
  authenticate used to be accepted, burn minutes of data collection, and only
  fail inside the first agent LLM step. ``LlmProbeGate`` rejects that run at
  submit time with the same classified reason the Settings ✗ shows.
"""

from __future__ import annotations

import asyncio

from finrobot.config import FinRobotSettings


def classify_provider_error(exc: BaseException) -> tuple[str, str]:
    """Map a provider call failure to (code, raw English detail).

    Stable ``code`` vocabulary the UI localizes: ok | no_key | no_model | auth |
    connect | not_found | http | unknown.
    """
    import httpx
    from pydantic_ai.exceptions import ModelHTTPError

    detail = str(exc)[:200] or type(exc).__name__
    if isinstance(exc, ModelHTTPError):
        if exc.status_code in (401, 403):
            return "auth", detail
        if exc.status_code == 404:
            return "not_found", detail
        return "http", detail
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "connect", detail
    low = str(exc).lower()
    if any(s in low for s in ("api key", "api_key", "unauthorized", "authentication")):
        return "auth", detail
    if any(s in low for s in ("not found", "does not exist", "no such model")):
        return "not_found", detail
    return "unknown", detail


async def probe_model(
    settings: FinRobotSettings, provider_id: str, model_id: str
) -> tuple[bool, str, str]:
    """One minimal live LLM call against the saved config; returns (ok, code, detail)."""
    from pydantic_ai.direct import model_request
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    try:
        model = settings.create_model(f"{provider_id}:{model_id}")
        await model_request(
            model,
            [ModelRequest(parts=[UserPromptPart(content="ping")])],
            model_settings={"max_tokens": 8},
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise  # never swallow control-flow / shutdown signals (red-line N2)
    except BaseException as exc:  # noqa: BLE001 — classify any provider failure for the UI
        code, detail = classify_provider_error(exc)
        return False, code, detail
    return True, "ok", ""


class LlmProbeGate:
    """Submit-time LLM reachability gate with a success-only fingerprint cache.

    Fingerprint = (model_name, provider key). A successful probe for a config is
    remembered for the process lifetime, so steady-state submits cost nothing;
    changing the key or model produces a new fingerprint and re-probes. Failures
    are deliberately NOT cached — a transient network error must not condemn a
    valid key until the next settings change.
    """

    def __init__(self) -> None:
        self._verified: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    @staticmethod
    def _fingerprint(settings: FinRobotSettings) -> tuple[str, str]:
        name = settings.model_name.strip()
        provider_id = name.partition(":")[0]
        return (name, settings.provider_key(provider_id) or "")

    def mark_verified(self, settings: FinRobotSettings, provider_id: str, model_id: str) -> None:
        """Seed the cache from an external successful probe (Settings auto-test).

        Only counts when the tested (provider, model) IS the configured
        ``model_name`` — testing a provider you are editing but have not
        selected must not green-light runs on the selected one.
        """
        if f"{provider_id}:{model_id}" == settings.model_name.strip():
            self._verified.add(self._fingerprint(settings))

    async def ensure(self, settings: FinRobotSettings) -> tuple[bool, str, str]:
        """Probe the configured model once per fingerprint; (ok, code, detail)."""
        name = settings.model_name.strip()
        provider_id, _, model_id = name.partition(":")
        # Mirror validate_runtime_config's test semantics: bare "test" is the
        # built-in harness provider with NO registry entry, and any registered
        # provider may declare kind="test" — neither makes live calls.
        if provider_id == "test":
            return True, "ok", ""
        cfg = settings.provider_by_id(provider_id)
        if cfg is None:
            return False, "no_model", f"Unknown provider '{provider_id}'."
        if cfg.kind == "test":
            return True, "ok", ""
        fingerprint = self._fingerprint(settings)
        if fingerprint in self._verified:
            return True, "ok", ""
        async with self._lock:
            if fingerprint in self._verified:
                return True, "ok", ""
            ok, code, detail = await probe_model(settings, provider_id, model_id)
            if ok:
                self._verified.add(fingerprint)
            return ok, code, detail
