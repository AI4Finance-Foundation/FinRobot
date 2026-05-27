# Raw Research: homepilot Compact + Memory + Task (Pillar 5)

**来源**: Explore 子 agent 通读 homepilot `engine/compact/`、`engine/memory/`、`engine/query/loop.py`
**日期**: 2026-05-12

---

## A. Compact 实现

### A.1 触发阈值

`engine/compact/auto_compact.py:16-37`：

```python
def calculate_compact_threshold(context_window, output_buffer=20_000, autocompact_buffer=13_000):
    effective = max(0, context_window - output_buffer)
    return effective - autocompact_buffer
```

例：64K 上下文 → (64K - 20K) - 13K = 31K 阈值

### A.2 执行

`engine/compact/compact.py:24-66`：

```python
async def compact_messages(messages, model_adapter, model, max_summary_tokens=20_000):
    if len(messages) <= 2:
        return messages

    content_blocks, _usage, _stop_reason = await model_adapter.complete(
        messages=messages,
        model=model,
        system_prompt=COMPACT_SYSTEM_PROMPT,
        max_tokens=max_summary_tokens,
    )

    summary_text = ""
    for block in content_blocks:
        if isinstance(block, TextBlock):
            summary_text += block.text

    if not summary_text.strip():
        return messages

    summary_message = UserMessage(content=COMPACT_USER_PREFIX + summary_text + COMPACT_USER_SUFFIX)
    return [summary_message]
```

**策略**：full summarization——整段历史一次性 LLM 摘要为单条消息。无增量、无 reactive。

### A.3 失败计数

`engine/compact/tracking.py:11-25`：

```python
@dataclass
class CompactTracking:
    compacted: bool = False
    turn_counter: int = 0
    consecutive_failures: int = 0

MAX_CONSECUTIVE_COMPACT_FAILURES = 3
```

熔断：`consecutive_failures >= 3` 时 should_auto_compact 返回 False。

### A.4 _try_auto_compact

`engine/query/loop.py:51-82`：

```python
def _try_auto_compact(state, model_adapter, config):
    try:
        from engine.compact.auto_compact import calculate_compact_threshold, should_auto_compact
        from engine.model.tokens import token_count_with_estimation

        if state.compact_tracking is None:
            state.compact_tracking = CompactTracking()

        current_tokens = token_count_with_estimation(state.messages)
        context_window = model_adapter.get_context_window(config.model)
        threshold = calculate_compact_threshold(context_window)

        return should_auto_compact(current_tokens, threshold, state.compact_tracking)
    except ImportError:
        return False
```

---

## B. Memory 实现

### B.1 MemoryStore Protocol

`engine/memory/store.py:19-50`：

```python
class MemoryStore(Protocol):
    def save(self, entry: MemoryEntry) -> str: ...
    def get(self, memory_id: str) -> MemoryEntry | None: ...
    def list_by_user(self, user_id, memory_type=None) -> list[MemoryEntry]: ...
    def update(self, memory_id, **kwargs) -> None: ...
    def delete(self, memory_id) -> None: ...
```

### B.2 InMemoryStore

`engine/memory/store.py:53-91`：dict[str, MemoryEntry]。生产用 PostgreSQL（未实现）。

### B.3 MemoryEntry 字段

`engine/memory/types.py:28-43`：

```python
@dataclass
class MemoryEntry:
    user_id: str
    memory_type: MemoryType   # USER / FEEDBACK / PROJECT / REFERENCE
    name: str
    content: str
    description: str | None
    memory_id: str | None
    created_at: datetime
    updated_at: datetime
```

### B.4 写入路径

无自动写入。需要外部代码（API 层 / 工具）显式调用 `store.save(entry)`。

---

## C. Task

**无 task_id / checkpoint 概念**。

`WorkerTask`（`engine/agent/coordinator.py:35-44`）是并发工作单位，不持久化：
```python
@dataclass
class WorkerTask:
    agent_def: AgentDefinition
    prompt: str
```

会话追踪仅靠 `QueryState.turn_count + session_id`。

---

## D. 关键代码

见 A/B 内嵌。

---

## E. 与 CC 差异

**简化**：
1. 仅 1 种 compact 策略（full summarization）vs CC 5 种
2. Memory 用 Protocol + InMemoryStore vs CC memdir 文件系统
3. 无 Reactive compact
4. 无 task_id / checkpoint
5. 无 LLM-based memory relevance（直接最近 N 条）

**改写**：
1. Protocol pattern（解耦后端）
2. Pydantic BaseModel for types
3. enum.StrEnum for MemoryType

**未实现**：
1. Reactive compact
2. LLM relevance selection
3. PostgreSQL backend
4. Memory 版本控制 / 冲突解决
5. Compact + Memory 交互（关键信息保存到 memory）

---

## F. 未理解的部分

1. **Memory 注入时机**：`build_memory_prompt()` 在 loop.py 无调用——预期外层 API 调用
2. **Memory 写入触发**：无自动逻辑将对话内容转为 MemoryEntry
3. **Compact + Memory 交互**：无机制保存关键信息到 Memory
4. **Token 计数精度**：compact 替换历史后 `token_count_with_estimation` 是否仍准确
