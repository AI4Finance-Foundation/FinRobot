# Pillar 2: Tool System + 并发 — 研究与 FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.3 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | v0.3 应用 mini-ADR-3 + 修 v0.2 评审 Blocking 4/6 |
| **依据** | Explore 子 agent 对 CC + homepilot 的并行深度通读 + 真实代码核对 |
| **前置 ADR** | mini-ADR-1 v1.1、mini-ADR-2、mini-ADR-3 v1.0、Pillar 1 v0.6 |
| **原始报告** | `raw/cc-pillar-2-raw.md`、`raw/homepilot-pillar-2-raw.md` |

---

## Changelog

### v0.3(2026-05-12)

应用 mini-ADR-3 + 修 v0.2 评审 Blocking 4/6:

**Blocking 修复**:
- **B-v03-1(评审 Blocking 4)**:`ToolUseContext` 从 9 字段扩到 19 字段(mini-ADR-3 §2.3),含 `audit_root_id / parent_chain_id / depth` 谱系 + 6 个 sub-agent 派生字段。`messages` 改 `tuple[Message, ...]`(immutable 快照)。`deps` 类型注解从 `Any` 提为 `FinRobotDeps`(TYPE_CHECKING 字符串注解)
- **B-v03-2(评审 Blocking 6)**:§4.8 `RunDCFTool` 真实 API 二次校正:核对 `finrobot/engine/models/financial.py:248` 确认字段是 `implied_price`(非 `fair_value_per_share`);`structured_data["dcf_calc"]` 是 **Pydantic `DCFResult` 对象**(`finrobot/engine/pipelines/dcf.py:98` `StepOutput(structured=dcf_result)` 传 model 不是 dict);wrapper 处理改为 `isinstance(..., DCFResult)` 后用属性访问

**新增**:
- §4.6 `ToolOrchestrator.__init__` 加 `shared_semaphore: asyncio.Semaphore | None = None` 关键字参数(mini-ADR-3 §3.1)
- §4.6.1 `fork_for_subagent(child_registry)` 方法,共享父 Semaphore(F-P7-2 解);UT 必须断言 `id(child._sem) == id(parent._sem)`(mini-ADR-3 §5.7)
- Pillar 3 协同:AgentProfile.analyst_style 加 `"ic_memo"` literal(Pillar 3 v0.2 patch,本 doc 引用)

### v0.2(2026-05-12)

### v0.2（2026-05-12）

修复 v0.1 评审反馈：

**Blocking（必修，5 项）**：
- **B1**：§4.8 pipeline wrapper 示例**整段重写**为真实 FinRobot API（`create_dcf_pipeline(agents)` 工厂 + `Pipeline.execute(deps, ticker, ...)` + `PipelineResult.structured_data / format_summary()`），暴露真实包装工作量
- **B3**：`asyncio.Semaphore` 从 per-batch 提到 `ToolOrchestrator.__init__`，**executor 级别全局上限**——sub-agent + 主 agent 并发场景仍生效
- **B4**：F-P2-1 诊断方向重写。真问题是 **"同步 lambda 包装 async 函数 → `iscoroutinefunction` 自省返回 False"**，不是 "lambda 丢 self"。修复方法相应改为 `async def _call` 实方法绑定
- **D2**：`ToolResult.data` 截断时类型变 str 破坏结构化数据 → 新增独立字段 `text_for_llm: str | None`，截断只覆盖该字段，`data` 永远保持原始结构
- **D7**：`ToolUseContext.deps: Any` 立即修，用 `TYPE_CHECKING + 字符串注解`，不等 v2

**Design 调整（5 项）**：
- **D1**：`max_result_size_chars` 默认值 256K → **64K**，filings 类工具显式 override 到 256K
- **D4**：`audit_payload` 不再 `** merge` 进 `build_audit` kwargs，改为显式 `tool_extra: dict[str, Any]` 字段
- **D5**：§4.9 加 concurrency 假设的验证负担说明（IT-P2-XX 必须通过才能确认 pipeline wrapper 真正 concurrency_safe）
- **D6**：§9 Week 4-5 `refine_dcf` 加 "依赖 Pillar 5 v1 task_id 决议，否则推 v2" 触发器
- **B2**：临时**降级**——`on_progress` 从 BaseTool.call / ToolOrchestrator.run 接口签名移除，标记 `# TODO(pillar-1-v0.4): 决议后回填`；§8 #1 升级为正式未决议

**Cleanup（7 项）**：
- §4.5 f-string 无插值 → 改为普通 str
- §4.6 `_partition` `except Exception` 收窄为 `except pydantic.ValidationError`，其他异常往上抛
- §4.7 Pillar 1 v0.4 diff 不再内嵌，改为列条目 + "Pillar 1 v0.4 prerequisite"
- §4.2 `read_only_default` / `destructive_default` / `concurrency_safe_default` 拆三个独立 ClassVar，默认值各自合理
- §4.3 删除 "自动注册到默认 ToolRegistry" docstring（与 §4.5 矛盾，**D3** 解决）
- §8 #4 cost_hint 锁定方向："如引入应走 metadata.cost_hint 不污染工具签名"
- §8 #2 `deps` 已在 v0.2 修复，从未决议清单删除

### v0.1（2026-05-12）

初版交付：调研综合 + FinRobot 决策对照表 + 4 项 FinRobot 补丁（UIAction / audit_payload / on_progress / pipeline wrapper 协议）+ 6 项推迟列表 + 自审 8 处。

---

## 0. TL;DR

- **CC Tool 系统**：50+ built-in + 任意 MCP 工具，Zod schema 两层验证，per-input 并发判断 + greedy partitioning，StreamingToolExecutor 边流式边并发，分级权限（allow/deny/ask）+ rule prefix matching，结果超阈值 persist 到磁盘
- **homepilot**：精简 Python 复刻——Pydantic schema、同样的 greedy partitioning、`asyncio.gather + Semaphore`、但缺失 MCP / 多模态 / 进度事件 / 分级权限 / disk persistence
- **FinRobot v1 决策**：以 homepilot 骨架为起点，补 4 项金融场景必需能力（UIAction 渲染指令、audit_payload 附加字段、进度事件、pipeline-wrapped tools 包装协议），明确推迟 6 项（MCP、StreamingToolExecutor、多模态、disk persistence、ask 模式权限、aliases）
- **工程量**：Week 2 同步完成（与 Pillar 1 实施并行起跑）

---

## 1. Pillar 2 的位置

Tool 系统是 agent 能力的承载层。Pillar 1（query loop）定义了"何时调用工具"，Pillar 2 定义了：

- 工具**是什么**（接口、schema、生命周期）
- 工具**怎么注册**（registry、发现）
- 工具**怎么调用**（输入验证、权限、并发、结果包装）
- 工具**怎么集成现有 pipeline**（FinRobot 特有的 DCF/LBO/comps 等如何成为 conversational tools）

Pillar 1 v0.2 §3.5.3 写过"pipeline → tool"的包装规则但只给了一个例子，没有完整契约——本 pillar 把这层补完。

---

