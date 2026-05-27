# Raw Research: homepilot Query Loop (Pillar 1)

**来源**: Explore 子 agent 深度通读 `/Users/zhunihaoyun/Desktop/code/zm/homepilot/`
**日期**: 2026-05-12
**用途**: 作为 Pillar 1 综合决策文档的事实依据

> 这份文档是子 agent 的原始研究笔记，未经编辑。事实陈述，不含决策。

---

## A. 整体架构

### 1. 入口函数签名

```python
async def query_loop(
    state: QueryState,
    config: QueryConfig,
    model_adapter: ModelAdapter,
    orchestrator: ToolOrchestrator,
    tool_registry: ToolRegistry,
    hook_registry: Any | None = None,
) -> AsyncGenerator[StreamEvent, None]:
```

**位置**：`engine/query/loop.py:108-115`

### 2. 输入对象

**QueryState** (`engine/query/state.py:31-57`)：
- `session_id: str`, `user_id: str`
- `messages: list[Message]`
- `turn_count: int`, `consecutive_failures: int`
- `max_output_tokens_recovery_count: int`
- `has_attempted_reactive_compact: bool`
- `transition: Transition | None`
- `compact_tracking: CompactTracking | None`
- `total_usage: TokenUsage`

**QueryConfig** (`engine/query/config.py:11-27`)：
- `model: str`, `system_prompt: str`
- `max_turns: int = 50`
- `max_output_tokens: int | None = None`
- `circuit_breaker_threshold: int = 3`
- `max_output_tokens_recovery_limit: int = 3`
- `temperature: float | None = None`
- `role: str = "user"`, `decision_style: str = "professional"`

### 3. 输出类型

`AsyncGenerator[StreamEvent, None]`

StreamEvent Union (`engine/types.py:177-187`)：
- MessageStartEvent / ContentBlockStartEvent / ContentBlockDeltaEvent
- ContentBlockStopEvent / MessageDeltaEvent / MessageStopEvent
- ToolExecutionStartEvent / ToolExecutionEndEvent / ErrorEvent

### 4. 调用关系

```
上游：
  server/api/chat.py::send_message() — POST /sessions/{id}/messages
  engine/agent/spawner.py — agent 子进程

query_loop():
  ├ ModelAdapter.stream()
  ├ ToolOrchestrator.run()
  └ 紧凑模块（可选）

内部:
  ├ _build_tool_schemas(registry)
  ├ _try_auto_compact(state, model_adapter, config)
  ├ _do_compact(state, model_adapter, config)
  └ _flush_tool_block(...)
```

---

## B. 状态机

### 1. 状态跟踪

显式通过 `turn_count`、`consecutive_failures`、`transition.reason`。

隐式阶段（每轮）：
1. 自动紧凑（若阈值触达）
2. max_turns 守卫
3. circuit_breaker 守卫
4. 调用模型（流式，累积内容块）
5. 拼装 AssistantMessage 并追加
6. 根据 stop_reason 分支

### 2. 状态转移表

| 当前 | 条件 | 下一 | 位置 |
|---|---|---|---|
| 初始化 | — | 模型调用 | L131 |
| 模型完成 | stop_reason == "tool_use" 或 tool_use_blocks 非空 | 工具执行 | L272 |
| 工具完成 | 无条件 | 继续 | L323 |
| 模型完成 | stop_reason == "max_tokens" | max_tokens 恢复 | L325 |
| max_tokens 恢复 | recovery_count <= limit | 继续 | L342 |
| max_tokens 恢复 | recovery_count > limit | break | L350 |
| 模型完成 | stop_reason == "end_turn" / 其他 | break | L354 |
| 任意 | 模型异常 | 中止 + ErrorEvent | L230-234 |
| 任意 | consecutive_failures >= threshold | 中止 + ErrorEvent | L145-154 |
| 任意 | turn_count >= max_turns | 中止 | L140-142 |

### 3. 退出条件

1. stop_reason == "end_turn"（或其他）—— 正常退出
2. turn_count >= max_turns
3. consecutive_failures >= threshold —— 熔断
4. max_tokens recovery 耗尽
5. 模型 API 异常

