# Raw Research: homepilot Tool System (Pillar 2)

**来源**: Explore 子 agent 深度通读 `/Users/zhunihaoyun/Desktop/code/zm/homepilot/engine/tool/`
**日期**: 2026-05-12
**用途**: Pillar 2 综合决策文档的事实依据

> 子 agent 原始研究笔记，未经编辑。

---

## A. Tool 抽象定义

**BaseTool**（`engine/tool/base.py:73-136`）

泛型抽象基类 `BaseTool[TInput]`，TInput 受限于 Pydantic BaseModel。核心成员：

- **类属性**：`name`、`description`、`input_model`、`max_result_size_chars`（默认 100K）
- **关键方法**：
  - `call(args: TInput, context: ToolUseContext) -> ToolResult`（抽象，必实现）
  - `is_concurrency_safe(args: TInput) -> bool`（默认 False）
  - `is_read_only(args: TInput) -> bool`（默认 False）
  - `is_destructive(args: TInput) -> bool`（默认 False）
  - `check_permissions(args, context) -> PermissionResult`（默认允许）
  - `validate_input(args, context) -> ValidationResult`（默认有效）
  - `parse_input(raw: dict) -> TInput`：`input_model.model_validate(raw)`
  - `get_input_json_schema() -> dict`：Pydantic 生成
  - `to_api_schema() -> dict`：生成 Claude API 函数调用格式

**输入 Schema**：Pydantic BaseModel（`base.py:17`），`TInput = TypeVar("TInput", bound=BaseModel)`。

示例（`tools/demo.py:15-16`）：
```python
class CalculatorInput(BaseModel):
    expression: str = Field(description="A math expression...")
```

**ToolResult**（`base.py:38-56`）：
```python
@dataclass
class ToolResult:
    data: Any
    is_error: bool = False
    new_messages: list[Message] | None = None
    context_modifier: Callable | None = None

    def to_text(self) -> str:
        if isinstance(self.data, str): return self.data
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data, ensure_ascii=False, indent=2)
        return str(self.data)
```

**工具实现形式**：class（BaseTool 子类），实例存储在 registry。

---

## B. Tool 注册与发现

**ToolRegistry**（`registry.py:13-42`）字典包装 `_tools: dict[str, BaseTool[Any]]`：

```python
def register(self, tool: BaseTool[Any]) -> None:
    if tool.name in self._tools:
        raise ValueError(f"Tool '{tool.name}' already registered")
    self._tools[tool.name] = tool
```

方法：
- `register(tool)` — 重复名称 ValueError
- `unregister(name)`
- `get(name) -> BaseTool | None`
- `list_tools() -> list[BaseTool]`（插入顺序）
- `get_api_schemas() -> list[dict]` — 遍历调用 `to_api_schema()`

**注册机制**：显式 `register()` 调用。demo 工具（`tools/demo.py:59`）定义 `DEMO_TOOLS = [...]`。

**未实现**：热插拔、装饰器、动态加载。

---

## C. 输入验证

**验证流程**（`orchestrator.py:101-166`）：

1. **Pydantic 解析**（`base.py:90-92`）：`tool.parse_input(raw_dict)` → `input_model.model_validate(raw)`，失败抛异常
2. **_partition 阶段**（`orchestrator.py:79-86`）：捕获解析异常，标记串行，`parsed_args=None`
3. **_execute_one 阶段**（`orchestrator.py:119-126`）：
   - 若 `parsed_args is None`，重新尝试解析
   - 异常 → 返回 `ToolResult(data="Input validation error: ...", is_error=True)`
4. **业务验证**（`orchestrator.py:137-142`）：`tool.validate_input(parsed_args, context)` → 返回 ValidationResult

无 fallback 重试。

---

## D. 并发执行

### is_concurrency_safe 签名

```python
def is_concurrency_safe(self, args: TInput) -> bool  # base.py:99-105
```
参数：已解析的 input。返回：bool，默认 False。per-call 判断（与 args 值可能相关）。

### _partition greedy 算法（`orchestrator.py:59-99`）

```python
is_safe = tool.is_concurrency_safe(parsed)

if is_safe and batches and batches[-1].is_concurrent:
    batches[-1].calls.append((call, tool, parsed))
else:
    batches.append(_Batch(is_concurrent=is_safe, calls=[(call, tool, parsed)]))
```

结果：[并发0, 串行1, 并发1, ...]

### 并发执行机制（`orchestrator.py:181-213`）

```python
if batch.is_concurrent and len(batch.calls) > 1:
    sem = asyncio.Semaphore(self._max_concurrency)
    async def _limited(call, tool, args):
        async with sem:
            return await self._execute_one(call, tool, args, context)
    tasks = [_limited(...) for ...]
    results = await asyncio.gather(*tasks)
    all_results.extend(results)
    # 批后应用 context modifiers
    for result in results:
        if result.context_modifier is not None:
            context = result.context_modifier(context)
else:
    # 串行：单个工具或不安全
    for call, tool, args in batch.calls:
        result = await self._execute_one(...)
        all_results.append(result)
        if result.context_modifier is not None:
            context = result.context_modifier(context)
```

- `MAX_CONCURRENCY = 10`（构造函数可覆盖）
- `asyncio.gather` 保证返回顺序与输入顺序一致
- Context modifier 在并发批后**统一应用**，串行批**立即应用**

---

## E. Permission Check

**实现**（`base.py:115-119`、`orchestrator.py:128-134`）：

```python
async def check_permissions(self, args, context) -> PermissionResult:
    return PermissionResult(allowed=True)  # 默认允许
```

执行时机：`_execute_one` 中，在验证后、call 前。

