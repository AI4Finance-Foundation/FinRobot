from pydantic import BaseModel


class Skill(BaseModel):
    """A loaded skill with metadata and content."""

    id: str  # e.g. "comps-analysis"
    name: str  # e.g. "Comparable Company Analysis"
    version: str  # e.g. "1.0.0"
    author: str  # e.g. "anthropic"
    domain: str  # e.g. "equity-research"
    description: str  # first paragraph of body, or frontmatter description
    triggers: list[str] = []  # search keywords
    requires_data: list[dict[str, str]] = []  # parsed but not enforced until P1b
    requires_tools: list[str] = []  # parsed but not enforced until P2c
    requires_skills: list[str] = []  # parsed but not enforced until P3a
    compatible_models: list[str] = []  # optional, informational only
    full_content: str  # entire Markdown body (everything after frontmatter)
    source_path: str  # filesystem path to SKILL.md

    def summary(self) -> str:
        """One-line summary for LLM context: '{id}: {name} — {description[:50]}'"""
        desc = self.description[:50] + "..." if len(self.description) > 50 else self.description
        return f"{self.id}: {self.name} — {desc}"
