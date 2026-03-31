# CLAUDE.md

## Project

FinAgent — A financial AI agent platform with extensible skill ecosystem.
Full architecture: see `ARCHITECTURE.md` in project root.

Tech stack: PydanticAI + FastAPI + Electron + React 19.
No LangChain. No LangGraph. No AutoGen. No LiteLLM.

## Current Phase: P1b

Read the current phase spec before writing any code:
```
specs/P1b.md
```

Previous completed phases (read if you need context on existing code):
```
specs/P0.md
specs/P1a.md
```

All phase specs are in `specs/` directory. Each contains: goal, acceptance criteria, file-by-file implementation order, and package structure.

---

## Development Rules

These rules apply to ALL phases. Do not violate them regardless of which phase you're working on.

### Rule 1: One file at a time

Never write multiple files in one pass. Workflow:
1. Write ONE file
2. Write its test file
3. Run tests, confirm pass
4. Only then move to the next file

### Rule 2: Test before moving on

After every file:
```bash
python -m pytest tests/ -x -v --tb=short
```
If any test fails, fix it before writing the next file. Never leave broken tests behind.

### Rule 3: Follow the implementation order exactly

Do not skip ahead. Do not reorder. The sequence in each phase spec is designed so each file only depends on files already completed above it.

### Rule 4: Only current phase code

Do not write code for future phases. If you need something from a future phase, write a `# TODO(phase): ...` comment and move on. Check the current phase spec for the explicit "Do NOT" list.

### Rule 5: Only approved dependencies

Check the current phase spec for the approved dependency list. Do not add any dependency not on that list without explicit approval.

### Rule 6: Follow ARCHITECTURE.md exactly

The architecture document contains exact class names, method signatures, tool docstrings, and pipeline step definitions. Use them verbatim. Do not rename classes, change signatures, or "improve" the design. If you think something in ARCHITECTURE.md is wrong, say so — don't silently change it.