## 2. 调研结论摘要

### 2.1 Claude Code（详见 `raw/cc-pillar-2-raw.md`）

- **核心抽象**：`Tool<Input, Output>` interface（`Tool.ts:362-695`），class instance 或 plain object
- **Schema**：Zod v4，`z.infer<Input>` 推导运行时类型；MCP 工具走原生 JSON Schema
- **注册**：`getAllBaseTools()` 返回 built-in 列表（条件加载），`assembleToolPool()` 合并 built-in + MCP
- **并发**：`isConcurrencySafe(input)` 按输入值判断，greedy partitioning，`all()` generator combinator 限流 10
- **StreamingToolExecutor**：CC 独有——模型流式响应时就开始执行工具，sibling abort
- **权限**：`canUseTool()` 函数，三态决策（allow/deny/ask），allow/deny rules 支持 prefix matching，denial tracking 自动 fallback
- **结果**：`ToolResult<T> { data, newMessages?, contextModifier?, mcpMeta? }`，超阈值 persist 到磁盘 + 预览
- **多模态**：text/image blocks + `mcpMeta._meta + structuredContent`
- **进度**：`ToolCallProgress` callback

### 2.2 homepilot（详见 `raw/homepilot-pillar-2-raw.md`）

- **核心抽象**：`BaseTool[TInput]` 泛型 ABC（`base.py:73-136`），TInput 是 Pydantic BaseModel
- **方法集**：`call` / `is_concurrency_safe` / `is_read_only` / `is_destructive` / `check_permissions` / `validate_input` / `parse_input` / `to_api_schema`
- **注册**：`ToolRegistry` 字典 + `register()` 显式调用，重名抛 ValueError
- **并发**：与 CC 一致的 per-input + greedy + `asyncio.gather + Semaphore`，`MAX_CONCURRENCY=10`
- **权限**：`check_permissions` 返回 `PermissionResult(allowed, reason)`——仅 allow/deny 二态，无 rules，无 tracking
- **结果**：`ToolResult { data, is_error, new_messages, context_modifier }`，`max_result_size_chars=100K`，超出截断 + `[Truncated: ...]`
- **未实现**：MCP / 多模态 / 进度 / disk persistence / aliases / denial tracking / streaming tool exec

---

## 3. CC vs homepilot vs FinRobot 决策对照

| 维度 | CC | homepilot | **FinRobot 决策** | 理由 |
|---|---|---|---|---|
| Tool 抽象形态 | class instance / plain object | class (BaseTool) | **class (BaseTool)** + `@as_tool` 装饰器糖 | 主形态对齐，复杂工具用 class，简单工具用装饰器 |
| Schema | Zod | Pydantic BaseModel | **Pydantic BaseModel** | 与 FinRobot 现有技术栈一致 |
| API schema 生成 | Zod → JSON Schema | `model.model_json_schema()` | **Pydantic v2 `.model_json_schema()`** | 直接 |
| 输入验证 | 两层（schema + validateInput） | 两层 | **两层** | 业务校验有独立必要（如"ticker 必须在 watchlist 内"）|
| 并发安全 | per-input `isConcurrencySafe(input)` | per-input | **per-input + 默认值标记** | 加 `concurrency_safe_default: bool` 类属性作为快速覆盖路径 |
| Greedy partitioning | ✅ | ✅ | **✅ 直接复刻** | 算法已证明 |
| MAX_CONCURRENCY | 10（env 可调） | 10 | **10**（config 可调） | 一致 |
| Streaming tool exec | ✅ | ❌ | **❌ v1 不做** | 复杂度过高，Pillar 1 v0.2 已决议 |
| Permission 模型 | allow/deny/ask + rules + tracking | allow/deny only | **allow/deny only（v1）** | v2 加 fund-level rules + ask 模式 |
| Result 体积 | 超阈值 persist 磁盘 + 预览 | 截断 + warning | **截断到 256K + audit warning + v2 加 disk persistence** | 10-K 全文经常 > 100K，但 disk persist 需要 audit-aware 存储设计 |
| Multimodal | ✅ | ❌ | **❌ v1 不做** | 金融场景文本为主 |
| 进度事件 | `onProgress` callback | ❌ | **✅ 必做** | pipeline 跑 30-60 秒，没进度反馈用户会以为卡死 |
| MCP 集成 | ✅ | ❌ | **❌ v1 不做** | 复杂度高，audit guarantees 不明，v2 evaluate |
| Tool aliases | ✅ | ❌ | **❌ v1 不做** | 名字管好就行 |
| Denial tracking | ✅ | ❌ | **❌ v1 不做** | audit log 已覆盖；统计走查询而非内置计数器 |
| Disk persistence for big results | ✅ | ❌ | **❌ v1 截断 + v2 加** | 需要 audit-aware 存储 |
| **UI Actions（桌面 app 渲染指令）** | ❌（CLI / IDE 渲染）| ❌ | **✅ 新增** | FinRobot 桌面 app 需要 chat panel → canvas 联动 |
| **Audit payload** | 间接（通过 hooks） | ❌ | **✅ 新增** | audit_chain_id 系统的一等公民字段 |
| 工具失败计入熔断 | ❌ 无 | ❌ 无 | **✅ 见 Pillar 1 §4.8** | Pillar 1 已实施 consecutive_tool_failures |

---

## 4. FinRobot 实现规格

### 4.1 模块结构

```
finrobot/conversation/                  # 已在 Pillar 1 v0.3 §4.1 定义
├─ tool/                                # 本 pillar 新增
│   ├─ __init__.py
│   ├─ base.py                          # BaseTool + ToolResult + UIAction
│   ├─ context.py                       # ToolUseContext（独立文件方便其他模块 import）
│   ├─ registry.py                      # ToolRegistry
│   ├─ orchestrator.py                  # ToolOrchestrator (greedy + async)
│   ├─ decorators.py                    # @as_tool 函数→类装饰器糖
│   └─ errors.py                        # ToolNotFound / InputValidationError 等
└─ tools/                               # FinRobot 实际工具集（不放 base/）
    ├─ pipeline_tools.py                # 包装 engine/pipelines/* 为 tools
    ├─ data_tools.py                    # 直接调用 DataLayer 的工具
    └─ utility_tools.py                 # get_time、explain_metric 等
```

### 4.2 BaseTool 类

