from __future__ import annotations

from pydantic import BaseModel, Field

from finrobot.warning_text import humanize_warnings


def _append_unique(target: list[str], items: list[str]) -> None:
    for item in items:
        if item not in target:
            target.append(item)


def _demote_step_headings(text: str) -> str:
    """Re-level a step output's own markdown headings under the report scaffold.

    ``format_summary`` nests every step under ``# FinRobot Analysis Report`` /
    ``## {Step}``, but step outputs arrive with their own top-level ``# …``
    headings — concatenated verbatim the document carried several competing
    H1s and bare ``###`` marker lines (external review read that structure as
    a pipeline defect). Demote in-step ATX headings two levels (capped at
    ``######``) so the hierarchy nests, and drop marker-only heading lines
    (decoration, never content). Fenced code blocks are left untouched.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence:
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 6:
                rest = stripped[hashes:]
                if not rest.strip():
                    continue  # bare '###' marker line — decoration, drop
                if rest.startswith(" "):
                    out.append("#" * min(6, hashes + 2) + rest)
                    continue
        out.append(line)
    return "\n".join(out)


class PipelineResult(BaseModel):
    steps: dict[str, str]
    structured_data: dict[str, object] = Field(default_factory=dict)
    failed_validations: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifact_id: str | None = Field(
        default=None,
        description="Set by Pipeline.execute() after artifact is persisted.",
    )

    def get_data(self, step_name: str) -> object | None:
        """Get structured data from a previous step. Returns None if not found."""
        return self.structured_data.get(step_name)

    def collect_warnings(self) -> list[str]:
        """The authoritative machine-readable warning haul for this run.

        Includes run-level degrades (``warnings``), steps that degraded after
        exhausting their retries (``failed_validations``) and every structured
        object's own ``warnings`` — deduped, order-preserving. Both the artifact
        builder and the /runs detail endpoint route through this so a
        half-degraded run reads IDENTICALLY in both rendering surfaces. (The
        /runs view previously collected only structured-object warnings, so a
        DCF degrade or a failed-validation line showed in the artifact but made
        the run look clean.)
        """
        warnings: list[str] = []
        _append_unique(warnings, humanize_warnings([str(w) for w in self.warnings]))
        for fv in self.failed_validations:
            line = f"Step {fv.get('step', '?')} degraded (validation failed): {fv.get('error', '')}"
            _append_unique(warnings, humanize_warnings([line]))
        for val in self.structured_data.values():
            val_warnings = getattr(val, "warnings", None)
            if val_warnings:
                _append_unique(warnings, humanize_warnings([str(w) for w in val_warnings]))
        return warnings

    @property
    def has_failures(self) -> bool:
        return len(self.failed_validations) > 0

    def format_summary(self) -> str:
        """Concatenate all step outputs into a readable Markdown report."""
        if not self.steps:
            return ""
        parts = ["# FinRobot Analysis Report\n"]
        if self.failed_validations:
            warning_lines = [
                "\n> **Warning — validation failures:**",
            ]
            for failure in self.failed_validations:
                step = failure.get("step", "unknown")
                error = failure.get("error", "unspecified error")
                cleaned = humanize_warnings([error])
                error = cleaned[0] if cleaned else "unspecified error"
                warning_lines.append(f"> - **{step}**: {error}")
            warning_lines.append(
                "> \n> Results from failed steps may contain inaccuracies. "
                "Verify before acting on this data.\n"
            )
            parts[0] += "\n".join(warning_lines)
        for step_name, output in self.steps.items():
            title = step_name.replace("_", " ").title()
            parts.append(f"## {title}\n\n{_demote_step_headings(output)}")

        # Collect all warnings from structured data (cross-validation
        # discrepancies, missing-field defaults, etc.) and surface them.
        all_warnings: list[str] = []
        primary_source: str | None = None
        for model in self.structured_data.values():
            if hasattr(model, "warnings"):
                _append_unique(all_warnings, humanize_warnings([str(w) for w in model.warnings]))
            if hasattr(model, "data_source") and primary_source is None:
                primary_source = model.data_source

        if all_warnings:
            notes = ["## Data Source Notes\n"]
            for w in all_warnings:
                notes.append(f"- {w}")
            if primary_source:
                notes.append(
                    f"\n> These discrepancies were detected by cross-provider "
                    f"validation.\n> Primary data source ({primary_source}) "
                    f"values were used in this report."
                )
            parts.append("\n".join(notes))

        # ---- Disclaimer ----
        disclaimer = (
            "---\n\n"
            "**Disclaimer:** This report is generated by FinRobot for informational purposes only. "
            "It does not constitute investment advice, a recommendation, or an offer to buy or sell any security. "
            "Financial data is sourced from public APIs (yfinance, FMP, Finnhub) and may contain errors, delays, or omissions. "
            "All projections are based on assumptions that may not materialize. "
            "Past performance does not guarantee future results. "
            "Consult a qualified financial advisor before making investment decisions.\n\n"
            "**Data Sources & Precision:** "
        )

        # Append data source info from warnings if available
        if self.warnings:
            source_warnings = [
                w
                for w in humanize_warnings([str(item) for item in self.warnings])
                if "source" in w.lower() or "stale" in w.lower() or "cache" in w.lower()
            ]
            if source_warnings:
                disclaimer += " ".join(source_warnings)
            else:
                disclaimer += (
                    "Data sourced from public APIs. Verify critical figures independently."
                )
        else:
            disclaimer += "Data sourced from public APIs. Verify critical figures independently."

        parts.append(disclaimer)

        return "\n\n---\n\n".join(parts)
