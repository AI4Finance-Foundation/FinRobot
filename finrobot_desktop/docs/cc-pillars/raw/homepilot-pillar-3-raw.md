# Raw Research: homepilot System Prompt Assembly (Pillar 3)

**来源**: Explore 子 agent 深度通读 homepilot `server/api/chat.py`、`engine/memory/prompt.py`、`config/decision_styles.yaml`
**日期**: 2026-05-12

---

## A. 装配流程

**入口**: `_build_system_prompt(engine, user_id, decision_style) -> str`
- 位置: `server/api/chat.py:74-100`

**调用链**：
1. POST `/sessions/{id}/messages` 接收 `decision_style` body 参数
2. `decision_style = body.decision_style or engine.styles_config.default_style`（line 177）
3. 调用 `_build_system_prompt(engine, user_id, decision_style)`（line 180）
4. 注入 `QueryConfig.system_prompt`（line 185）
5. 传给 `query_loop()` → `model_adapter.stream()`

## B. 装配的 4 层（按顺序）

```python
def _build_system_prompt(engine, user_id, decision_style):
    parts = []

    # Layer 1: 日期时间戳
    parts.append(f"当前日期：{date.today().isoformat()}（{date.today().strftime('%Y年%m月%d日')}）")

    # Layer 2: Decision Style
    style = engine.styles_config.styles.get(decision_style)
    if style is not None:
        parts.append(style.prompt.strip())

    # Layer 3: 数据纪律
    parts.append(
        "数据纪律：所有具体数字（房价、成交量、利率等）必须来自工具查询结果。"
        "没有通过工具查到的数据，不要编造。"
        "可以提供分析框架、判断逻辑和思考方向。"
    )

    # Layer 4: Memory
    memory_prompt = build_memory_prompt(engine.memory_store, user_id)
    if memory_prompt:
        parts.append(memory_prompt)

    return "\n\n".join(parts)
```

## C. Decision Style 机制

**4 种 style**（在 `decision_styles.yaml`）：
- `professional`（默认）— 直接、数据驱动
- `detailed` — 深度分析、表格 / 矩阵
- `beginner_friendly` — 入门友好、解释术语
- `investor` — 投资视角、租售比 / 收益率

**配置位置**: `config/decision_styles.yaml`

**结构**：
```yaml
styles:
  professional:
    display_name: "专业顾问"
    description: "直接、数据驱动..."
    prompt: |
      [30-50 行的详细 prompt 文本]
default_style: professional
```

**加载** (`engine/bootstrap.py:67`)：
```python
styles_config = load_styles_config(config_dir / "decision_styles.yaml")
```

**数据类** (`engine/config.py:144-175`)：
```python
class DecisionStyleConfig(BaseModel):
    display_name: str
    description: str
    prompt: str

class StylesConfig(BaseModel):
    styles: dict[str, DecisionStyleConfig]
    default_style: str = "professional"
```

**切换方式**：
- API 参数：`POST /sessions/.../messages` 的 body `decision_style: str | None`
- 默认：`engine.styles_config.default_style`

**append 逻辑**（不替换其他层）：style prompt 作为整体块 append 到 parts 列表，其他 3 层始终存在。

## D. Memory 注入

**Memory 类型** (`engine/memory/types.py:21-25`)：
```python
class MemoryType(StrEnum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"
```

**加载** (`engine/memory/prompt.py:26-49`)：
```python
def build_memory_prompt(store, user_id) -> str:
    entries = store.list_by_user(user_id)
    if not entries:
        return ""

    entries = entries[:MAX_MEMORY_ENTRIES]  # = 20

    lines = ["<user-memories>"]
    total_chars = 0
    for entry in entries:
        formatted = _format_entry(entry)
        if total_chars + len(formatted) > MAX_MEMORY_CHARS:  # = 25_000
            break
        lines.append(formatted)
        total_chars += len(formatted)
    lines.append("</user-memories>")

    return "\n".join(lines)
```

**存储**：
- 接口：`MemoryStore` Protocol（save / get / list_by_user / update / delete）
- 默认 `InMemoryStore`（dict 后端）
- 生产用 PostgreSQL（未实现）

## E. Skill 注入

homepilot 有完整 Skill 系统（仿 CC）。

**定义**：Markdown + YAML frontmatter，放在 `skills/` 目录。

**结构** (`engine/skill/types.py:24-40`)：
```python
@dataclass
class SkillDefinition:
    name: str
    description: str
    prompt_template: str
    source_path: str = ""
    allowed_tools: list[str] | None = None
    user_invocable: bool = False
    model: str | None = None
    context: Literal["inline", "fork"] = "inline"
    agent_type: str | None = None
```

**关键**：Skill **不注入 system prompt**，在 query loop 的 tool call 阶段动态调用。

## F. 与 CC 差异

| 维度 | CC | homepilot |
|---|---|---|
| 装配层数 | 12+（含 boundary）| 4 |
| 静态/动态分隔 | SYSTEM_PROMPT_DYNAMIC_BOUNDARY | 无 |
| Output style 分发 | .md 文件多源 | 单 YAML |
| Skill 在 prompt 中 | 列名称 | 不列 |
| Memory 后端 | 文件系统 | 内存 / DB |
| Prompt caching | 支持 | 不支持 |
| Env / git / cwd | 注入 | 不注入 |

## G. 关键代码片段

见 §B / §C / §D 内嵌代码。

## H. 未理解的部分

1. Memory relevance filtering（`engine/memory/relevance.py`）未审查
2. Compact prompt 与主 system prompt 的合并机制
3. Hook registry 是否能在装配阶段修改 system prompt
4. Agent 是否有独立 system prompt
5. Session 中途切换 decision_style 时历史消息的 prompt 不变——设计意图？