### 4. Turn 计数

- 计数：每完成一次模型调用后 `turn_count += 1`（L254）
- 检查：每轮循环开始前（L140）
- 最大：`config.max_turns`，默认 50

---

## C. 模型调用

### 1. 客户端

**LiteLLM**（多 provider）：`litellm.acompletion()`（L168）。

ModelAdapter (`engine/model/adapter.py`) 封装。

**无 Anthropic SDK 直接使用** — 这是相对 CC 的重大简化。

### 2. 请求构建

```python
api_messages: list[dict[str, Any]] = []
if system_prompt:
    api_messages.append({"role": "system", "content": system_prompt})
for msg in messages:
    api_messages.append(_message_to_dict(msg))

kwargs = {
    "model": model,
    "messages": api_messages,
    "max_tokens": max_tokens,
    "stream": True,
}
if tools:
    kwargs["tools"] = tools  # list of {"type": "function", "function": {...}}
if temperature is not None:
    kwargs["temperature"] = temperature
```

`_message_to_dict()` 转换 (`adapter.py:50-92`)：
- `ToolResultMessage` → `{"role": "tool", "tool_call_id": ..., "content": str}`
- `UserMessage` → `{"role": "user", "content": str/joined}`
- `AssistantMessage` → `{"role": "assistant", "content": ..., "tool_calls": [...]}`
- `SystemMessage` → `{"role": "system", "content": str}`

### 3. 流式

`stream=True`。事件由 ModelAdapter 产生：MessageStartEvent / ContentBlockStartEvent / ContentBlockDeltaEvent / ContentBlockStopEvent / MessageDeltaEvent / MessageStopEvent。

### 4. 重试策略

**主 loop 级别：无重试**（异常直接中止）。

单独的 retry 模块 (`engine/model/retry.py`)：
- `with_retry(operation, config)` 函数
- `max_retries=10`, `base_delay=1s`, `max_delay=32s`, `jitter=0.25`, `max_consecutive_overloads=3`
- 仅供上游使用，**loop 内不调用**

### 5. Prompt Caching

**不使用**。TokenUsage 字段保留（cache_read_input_tokens, cache_creation_input_tokens）但从不设置。

---

## D. Tool 执行

### 1. 并发策略

`ToolOrchestrator._partition()` (`engine/tool/orchestrator.py:59-99`)：

贪心顺序分区 (greedy sequential partitioning)：连续的"安全"工具形成并发批，不安全工具单独串行。

```
例：A(safe) + B(safe) + C(unsafe) + D(safe)
→ Batch1(concurrent): [A, B]
→ Batch2(serial): [C]
→ Batch3: [D]
```

依据：每个工具的 `is_concurrency_safe(args)` 方法。

### 2. 并发执行 (`orchestrator.py:167-213`)

```python
for batch in batches:
    if batch.is_concurrent and len(batch.calls) > 1:
        sem = asyncio.Semaphore(self._max_concurrency)  # 默认 10

        async def _limited(call, tool, args):
            async with sem:
                return await self._execute_one(call, tool, args, context)

        tasks = [_limited(call, tool, args) for ...]
        results = await asyncio.gather(*tasks)
        all_results.extend(results)

        # 并发批后统一应用 context_modifier
        for result in results:
            if result.context_modifier is not None:
                context = result.context_modifier(context)
    else:
        for call, tool, args in batch.calls:
            result = await self._execute_one(call, tool, args, context)
            all_results.append(result)
            if result.context_modifier is not None:
                context = result.context_modifier(context)
```

### 3. Tool Result 转 Messages

```python
for tc, result in zip(tool_calls, results):
    yield ToolExecutionEndEvent(...)
    tool_result_msg = ToolResultMessage(
        tool_use_id=tc.tool_use_id,
        content=result.to_text(),
        is_error=result.is_error,
    )
    state.messages.append(tool_result_msg)
    if result.new_messages:
        state.messages.extend(result.new_messages)
```

`ToolResultMessage.role = Role.USER`（注：作为 user 消息发送，由 adapter 转换为 `role: "tool"` 给 API）。

