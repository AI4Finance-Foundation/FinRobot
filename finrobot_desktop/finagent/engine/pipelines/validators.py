from pydantic import BaseModel


class ValidationResult(BaseModel):
    passed: bool
    error: str | None = None


def validate_is_non_empty(output: str) -> ValidationResult:
    """P0 validator. Passes if output is a non-empty, non-whitespace string."""
    if output and output.strip():
        return ValidationResult(passed=True)
    return ValidationResult(passed=False, error="Output is empty or whitespace")


def validate_has_fields(output: str, fields: list[str]) -> ValidationResult:
    """P0 validator. Checks that output string mentions all required field names."""
    missing = [f for f in fields if f.lower() not in output.lower()]
    if not missing:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Output missing required fields: {', '.join(missing)}",
    )

# TODO(P1b): validate_has_peers(output, min_peers=3) — requires skill methodology injection
# TODO(P1b): validate_has_valuation(output) — requires skill methodology injection
# TODO(P1b): validate_has_sections(output) — requires skill methodology injection
# TODO(P1b): validate_report_format(output) — requires skill methodology injection