```python
# finrobot/conversation/tool/base.py

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel

TInput = TypeVar("TInput", bound=BaseModel)


@dataclass
class UIAction:
    """传给桌面 app 的 UI 渲染指令。SSE 端点收到后转发给客户端。
    Loop / 模型 不读这些字段——仅供前端消费。"""

    type: Literal[
        "render_chart",
        "render_report",
        "show_assumption_panel",
        "update_watchlist",
        "open_url",
        "scroll_to_section",
        "highlight_metric",
    ]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionResult:
    allowed: bool
    reason: str | None = None


@dataclass
class ValidationResult:
    valid: bool
    message: str | None = None


@dataclass
class ToolResult:
    """工具返回值。同时承载 LLM 可见数据 + 前端可见动作 + audit 附加信息。

    v0.2 修复 D2：截断不破坏结构化数据。
    - data: 永远保留工具返回的原始（可结构化）值
    - text_for_llm: 截断/格式化后塞进 tool_result content block 的纯文本
    - to_text() 优先返回 text_for_llm，否则按 data 类型序列化
    """

    data: Any
    """给下游（含 LLM）的原始内容。可以是 str / dict / BaseModel / 任意结构。
       Orchestrator 截断时**不修改这个字段**。"""

    is_error: bool = False

    text_for_llm: str | None = None
    """显式给 LLM 的文本版本（可选）。
       - None: to_text() 按 data 类型序列化
       - 非 None: to_text() 直接返回这个字符串
       Orchestrator 体积截断时**只修改这个字段**（即写入截断后的文本），
       data 保持原始。"""

    new_messages: list["Message"] = field(default_factory=list)  # v0.2 cleanup: 用字符串注解
    """工具可注入额外 messages（如 reflection、上下文修正）。"""

    context_modifier: Callable[["ToolUseContext"], "ToolUseContext"] | None = None
    """工具完成后修改 ToolUseContext 的回调。"""

    ui_actions: list[UIAction] = field(default_factory=list)
    """前端渲染指令。query_loop yield 为 UIAction stream events，SSE 转发给客户端。"""

    audit_payload: dict[str, Any] = field(default_factory=dict)
    """post_tool_use hook 写 audit log 时附加的 type-specific 字段。
       例：DCF 工具返回 {"fair_value": 185, "wacc": 0.083, "task_id": "..."}
       让 audit log 直接查询"那次 user turn 用了哪些 WACC 假设"成为可能。

       v0.2 D4 修复：audit_payload 不再 ** merge 进 build_audit kwargs，
       而是作为显式 tool_extra 字段传入，避免与 build_audit 标准字段冲突。"""

    duration_ms: int | None = None
    """orchestrator 自动填，不由工具自己填。"""

    def to_text(self) -> str:
        """序列化为 LLM 可见的纯文本。

        优先 text_for_llm（含截断后的版本），否则按 data 类型序列化。
        """
        if self.text_for_llm is not None:
            return self.text_for_llm

        import json
        if isinstance(self.data, str):
            return self.data
        if isinstance(self.data, BaseModel):
            return self.data.model_dump_json(indent=2)
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data, ensure_ascii=False, indent=2, default=str)
        return str(self.data)


# v0.2 B2 临时降级：on_progress 从 BaseTool.call 接口移除。
# Pillar 1 v0.4 决议进度信号流转方式后再回填。当前保留类型定义但不参与调用。
# ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
# 当前 §4.6 _execute_one 和 BaseTool.call 都不传 on_progress。


class BaseTool(ABC, Generic[TInput]):
    """所有 FinRobot 工具的基类。"""

    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    # ─── 体积上限：v0.2 D1 默认值改为 64K，filing 类工具显式 override 到 256K ───
    max_result_size_chars: ClassVar[int] = 64_000
    """默认 64K（覆盖 95% 工具：财务数据、估值结果、市场数据）。
       超大返回（filings 全文、长 transcript）应该是显式声明而非隐式默认。
       Filing 工具示例：max_result_size_chars = 256_000。"""

    # ─── v0.2 cleanup：拆三个独立默认（不再从 concurrency_safe_default 推断）───
    concurrency_safe_default: ClassVar[bool | None] = None
    """快速路径：
       - True: 所有 input 都安全（如纯查询工具）
       - False: 所有 input 都不安全（如写操作）
       - None: 必须 override is_concurrency_safe(args) 做 per-call 判断"""

    read_only_default: ClassVar[bool] = True
    """默认 True（多数 FinRobot 工具是只读查询）。
       写操作类工具（add_to_watchlist、export_to_*）应显式 = False。"""

    destructive_default: ClassVar[bool] = False
    """默认 False（多数工具非破坏性）。
       真正破坏性操作（删除、覆盖）应显式 = True。"""

    @abstractmethod
    async def call(
        self,
        args: TInput,
        context: "ToolUseContext",
        # on_progress 暂时移除（v0.2 B2 降级，等 Pillar 1 v0.4 决议）
    ) -> ToolResult:
        """工具执行入口。"""

    # ─── 默认实现：可按需 override ───

    def is_concurrency_safe(self, args: TInput) -> bool:
        if self.concurrency_safe_default is None:
            raise NotImplementedError(
                f"Tool '{self.name}' must either set concurrency_safe_default "
                "or override is_concurrency_safe()."  # v0.2 cleanup: 移除 f-string 无插值
            )
        return self.concurrency_safe_default

    def is_read_only(self, args: TInput) -> bool:
        return self.read_only_default  # v0.2 cleanup：用独立默认

    def is_destructive(self, args: TInput) -> bool:
        return self.destructive_default  # v0.2 cleanup：用独立默认

    async def check_permissions(
        self, args: TInput, context: "ToolUseContext"
    ) -> PermissionResult:
        return PermissionResult(allowed=True)

    async def validate_input(
        self, args: TInput, context: "ToolUseContext"
    ) -> ValidationResult:
        return ValidationResult(valid=True)

    # ─── Schema ───

    def parse_input(self, raw: dict[str, Any]) -> TInput:
        return self.input_model.model_validate(raw)

    def get_input_json_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def to_api_schema(self) -> dict[str, Any]:
        """生成 PydanticAI / Anthropic API 期望的 tool spec 格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_input_json_schema(),
        }
```

### 4.3 `@as_tool` 装饰器糖

为简单工具提供简洁声明形式：

```python
# finrobot/conversation/tool/decorators.py

def as_tool(
    *,
    name: str,
    description: str,
    input_model: type[BaseModel],
    concurrency_safe: bool,
    max_result_size_chars: int = 64_000,  # v0.2 D1 同步
) -> Callable[[Callable], type[BaseTool]]:
    """把 async function 包装成 BaseTool 子类。

    Usage:
        @as_tool(
            name="get_financials",
            description="Fetch financial statements for a ticker",
            input_model=GetFinancialsArgs,
            concurrency_safe=True,
        )
        async def get_financials(args, context):
            return ToolResult(data=...)

    **不自动注册**——返回的 class 需要调用方显式 `registry.register(MyTool())`。
    （v0.2 D3 修复：与 §4.5 一致，避免 import order 问题。）

    复杂工具（per-call 安全判断、自定义 validate_input 等）应该直接继承 BaseTool。
    """
    def decorator(fn):
        # v0.2 B4 修复：用 async def 实方法绑定，而非同步 lambda 包装 coroutine。
        # 同步 lambda 返回 awaitable 会导致 inspect.iscoroutinefunction 返回 False，
        # 上游调度器若用此自省判断会走错路径；同时 lambda 体内的异常会在 await
        # 之前抛出，不进 _execute_one 的 try/except。
        async def _call(self, args, context):
            return await fn(args, context)

        class _Tool(BaseTool):
            pass
        _Tool.name = name
        _Tool.description = description
        _Tool.input_model = input_model
        _Tool.concurrency_safe_default = concurrency_safe
        _Tool.max_result_size_chars = max_result_size_chars
        _Tool.call = _call  # 类属性绑定 async 方法，描述符协议正常工作
        _Tool.__name__ = f"{name.title()}Tool"
        return _Tool
    return decorator
```

