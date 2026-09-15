import yaml  # type: ignore[import-untyped]
from pathlib import Path
from typing import Any

import pydantic

from finrobot.engine.skills.spec import Skill


class SkillLoadError(Exception):
    """Raised when a skill file cannot be parsed."""


def load_skill(path: Path) -> Skill:
    """Load a single SKILL.md file into a Skill model.

    Expected format (FinRobot native — output of convert_skills.py):
    ---
    id: comps-analysis
    name: Comparable Company Analysis
    version: 1.0.0
    author: anthropic
    domain: equity-research
    triggers: [...]
    ---

    # Comparable Company Analysis
    ## Workflow
    ...
    """
    content = path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(content)

    if "id" not in frontmatter:
        raise SkillLoadError(f"Missing required field 'id' in {path}")
    if "name" not in frontmatter:
        raise SkillLoadError(f"Missing required field 'name' in {path}")

    description = _extract_description(frontmatter, body)

    try:
        return Skill(
            id=frontmatter["id"],
            name=frontmatter["name"],
            version=frontmatter.get("version", "1.0.0"),
            author=frontmatter.get("author", "unknown"),
            domain=frontmatter.get("domain", "general"),
            description=description,
            triggers=frontmatter.get("triggers", []),
            requires_data=frontmatter.get("requires_data", []),
            requires_tools=frontmatter.get("requires_tools", []),
            requires_skills=frontmatter.get("requires_skills", []),
            compatible_models=frontmatter.get("compatible_models", []),
            full_content=body,
            source_path=str(path),
        )
    except pydantic.ValidationError as e:
        raise SkillLoadError(f"Invalid frontmatter field types in {path}: {e}") from e


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from Markdown body.
    Returns (frontmatter_dict, markdown_body).
    Raises SkillLoadError if no valid frontmatter found."""
    if not content.startswith("---"):
        raise SkillLoadError("No YAML frontmatter found (file must start with '---')")

    # Find the closing --- (skip the opening one)
    end_idx = content.find("---", 3)
    if end_idx == -1:
        raise SkillLoadError("No closing '---' for YAML frontmatter")

    yaml_str = content[3:end_idx].strip()
    body = content[end_idx + 3 :].strip()

    try:
        frontmatter = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise SkillLoadError(f"Invalid YAML frontmatter: {e}") from e

    if not isinstance(frontmatter, dict):
        raise SkillLoadError("YAML frontmatter must be a mapping")

    return frontmatter, body


def _extract_description(frontmatter: dict[str, Any], body: str) -> str:
    """Get description from frontmatter, or fall back to first paragraph of body."""
    if "description" in frontmatter and frontmatter["description"]:
        return str(frontmatter["description"])

    # Fall back to first non-empty paragraph of body
    for paragraph in body.split("\n\n"):
        text = paragraph.strip()
        if text and not text.startswith("#"):
            return text

    return ""
