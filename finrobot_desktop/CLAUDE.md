# CLAUDE.md

## Project

FinAgent — A financial AI agent platform with extensible skill ecosystem.
Full architecture: see `ARCHITECTURE.md` in project root.

**This is an open-source project. Every line of code will be publicly reviewed.**

Tech stack: PydanticAI + FastAPI + Electron + React 19.
No LangChain. No LangGraph. No AutoGen. No LiteLLM.

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| P0 | 核心引擎 | ✅ 完成 |
| P1a | Skill 运行时 | ✅ 完成 |
| P1b | 子 agent 拆分 | ✅ 完成 |
| P1.5 | 金融计算核心 | ✅ 完成 |
| P1c | Desktop app 骨架 | ✅ 完成 |
| P2a | 数据源扩展 | ✅ 完成 |
| **P2c** | **补齐 FinRobot 基线 + Desktop UI** | **← 当前阶段** |

All phase specs are in `specs/` directory. Each contains: goal, acceptance criteria, file-by-file implementation order, and package structure.

## 下一步工作

读 `specs/P2c.md`（补齐 FinRobot 基线：图表 + 报告 + 数据处理 + 催化剂分析 + Desktop UI），按里面的实现顺序进行。

如果 `specs/P2c.md` 不存在，先停下来，告诉用户需要先写 spec，不要凭空开始实现。

## 已知技术债

| 优先级 | 问题 | 修复计划 |
|--------|------|----------|
| 高 | P2a 数据清洗缺失（FinRobot 的 clean_financial_number 等逻辑被跳过） | P2c 模块 7 修复 |

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

### Rule 7: Design for scrutiny

This is an open-source project. Every design decision will be publicly reviewed. Before writing any code, answer these questions:

- **What does this code do that an LLM API call alone cannot?** If the answer is "nothing", the code should not exist.
- **If a senior engineer reads this, will they see real logic or just a wrapper?** Wrappers that add no value are not acceptable.
- **Are data structures between components typed and validated, or free-text strings?** Passing `str` between pipeline steps is forbidden — use Pydantic models.
- **Does the test verify actual correctness, or just that code runs without crashing?** Tests that only check "output is non-empty" or "no exception raised" are insufficient.

If the answer to any of these is unsatisfactory, redesign before implementing.

### Rule 8: Irreplaceability statement

Every file spec must include:

```
**What this code does that raw LLM cannot**: [specific explanation]
```

If this cannot be filled with a concrete answer, the file should not exist. Code that merely wraps an LLM call with no additional logic, computation, or structural guarantee has no value in an open-source project.

### Rule 9: Self-adversarial review

After completing each phase spec (before implementation), perform a self-attack:

1. **Wrapper audit**: Which parts of this design are "LLM wrapper" with no irreplaceable code value? List them explicitly.
2. **Data typing audit**: Where does data flow between components as `str` instead of structured types? Each instance is a bug.
3. **Test honesty audit**: Which tests only verify "code runs" rather than "code produces correct results"? Each instance must be upgraded.
4. **README audit**: Does every claim in README/ARCHITECTURE.md have corresponding working code? List any claim without implementation.

Document the results in the spec under a `## Self-Review` section. Do not proceed to implementation until all issues are resolved.