### 4.4 ToolUseContext

```python
# finrobot/conversation/tool/context.py

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.conversation.types import Message


@dataclass
class ToolUseContext:
    """传给工具运行时的上下文。从 QueryState 派生。

    v0.3 应用 mini-ADR-3 §2.3:19 字段。前 13 个为普通工具读,
    后 6 个为 sub-agent 派生用(spawn_subagent tool 内访问;普通工具不应触碰)。
    """

    # ─── 身份(来自 QueryState,谱系字段全部传入)───
    session_id: str
    user_id: str
    fund_id: str
    audit_chain_id: str
    audit_root_id: str
    parent_chain_id: str | None
    depth: int

    # ─── 工具运行时所需 ───
    role: Literal["user", "agent"]
    messages: tuple["Message", ...]  # F-P2-3:tuple 不可变,工具无法 mutate
    """只读快照。工具想读历史走这个,但不能改。"""
    model: str

    # ─── 外部依赖(进程级,mini-ADR-3 §2.1)───
    deps: "FinRobotDeps"
    """显式字段;工具通过 context.deps.memory_store / checkpoint_store /
       audit_store / pipeline_factories / sub_agents / model_adapter / ...
       访问进程级单例。不再用 payload 走私。"""

    # ─── Abort 信号 ───
    abort_requested: bool = False

    # ─── 自由扩展 ───
    metadata: dict[str, Any] = field(default_factory=dict)

    # ─── v0.3 新增:Sub-agent 派生字段(mini-ADR-3 §2.3 后 6 字段)───
    # 这些字段仅供 spawn_subagent tool / spawn_parallel_subagents tool 使用。
    # 普通工具(run_dcf / get_financials 等)不应该读取,更不应该 mutate。

    parent_state: "QueryState | None" = None
    """spawn 时传入主 QueryState,fork_subagent_state 用它派生 child_state。
       普通工具调用路径:由 query_loop 在构造 ToolUseContext 时填入 state 自身;
       sub-agent 内调用 spawn 时,这里仍是 sub-agent 自己的 state。"""

    parent_config: "QueryConfig | None" = None
    """spawn 时继承 / 覆盖 max_turns / temperature / language 等。"""

    parent_profile: "AgentProfile | None" = None
    """spawn 时继承 analyst_style / market / fund_id;可被 agent_def 覆盖。"""

    tool_registry: "ToolRegistry | None" = None
    """spawn_subagent 用此调用 resolve_agent_tools(parent_registry, agent_def)
       派生 child_registry。"""

    tool_orchestrator: "ToolOrchestrator | None" = None
    """spawn_subagent 用此调用 fork_for_subagent(child_registry),
       共享父 Semaphore(mini-ADR-3 §3.1)。"""

    hook_registry: "HookRegistry | None" = None
    """sub-agent 默认继承父 hook_registry;agent_def.disable_hooks=True 时不传。"""
```

> **mini-ADR-3 §2.1 决议**:`model_adapter` 在 FinRobotDeps,**不**放 ToolUseContext。
> spawn_subagent tool 调用 `spawn_subagent(model_adapter=context.deps.model_adapter, ...)`。

### 4.5 ToolRegistry

```python
# finrobot/conversation/tool/registry.py

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered.")
        if not tool.name or not tool.description:
            raise ValueError("Tool must have non-empty name and description.")  # v0.2 cleanup: 移除 f-string 无插值
        self._tools[tool.name] = tool

    def register_all(self, tools: list[BaseTool]) -> None:
        for t in tools:
            self.register(t)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get_or_raise(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ToolNotFound(name)
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def api_schemas(self) -> list[dict[str, Any]]:
        return [t.to_api_schema() for t in self._tools.values()]
```

**不实现**（v1）：
- 装饰器自动注册（避免 import order 问题）
- 热插拔 / 动态加载
- Plugin 系统
- Aliases

### 4.6 ToolOrchestrator（并发编排）

