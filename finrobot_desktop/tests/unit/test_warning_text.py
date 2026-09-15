"""Contract tests for the user-facing error/warning sanitizer.

``safe_error_text`` is THE single sanitization home (five per-module copies
once diverged on the empty-after-cleaning fallback — two echoed the raw text,
which leaks ``?apikey=…`` when an exception's str() is a bare URL). These
tests pin the consolidated contract so a future copy-paste can't reopen it.
"""

from __future__ import annotations

from finrobot.warning_text import humanize_warnings, safe_error_text


class _ProviderBoom(RuntimeError):
    pass


class TestHumanizeWarnings:
    def test_strips_httpx_url_tail_keeps_lead_text(self) -> None:
        out = humanize_warnings(
            [
                "Server error '500' for url 'https://fmp.example/api/v3/quote?apikey=SECRET'\n"
                "For more information check: https://developer.mozilla.org/..."
            ]
        )
        assert out == ["Server error '500'"]
        assert "SECRET" not in out[0]

    def test_bare_url_only_warning_is_dropped(self) -> None:
        assert humanize_warnings(["https://fmp.example/quote?apikey=SECRET"]) == []

    def test_plain_text_passes_through(self) -> None:
        assert humanize_warnings(["FMP rate limited"]) == ["FMP rate limited"]


class TestSafeErrorText:
    def test_url_only_exception_falls_back_to_type_name_never_raw(self) -> None:
        # The leak case: str(exc) is a bare URL with no lead prose. After the
        # URL strip nothing survives — the ONLY safe fallback is the type name.
        exc = _ProviderBoom("https://fmp.example/api/v3/quote?apikey=SECRET")
        out = safe_error_text(exc)
        assert out == "_ProviderBoom"
        assert "SECRET" not in out
        assert "apikey" not in out

    def test_url_only_string_falls_back_to_placeholder(self) -> None:
        out = safe_error_text("https://fmp.example/api/v3/quote?apikey=SECRET")
        assert out == "unspecified error"
        assert "SECRET" not in out

    def test_lead_text_survives_with_url_stripped(self) -> None:
        exc = _ProviderBoom(
            "Client error '429 Too Many Requests' for url 'https://fmp.example/x?apikey=SECRET'"
        )
        out = safe_error_text(exc)
        assert "429" in out
        assert "SECRET" not in out

    def test_empty_message_uses_type_name(self) -> None:
        assert safe_error_text(_ProviderBoom("")) == "_ProviderBoom"

    def test_empty_string_input_uses_placeholder(self) -> None:
        assert safe_error_text("   ") == "unspecified error"

    def test_limit_truncates(self) -> None:
        assert safe_error_text(_ProviderBoom("x" * 900), limit=500) == "x" * 500

    def test_no_limit_keeps_full_text(self) -> None:
        assert safe_error_text(_ProviderBoom("y" * 900)) == "y" * 900