示例（`test_orchestrator.py:68-71`）：
```python
class PermissionDeniedTool(BaseTool[...]):
    async def check_permissions(self, args, context):
        return PermissionResult(allowed=False, reason="agent role not allowed")
```

无 allow/deny rules、无 prefix matching、无 denial tracking、无 ask 模式。

---

## F. Tool Result 包装

**ToolResult 字段**（`base.py:38-56`）：

- `data: Any`
- `is_error: bool = False`
- `new_messages: list[Message] | None = None`
- `context_modifier: Callable | None = None`

**to_text() 实现**（line 50-56）：
```python
def to_text(self) -> str:
    if isinstance(self.data, str): return self.data
    if isinstance(self.data, (dict, list)):
        return json.dumps(self.data, ensure_ascii=False, indent=2)
    return str(self.data)
```

**体积限制**（`orchestrator.py:149-157`）：
- `tool.max_result_size_chars`（默认 100K）
- 超出截断 + 追加 `[Truncated: X chars exceeded Y limit]`

**多模态**：未实现。

**进度事件**：未实现。

---

## G. Tool Use Context

```python
@dataclass
class ToolUseContext:
    session_id: str
    user_id: str
    role: str = "user"  # "user" / "agent"
    messages: list[Message] = field(default_factory=list)
    model: str = ""
    abort_requested: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

工具运行时能访问：会话标识、用户标识、角色、消息历史、模型名称、元数据。

**abort_requested**：标志位，工具自主检查，无强制中断机制。

---

## H. MCP 集成

**未实现**。Plugin 系统有概念但不涉及 MCP。

---

## I. 关键代码片段

### 1. BaseTool 定义（`base.py:73-136`）

```python
class BaseTool(ABC, Generic[TInput]):
    name: str
    description: str
    input_model: type[TInput]
    max_result_size_chars: int = 100_000

    def is_concurrency_safe(self, args: TInput) -> bool:
        return False

    async def call(self, args: TInput, context: ToolUseContext) -> ToolResult:
        ...

    async def check_permissions(self, args, context) -> PermissionResult:
        return PermissionResult(allowed=True)
```

### 2. ToolRegistry 注册（`registry.py:22-26`）

```python
def register(self, tool: BaseTool[Any]) -> None:
    if tool.name in self._tools:
        raise ValueError(f"Tool '{tool.name}' already registered")
    self._tools[tool.name] = tool
```

### 3. _partition greedy（`orchestrator.py:89-97`）

```python
is_safe = tool.is_concurrency_safe(parsed)

if is_safe and batches and batches[-1].is_concurrent:
    batches[-1].calls.append((call, tool, parsed))
else:
    batches.append(_Batch(is_concurrent=is_safe, calls=[(call, tool, parsed)]))
```

### 4. ToolOrchestrator.run() 核心（`orchestrator.py:167-213`）

```python
async def run(self, calls, context):
    batches = self._partition(calls, context)
    all_results = []

    for batch in batches:
        if batch.is_concurrent and len(batch.calls) > 1:
            sem = asyncio.Semaphore(self._max_concurrency)
            tasks = [_limited(...) for ...]
            results = await asyncio.gather(*tasks)
            all_results.extend(results)
        else:
            for call, tool, args in batch.calls:
                result = await self._execute_one(...)
                all_results.append(result)

    return all_results
```

### 5. ToolResult 错误处理（`orchestrator.py:113-165`）

```python
if tool is None:
    return ToolResult(data=f"Error: tool '{call.tool_name}' not found", is_error=True)

if parsed_args is None:
    try:
        parsed_args = tool.parse_input(call.input)
    except Exception as exc:
        return ToolResult(data=f"Input validation error: {exc}", is_error=True)

perm = await tool.check_permissions(parsed_args, context)
if not perm.allowed:
    return ToolResult(data=f"Permission denied: {perm.reason}", is_error=True)

validation = await tool.validate_input(parsed_args, context)
if not validation.valid:
    return ToolResult(data=f"Validation error: {validation.message}", is_error=True)

try:
    result = await tool.call(parsed_args, context)
except Exception as exc:
    return ToolResult(data=f"Tool execution error: {exc}", is_error=True)
```

---

## J. 偏离 CC 的地方

| 维度 | CC | homepilot |
|---|---|---|
| Schema | Zod | Pydantic |
| 并发判断 | per-input | per-input（一致）|
| Greedy | 完整实现 | 完整实现 |
| Context Modifier | 复杂 | 简化为单个 Callable |
| Permission | 分级（allow/deny/ask + rules）| 仅 allowed/denied |
| Result 截断 | 超阈值 persist 磁盘 | 简单截断 |
| 多模态 | 支持（图像）| 不支持 |
| 进度事件 | 支持 | 不支持 |
| MCP | 完整 | 不支持 |
| 工具数量 | 50+ built-in | 仅 demo |
| Aliases | 支持 | 不支持 |
| Denial tracking | 支持 | 不支持 |

---

## K. 未理解的部分

1. **Context modifier 并发原子性**：多个工具修改同一 metadata 键的最终结果由迭代顺序决定，无同步机制
2. **Tool Call 结果顺序**：`asyncio.gather` 保证但无显式文档
3. **Abort 机制不完整**：`abort_requested` 是标志，工具需主动检查
4. **parse_input 异常类型**：只捕获泛 Exception，Pydantic ValidationError 详细信息未特殊处理
5. **Max result size**：100K 硬编码，是否根据模型自动调整？

---

## 总结

homepilot Tool 系统是 CC 的精简 Python 复刻：
- Pydantic 替代 Zod
- 同样的 per-input 并发判断 + greedy partitioning
- asyncio.gather + Semaphore 实现并发
- 缺失：MCP、多模态、进度事件、分级权限、disk persistence、aliases