```python
# finrobot/conversation/tool/orchestrator.py

import asyncio
import time
from dataclasses import dataclass

MAX_CONCURRENCY = 10  # 与 CC / homepilot 一致；可由 config 覆盖


@dataclass
class ToolCallRequest:
    tool_use_id: str
    tool_name: str
    raw_input: dict[str, Any]


@dataclass
class _Batch:
    is_concurrent: bool
    calls: list[tuple[ToolCallRequest, BaseTool | None, BaseModel | None]]


class ToolOrchestrator:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_concurrency: int = MAX_CONCURRENCY,
        shared_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        """
        v0.3(mini-ADR-3 §3.1):构造支持 shared_semaphore 关键字。

        Args:
            registry: 本 orchestrator 管理的 ToolRegistry
            max_concurrency: 默认 10。仅在 shared_semaphore is None 时生效
            shared_semaphore: 若非 None,借用此 Semaphore 替代新建。
                Sub-agent fork 路径用此参数复用父 Semaphore,确保整棵
                agent 树共用同一全局并发上限(mini-ADR-3 §5.7 不变量)。

                WARNING: shared_semaphore 必须与本 orchestrator 运行在
                同一 event loop;跨 loop 行为未定义。
        """
        self._registry = registry
        self._max_concurrency = max_concurrency
        self._sem = (
            shared_semaphore
            if shared_semaphore is not None
            else asyncio.Semaphore(max_concurrency)
        )

    def fork_for_subagent(self, child_registry: ToolRegistry) -> "ToolOrchestrator":
        """派生 sub-agent 用的子 orchestrator,与父共享 Semaphore。

        Invariant(mini-ADR-3 §5.7):
            assert id(self.fork_for_subagent(r)._sem) == id(self._sem)

        WARNING: 子必须运行在与父同一 event loop。
        """
        return ToolOrchestrator(
            registry=child_registry,
            max_concurrency=self._max_concurrency,
            shared_semaphore=self._sem,
        )

    async def run(
        self,
        calls: list[ToolCallRequest],
        context: ToolUseContext,
    ) -> list[ToolResult]:
        """执行一批工具调用，返回与输入顺序一致的结果列表。

        v0.2 B2 降级：移除 on_progress 参数。进度信号机制待 Pillar 1 v0.4 决议。
        """
        batches = self._partition(calls)
        all_results: list[ToolResult] = []

        for batch in batches:
            if batch.is_concurrent and len(batch.calls) > 1:
                async def _limited(c, t, a):
                    async with self._sem:  # v0.2 B3：用 self._sem 全局上限
                        return await self._execute_one(c, t, a, context)

                tasks = [_limited(call, tool, args) for call, tool, args in batch.calls]
                results = await asyncio.gather(*tasks)
                all_results.extend(results)
                # 并发批：所有任务完成后统一应用 context_modifier
                for result in results:
                    if result.context_modifier:
                        context = result.context_modifier(context)
            else:
                # 串行批：立即应用 context_modifier
                for call, tool, args in batch.calls:
                    result = await self._execute_one(call, tool, args, context)
                    all_results.append(result)
                    if result.context_modifier:
                        context = result.context_modifier(context)

        return all_results

    def _partition(
        self, calls: list[ToolCallRequest]
    ) -> list[_Batch]:
        """Greedy: 连续 is_concurrency_safe=True 的工具合并为并发批。"""
        from pydantic import ValidationError

        batches: list[_Batch] = []

        for call in calls:
            tool = self._registry.get(call.tool_name)
            parsed: BaseModel | None = None
            is_safe: bool = False

            if tool is not None:
                try:
                    parsed = tool.parse_input(call.raw_input)
                    is_safe = tool.is_concurrency_safe(parsed)
                except ValidationError:
                    # v0.2 cleanup：只捕获 Pydantic 验证错误，标记串行让 _execute_one 报错给 LLM
                    is_safe = False
                # 其他异常（NotImplementedError、ImportError 等）不 catch，向上传播
                # 让程序员看到真问题而不是吞掉

            if is_safe and batches and batches[-1].is_concurrent:
                batches[-1].calls.append((call, tool, parsed))
            else:
                batches.append(_Batch(is_concurrent=is_safe, calls=[(call, tool, parsed)]))

        return batches

    async def _execute_one(
        self,
        call: ToolCallRequest,
        tool: BaseTool | None,
        parsed_args: BaseModel | None,
        context: ToolUseContext,
    ) -> ToolResult:
        started = time.perf_counter()

        # 1. Tool 存在性
        if tool is None:
            return ToolResult(
                data=f"Error: tool '{call.tool_name}' not found",
                is_error=True,
                duration_ms=_elapsed_ms(started),
            )

        # 2. 输入解析（若 _partition 已成功解析则跳过）
        if parsed_args is None:
            from pydantic import ValidationError
            try:
                parsed_args = tool.parse_input(call.raw_input)
            except ValidationError as exc:
                # v0.2 F-P2-4 修复：捕获 ValidationError 而非 Exception，
                # 提取详细错误（field path + msg）给 LLM 看
                error_details = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    for e in exc.errors()
                )
                return ToolResult(
                    data=f"Input validation error: {error_details}",
                    is_error=True,
                    duration_ms=_elapsed_ms(started),
                )

        # 3. 权限检查
        try:
            perm = await tool.check_permissions(parsed_args, context)
            if not perm.allowed:
                return ToolResult(
                    data=f"Permission denied: {perm.reason or 'no reason provided'}",
                    is_error=True,
                    duration_ms=_elapsed_ms(started),
                )
        except Exception as exc:
            return ToolResult(
                data=f"Permission check error: {exc}",
                is_error=True,
                duration_ms=_elapsed_ms(started),
            )

        # 4. 业务验证
        try:
            valid = await tool.validate_input(parsed_args, context)
            if not valid.valid:
                return ToolResult(
                    data=f"Validation error: {valid.message or 'unspecified'}",
                    is_error=True,
                    duration_ms=_elapsed_ms(started),
                )
        except Exception as exc:
            return ToolResult(
                data=f"Validation check error: {exc}",
                is_error=True,
                duration_ms=_elapsed_ms(started),
            )

        # 5. 执行
        try:
            result = await tool.call(parsed_args, context)
        except asyncio.CancelledError:
            raise  # 让 cancellation 正常传播
        except Exception as exc:
            return ToolResult(
                data=f"Tool execution error: {exc}",
                is_error=True,
                duration_ms=_elapsed_ms(started),
            )

        # 6. 体积截断（v0.2 D2 修复：只写 text_for_llm，不破坏 data）
        result_text = result.to_text()
        if len(result_text) > tool.max_result_size_chars:
            truncated = result_text[: tool.max_result_size_chars]
            warning = (
                f"\n\n[Truncated: result was {len(result_text)} chars, "
                f"truncated to {tool.max_result_size_chars} chars. "
                "Consider narrowing the query or splitting into multiple tool calls.]"
            )
            # 只覆盖 text_for_llm，data 保持原始结构化值
            result.text_for_llm = truncated + warning

        # 7. 自动填 duration
        result.duration_ms = _elapsed_ms(started)

        return result


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
```

### 4.7 与 Pillar 1 的对接（Pillar 1 v0.4 prerequisite）

`query_loop` 在 tool_use 分支调用 `ToolOrchestrator.run()`（已在 Pillar 1 v0.3 §4.8 定义）。Pillar 2 引入新对接点，**diff 实体写在 Pillar 1 v0.4 草案里**（本 doc 只列条目）：

**Pillar 1 v0.4 需要做的事**（按优先级）：

1. **UIAction 流转**（必做）：`_handle_tool_use` 在合成 ToolResultMessage 之前，遍历 `result.ui_actions` 并 yield 为 `UIActionEvent`，让 SSE 端点转发给桌面 app
2. **audit_payload 合并**（必做）：`post_tool_use` 完成后构造 audit event 时，把 `result.audit_payload` 作为**独立字段** `tool_extra: dict[str, Any]` 传入 `build_audit()`（v0.2 D4 修复 — 不再 ** kwargs merge，避免与 `tool_name` / `is_error` 等标准字段冲突）
3. **AuditEvent.payload 添加 `tool_extra` 字段**（schema 级改动）：在 Pillar 1 v0.4 的 `build_audit()` 签名增加 `tool_extra: dict[str, Any] | None = None` 显式参数
4. **进度信号机制**（**未决议，先空着**）：on_progress 怎么从 orchestrator 流到 SSE 客户端——v0.2 B2 已经把它从 `ToolOrchestrator.run()` 和 `BaseTool.call()` 接口移除。决议见 §8 #1，Pillar 1 v0.4 联调时再补回

### 4.8 Pipeline → Tool 包装规则（v0.2 B1 整段重写为真实 API）

每个现有 `engine/pipelines/*` pipeline 由一个 wrapper tool 暴露到对话。规则：

**入口包装**（不暴露内部步骤）：

