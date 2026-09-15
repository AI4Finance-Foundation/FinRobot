"""Read-only live basket probe for report-level numeric audit calibration.

The output is evidence for gate calibration, not the gate itself. It compares
independent provider payloads and SEC XBRL where available, then prints field
diff distributions that can later become calibrated severity bands.

Usage:
    uv run python scripts/probe_numeric_audit_basket.py
    uv run python scripts/probe_numeric_audit_basket.py AAPL MSFT TSLA --json-out /tmp/basket.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from finrobot.config import get_settings
from finrobot.engine.data.factory import build_data_layer
from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.normalize import normalize_financials, normalize_price
from finrobot.engine.data.normalize.contracts import NormalizedFinancials, NormalizedPrice
from finrobot.engine.data.types import DataType
from finrobot.engine.data.validator import cross_validate, market_cap_consistency
from finrobot.paths import SETTINGS_JSON
from finrobot.routes.settings import load_non_secret_settings
from finrobot.secret_store import create_secret_store
from finrobot.server import hydrate_settings_from_secrets

DEFAULT_BASKET = ("AAPL", "MSFT", "NVDA", "TSLA", "TSM", "SAP", "KO", "JPM", "F", "MU")
PROVIDER_A = "fmp"
PROVIDER_B = "yfinance"


@dataclass(frozen=True)
class FieldDiff:
    ticker: str
    field: str
    source_provider: str
    source_value: float | None
    benchmark_provider: str
    benchmark_value: float | None
    rel_diff: float | None
    abs_diff: float | None
    source_as_of: str | None = None
    benchmark_as_of: str | None = None
    source_currency: str | None = None
    benchmark_currency: str | None = None
    source_period: str | None = None
    benchmark_period: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class TickerProbe:
    ticker: str
    errors: list[str]
    warnings: list[str]
    price_as_of_days: dict[str, int | None]
    diffs: list[FieldDiff]


def _provider_by_name(providers: list[DataProvider], name: str) -> DataProvider | None:
    for provider in providers:
        if provider.name == name:
            return provider
    return None


async def _fetch(
    provider: DataProvider | None,
    ticker: str,
    data_type: DataType,
) -> DataResult | None:
    if provider is None or data_type not in provider.capabilities():
        return None
    return await provider.fetch(ticker, data_type)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _rel_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def _abs_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(a - b)


def _dt_text(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _days_since(value: datetime | None) -> int | None:
    if value is None:
        return None
    now = datetime.now(tz=timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, (now.date() - value.date()).days)


def _price_field(
    ticker: str,
    field: str,
    a: NormalizedPrice | None,
    b: NormalizedPrice | None,
    getter: str,
) -> FieldDiff:
    av = _num(
        getattr(a, getter)() if getter.startswith("fifty") and a else getattr(a, getter, None)
    )
    bv = _num(
        getattr(b, getter)() if getter.startswith("fifty") and b else getattr(b, getter, None)
    )
    return FieldDiff(
        ticker=ticker,
        field=field,
        source_provider=a.provenance.provider if a else PROVIDER_A,
        source_value=av,
        benchmark_provider=b.provenance.provider if b else PROVIDER_B,
        benchmark_value=bv,
        rel_diff=_rel_diff(av, bv),
        abs_diff=_abs_diff(av, bv),
        source_as_of=_dt_text(a.provenance.as_of) if a else None,
        benchmark_as_of=_dt_text(b.provenance.as_of) if b else None,
        source_currency=a.quote_currency if a else None,
        benchmark_currency=b.quote_currency if b else None,
    )


def _financial_field(
    ticker: str,
    field: str,
    a: NormalizedFinancials | None,
    b: NormalizedFinancials | None,
    *,
    note: str | None = None,
) -> FieldDiff:
    av = _num(getattr(a, field, None))
    bv = _num(getattr(b, field, None))
    return FieldDiff(
        ticker=ticker,
        field=field,
        source_provider=a.provenance.provider if a else PROVIDER_A,
        source_value=av,
        benchmark_provider=b.provenance.provider if b else PROVIDER_B,
        benchmark_value=bv,
        rel_diff=_rel_diff(av, bv),
        abs_diff=_abs_diff(av, bv),
        source_as_of=_dt_text(a.as_of) if a else None,
        benchmark_as_of=_dt_text(b.as_of) if b else None,
        source_currency=a.reporting_currency if a else None,
        benchmark_currency=b.reporting_currency if b else None,
        source_period=a.period_basis.upper() if a else None,
        benchmark_period=b.period_basis.upper() if b else None,
        note=note,
    )


def _sec_value(payload: dict[str, Any], key: str) -> tuple[float | None, str | None]:
    raw = payload.get(key)
    if isinstance(raw, dict):
        return _num(raw.get("value")), str(raw.get("period_end")) if raw.get("period_end") else None
    return None, None


def _sec_diff(
    ticker: str,
    field: str,
    fin: NormalizedFinancials | None,
    sec_result: DataResult | None,
    sec_key: str,
) -> FieldDiff:
    source_value = _num(getattr(fin, field, None))
    benchmark_value, benchmark_as_of = (
        _sec_value(sec_result.data, sec_key) if sec_result is not None else (None, None)
    )
    return FieldDiff(
        ticker=ticker,
        field=f"{field}_vs_sec",
        source_provider=fin.provenance.provider if fin else PROVIDER_A,
        source_value=source_value,
        benchmark_provider=sec_result.provider if sec_result else "edgar_tools",
        benchmark_value=benchmark_value,
        rel_diff=_rel_diff(source_value, benchmark_value),
        abs_diff=_abs_diff(source_value, benchmark_value),
        source_as_of=_dt_text(fin.as_of) if fin else None,
        benchmark_as_of=benchmark_as_of,
        source_currency=fin.reporting_currency if fin else None,
        benchmark_currency="USD",
        source_period=fin.period_basis.upper() if fin else None,
        benchmark_period="TTM",
        note="SEC XBRL is compared only when edgartools returns a USD TTM fact.",
    )


async def probe_ticker(
    ticker: str,
    fmp: DataProvider | None,
    yf: DataProvider | None,
    sec: DataProvider | None,
    *,
    provider_timeout_s: float,
) -> TickerProbe:
    errors: list[str] = []
    warnings: list[str] = []

    async def safe_fetch(provider: DataProvider | None, data_type: DataType) -> DataResult | None:
        try:
            return await asyncio.wait_for(
                _fetch(provider, ticker, data_type),
                timeout=provider_timeout_s,
            )
        except TimeoutError:
            errors.append(
                f"{provider.name if provider else 'missing'} {data_type}: "
                f"timeout after {provider_timeout_s:.0f}s"
            )
            return None
        except ProviderError as exc:
            errors.append(f"{provider.name if provider else 'missing'} {data_type}: {exc}")
            return None

    # Fetches are deliberately sequential per ticker. Yahoo rate limits are part
    # of the empirical evidence; the probe must not create artificial failures by
    # firing multiple heavyweight yfinance calls at once.
    fmp_price_raw = await safe_fetch(fmp, DataType.PRICE)
    fmp_fin_raw = await safe_fetch(fmp, DataType.FINANCIALS)
    yf_price_raw = await safe_fetch(yf, DataType.PRICE)
    yf_fin_raw = await safe_fetch(yf, DataType.FINANCIALS)
    sec_raw = await safe_fetch(sec, DataType.XBRL_FACTS)

    fmp_price = normalize_price(fmp_price_raw) if fmp_price_raw is not None else None
    yf_price = normalize_price(yf_price_raw) if yf_price_raw is not None else None
    fmp_fin = normalize_financials(fmp_fin_raw) if fmp_fin_raw is not None else None
    yf_fin = normalize_financials(yf_fin_raw) if yf_fin_raw is not None else None

    if fmp_fin_raw is not None and yf_fin_raw is not None:
        warnings.extend(cross_validate(fmp_fin_raw, yf_fin_raw))
        warnings.extend(market_cap_consistency(fmp_fin_raw, yf_fin_raw))
    for result in (fmp_price_raw, yf_price_raw, fmp_fin_raw, yf_fin_raw, sec_raw):
        if result is not None:
            warnings.extend(result.warnings)

    diffs = [
        _price_field(ticker, "current_price", fmp_price, yf_price, "current_price"),
        _price_field(ticker, "52w_high", fmp_price, yf_price, "fifty_two_week_high"),
        _price_field(ticker, "52w_low", fmp_price, yf_price, "fifty_two_week_low"),
    ]
    for field in (
        "market_cap",
        "shares_outstanding",
        "revenue",
        "net_income",
        "total_debt",
        "total_cash",
        "pe_ratio",
        "gross_margin",
        "operating_margin",
    ):
        note = None
        if field == "shares_outstanding":
            note = "Shares must pass lineage checks before serving as a benchmark."
        if field in ("revenue", "net_income"):
            note = "Provider-vs-provider comparison can mix TTM/FY when sources differ."
        diffs.append(_financial_field(ticker, field, fmp_fin, yf_fin, note=note))
    diffs.extend(
        [
            _sec_diff(ticker, "revenue", fmp_fin, sec_raw, "ttm_revenue"),
            _sec_diff(ticker, "net_income", fmp_fin, sec_raw, "ttm_net_income"),
        ]
    )

    return TickerProbe(
        ticker=ticker,
        errors=errors,
        warnings=list(dict.fromkeys(warnings)),
        price_as_of_days={
            "fmp": _days_since(fmp_price.provenance.as_of) if fmp_price else None,
            "yfinance": _days_since(yf_price.provenance.as_of) if yf_price else None,
        },
        diffs=diffs,
    )


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "median": None, "p90": None, "max": None}
    ordered = sorted(values)
    p90_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.9)))
    return {
        "n": len(values),
        "median": statistics.median(ordered),
        "p90": ordered[p90_index],
        "max": max(ordered),
    }


def summarize(probes: list[TickerProbe]) -> dict[str, Any]:
    by_field: dict[str, list[float]] = {}
    missing: dict[str, int] = {}
    for probe in probes:
        for diff in probe.diffs:
            if diff.rel_diff is None:
                missing[diff.field] = missing.get(diff.field, 0) + 1
                continue
            by_field.setdefault(diff.field, []).append(diff.rel_diff)
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "basket": [p.ticker for p in probes],
        "relative_diff_distribution": {
            field: _distribution(values) for field, values in sorted(by_field.items())
        },
        "missing_comparisons": dict(sorted(missing.items())),
    }


def print_report(probes: list[TickerProbe], summary: dict[str, Any]) -> None:
    print("\n=== Numeric Audit Basket Probe ===")
    print(f"generated_at: {summary['generated_at']}")
    print("basket:", ", ".join(summary["basket"]))
    print("\n-- Relative Diff Distribution --")
    for field, dist in summary["relative_diff_distribution"].items():
        median = "-" if dist["median"] is None else f"{dist['median']:.4%}"
        p90 = "-" if dist["p90"] is None else f"{dist['p90']:.4%}"
        max_v = "-" if dist["max"] is None else f"{dist['max']:.4%}"
        print(f"{field:22s} n={dist['n']:2d} median={median:>9s} p90={p90:>9s} max={max_v:>9s}")
    if summary["missing_comparisons"]:
        print("\n-- Missing Comparisons --")
        for field, count in summary["missing_comparisons"].items():
            print(f"{field:22s} missing={count}")

    print("\n-- Per Ticker Exceptions / Warnings --")
    for probe in probes:
        freshness = ", ".join(
            f"{provider}_price_as_of_days={days}"
            for provider, days in probe.price_as_of_days.items()
        )
        print(f"{probe.ticker:5s} {freshness}")
        for err in probe.errors:
            print(f"  ERROR: {err}")
        for warning in probe.warnings[:6]:
            print(f"  WARN: {warning}")
        if len(probe.warnings) > 6:
            print(f"  WARN: ... {len(probe.warnings) - 6} more")

    print("\n-- Largest Field Diffs --")
    ranked = sorted(
        (d for p in probes for d in p.diffs if d.rel_diff is not None),
        key=lambda d: d.rel_diff or 0.0,
        reverse=True,
    )[:25]
    for diff in ranked:
        print(
            f"{diff.ticker:5s} {diff.field:22s} {diff.rel_diff:9.4%} "
            f"{diff.source_provider}={diff.source_value} "
            f"{diff.benchmark_provider}={diff.benchmark_value} "
            f"as_of={diff.source_as_of}/{diff.benchmark_as_of}"
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", default=list(DEFAULT_BASKET))
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Ticker-level concurrency. Default 1 keeps provider rate-limit evidence clean.",
    )
    parser.add_argument(
        "--provider-timeout",
        type=float,
        default=45.0,
        help="Seconds allowed for one provider fetch before recording a timeout.",
    )
    args = parser.parse_args()

    settings = get_settings(**load_non_secret_settings(SETTINGS_JSON))
    store, _ = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, store)
    data_layer = build_data_layer(settings)
    try:
        providers = data_layer._providers
        fmp = _provider_by_name(providers, PROVIDER_A)
        yf = _provider_by_name(providers, PROVIDER_B)
        sec = _provider_by_name(providers, "edgar_tools")
        semaphore = asyncio.Semaphore(max(1, args.concurrency))

        async def bounded(ticker: str) -> TickerProbe:
            async with semaphore:
                return await probe_ticker(
                    ticker.upper(),
                    fmp,
                    yf,
                    sec,
                    provider_timeout_s=args.provider_timeout,
                )

        probes = await asyncio.gather(*(bounded(t) for t in args.tickers))
        summary = summarize(list(probes))
        payload = {"summary": summary, "probes": [asdict(p) for p in probes]}
        print_report(list(probes), summary)
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"\njson_out: {args.json_out}")
        return 0
    finally:
        # Non-server entrypoint: join the aiosqlite workers + checkpoint WAL so the
        # process exits cleanly instead of hanging on "Event loop is closed" (2026-06-24).
        from finrobot.engine.data.factory import shutdown_data_layer

        await shutdown_data_layer(data_layer)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
