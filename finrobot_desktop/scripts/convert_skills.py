"""Convert Anthropic financial-services-plugins to FinRobot native skill format.

Usage:
    python scripts/convert_skills.py --source ~/Desktop/code/Fin/financial-services-plugins/ --output skills/

Upstream has TWO formats:
  Format A (no frontmatter): H1 heading + description: line + body
  Format B (YAML frontmatter): --- delimited YAML with name + description + body
"""

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml


def parse_upstream_skill(content: str) -> tuple[str, str, str]:
    """Detect upstream format and extract (name, description, body).

    Format A (no frontmatter): H1 heading + description: line + body
    Format B (YAML frontmatter): --- delimited YAML + body
    """
    if content.startswith("---"):
        # Format B: YAML frontmatter
        end_idx = content.find("---", 3)
        if end_idx == -1:
            raise ValueError("No closing --- for YAML frontmatter")
        yaml_str = content[3:end_idx].strip()
        body = content[end_idx + 3 :].strip()
        fm = yaml.safe_load(yaml_str) or {}
        name = fm.get("name", "Unknown")
        description = fm.get("description", "")
        if isinstance(description, str):
            description = description.strip()
        return name, description, body
    else:
        # Format A: H1 heading + description: text line
        lines = content.splitlines()
        name = lines[0].lstrip("# ").strip() if lines else "Unknown"
        desc_line = next((line for line in lines if line.strip().startswith("description:")), "")
        description = desc_line.split("description:", 1)[-1].strip() if desc_line else ""
        body = content  # keep full body unchanged
        return name, description, body


def extract_triggers(name: str, description: str) -> list[str]:
    """Extract keyword triggers. Priority:
    1. Parse explicit 'Triggers on "comps", "peer analysis"' from description
    2. Fall back to splitting name into lowercase words
    """
    # Try to extract explicit triggers from description
    match = re.search(r"[Tt]riggers?\s+on\s+(.+?)\.?\s*$", description, re.MULTILINE)
    if match:
        trigger_str = match.group(1)
        # Extract quoted strings
        quoted = re.findall(r'"([^"]+)"', trigger_str)
        if quoted:
            return quoted

    # Fall back to name words
    words = re.findall(r"[a-z]+", name.lower())
    # Filter out very short/common words
    stop_words = {"a", "an", "the", "and", "or", "of", "for", "in", "to", "with"}
    return [w for w in words if w not in stop_words and len(w) > 1]


def generate_id(name: str, source_path: Path) -> str:
    """Generate kebab-case id from the skill directory name."""
    # Use the directory name (already kebab-case in upstream)
    return source_path.parent.name


def infer_domain(source_path: Path) -> str:
    """Infer domain from upstream directory structure.

    Upstream paths:
      equity-research/skills/catalyst-calendar/SKILL.md  → equity-research
      partner-built/lseg/skills/fx-carry-trade/SKILL.md  → partner-lseg
      partner-built/spglobal/skills/tear-sheet/SKILL.md   → partner-spglobal
    """
    parts = source_path.parts
    # Find "skills" in the path, domain is everything before it
    try:
        skills_idx = parts.index("skills")
    except ValueError:
        return "general"

    # For partner-built/lseg/skills/... → "partner-lseg"
    # For equity-research/skills/... → "equity-research"
    domain_parts = []
    # Walk backwards from skills_idx to find the domain components
    # relative to the source root
    for i in range(skills_idx):
        part = parts[i]
        # Skip the overall source root parts
        if part in (".", "/") or part.endswith(":"):
            continue
        domain_parts.append(part)

    if not domain_parts:
        return "general"

    # For partner-built subdirs, flatten: "partner-built/lseg" → "partner-lseg"
    if domain_parts[0] == "partner-built" and len(domain_parts) > 1:
        return f"partner-{domain_parts[1]}"

    return domain_parts[0]


def convert_skill(source_path: Path, source_root: Path, output_dir: Path) -> str:
    """Convert a single upstream skill to FinRobot native format.
    Returns the format type used ("A" or "B").
    """
    content = source_path.read_text(encoding="utf-8")
    name, description, body = parse_upstream_skill(content)

    # Use path relative to source root for domain inference
    rel_path = source_path.relative_to(source_root)
    skill_id = generate_id(name, source_path)
    domain = infer_domain(rel_path)
    triggers = extract_triggers(name, description)

    # Truncate very long descriptions for frontmatter (keep first paragraph)
    short_desc = description.split("\n\n")[0].replace("\n", " ").strip()
    if len(short_desc) > 300:
        short_desc = short_desc[:297] + "..."

    # Build FinRobot native frontmatter
    frontmatter = {
        "id": skill_id,
        "name": name,
        "version": "1.0.0",
        "author": "anthropic",
        "domain": domain,
        "description": short_desc,
        "triggers": triggers,
        "requires_data": [],
        "requires_tools": [],
        "requires_skills": [],
        "compatible_models": [],
    }

    # Write output
    out_path = output_dir / domain / skill_id / "SKILL.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    out_path.write_text(f"---\n{yaml_str}---\n\n{body}\n", encoding="utf-8")

    fmt = "B" if content.startswith("---") else "A"
    return fmt


def main():
    parser = argparse.ArgumentParser(description="Convert Anthropic skills to FinRobot format")
    parser.add_argument("--source", required=True, help="Path to financial-services-plugins/")
    parser.add_argument("--output", default="skills/", help="Output directory")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    if not source.exists():
        print(f"Source directory not found: {source}")
        return

    count_a = 0
    count_b = 0
    errors = 0

    for skill_path in sorted(source.glob("**/SKILL.md")):
        try:
            fmt = convert_skill(skill_path, source, output)
            if fmt == "A":
                count_a += 1
            else:
                count_b += 1
        except Exception as e:
            print(f"  ERROR: {skill_path}: {e}")
            errors += 1

    total = count_a + count_b

    # Write version file
    version_file = output / "UPSTREAM_VERSION.txt"
    version_file.write_text(
        f"Source: {source}\n"
        f"Converted: {datetime.now(timezone.utc).isoformat()}\n"
        f"Total: {total} skills ({count_a} Format A, {count_b} Format B)\n"
        f"Errors: {errors}\n"
    )

    print(
        f"Converted {total} skills to {output} ({count_a} Format A, {count_b} Format B, {errors} errors)"
    )


if __name__ == "__main__":
    main()