```python
# finrobot/conversation/tools/pipeline_tools.py

from typing import Any
from pydantic import BaseModel, Field
from finrobot.engine.pipelines.base import PipelineResult
from finrobot.engine.models.financial import ForecastAssumptions, DCFResult


class RunDCFArgs(BaseModel):
    ticker: str = Field(description="Stock ticker (e.g. 'AAPL', '000001.SZ')")
    assumptions: ForecastAssumptions | None = Field(
        default=None,
        description="Optional assumption overrides (WACC, terminal_growth, tax_rate)."
    )


class RunDCFTool(BaseTool[RunDCFArgs]):
    name = "run_dcf"
    description = (
        "Run full DCF valuation on a ticker. Returns implied share price, WACC "
        "used, and a checkpoint task_id for follow-up refine queries. Read-only."
    )
    input_model = RunDCFArgs
    concurrency_safe_default = True
    read_only_default = True

    async def call(self, args, context):
        # v0.3 真实 FinRobot API(核对 finrobot/engine/pipelines/dcf.py:101 +
        # base.py:121 + models/financial.py:248):
        #
        # 1) factory 从 deps.pipeline_factories 取(mini-ADR-3 §2.1)
        # 2) factory 签名 create_dcf_pipeline(agents: dict[str, Agent])
        # 3) Pipeline.execute(deps, ticker, progress, lang, **kwargs)
        # 4) PipelineResult 字段:steps / structured_data / failed_validations / warnings
        # 5) structured_data["dcf_calc"] 是 DCFResult Pydantic 对象(不是 dict)
        # 6) DCFResult 字段是 implied_price(不是 fair_value_per_share)

        factory = context.deps.pipeline_factories["dcf"]
        pipeline = factory(agents=context.deps.sub_agents)

        result: PipelineResult = await pipeline.execute(
            deps=context.deps,
            ticker=args.ticker,
            **(args.assumptions.model_dump() if args.assumptions else {}),
        )

        # 提取 DCFResult Pydantic 对象(B-v03-2 核心修复:不是 dict.get)
        dcf_calc = result.structured_data.get("dcf_calc")
        implied_price: float | None = None
        wacc_used: float | None = None
        enterprise_value: float | None = None
        sensitivity_table: dict | None = None
        fcf_warning: str | None = None

        if isinstance(dcf_calc, DCFResult):
            implied_price = dcf_calc.implied_price
            wacc_used = dcf_calc.wacc
            enterprise_value = dcf_calc.enterprise_value
            sensitivity_table = dcf_calc.sensitivity_table
            fcf_warning = dcf_calc.fcf_formula_warning

        # Surrogate task_id(mini-ADR-3 §6 决议:PipelineResult 不污染原生
        # task_id,wrapper tool 在 conversation/tool 层合成)
        surrogate_task_id = f"{context.audit_chain_id}:{args.ticker.upper()}:dcf"

        # 写 checkpoint(Pillar 5 v0.2 落盘 + 读取保留,refine 降 v2)
        await context.deps.checkpoint_store.save_pipeline_result(
            task_id=surrogate_task_id,
            user_id=context.user_id,
            fund_id=context.fund_id,
            audit_chain_id=context.audit_chain_id,
            pipeline_name="dcf",
            ticker=args.ticker.upper(),
            result=result,
        )

        return ToolResult(
            data=result,
            text_for_llm=result.format_summary(),
            ui_actions=[
                UIAction(
                    type="render_chart",
                    payload={
                        "chart_id": f"dcf_sens_{args.ticker}",
                        "task_id": surrogate_task_id,
                        # DCFResult 用 model_dump() 序列化为 dict 给前端
                        "structured": dcf_calc.model_dump() if isinstance(dcf_calc, DCFResult) else None,
                    },
                ),
                UIAction(
                    type="show_assumption_panel",
                    payload={"task_id": surrogate_task_id,
                             "editable": ["wacc", "terminal_growth", "tax_rate"],
                             "refine_available": False},  # v1 refine 降 v2,UI 不暴露
                ),
            ],
            audit_payload={
                "ticker": args.ticker.upper(),
                "implied_price": implied_price,       # ← B-v03-2 修复:用真实字段名
                "wacc": wacc_used,
                "enterprise_value": enterprise_value,
                "fcf_formula_warning": fcf_warning,    # 用户可见警告(DCF 简化公式)
                "warnings_count": len(result.warnings),
                "failed_validations_count": len(result.failed_validations),
                "task_id": surrogate_task_id,
            },
        )
```

**实施期会暴露的工作量(v0.3 二次核对后)**:

1. **Pipeline.execute 不直接收 assumptions** — v1 走 **kwargs 透传,Pipeline 内部 forecast step 解构。Pillar 5 refine 已**降级到 v2**(mini-ADR-3 §6),所以本条 v1 阶段不需要扩展 Pipeline.execute 签名
2. **PipelineResult 没有 task_id 字段** — **mini-ADR-3 §6 决议保持现状**:不污染 PipelineResult,wrapper tool 在 audit_payload + UIAction.payload 自行合成 `{chain_id}:{ticker}:{pipeline_name}` surrogate task_id。v2 refine 真要成为 pipeline 原生能力时再考虑下沉 `PipelineRunIdentity`
3. **structured_data["dcf_calc"] 是 DCFResult Pydantic 对象** — v0.3 已修正:用 `isinstance(..., DCFResult)` 判断后属性访问,不再 `dict.get`。验证位置:`pipelines/dcf.py:98` `StepOutput(structured=dcf_result)`,`models/financial.py:227-248`
4. **DCFResult 字段是 implied_price 而非 fair_value_per_share** — v0.3 已修正(`models/financial.py:248`)。其他 wrapper(LBO/comps 等)实施时也要类似核对真实字段名
5. **`format_summary()` 返回多行文本** — IT 测试需覆盖最坏情况(超长 narrative + 长 warnings 列表)

**不暴露 pipeline 内部步骤**——这是与 Pillar 1 §3.5.3 一致的硬约束。例如绝对不要：

```python
# ❌ 不要这样做
@as_tool("dcf_step_compute_wacc", ...) ...
@as_tool("dcf_step_project_fcf", ...) ...
```

理由：pipeline 是经审计、有验证、有 audit trail 的工作流。拆碎给 LLM 自由组合等于让 LLM 重新设计 DCF——违背"代码兜底"差异化。

### 4.9 工具分类清单（v1 目标）

| 类别 | 工具 | concurrency_safe | max_result_size | 备注 |
|---|---|---|---|---|
| Pipeline wrappers | `run_dcf`, `run_lbo`, `run_comps`, `run_earnings_analysis`, `run_ic_memo`, `run_equity_research`, `run_ddm` | ⚠️ 默认 True（**待 IT 验证**） | 64K | 7 个 wrapper |
| Refine wrappers | `refine_dcf`（输入 task_id + 新假设）| ✅ True | 64K | **依赖 Pillar 5 v1 task_id 决议；否则推迟到 v2** |
| Data fetchers | `get_financials`, `get_market_data`, `get_news` | ✅ True | 64K | 直接调 DataLayer |
| Filing fetcher | `get_filings` | ✅ True | **256K** | 10-K 等长文本，显式覆盖默认 |
| Watchlist ops | `get_watchlist`, `add_to_watchlist`, `remove_from_watchlist` | get/✅, mut/❌ | 64K | per-call 判断（override is_concurrency_safe） |
| Compare / portfolio | `compare_tickers`, `portfolio_summary` | ✅ True | 64K | |
| Education | `explain_metric` | ✅ True | 64K | 纯文档查询 |
| Export | `export_report_excel`, `export_report_word`, `export_report_pdf` | ❌ False | 64K | 生成文件，destructive_default = False (生成新文件不算 destructive) |

**v0.2 D5 修复 — concurrency_safe 是未验证假设**：

Pipeline wrapper 标 `concurrency_safe_default = True` 是基于"pipeline 只读、走 DataLayer cache"的假设，但 **`Pipeline.execute` 内部行为没有显式审计**：

