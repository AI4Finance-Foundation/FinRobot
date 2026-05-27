import logging
from pathlib import Path

from finrobot.engine.skills.loader import load_skill, SkillLoadError
from finrobot.engine.skills.spec import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Loads and indexes all skills from a directory tree.

    Expected directory structure:
    skills/
    ├── equity-research/
    │   ├── comps-analysis/
    │   │   └── SKILL.md
    │   └── dcf-model/
    │       └── SKILL.md
    └── ...
    """

    def __init__(self, skills_dir: Path):
        self._skills: dict[str, Skill] = {}  # id → Skill
        self._load_all(skills_dir)

    def _load_all(self, skills_dir: Path) -> None:
        """Walk skills_dir, find all SKILL.md files, load each.
        Log warning and skip on SkillLoadError (don't crash on one bad skill)."""
        for skill_path in sorted(skills_dir.glob("**/SKILL.md")):
            try:
                skill = load_skill(skill_path)
                self._skills[skill.id] = skill
            except SkillLoadError as e:
                logger.warning("Skipping bad skill %s: %s", skill_path, e)

    def get(self, skill_id: str) -> Skill | None:
        """Get skill by exact id. Returns None if not found."""
        return self._skills.get(skill_id)

    def search(self, query: str) -> list[Skill]:
        """Search skills by keyword matching against name, triggers, description.
        Case-insensitive. Returns skills sorted by relevance
        (name match > trigger match > description match)."""
        query_lower = query.lower()
        scored: list[tuple[int, Skill]] = []

        for skill in self._skills.values():
            score = 0
            if query_lower in skill.name.lower():
                score += 3
            if any(query_lower in t.lower() for t in skill.triggers):
                score += 2
            if query_lower in skill.description.lower():
                score += 1
            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: (-x[0], x[1].id))
        return [skill for _, skill in scored]

    def list_all(self) -> list[Skill]:
        """Return all loaded skills, sorted by domain then id."""
        return sorted(self._skills.values(), key=lambda s: (s.domain, s.id))

    def list_summary(self) -> str:
        """Compact summary of all skills for LLM context window."""
        skills_by_domain: dict[str, list[Skill]] = {}
        for skill in self.list_all():
            skills_by_domain.setdefault(skill.domain, []).append(skill)

        lines = ["## Available Skills", ""]
        for domain in sorted(skills_by_domain):
            lines.append(f"**{domain}**")
            for skill in skills_by_domain[domain]:
                lines.append(f"- {skill.summary()}")
            lines.append("")

        lines.append("Use activate_skill(skill_id) to load full methodology.")
        return "\n".join(lines)

    def list_ids(self) -> list[str]:
        """Return all skill ids. Used by activate_skill error message."""
        return sorted(self._skills.keys())

    @property
    def count(self) -> int:
        return len(self._skills)