### 4. 失败处理 (`orchestrator.py:101-165`)

| 失败类型 | 处理 |
|---|---|
| 工具不存在 | `ToolResult(is_error=True, data="Error: tool '...' not found")` |
| 输入解析失败 | `ToolResult(is_error=True, data="Input validation error: ...")` |
| 权限拒绝 | `ToolResult(is_error=True, data="Permission denied: ...")` |
| 业务验证失败 | `ToolResult(is_error=True, data="Validation error: ...")` |
| 执行异常 | `ToolResult(is_error=True, data="Tool execution error: ...")` |
| 结果超大 | 截断到 `max_result_size_chars`（默认 100k），附加 [Truncated] |

**无超时机制**。

`is_error` 传播：写入 ToolResultMessage.is_error，下一轮模型感知。

---

## E. Stop Reason 处理

| stop_reason | 值 | 处理 | 位置 |
|---|---|---|---|
| `tool_use` | "tool_use" | 1. 检测 tool_use_blocks；2. 构建 ToolCallRequest；3. orchestrator.run()；4. 追加 ToolResultMessage；5. continue | L272-323 |
| `max_tokens` | "max_tokens" | recovery_count += 1；若 <= limit，注入 UserMessage("Continue...")，continue；否则 consecutive_failures += 1，break | L325-350 |
| `end_turn` | "end_turn" | break | L352-354 |
| `refusal` | (LiteLLM 映射) | 作为默认情况，break | L352-354 |
| 其他 | length 等 | break | L352-354 |

stop_reason 来源 (`adapter.py:227-233`)：

```python
if choice.finish_reason == "tool_calls":
    stop_reason = "tool_use"
elif choice.finish_reason == "length":
    stop_reason = "max_tokens"
else:
    stop_reason = "end_turn"
```

---

## F. 边界 case

### 1. max_tokens 续传 (`loop.py:325-350`)

```python
elif stop_reason == "max_tokens":
    state.max_output_tokens_recovery_count += 1
    if state.max_output_tokens_recovery_count <= config.max_output_tokens_recovery_limit:
        state.messages.append(
            UserMessage(content="Continue from where you left off. Resume directly without repeating.")
        )
        state.transition = Transition(reason="max_tokens_recovery", recovery_count=...)
        continue
    else:
        state.consecutive_failures += 1
        break
```

- 最多重试：`config.max_output_tokens_recovery_limit` 默认 3
- **消息硬编码英文**

### 2. JSON 解析失败 (`loop.py:357-374`)

```python
def _flush_tool_block(..., args_json: str, ...):
    try:
        tool_input = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        tool_input = {}  # 默认空字典
    content_blocks.append(ToolUseBlock(..., input=tool_input))
```

**无异常，无日志**。畸形 JSON 当作 `{}`，工具执行时在 `parse_input()` 阶段失败（is_error=True）。

### 3. 网络/API 错误 (`loop.py:230-234`)

```python
except Exception as exc:
    logger.exception("Model API call failed")
    state.consecutive_failures += 1
    yield ErrorEvent(error_type=type(exc).__name__, message=str(exc))
    break
```

无重试，无错误分类，直接中止 loop。

错误分类在 `engine/model/errors.py` 但 loop 不用：
- 429 → RateLimitError (retryable)
- 529 → OverloadError (retryable)
- 401/403 → AuthenticationError (non-retryable)
- 400 "too long" → PromptTooLongError (non-retryable)

### 4. Circuit Breaker (`loop.py:145-154`, `state.py:50-52`)

```python
def should_circuit_break(self, threshold: int) -> bool:
    return self.consecutive_failures >= threshold

# In loop:
if state.should_circuit_break(config.circuit_breaker_threshold):
    yield ErrorEvent(error_type="CircuitBreaker", message=f"Stopped after {failures} consecutive failures")
    break
```

阈值：默认 3。

**重置条件**：仅工具执行成功时（L274）`state.consecutive_failures = 0`。
**递增条件**：
- 模型 API 异常 +1
- max_tokens recovery 耗尽 +1
- **工具失败不递增**（bug）

### 5. Auto-Compact

入口 (`loop.py:133-137`)：