- 是否共享 logger / 写 audit log（已知会）
- 是否读取 `deps.skill_runtime` 状态（已知会）
- 是否走 DataLayer cache 而 cache 内部并发安全（已知 Pillar 1 v0.3 N5 修复后是 WAL + asyncio.Lock，安全）

**IT-P2-05（新增）必须验证**：10 并发跑 `run_dcf` 7 次（同一 ticker + 不同 ticker 混合），结果一致、无 race、无 cache corruption。若 IT-P2-05 失败，所有 pipeline wrapper 改为 `concurrency_safe_default = False`，并发收益让位给正确性。

---

**v1 不做**：
- search / web 类工具（信息检索由 LLM 自身完成）
- 自定义 SQL / 代码执行（安全风险高）
- 邮件 / Slack 发送（v2 加 ask 模式权限后再做）

---

## 5. v1 明确推迟的功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| Streaming Tool Execution | 拓扑排序 + 流式协调高复杂度；金融 pipeline 单工具 30-60 秒，并发收益有限 | Pillar 2 v2 |
| MCP 集成（client） | audit guarantees 不明；接入 Bloomberg/外部工具 v2 评估 | Pillar 2 v2 |
| Disk persistence for big results | 需要 audit-aware 存储设计；与 audit log 协同时机不明 | Pillar 2 v2 |
| 多模态（image/video tool result） | 金融场景以文本 / 数值为主；图表用 UIAction 渲染指令而非内嵌 | v3 评估 |
| Tool aliases | 名字管好就行，aliases 会增加 prompt cache 不稳定 | 不实施 |
| Denial tracking 内置计数器 | audit log 已记录全部 denials，计数走查询 | 不实施 |
| Ask 模式权限 | v1 全 allow，v2 加 fund-level rules + ask 一起做 | Pillar 8 v2 |
| Permission rule prefix matching | v1 工具集小，硬编码即可 | Pillar 8 v2 |
| `auto` / `dontAsk` / `bypassPermissions` 权限 mode | CC 的 IDE 工作流概念，FinRobot 无对应 | 不实施 |

---

## 6. 自审与评审历程

### 6.1 v0.1 自审 8 处（v0.2 状态）

| ID | 严重度 | 问题 | v0.2 处理 |
|---|---|---|---|
| F-P2-1 | 🔴 | ~~"lambda 丢 self"~~ **诊断方向错（v0.1 评审 B4 纠正）**。真问题：同步 lambda 包装 async 函数 → `inspect.iscoroutinefunction(tool.call)` 返回 False，调度器自省失败；lambda 内异常在 await 前抛 | ✅ 已修复 — `@as_tool` 改为 `async def _call` 实方法绑定，描述符协议正常工作 |
| F-P2-2 | 🟠 | `is_read_only` / `is_destructive` 默认从 `concurrency_safe_default` 推断不严谨 | ✅ 已修复 — 拆 3 个独立 ClassVar：`concurrency_safe_default` / `read_only_default=True` / `destructive_default=False` |
| F-P2-3 | 🟠 | `ToolUseContext.messages: list[Any]` 工具能 mutate 引用 | ✅ 已修复 — 改为 `tuple["Message", ...]` 不可变 |
| F-P2-4 | 🟡 | `parse_input` Exception 兜底丢失 ValidationError 详细信息 | ✅ 已修复 — `_execute_one` 显式 catch `pydantic.ValidationError`，提取 field path + msg |
| F-P2-5 | 🟡 | `_partition` + `_execute_one` 重复 parse | ⚠️ v0.3 修复 — 当前规格仍允许 `_execute_one` 重试 parse（容忍 _partition 阶段未解析的边界），但优化空间识别 |
| F-P2-6 | 🟡 | 体积截断 mutate `result.data` | ✅ 已修复 — `ToolResult` 加 `text_for_llm` 字段，截断只写它，`data` 保持原始 |
| F-P2-7 | 🟡 | `on_progress` 回调无错误处理 | 🟢 v0.2 临时降级 — `on_progress` 已从接口移除，问题暂不存在；Pillar 1 v0.4 决议时连带处理 |
| F-P2-8 | 🟡 | `new_messages` 类型注解循环 import | ✅ 已修复 — 字符串注解 `list["Message"]` |

### 6.2 v0.1 评审反馈（v0.2 处理）

**Blocking（4 项）全部修复**：B1 pipeline wrapper 真实 API、B2 on_progress 降级公开未决、B3 Semaphore 提到 __init__、B4 F-P2-1 诊断重写。

**Design（7 项）**：
- D1 max 默认改 64K ✅
- D2 text_for_llm 字段 ✅
- D3 删除自动注册 docstring ✅
- D4 tool_extra 命名空间 ✅
- D5 concurrency 假设公开 + IT-P2-05 验证负担 ✅
- D6 refine_dcf 加 Pillar 5 触发器 ✅
- D7 deps 类型注解就地修 ✅

**Cleanup（6 项）全部修复**：f-string、_partition except 收窄、Pillar 1 v0.4 diff 不内嵌、ClassVar 拆分、自动注册矛盾、cost_hint 决议方向。

### 6.3 v0.3 自审状态

C5 修订:v0.2 §6.3 标题"v0.3 待修"已过时(本 doc 已升 v0.3)。v0.3 实质改动:
- ToolUseContext 19 字段(后 6 sub-agent 派生字段对普通工具不可见,mini-ADR-3 §5.8 不变量)
- ToolOrchestrator shared_semaphore + fork_for_subagent
- RunDCFTool 改用真实 DCFResult.implied_price

v0.3 本轮无新增自审遗留。v0.4 待处理项见 §8 未决问题(`on_progress` 进度信号机制仍未决议,等 Pillar 1 v0.7 → v0.8 联调时定)。

---

## 7. 测试要点

### 7.1 单元测试

- **UT-P2-01..05** Tool 注册：register / unregister / get / duplicate name / empty name
- **UT-P2-06** `to_api_schema()` 输出符合 Anthropic API spec
- **UT-P2-07..09** 输入验证三态：schema 通过、schema 失败、validate_input 业务失败
- **UT-P2-10..12** 权限三态：allowed、denied with reason、check_permissions 抛异常
- **UT-P2-13** ToolResult.to_text 对 str / dict / list / Pydantic / 其他类型的序列化
- **UT-P2-14** 体积截断触发 + warning 出现
- **UT-P2-15..18** Orchestrator partition：全部安全 → 1 个并发批；全部不安全 → N 个串行批；混合 → 正确分组
- **UT-P2-19** Orchestrator concurrency：5 个并发安全工具用 Semaphore 限到 max=10
- **UT-P2-20** Orchestrator 结果顺序与输入顺序一致
- **UT-P2-21** Context modifier 在并发批后统一应用、串行批立即应用
- **UT-P2-22** Tool 执行异常 → ToolResult(is_error=True) 而不抛
- **UT-P2-23** asyncio.CancelledError 正确传播（不被 catch 成 is_error）
- **UT-P2-24** on_progress 回调按预期触发
- **UT-P2-25** UIAction 和 audit_payload 字段透传到 ToolResult

### 7.2 集成测试

- **IT-P2-01** 端到端：注册 3 个工具 → orchestrator.run → 结果按输入顺序、UIAction 全捕获
- **IT-P2-02** pipeline wrapper：`run_dcf` 工具调用现有 DCFPipeline 端到端
- **IT-P2-03** 大结果截断：tool 返回 300K 字符 → 截断到 256K + warning 嵌入
- **IT-P2-04** 工具失败 + Pillar 1 熔断联动：5 次连续 is_error → consecutive_tool_failures 触发 tool_circuit_breaker

### 7.3 不需要测试的（v1 推迟）

- ~~MCP 工具集成~~
- ~~Streaming tool execution~~
- ~~Multimodal result~~
- ~~Tool aliases~~
- ~~Disk persistence~~
- ~~Permission ask mode~~

---

## 8. 未决问题

1. **`on_progress` 进度信号机制**（v0.2 B2 降级为公开未决）
   - 当前状态：BaseTool.call、ToolOrchestrator.run、_execute_one **接口签名都不含 on_progress**
   - 待决议：Generator-based vs 队列 vs callback？信号从 orchestrator 怎么流到 SSE 客户端？
   - **决议时机：Pillar 1 v0.4 联调时**——届时把接口签名同步回填，本 doc 升 v0.3
   - **重要**：Week 2 实施者不要落地 on_progress 参数，等本未决议解开

2. ~~`ToolUseContext.deps: Any` 类型注解模糊~~ ✅ **v0.2 D7 已修**（TYPE_CHECKING + 字符串注解）

3. **Refine wrapper（`refine_dcf`）的接口**——v0.2 D6 触发器
   - 输入 task_id + 新假设；task_id 的生命周期、是否跨会话有效需要定
   - **决议时机：Pillar 5 v1**（auto-compact 决议长会话内 task_id 存活）
   - **触发器**：Pillar 5 v1 在 Week 4 前未决议则 `refine_dcf` 推迟到 v2，Week 4-5 实施清单移除

4. **`cost_hint` 字段决议方向锁定**（v0.2 cleanup）
   - v1 不加，理由 YAGNI
   - **如未来引入**：应该走 `metadata.cost_hint` 让外部调度器读，**不应进 BaseTool ClassVar 污染工具签名**

5. **Pipeline wrapper 失败时是否重试**？
   - v1 **不重试**（pipeline 内部已经有 retry，外层重试有 double-spend 风险）
   - 决议明确：工具层不重试

6. **`as_tool` 装饰器生成的 class 怎么参与 type checking**？
   - 当前规格：动态构造的 class 没法被 mypy 识别为特定类型
   - 决议：v1 接受，v2 evaluate 用 protocol + Generic 解
   - 复杂工具直接继承 BaseTool 时类型完整

7. **D3 `@as_tool` 自动注册矛盾的最终决议**（v0.2 cleanup 处理）
   - v0.1 §4.3 docstring 说"自动注册"，§4.5 又说"不自动注册"，矛盾
   - **v0.2 决议：不自动注册**（与 FinRobot 现有 SkillRegistry 显式 register 模式一致）
   - §4.3 docstring 已删除矛盾陈述

---

## 9. 实施计划

### Week 2（与 Pillar 1 实施并行）

- [ ] `finrobot/conversation/tool/base.py`：BaseTool + ToolResult + UIAction + PermissionResult + ValidationResult
- [ ] `finrobot/conversation/tool/context.py`：ToolUseContext（4 个谱系字段 + deps + abort）
- [ ] `finrobot/conversation/tool/registry.py`：ToolRegistry
- [ ] `finrobot/conversation/tool/orchestrator.py`：ToolOrchestrator + _partition + _execute_one
- [ ] `finrobot/conversation/tool/decorators.py`：@as_tool（含 F-P2-1 修复）
- [ ] `finrobot/conversation/tool/errors.py`：ToolNotFound / InputValidationError
- [ ] UT-P2-01..25 单元测试

### Week 3（与 Pillar 1 端到端整合同步）

- [ ] `finrobot/conversation/tools/pipeline_tools.py`：先包 `run_dcf` 一个
- [ ] `finrobot/conversation/tools/data_tools.py`：`get_financials`、`get_market_data`
- [ ] Pillar 1 v0.4 同步：`_handle_tool_use` 加 UIAction yield 和 audit_payload 合并
- [ ] IT-P2-01..04 集成测试
- [ ] 应用本 doc §6 列出的 8 处自审修复

### Week 4-5（Pillar 1 + Pillar 2 联调收尾）

- [ ] 包装剩余 6 个 pipeline（lbo / comps / earnings_analysis / ic_memo / equity_research / ddm）
- [ ] **`refine_dcf` 实施有 Pillar 5 v1 task_id 决议作为前置条件**（v0.2 D6）
  - 若 Pillar 5 v1 在 Week 4 开始前已决议 task_id 生命周期 → 实施 refine_dcf
  - 若未决议 → 推迟到 v2，Week 4-5 不实施
- [ ] `compare_tickers` / `portfolio_summary` 工具实现
- [ ] watchlist 工具（per-call 安全判断）
- [ ] **IT-P2-05（v0.2 D5 必跑）**：10 并发跑 `run_dcf` 7 次混合 ticker，验证 pipeline wrapper 真正 concurrency_safe；若失败回退所有 wrapper 为 concurrency_safe=False

---

## 10. 参考资料

- **CC 源码**：`/Users/zhunihaoyun/Desktop/code/claude-code/src/Tool.ts`、`src/tools/`、`src/services/tools/`
- **homepilot 实现**：`/Users/zhunihaoyun/Desktop/code/zm/homepilot/engine/tool/`
- **原始研究报告**：`raw/cc-pillar-2-raw.md`、`raw/homepilot-pillar-2-raw.md`
- **前置 ADR**：
  - Pillar 1 v0.3（query loop + audit trail + hook 调用点）
  - mini-ADR-1（Hook 时机 — `pre_tool_use` / `post_tool_use` 在本 pillar 触发）
  - mini-ADR-2（Sub-agent chain — ToolUseContext 4 个谱系字段）
- **现有 FinRobot 关联模块**：
  - `finrobot/engine/pipelines/`（被 wrapper tools 调用）
  - `finrobot/engine/data/layer.py`（被 data_tools 调用）
  - `finrobot/engine/deps.py`（注入 ToolUseContext.deps）

---

## 评审 Checklist

- [ ] CC / homepilot 引用的文件名行号已抽样校验
- [ ] FinRobot 决策每条有理由列
- [ ] v1 推迟功能明确何时启动
- [ ] 8 处自审修复在 §6 列明
- [ ] 单元测试 ≥ 25、集成测试 ≥ 4
- [ ] Pillar 1 v0.4 需同步的 diff 在 §4.7 列出
- [ ] Pipeline → Tool 包装规则明确（不暴露内部步骤）
- [ ] UIAction / audit_payload 字段的端到端流转描述清楚
- [ ] 未决问题有决策时机