```python
if _try_auto_compact(state, model_adapter, config):
    await _do_compact(state, model_adapter, config)
if state.compact_tracking is not None:
    state.compact_tracking.turn_counter += 1
```

触发逻辑 (`engine/compact/auto_compact.py:40-53`)：

```python
def should_auto_compact(current_tokens, threshold, tracking):
    if tracking.consecutive_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:  # 3
        return False
    return current_tokens >= threshold

def calculate_compact_threshold(context_window, output_buffer=20_000, autocompact_buffer=13_000):
    effective = max(0, context_window - output_buffer)
    return effective - autocompact_buffer
```

例：64k 上下文 → (64k - 20k) - 13k = 31k 阈值。

紧凑操作 (`_do_compact`, L85-106)：用 LLM 调用生成摘要，替换整个消息列表为 `[summary_message]`。

### 6. 总 token 预算

**无显式处理**。

---

## G. 关键数据结构

```python
class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str | list[ContentBlock]
    timestamp: datetime
    uuid: str

class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: list[ContentBlock]
    stop_reason: str | None = None
    usage: TokenUsage | None = None

class ToolResultMessage(BaseModel):
    role: Literal["user"] = "user"  # ← 注：作为 user 消息
    tool_use_id: str
    content: str | list[TextBlock]
    is_error: bool = False

class SystemMessage(BaseModel):
    role: Literal["system"] = "system"
    content: str

@dataclass
class Transition:
    reason: str  # "next_turn", "max_tokens_recovery", ...
    recovery_count: int = 0

@dataclass
class CompactTracking:
    compacted: bool = False
    turn_counter: int = 0
    consecutive_failures: int = 0

@dataclass
class ToolUseContext:
    session_id: str
    user_id: str
    role: str = "user"
    messages: list[Message] = field(default_factory=list)
    model: str = ""
    abort_requested: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ToolResult:
    data: Any
    is_error: bool = False
    new_messages: list[Message] | None = None
    context_modifier: Callable[[ToolUseContext], ToolUseContext] | None = None
```

---

## H. 关键代码片段

### 1. Loop 主循环（`loop.py:131-354`）

```python
while True:
    if _try_auto_compact(state, model_adapter, config):
        await _do_compact(state, model_adapter, config)
    if state.compact_tracking is not None:
        state.compact_tracking.turn_counter += 1

    if state.should_stop_max_turns(config.max_turns):
        break

    if state.should_circuit_break(config.circuit_breaker_threshold):
        yield ErrorEvent(...)
        break

    # ... 流式调用模型，累积 content_blocks，捕获 stop_reason

    # 分支
    if stop_reason == "tool_use" or tool_use_blocks:
        # 工具执行
        state.consecutive_failures = 0
        tool_calls = [ToolCallRequest(...) for block in tool_use_blocks]
        results = await orchestrator.run(tool_calls, tool_context)
        for tc, result in zip(tool_calls, results):
            yield ToolExecutionEndEvent(...)
            state.messages.append(ToolResultMessage(...))
        continue
    elif stop_reason == "max_tokens":
        # max_tokens 恢复（见 F.1）
        ...
    else:
        break
```

### 2. ModelAdapter 入口 (`adapter.py:123-159`)

```python
async def stream(
    self,
    messages: list[Message],
    model: str | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    model = model or self.default_model
    max_tokens = max_tokens or self.get_max_output_tokens(model)

    api_messages = [...]
    kwargs = {...}
    yield MessageStartEvent(model=model)
    # ... 流式处理
```

### 3. 工具并发 (`orchestrator.py:180-212`) —— 见 D.2

### 4. Stop reason 分支 (`loop.py:272-354`) —— 见 E

### 5. Max_tokens 续传 (`loop.py:325-350`) —— 见 F.1

### 6. Circuit breaker (`loop.py:145-154`) —— 见 F.4

### 7. Auto-compact 入口 (`loop.py:133-137`) —— 见 F.5

---

## I. 偏离 Claude Code 的地方

### 1. 明显简化（homepilot 未实现 CC 有的特性）

| 特性 | CC | homepilot |
|---|---|---|
| Prompt Caching | ✅ `cache_control` | ❌ 字段保留不用 |
| Extended Thinking | ✅ thinking blocks | ❌ ThinkingBlock 类型存在但无处理 |
| Anthropic SDK 直调 | ✅ | ❌ 仅 LiteLLM |
| Streaming tool execution | ✅ 模型流式中并行执行 | ❌ greedy partitioning |
| Reactive compact | ✅ max_tokens 后触发 | ❌ 字段存在不用 |
| Fallback model | ✅ 529 触发切换 | ❌ |
| Stop hooks 完整 | ✅ blockingErrors 等 | ❌ 参数预留不用 |
| Multi-stage recovery | ✅ collapse → reactive → escalate → recovery | ❌ 单层 recovery |
| Memory prefetch | ✅ | ❌ |
| Tool use summary | ✅ Haiku 异步生成 | ❌ |

### 2. 改写（Python idiom）

| 方面 | CC (TS) | homepilot (Py) |
|---|---|---|
| Async | async function + Promise | async def + asyncio |
| 流式 | EventEmitter | AsyncGenerator |
| 状态机 | 隐式 switch | 显式 while True + if/elif |
| 类型 | TS interface | Pydantic BaseModel + dataclass |
| 并发 | Promise.all + queueing | asyncio.gather + Semaphore |
| JSON 流 | JSON.parse + buffer | 字符串累积 + json.loads |

### 3. 加料（homepilot 有但 CC 无）

1. **CompactTracking 细粒度状态** —— turn_counter / consecutive_failures 分开
2. **Transition 显式记录** —— CC 隐式状态
3. **Hook Registry 入口** —— 参数预留（虽未实现）
4. **Decision Style 参数** —— 注入系统提示的风格选项
5. **Role 参数** —— "user" vs "agent" 区分

### 4. 可疑 / 可能 bug

1. **max_tokens 恢复消息硬编码英文** —— `loop.py:334-336` 不支持多语言
2. **ToolResultMessage.role = USER** —— 不同于语义正确的 "tool"。依赖 adapter 转换
3. **异常无堆栈记录** —— 仅 `consecutive_failures += 1`，无错误分类（`loop.py:230-234`）
4. **JSON 解析失败静默** —— 工具调用 JSON 损坏当作 `{}`，无日志（`loop.py:366-367`）
5. **Auto-compact ImportError 静默** —— 模块不存在直接跳过（`loop.py:81-82`）
6. **Stream usage 不确定** —— LiteLLM chunk.usage 可能任意出现或不出现（`adapter.py:238-243`）
7. **Tool 失败不触发 consecutive_failures** —— 仅工具成功时重置，失败时不增加（`loop.py:274`）—— **熔断不基于工具失败**

---

## J. 不确定 / 没看懂

1. **Hook Registry 实际用途** —— `query_loop()` 接受参数但从不使用
2. **has_attempted_reactive_compact 字段** —— 定义但代码中无引用
3. **AssistantMessage.token_count** —— 字段存在从不设置
4. **ContentBlockDeltaEvent index** —— 流式中累积逻辑复杂，文本/工具块切换时 index 管理可能有歧义
5. **tool_registry 与 orchestrator.registry** —— 重复传递（为什么不复用同一个？）
6. **Memory 与 compact 的优先级** —— Memory 大时是否触发频繁 compact？

---

## 总结

homepilot 是一个**完整的、可工作的 Python 复刻**，架构与 CC 一致（while + 流式 + 工具编排），但做了重要简化：

1. 异步模型：AsyncGenerator 而非 EventEmitter
2. 错误处理：极简（无降级）
3. 多 provider：LiteLLM 抽象
4. 工具并发：原理同，asyncio.gather 实现更清晰
5. 自动紧凑：单一阈值策略

**关键差异**：无 prompt caching、无扩展思维、无被动紧凑、无 fallback model、无 streaming tool execution、无 stop hooks 完整支持。这些都是"可以加上的"，表明 homepilot 是**精简参考实现**。

**Loop 本身逻辑清晰**，但若干边界 case（JSON 失败、错误分类、工具失败计数）可能需要加强。
