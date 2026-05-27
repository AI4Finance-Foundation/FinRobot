# Pillar 1: Query Loop — 研究与 FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.7 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | v0.7 修 v0.6 评审 Blocking B1/B2 |
| **依据** | Explore 子 agent 对 CC + homepilot 的并行深度通读 + 自审 + v0.5/v0.6 评审 |
| **原始报告** | `raw/cc-pillar-1-raw.md`、`raw/homepilot-pillar-1-raw.md` |
| **决议依据** | `adrs/mini-adr-1-hook-timing.md` v1.2、`adrs/mini-adr-2-subagent-chain-id.md`、`adrs/mini-adr-3-runtime-context.md` v1.0 |

---

## Changelog

### v0.7(2026-05-12)

修 v0.6 评审 Blocking 2 项:

- **B1**:`post_model_call` hook 从"仅 COMPLETED 路径触发"改为**无条件每轮 1 次**(与 mini-ADR-1 §2.6 表对齐)。`_run_model_call` 失败路径在异常块里把已积累的 `usage` 局部变量塞进 `_OutcomeSentinel.payload`,主循环据此构造 post_model_call payload,失败时 `stop_reason` 用 `outcome.value` 兜底,`usage` 可为 None。RetryableAPIError × 3 retry 的 input/cache token 不再漏算
- **B2**:`ModelCallOutcome` 内外语义:
  - `DATA_QUALITY` → **retryable**(LLM 输出格式错误重发大概率好),从 §4.6 fatal 列表移除,改 `continue`;`_run_model_call` 内保留 `consecutive_failures += 1` 由 circuit breaker 兜底
  - `INFRASTRUCTURE` → **fatal**(网络/认证不自愈),保留 §4.6 fatal 列表,删除 `_run_model_call` 内 `consecutive_failures += 1`(写后即丢)
  - `FATAL_ERROR` → 不变,仍 fatal
  - `RETRYABLE_ERROR` → 不变,仍 continue

### v0.6(2026-05-12)

应用 mini-ADR-3 + 修 v0.5 评审 4 项 Blocking:

**Blocking 修复**:
- **B-v06-1**:`hook_registry.run(...)` 调用接口从 v0.5 的 `run(timing, state, config)` / `run(timing, tool_calls, tool_context)` 改为 mini-ADR-1 v1.1 + Pillar 8 v0.2 的真实签名 `run(timing, context: HookContext)` —— 见 §4.6 (3) / §4.8 (h)
- **B-v06-2**:加 `post_model_call` hook 调用(`_run_model_call` 成功路径末尾)+ cost metadata 聚合到 `state.cumulative_cost_usd` + pre-loop `_should_cost_break` cost guard
- **B-v06-3**:`_run_model_call` 改返回 typed `ModelCallOutcome` enum,外层据此 continue/break,不再读可能不存在的 assistant message
- **B-v06-4**:`ToolUseContext` 构造按 mini-ADR-3 §2.3 19 字段,`messages` 用 `tuple(state.messages)`,补 `audit_root_id / parent_chain_id / depth / deps` + 6 sub-agent 派生字段

**新增**:
- `ModelCallOutcome` enum(§4.7)
- `_should_cost_break(state, config)` pre-loop guard
- `_build_hook_context(state, deps, timing, payload)` HookContext 构造 helper
- `_apply_post_model_call_metadata(state, results)` cost metadata 聚合 helper
- `query_loop` 入参加 `deps: FinRobotDeps` 显式参数 + `profile: AgentProfile` + `tool_orchestrator` 已有

**Spec 引用**:`ToolUseContext` / `HookContext` / `FinRobotDeps` 完整字段表定义在 mini-ADR-3 §2.1 / §2.3 / §2.4,本 doc 不重复;只列构造样例。

### v0.5(2026-05-12)

合并 Pillar 3-8 v0.1 决议产生的对 Pillar 1 的影响：

**QueryState 字段扩展**:
- 新增 `cumulative_cost_usd: float = 0.0`（Pillar 6 cost circuit breaker 用）

**QueryConfig 字段扩展**:
- 新增 `max_cost_usd_per_turn: float | None = None`（Pillar 6 cost circuit breaker）

**Pre-loop guards 扩展**:
- 加入 `_should_cost_break(state, config)` 守卫（Pillar 6 §2.1）

**StreamEvent union 完整化**:
- Pillar 4 v0.1 已定义 12 个事件类型；Pillar 1 §4.12.1 引用 Pillar 4 定义而非自己重复

**Compact 接口**:
- `should_auto_compact()` / `do_compact()` 实现由 Pillar 5 §4.2 提供
- Pillar 1 主循环调用即可

**Hook context deps 字段**:
- HookContext 需要 deps 字段（Pillar 8 F-P8-5 自审）
- 影响 query_loop 调用 `hook_registry.run()` 时构造 context 的位置

**ToolUseContext 扩展**:
- 新增 `parent_state` 字段供 spawn_subagent tool 用（Pillar 7 F-P7-1）

**Sub-agent fork 与 Pillar 1 集成**:
- `fork_subagent_state()` 已在 v0.3 定义，Pillar 7 直接复用
- `MAX_DEPTH_HARD_CAP = 10`（v0.3）配合 Pillar 7 默认 `max_depth=3`

**未实施 / 留 v0.6**:
- F-P8-1 cost mutation 路径——hook 不直接 mutate state，需要 query_loop 在 post_model_call hook 调用后**收集 hook results 中的 cost metadata** 并 update state
- F-P8-5 HookContext.deps 显式字段（v0.2 内置 hooks 已经通过 payload["_deps"] 临时方案）

### v0.4（2026-05-12）

合并 Pillar 2 v0.2 引入的接口对接点：

- 新增 `UIActionEvent` 流事件类型（types.py），供 `_handle_tool_use` yield 给 SSE 端点 → 桌面 app
- `AuditEvent` 加 `tool_extra: dict[str, Any] | None` 字段，承载 ToolResult.audit_payload 业务字段
- `build_audit()` 加 `tool_extra` 显式参数（**不再 ** merge 进 kwargs**，避免与 tool_name/is_error 冲突）
- `_handle_tool_use` 增加：每个 ToolResult 的 ui_actions 遍历 yield UIActionEvent
- `on_progress` 进度信号机制**保持未实施**——Pillar 2 v0.2 B2 已降级为公开未决议，本 doc 暂不引入接口

### v0.3（2026-05-12）

合并 Week 0 两份 mini-ADR 决议 + 自审 11 处修复：

**mini-ADR-1（Hook 时机）合并**：
- 7 个 hook 时机：`loop_start` / `pre_model_call` / `post_model_call` / `pre_tool_use` / `post_tool_use` / `pre_compact` / `loop_terminate`
- 执行模型：async + 顺序 + 失败默认非阻塞 + 仅 in-process callback
- HookResult dataclass + last-write-wins modified_input 语义
- 每个时机的 payload schema 已定义

**mini-ADR-2（Sub-agent chain）合并**：
- QueryState 新增 3 字段：`audit_root_id` / `parent_chain_id` / `depth`
- `audit_root_id` 默认 None，__post_init__ 自动对齐为 audit_chain_id（F2.1）
- `MAX_DEPTH_HARD_CAP = 10` 防御性约束 + 一致性 invariants
- Fork helper 默认 max_depth=3，明确不继承的 10 个字段

**§8.1 Week 0 mini-ADR 标记为已决议** ✅

### v0.2（2026-05-12）

修复 v0.1 评审反馈：

**Blocking（4 项）**：
- B1：废除 `sink=yield_` 反模式，所有 helper 改为 `async def ... -> AsyncGenerator`，外层用 `async for ev in helper(...): yield ev` 转发
- B2：escalate 改为 model-aware，引入 `ModelCapability` 注册表；DeepSeek 等硬上限 8k 的模型 escalate 是 no-op，直接进 recovery
- B3：废除"loop 内改 config"反模式，运行时 max_tokens 通过 `resolved_max_tokens(state, config)` 计算，state 持有 override
- B4：删除 exhausted 路径里写后即丢的 `consecutive_failures += 1`，由 audit event 携带最终状态

**Design（6 项）**：
- D1：删除全部 LiteLLM 提及，明确 ModelAdapter 仅 PydanticAIAdapter 一种 v1 实现（CLAUDE.md 第 11 行硬约束）
- D2：新增 §3.5 Runtime Topology，写清新 loop 与现有 SDK / server / pipelines 的共存策略
- D3：删除 AuditEmitter 类，AuditEvent 直接 `dataclass(...)` 构造并 yield，上游 SSE 端点按类型分流
- D4：写明 ModelAdapter 契约必须把所有 provider 的拒答信号 normalize 成 `stop_reason="refusal"`，原始信号入 audit
- D5：prompt caching 改为打在最近 assistant 边界，不再回避 tool_result
- D6：拆出 `AgentProfile`，analyst_style / market / fund_id 从 QueryConfig 移出

**Cleanup（6 项）**：
- `SystemError` → `InfrastructureError`（避免遮蔽 Python 内置）
- `datetime.utcnow()` → `datetime.now(timezone.utc)`（3.12 deprecated）
- 路径 `engine/agents/` → `finrobot/engine/agents/`
- 明确 `session_id` vs `audit_chain_id` 语义
- 主循环补 `try/finally` 处理 cancellation
- §8 里影响公共接口的两条（chain_id 父子、hook pre/post）提到 Week 0 mini-ADR

---

## 0. TL;DR

- **CC 的 query loop** 是一个 30+ 分支的多阶段恢复状态机（5 层错误恢复 + 5 种压缩策略 + fallback model + streaming tool exec）
- **homepilot** 用 Python 复刻了其中约 30% 核心（单层恢复、单一压缩、greedy partitioning），骨架正确但有 7 处坑
- **FinRobot v1 决策**：以 homepilot 为骨架启动，**针对金融分析场景补 7 项 CC 关键缺失**（model-aware escalate、prompt cache、错误分类、refusal 跨 provider normalization、双语 recovery、工具失败熔断、内嵌 audit trail）；**明确推迟 10 项高复杂度特性**
- **实施工程量**：3 周完成 Pillar 1 完整版（含 Week 0 两个 mini-ADR）

---

## 1. Pillar 1 的位置

Query Loop 是 agent 状态机本体：**用户消息进来 → 模型调用 ↔ 工具执行 ↔ 状态判断 ↔ 下一轮，直到 agent 停止**。

没有这个 loop，FinRobot 只是一次性 prompt / 一次性响应的 chatbot；有了它，agent 才能完成"读 10-K → 找 peer → 算 WACC → 写 narrative"这种多步骤推理工作流。

Pillar 1 是其他 7 个 pillar 的承载体。Pillar 2（tool 系统）、5（auto-compact）、7（sub-agent）、8（hooks）都在 query loop 内部被调用或被穿插。**Pillar 1 设计错了，其他 pillar 全部受连累**。

---

## 2. 调研结论摘要

### 2.1 Claude Code 实现（详见 `raw/cc-pillar-1-raw.md`）

- **入口**：`query()` → `queryLoop()`，`src/query.ts:219-1729`
- **核心**：`while (true)` 多阶段状态机，每轮跑 6 个阶段（pre-API → API → post-streaming → tool exec → attachments → continue/terminate）
- **5 层错误恢复阶梯**（按损失递增尝试）：
  1. Context collapse drain（最便宜）
  2. Reactive compact
  3. Max_tokens escalate（一次性 8k→64k）
  4. Max_tokens recovery（最多 3 次，注入 resume 消息）
  5. Fallback model（如配置）
- **退出条件 9 种**：completed / max_turns / aborted_streaming / aborted_tools / prompt_too_long / image_error / blocking_limit / model_error / hook_stopped
- **关键能力**：streaming tool execution、prompt caching、stop hooks、fallback model、tool use summary（Haiku 异步）

### 2.2 homepilot 实现（详见 `raw/homepilot-pillar-1-raw.md`）

- **入口**：`async def query_loop(...)`，`engine/query/loop.py:108`
- **核心**：显式 `while True` + Pydantic state，约 250 行
- **简化策略**：单层错误恢复、单一 auto-compact 阈值、LiteLLM 多 provider、无 streaming tool exec / 无 fallback / 无 prompt caching
- **7 处问题**：见下文 §6

---

## 3. CC vs homepilot vs FinRobot 决策对照

| 维度 | CC | homepilot | **FinRobot 决策** | 理由 |
|---|---|---|---|---|
| 入口签名 | AsyncGenerator | AsyncGenerator | **AsyncGenerator** | 与上游 SSE 对齐 |
| 状态管理 | 单 State 扁平 | Pydantic QueryState | **dataclass QueryState（扩展）** | 类型安全 + 可持久化 |
| 模型客户端 | Anthropic SDK 直调 | LiteLLM | **PydanticAI（保留现状）+ ModelAdapter Protocol** | CLAUDE.md 禁 LiteLLM；现有 PydanticAI 投资不打破。多 provider 路由是独立 ADR |
| 流式 vs 非流式 | 流式 + fallback 非流式 | 仅流式 | **仅流式（v1）** | 简化，非流式 fallback v2 评估 |
| max_turns 默认 | 调用方传入 | 50 | **30** | 金融分析单次 task 通常 < 30 轮 |
| Max tokens recovery | escalate 1 + recovery 3 | recovery 3 | **model-aware escalate + recovery 3** | 模型硬上限不一样，escalate 在 DeepSeek 上是 no-op |
| Circuit breaker | 隐式（多种限制） | consecutive_failures >= 3 | **显式 + 工具失败也计数** | 修复 homepilot bug |
| Auto-compact | 多策略 | 单一阈值 | **阈值触发（v1）+ reactive compact 占位（v2）** | v1 简化 |
| 工具并发 | streaming tool exec | greedy partitioning | **greedy partitioning** | streaming tool exec 复杂度过高，v2 再加 |
| Tool 失败 | 不直接计入 | 不计入 | **5 个连续 is_error 计 1 次熔断** | 防止工具 bug 让 loop 烧钱 |
| Fallback model | 完整支持 | 无 | **v1 不做，v2 必加** | DeepSeek ↔ Claude 真实需求 |
| Stop hooks | 完整 | 参数预留 | **预留 hook 点（noop 实现）** | 与 Pillar 8 协同 |
| Prompt caching | 系统提示 + 最后用户消息 | 不用 | **系统提示末尾 + 最近 assistant 边界** | 工具密集会话也能命中 cache |
| Stop reason 处理 | 5 种 | 3 种 + 默认 | **3 种 + 显式 refusal 分支 + ModelAdapter normalize** | 跨 provider refusal 信号差异巨大 |
| Recovery 消息 | 英文 | 英文 | **按 config.language 双语** | 中文用户体验 |
| Audit trail | 通过 hooks 部分 | 无 | **AuditEvent 直接 yield 入 union stream** | FinRobot 核心差异化 |
| 错误分类 | 细分 | 单一 except Exception | **分 4 类：retryable / fatal / data_quality / infrastructure** | 工程债防控 |
| Tool result 体积上限 | (依赖工具) | 100k 字符 | **256k 字符** | 金融 10-K 经常 > 100k |

---

## 3.5 Runtime Topology（NEW）

> Pillar 1 引入的是**顶层对话状态机**，需要明确它与现有 FinRobot 入口的关系。

### 3.5.1 现状（v0 / 当前 main 分支）

```
                ┌─────────────────────┐
   CLI ────→    │   FinRobot SDK      │
   Python use ─→│   (finrobot/sdk.py) │ ──→ 选 pipeline → run → 返回 PipelineResult
                └─────────────────────┘                        ↑
                                                 (用 lead_agent + sub_agents 编排)
                ┌─────────────────────┐
   HTTP ────→   │ FastAPI server      │ ──→ routes/{ask,compute,data,export,runs}
   Desktop  ──→ │ (finrobot/server.py)│           ↑
                └─────────────────────┘   (调用 SDK 或 pipeline factory)

Pipeline 注册表 (engine/pipelines/registry.py):
  - dcf, ddm, comps, lbo, ic_memo, earnings_analysis, equity_research, ...
```

入口形态：**一次性 task**。用户给 ticker + pipeline 类型，系统跑完返回完整 result。没有"持续对话"概念，没有"用户改假设后只重算下游"的能力。

### 3.5.2 v1 目标拓扑（Pillar 1 完工后）

```
                ┌─────────────────────────┐
   CLI ────→    │   FinRobot SDK          │  保留：脚本、CI、批处理
   Python use ─→│   .research() .dcf()    │       一次性 pipeline 调用
                └─────────────────────────┘
                          │
                          ▼
                ┌─────────────────────────┐
                │   Pipeline Registry     │  ←─ 单一事实源
                └─────────────────────────┘
                          ▲
                          │ (作为 conversational tool)
                ┌─────────────────────────┐
   HTTP /api/   │ FastAPI server          │
   chat ───────→│   POST /api/chat/...    │ ──→ query_loop (NEW, Pillar 1)
                │   GET  routes/*         │ ──→ 旧 pipeline 入口（保留）
                └─────────────────────────┘
                          ↑
                          │
   Desktop ────────────────┘
   - 左：watchlist / coverage 列表（旧入口，一键 run pipeline）
   - 右：chat panel（新入口，走 query_loop）
```

**核心原则**：
1. **Pipeline 是单一事实源**。`engine/pipelines/registry.py` 已经是注册表，conversation tools 注册的是"运行某个 pipeline"的包装函数，**不是把 pipeline 内部步骤拆开暴露给 LLM**
2. **新旧入口并存，不替换**。SDK 的 `agent.research("AAPL")` 一次性调用永远保留——它服务 CI、批处理、脚本场景，比对话快
3. **对话入口是新增能力**，覆盖"用户想边讨论边调假设"的场景，**不替代**"用户想要一份完整研报"的场景
4. **桌面 app v1 双栏**：左侧 watchlist + 一键 run（旧入口），右侧 chat panel（新入口）

### 3.5.3 Pipeline → Conversational Tool 包装规则

每个 pipeline 在 conversation 中注册为**一个工具**（不暴露内部步骤）：

```python
# finrobot/conversation/tools/pipeline_tools.py（v1 新增）

@register_tool(
    name="run_dcf",
    description="Run full DCF valuation pipeline on a ticker. Returns fair value + sensitivity.",
    concurrency_safe=True,  # 只读型
)
async def tool_run_dcf(args: DCFArgs, context: ToolUseContext) -> ToolResult:
    factory = pipeline_factories["dcf"]
    pipeline = factory(deps=context.deps)
    result: PipelineResult = await pipeline.run(args.ticker, args.assumptions)
    return ToolResult(
        data=result.summary,  # 给 LLM 的简洁摘要
        ui_actions=[
            {"type": "render_report", "id": result.task_id},
            {"type": "show_assumption_panel", "task_id": result.task_id,
             "editable": ["wacc", "terminal_growth"]},
        ],
        new_messages=[],
    )
```

**反例**（不要这么做）：

```python
# ❌ 错：把 pipeline 内部步骤拆给 LLM
@register_tool("dcf_step_compute_wacc")
@register_tool("dcf_step_project_fcf")
@register_tool("dcf_step_calculate_terminal_value")
@register_tool("dcf_step_discount")
```

理由：pipeline 已经是经过审计的、有验证的、有 audit trail 的工作流。把它拆碎给 LLM 自由组合，等于让 LLM 重新设计 DCF 流程——这违背 FinRobot 的"代码兜底"差异化。

### 3.5.4 迁移路径（v1 → v2+）

| 阶段 | 月份 | 动作 |
|---|---|---|
| v1 | M1-3 | 对话入口与旧入口并存；桌面 app 双栏 |
| v1.5 | M4-6 | 对话入口能力反超：refinement loop（改 WACC 局部重算）只在 conversation 里支持 |
| v2 | M7-12 | 旧 pipeline 直接入口在 desktop 上隐藏到"高级"菜单；chat 成主入口 |
| v3 | M12+ | SDK 的 `agent.research()` 保留供脚本/CI；UI 层只暴露 chat |

---

## 4. FinRobot 实现规格

### 4.1 模块结构

```
finrobot/conversation/                     # 全部新增
├─ __init__.py
├─ loop.py                # query_loop 主体（本 pillar）
├─ state.py               # QueryState
├─ config.py              # QueryConfig
├─ profile.py             # AgentProfile（NEW v0.2，从 QueryConfig 拆出）
├─ types.py               # StreamEvent / Message / ContentBlock / AuditEvent
├─ adapter.py             # ModelAdapter Protocol + PydanticAIAdapter
├─ model_registry.py      # ModelCapability 注册（NEW v0.2）
├─ orchestrator.py        # ToolOrchestrator（Pillar 2 详细设计）
├─ compact.py             # auto-compact（Pillar 5 详细设计，本 pillar 仅留接口）
├─ hooks.py               # HookRegistry（Pillar 8 详细设计，本 pillar 仅留接口）
├─ errors.py              # 4 类错误体系
└─ messages.py            # 双语消息字典 + recovery_msg(lang) 等

finrobot/conversation/tools/               # 全部新增
├─ __init__.py
├─ pipeline_tools.py      # 把现有 engine/pipelines/ 包装为 conversational tools
└─ data_tools.py          # get_financials / get_news / get_filings 等基础工具
```

### 4.2 入口签名

```python
# finrobot/conversation/loop.py

from collections.abc import AsyncGenerator

async def query_loop(
    state: QueryState,
    config: QueryConfig,
    deps: "FinRobotDeps",              # v0.6 新增,mini-ADR-3 §2.1
    profile: "AgentProfile",            # v0.6 新增,供 ToolUseContext sub-agent 字段
    model_adapter: ModelAdapter,
    tool_orchestrator: ToolOrchestrator,
    tool_registry: ToolRegistry,
    hook_registry: "HookRegistry | None" = None,
) -> AsyncGenerator[StreamEvent | AuditEvent, None]:
    """FinRobot 的 agent 状态机循环。

    每轮:守卫(max_turns / circuit / cost) → auto-compact → pre_model_call hook
    → 模型调用 → post_model_call hook + cost 聚合 → stop_reason 分支 →
    可选工具执行(pre/post_tool_use hook) → continue/break。

    输出混合流:
    - StreamEvent: 上游 SSE 端点过滤后转发给客户端
    - AuditEvent:  上游写入 audit log,不发给客户端

    v0.6 行为变更:
    - deps 必传(mini-ADR-3 §5 fail-fast assert),用于 HookContext.deps / ToolUseContext.deps
    - profile 必传,供 ToolUseContext.parent_profile(sub-agent fork 时被 agent_def 覆盖)
    - hook_registry 调用全部走 `run(timing, context: HookContext)` 单参签名
    - 加 _should_cost_break pre-loop guard
    - _run_model_call 改返回 ModelCallOutcome(不再隐式 mutate + return)

    取消语义:调用方 .aclose() 时进入 try/finally 路径,emit
    loop_terminate AuditEvent(reason="cancelled"),所有未完成 tool task 被取消。
    """

    # mini-ADR-3 §5 不变量 5: conversation 用字段 fail-fast
    _assert_conversation_deps(deps)
```

### 4.3 QueryState

```python
# finrobot/conversation/state.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


MAX_DEPTH_HARD_CAP = 10
"""硬上限：QueryState 任何路径构造（含直接 QueryState(depth=...)）都不允许超过。
   Fork helper 默认软上限 3，可调。详见 mini-ADR-2 §2.1。"""


@dataclass
class QueryState:
    """运行时可变状态。每个 query_loop 调用持有一份。"""

    # ─── 会话身份 ───
    session_id: str
    """用户可见的会话 ID（一个会话可含多次 query_loop 调用，跨多个 user turn）。"""

    user_id: str
    fund_id: str
    """FinRobot 多租户关键，从 user_id 派生。"""

    # ─── Audit 谱系（v0.3 合并 mini-ADR-2）───
    audit_chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """本次 query_loop 调用的事件 ID。
    主 agent: 新 UUID；Sub-agent: 新 UUID（与父隔离，不继承）。
    "这个 sub-agent 干了什么"用此 ID 查询。"""

    audit_root_id: str | None = None
    """整棵 agent 树的根 ID。
    主 agent: __post_init__ 自动设置 == audit_chain_id；
    Sub-agent: 由 fork_subagent_state 显式传入父的 root_id。
    "这次 user turn 涉及全部 agent" 用此 ID 聚合查询。"""

    parent_chain_id: str | None = None
    """直接父 query_loop 的 audit_chain_id。
    主 agent: None；Sub-agent: 父的 chain_id。"""

    depth: int = 0
    """谱系深度。主 agent: 0；Sub-agent: parent.depth + 1。"""

    # ─── 消息历史 ───
    messages: list[Message] = field(default_factory=list)

    # ─── 计数与限制 ───
    turn_count: int = 0
    consecutive_failures: int = 0          # 模型 API 失败计数
    consecutive_tool_failures: int = 0     # 工具失败计数（FIX homepilot bug）
    cumulative_cost_usd: float = 0.0       # v0.5: cost circuit breaker（Pillar 6）

    # ─── 恢复跟踪 ───
    max_output_tokens_recovery_count: int = 0
    max_output_tokens_override: int | None = None
    has_attempted_escalate: bool = False

    # ─── 压缩跟踪 ───
    compact_tracking: CompactTracking | None = None

    # ─── 状态转移 ───
    transition: Transition | None = None

    # ─── Token 累计 ───
    total_usage: TokenUsage = field(default_factory=TokenUsage)

    # ─── 时间戳 ───
    started_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        # F2.1: audit_root_id 自动对齐为 chain_id（仅当未显式传入）
        if self.audit_root_id is None:
            self.audit_root_id = self.audit_chain_id

        # F2.2: depth 硬上限
        if self.depth > MAX_DEPTH_HARD_CAP:
            raise ValueError(
                f"QueryState.depth = {self.depth} exceeds hard cap "
                f"{MAX_DEPTH_HARD_CAP}. Use fork_subagent_state() to control growth."
            )

        # 一致性 invariants
        if self.depth == 0:
            if self.parent_chain_id is not None:
                raise ValueError("Top-level state (depth=0) must have parent_chain_id=None.")
            if self.audit_root_id != self.audit_chain_id:
                raise ValueError("Top-level state must have audit_root_id == audit_chain_id.")
        else:
            if self.parent_chain_id is None:
                raise ValueError(f"Sub-agent state (depth={self.depth}) must have parent_chain_id.")

    # ─── 守卫方法 ───
    def should_stop_max_turns(self, max_turns: int) -> bool:
        return self.turn_count >= max_turns

    def should_circuit_break(self, threshold: int) -> bool:
        return self.consecutive_failures >= threshold

    def should_tool_circuit_break(self, threshold: int) -> bool:
        return self.consecutive_tool_failures >= threshold


def create_top_level_state(
    *, session_id: str, user_id: str, fund_id: str
) -> QueryState:
    """主 agent（user turn 入口）的 QueryState 工厂。

    __post_init__ 会自动让 audit_root_id == audit_chain_id。
    """
    return QueryState(
        session_id=session_id, user_id=user_id, fund_id=fund_id,
    )


def fork_subagent_state(
    parent_state: QueryState,
    *,
    initial_messages: list[Message],
    max_depth: int = 3,
) -> QueryState:
    """Sub-agent fork 工厂。详见 mini-ADR-2 §2.3。

    继承：session_id / user_id / fund_id / audit_root_id / parent_chain_id 指向父
    重置：所有失败计数 / recovery / escalate / compact / transition / usage
    """
    if parent_state.depth >= max_depth:
        raise SubAgentDepthExceeded(
            f"Cannot spawn sub-agent at depth {parent_state.depth + 1}, "
            f"max_depth = {max_depth}."
        )

    return QueryState(
        session_id=parent_state.session_id,
        user_id=parent_state.user_id,
        fund_id=parent_state.fund_id,
        audit_root_id=parent_state.audit_root_id,
        parent_chain_id=parent_state.audit_chain_id,
        depth=parent_state.depth + 1,
        messages=initial_messages,
        # 其他字段全部走 dataclass 默认值（0 / None / 空）
    )
```

### 4.4 QueryConfig + AgentProfile（NEW v0.2 拆分）

```python
# finrobot/conversation/config.py

from dataclasses import dataclass
from typing import Literal


@dataclass
class QueryConfig:
    """Loop 控制配置。只包含 query_loop 直接读取的参数。"""

    # ─── 必需 ───
    model: str
    system_prompt: str
    """已经装配好的完整 system prompt。Profile 的注入在外层 system_prompt builder 完成。"""

    # ─── 限制 ───
    max_turns: int = 30
    max_output_tokens: int | None = None
    """用户显式覆盖。None 时用 ModelRegistry 提供的默认。"""

    max_output_tokens_escalated: int = 64_000
    """Escalate 目标值。实际生效值是 min(此值, model.hard_max_output)。"""

    # ─── 失败恢复 ───
    circuit_breaker_threshold: int = 3
    tool_circuit_breaker_threshold: int = 5
    max_output_tokens_recovery_limit: int = 3

    # ─── 采样 ───
    temperature: float | None = None

    # ─── Loop 行为 ───
    language: Literal["zh", "en"] = "zh"
    """影响 recovery / error 消息的展示语言。"""

    use_prompt_caching: bool = True
    """仅在 model 由 ModelRegistry 标记为支持 caching 时生效。"""

    # ─── Cost circuit breaker（v0.5，Pillar 6）───
    max_cost_usd_per_turn: float | None = None
    """单次 user turn cost 上限。None = 不检查。建议生产值 0.50 USD。"""


# finrobot/conversation/profile.py（NEW v0.2）

@dataclass
class AgentProfile:
    """Agent 人格画像 + 业务上下文。由外层 system_prompt builder 消费，
    不直接进入 query_loop。loop 不读这些字段。"""

    analyst_style: Literal["value", "growth", "quant", "education", "ic_memo"] = "value"
    """v0.6 加 'ic_memo'(评审一致性修复:Pillar 3 §4.3 5 种 + README 描述与 Pillar 1 v0.5 仅 4 种不一致)"""
    market: Literal["us", "cn", "hk", "global"] = "us"
    fund_id: str | None = None
    fund_style: str | None = None
    """e.g. 'long-only value', 'event-driven', 'systematic'."""
    covered_tickers: list[str] = field(default_factory=list)
    """Watchlist 注入到 system prompt 用。"""

    # builder 调用方式：
    #   system_prompt = build_system_prompt(profile, additional_context)
    #   config = QueryConfig(model=..., system_prompt=system_prompt, ...)
```

### 4.5 ModelRegistry（NEW v0.2，B2 核心修复）

```python
# finrobot/conversation/model_registry.py

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapability:
    name: str
    default_max_output: int       # 厂商默认 max_tokens
    hard_max_output: int          # 厂商硬上限（escalate 不能超过这个）
    supports_prompt_caching: bool
    supports_thinking: bool        # 预留，本 pillar 不用
    supports_streaming: bool = True

    @property
    def escalate_useful(self) -> bool:
        """如果硬上限 == 默认，escalate 是 no-op。"""
        return self.hard_max_output > self.default_max_output


MODEL_REGISTRY: dict[str, ModelCapability] = {
    # Anthropic
    "anthropic:claude-opus-4-7":   ModelCapability(name="...", default_max_output=8_192,  hard_max_output=64_000, supports_prompt_caching=True,  supports_thinking=True),
    "anthropic:claude-sonnet-4-6": ModelCapability(name="...", default_max_output=8_192,  hard_max_output=64_000, supports_prompt_caching=True,  supports_thinking=True),
    "anthropic:claude-haiku-4-5":  ModelCapability(name="...", default_max_output=8_192,  hard_max_output=8_192,  supports_prompt_caching=True,  supports_thinking=False),

    # DeepSeek（硬上限 8k——escalate 是 no-op）
    "deepseek:deepseek-chat":      ModelCapability(name="...", default_max_output=8_192,  hard_max_output=8_192,  supports_prompt_caching=False, supports_thinking=False),
    "deepseek:deepseek-reasoner":  ModelCapability(name="...", default_max_output=8_192,  hard_max_output=8_192,  supports_prompt_caching=False, supports_thinking=True),

    # OpenAI
    "openai:gpt-4o":               ModelCapability(name="...", default_max_output=16_384, hard_max_output=16_384, supports_prompt_caching=False, supports_thinking=False),
    "openai:gpt-4o-mini":          ModelCapability(name="...", default_max_output=16_384, hard_max_output=16_384, supports_prompt_caching=False, supports_thinking=False),
}


def get_capability(model: str) -> ModelCapability:
    if model not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model '{model}'. Register in MODEL_REGISTRY first. "
            f"Available: {sorted(MODEL_REGISTRY.keys())}"
        )
    return MODEL_REGISTRY[model]


def resolved_max_tokens(state: QueryState, config: QueryConfig) -> int:
    """计算本轮调用应使用的 max_tokens。

    优先级（从高到低）：
      1. state.max_output_tokens_override（escalate 写入的运行时值）
      2. config.max_output_tokens（用户显式覆盖）
      3. registry 默认
    """
    if state.max_output_tokens_override is not None:
        return state.max_output_tokens_override
    if config.max_output_tokens is not None:
        return config.max_output_tokens
    return get_capability(config.model).default_max_output


def can_escalate(state: QueryState, config: QueryConfig) -> tuple[bool, int]:
    """检查能否 escalate 以及目标值。

    Returns:
        (能否 escalate, 目标 max_tokens)。

    如果模型硬上限 == 当前生效值（如 DeepSeek 在默认 8k 下），escalate 无意义，
    返回 (False, _)。Loop 据此跳到 recovery 阶段。
    """
    if state.has_attempted_escalate:
        return False, 0

    cap = get_capability(config.model)
    current = resolved_max_tokens(state, config)
    target = min(config.max_output_tokens_escalated, cap.hard_max_output)

    if target <= current:
        return False, current

    return True, target


def should_use_caching(config: QueryConfig) -> bool:
    if not config.use_prompt_caching:
        return False
    return get_capability(config.model).supports_prompt_caching
```

### 4.6 主循环骨架(v0.6 重写:hook 接口对齐 + cost guard + typed outcome)

```python
# finrobot/conversation/loop.py

import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from .audit import AuditEvent, build_audit
from .hooks import HookContext, HookResult
from .messages import recovery_msg, exhausted_msg, circuit_breaker_msg, tool_circuit_breaker_msg, refusal_compliance_msg, cost_break_msg
from .model_registry import resolved_max_tokens, can_escalate, should_use_caching


async def query_loop(
    state: QueryState,
    config: QueryConfig,
    deps: "FinRobotDeps",
    profile: "AgentProfile",
    model_adapter: ModelAdapter,
    tool_orchestrator: ToolOrchestrator,
    tool_registry: ToolRegistry,
    hook_registry: "HookRegistry | None" = None,
) -> AsyncGenerator[StreamEvent | AuditEvent, None]:

    _assert_conversation_deps(deps)  # mini-ADR-3 §5 fail-fast

    yield build_audit("loop_start", state=state)

    # (a) loop_start hook
    if hook_registry:
        ctx = _build_hook_context(state, deps, "loop_start", payload={})
        await hook_registry.run("loop_start", ctx)

    try:
        while True:
            # ─── (1) Pre-loop guards ───
            if state.should_stop_max_turns(config.max_turns):
                yield build_audit("loop_terminate", state=state, reason="max_turns")
                return

            if state.should_circuit_break(config.circuit_breaker_threshold):
                yield ErrorEvent(
                    error_type="CircuitBreaker",
                    message=circuit_breaker_msg(config.language, state.consecutive_failures),
                )
                yield build_audit("loop_terminate", state=state, reason="circuit_breaker")
                return

            if state.should_tool_circuit_break(config.tool_circuit_breaker_threshold):
                yield ErrorEvent(
                    error_type="ToolCircuitBreaker",
                    message=tool_circuit_breaker_msg(config.language, state.consecutive_tool_failures),
                )
                yield build_audit("loop_terminate", state=state, reason="tool_circuit_breaker")
                return

            # v0.6 新增:cost circuit breaker(Pillar 6 §2.1)
            if _should_cost_break(state, config):
                yield ErrorEvent(
                    error_type="CostCircuitBreaker",
                    message=cost_break_msg(config.language,
                                            state.cumulative_cost_usd,
                                            config.max_cost_usd_per_turn),
                )
                yield build_audit("loop_terminate", state=state, reason="cost_break",
                                   cumulative_cost_usd=state.cumulative_cost_usd)
                return

            # ─── (2) Auto-compact ───
            if await should_auto_compact(state, config):
                # pre_compact hook
                if hook_registry:
                    ctx = _build_hook_context(state, deps, "pre_compact", payload={})
                    results = await hook_registry.run("pre_compact", ctx)
                    if any(r.block for r in results):
                        # 跳过本次 compact(mini-ADR-1 §2.6)
                        yield build_audit("compact_skipped", state=state,
                                           reason=next((r.reason for r in results if r.block), None))
                    else:
                        await do_compact(state, model_adapter, config)
                        yield build_audit("compact", state=state)
                else:
                    await do_compact(state, model_adapter, config)
                    yield build_audit("compact", state=state)

            # ─── (3) Pre-model-call hook ───
            if hook_registry:
                ctx = _build_hook_context(state, deps, "pre_model_call",
                                           payload={"model": config.model})
                results = await hook_registry.run("pre_model_call", ctx)
                if any(r.block for r in results):
                    block_reason = next((r.reason for r in results if r.block), "blocked by hook")
                    yield ErrorEvent(error_type="HookBlock", message=block_reason)
                    yield build_audit("loop_terminate", state=state, reason="hook_stopped")
                    return

            # ─── (4) 模型调用(v0.6: 返回 typed outcome,不再读 _last_stop_reason)───
            outcome: ModelCallOutcome | None = None
            outcome_payload: dict | None = None
            async for event in _run_model_call(state, config, model_adapter, tool_registry):
                if isinstance(event, _OutcomeSentinel):
                    outcome = event.outcome
                    outcome_payload = event.payload  # v0.7: 含 usage / duration_ms / stop_reason
                else:
                    yield event
            assert outcome is not None, "_run_model_call must emit ModelCallOutcome sentinel"

            # ─── (4.5) post_model_call hook —— v0.7 B1 修复:每轮无条件触发(mini-ADR-1 §2.6)───
            if hook_registry:
                # 成功路径:从最新 assistant message 取 stop_reason / usage
                # 失败路径:从 outcome_payload 取 usage(已积累,可能 None),stop_reason 用 outcome.value 兜底
                if outcome == ModelCallOutcome.COMPLETED:
                    last_assistant = state.messages[-1]
                    if isinstance(last_assistant, AssistantMessage):
                        post_stop_reason = last_assistant.stop_reason
                        post_usage = last_assistant.usage
                    else:
                        # 防御性:_run_model_call 成功路径必 append AssistantMessage,
                        # 这里到不了。万一到了,降级到 outcome_payload。
                        post_stop_reason = (outcome_payload or {}).get("stop_reason")
                        post_usage = (outcome_payload or {}).get("usage")
                else:
                    post_stop_reason = (outcome_payload or {}).get("stop_reason") or outcome.value
                    post_usage = (outcome_payload or {}).get("usage")  # 失败路径可 None

                ctx = _build_hook_context(
                    state, deps, "post_model_call",
                    payload={
                        "model": config.model,
                        "stop_reason": post_stop_reason,
                        "usage": post_usage,
                        "duration_ms": (outcome_payload or {}).get("duration_ms"),
                    },
                )
                results = await hook_registry.run("post_model_call", ctx)
                _apply_post_model_call_metadata(state, results)

            # ─── (5) Outcome 分支(v0.7 B2 修复:DATA_QUALITY 改 retryable)───
            if outcome in (ModelCallOutcome.FATAL_ERROR,
                            ModelCallOutcome.INFRASTRUCTURE):
                yield build_audit("loop_terminate", state=state,
                                   reason=outcome.value)
                return

            if outcome in (ModelCallOutcome.RETRYABLE_ERROR,
                            ModelCallOutcome.DATA_QUALITY):
                # 计数已在 _run_model_call 内累加,下一轮 pre-loop guard 触发 circuit breaker
                continue

            # outcome == COMPLETED:读最新 assistant message 的 stop_reason
            last_assistant = state.messages[-1]
            stop_reason = getattr(last_assistant, "stop_reason", None)
            content_blocks = last_assistant.content
            tool_use_blocks = [b for b in content_blocks if isinstance(b, ToolUseBlock)]

            if stop_reason == "tool_use" or tool_use_blocks:
                async for event in _handle_tool_use(
                    state, config, deps, profile, tool_orchestrator,
                    tool_registry, tool_use_blocks, hook_registry,
                ):
                    yield event
                continue

            if stop_reason == "max_tokens":
                async for event in _handle_max_tokens(state, config):
                    yield event
                if state.transition is None or state.transition.reason == "max_tokens_exhausted":
                    return
                continue

            if stop_reason == "refusal":
                yield SystemMessage(content=refusal_compliance_msg(config.language))
                yield build_audit("refusal", state=state)
                return

            # end_turn / stop_sequence / 其他 → 正常退出
            yield build_audit("loop_terminate", state=state, reason="end_turn")
            return

    except GeneratorExit:
        # Caller .aclose() 时进入此分支（cancellation）
        yield build_audit("loop_terminate", state=state, reason="cancelled")
        # tool tasks 的取消由 ToolOrchestrator 内部 asyncio.gather 的传播完成；
        # 这里不需要显式取消（外层 generator 关闭 → 内层 async for 中断 →
        # gather 收到 CancelledError → 所有 tool task cancel）。
        raise

    except Exception as exc:
        # 顶层兜底：永远不让 query_loop 抛裸异常给上游
        yield ErrorEvent(error_type="LoopFailure", message=str(exc))
        yield build_audit("loop_terminate", state=state, reason="exception", error=exc)
        return
```

### 4.7 Helper: 模型调用(v0.6: typed outcome,Blocking-3 修复)

```python
from enum import Enum
from dataclasses import dataclass


class ModelCallOutcome(str, Enum):
    """_run_model_call 返回的状态机信号(v0.6 新增)。

    Loop 据此分支,不再读 _last_stop_reason(state.messages) —— 因为失败路径
    根本没 append assistant message,旧逻辑会读旧消息或崩(v0.5 Blocking 3)。
    """
    COMPLETED = "completed"
    RETRYABLE_ERROR = "retryable_error"
    FATAL_ERROR = "fatal_error"
    DATA_QUALITY = "data_quality"
    INFRASTRUCTURE = "infrastructure"


@dataclass
class _OutcomeSentinel:
    """内部 sentinel,通过 yield 把 outcome 传给主循环。

    v0.7 加 payload:失败路径在异常块里已积累的 usage / stop_reason / duration_ms
    塞进 payload,供主循环 post_model_call hook 用(B1 修复)。
    """
    outcome: ModelCallOutcome
    payload: dict = field(default_factory=dict)


async def _run_model_call(
    state: QueryState,
    config: QueryConfig,
    model_adapter: ModelAdapter,
    tool_registry: ToolRegistry,
) -> AsyncGenerator[StreamEvent | AuditEvent | _OutcomeSentinel, None]:
    """流式调用模型。成功路径推进 state.messages + state.turn_count,
    失败路径只累加 retryable 计数器,**不读不写 messages**(B3 修复)。

    最后一定 yield 一个 _OutcomeSentinel(outcome=..., payload=...) 告诉主循环结果。
    payload 必含字段:`usage`(可 None)、`stop_reason`(可 None)、`duration_ms`。
    """

    content_blocks: list[ContentBlock] = []
    stop_reason: str | None = None
    usage: TokenUsage | None = None
    started = time.perf_counter()

    try:
        async for event in model_adapter.stream(
            messages=state.messages,
            model=config.model,
            system_prompt=config.system_prompt,
            tools=tool_registry.api_schemas(),
            max_tokens=resolved_max_tokens(state, config),
            temperature=config.temperature,
            use_prompt_caching=should_use_caching(config),
        ):
            yield event
            stop_reason = _capture_stop_reason(event, stop_reason)
            content_blocks = _accumulate_content(event, content_blocks)
            usage = _capture_usage(event, usage)

    except RetryableAPIError as exc:
        # v0.7 B2:RETRYABLE_ERROR 保留计数,下一轮 circuit breaker 兜底
        state.consecutive_failures += 1
        yield ErrorEvent(error_type=type(exc).__name__, message=str(exc), retryable=True)
        yield build_audit("model_error", state=state, error=exc,
                          duration_ms=_elapsed_ms(started))
        # v0.7 B1:把已积累的 usage 塞进 sentinel,让主循环 post_model_call 能算成本
        yield _OutcomeSentinel(
            ModelCallOutcome.RETRYABLE_ERROR,
            payload={"usage": usage, "stop_reason": stop_reason,
                     "duration_ms": _elapsed_ms(started)},
        )
        return

    except FatalAPIError as exc:
        # v0.7 B2:FATAL_ERROR 不计数(fatal,直接退出),只标 transition
        state.transition = Transition(reason="fatal_api_error")
        yield ErrorEvent(error_type=type(exc).__name__, message=str(exc), retryable=False)
        yield build_audit("model_error_fatal", state=state, error=exc,
                          duration_ms=_elapsed_ms(started))
        yield _OutcomeSentinel(
            ModelCallOutcome.FATAL_ERROR,
            payload={"usage": usage, "stop_reason": stop_reason,
                     "duration_ms": _elapsed_ms(started)},
        )
        return

    except DataQualityError as exc:
        # v0.7 B2:DATA_QUALITY 改 retryable 语义,保留计数;主循环改 continue
        state.consecutive_failures += 1
        yield ErrorEvent(error_type=type(exc).__name__, message=str(exc), retryable=True)
        yield build_audit("model_error_data_quality", state=state, error=exc,
                          duration_ms=_elapsed_ms(started))
        yield _OutcomeSentinel(
            ModelCallOutcome.DATA_QUALITY,
            payload={"usage": usage, "stop_reason": stop_reason,
                     "duration_ms": _elapsed_ms(started)},
        )
        return

    except InfrastructureError as exc:
        # v0.7 B2:INFRASTRUCTURE 当 fatal(网络/认证不自愈),删除写后即丢的 +=1
        state.transition = Transition(reason="infrastructure_error")
        yield ErrorEvent(error_type=type(exc).__name__, message=str(exc), retryable=False)
        yield build_audit("model_error_infrastructure", state=state, error=exc,
                          duration_ms=_elapsed_ms(started))
        yield _OutcomeSentinel(
            ModelCallOutcome.INFRASTRUCTURE,
            payload={"usage": usage, "stop_reason": stop_reason,
                     "duration_ms": _elapsed_ms(started)},
        )
        return

    # 成功:推进状态
    state.turn_count += 1
    state.total_usage = state.total_usage + (usage or TokenUsage())
    state.messages.append(AssistantMessage(
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    ))
    yield build_audit("model_call_complete", state=state,
                      stop_reason=stop_reason, usage=usage,
                      duration_ms=_elapsed_ms(started))
    # 成功路径 sentinel(payload 字段与失败路径对齐,便于主循环统一消费)
    yield _OutcomeSentinel(
        ModelCallOutcome.COMPLETED,
        payload={"usage": usage, "stop_reason": stop_reason,
                 "duration_ms": _elapsed_ms(started)},
    )
```

### 4.8 Helper: Tool use 处理(v0.6: 19 字段 ToolUseContext + hook 单参签名)

```python
async def _handle_tool_use(
    state: QueryState,
    config: QueryConfig,
    deps: "FinRobotDeps",
    profile: "AgentProfile",
    orchestrator: ToolOrchestrator,
    tool_registry: ToolRegistry,
    tool_use_blocks: list[ToolUseBlock],
    hook_registry: "HookRegistry | None",
) -> AsyncGenerator[StreamEvent | AuditEvent, None]:

    tool_calls = [
        ToolCallRequest(tool_use_id=b.id, tool_name=b.name, raw_input=b.input)
        for b in tool_use_blocks
    ]

    # (h) ToolUseContext 19 字段(mini-ADR-3 §2.3)
    tool_context = ToolUseContext(
        # 基础身份
        session_id=state.session_id,
        user_id=state.user_id,
        fund_id=state.fund_id,
        # 谱系(mini-ADR-2 4 字段)
        audit_chain_id=state.audit_chain_id,
        audit_root_id=state.audit_root_id,
        parent_chain_id=state.parent_chain_id,
        depth=state.depth,
        # 工具运行时
        role="user" if state.depth == 0 else "agent",
        messages=tuple(state.messages),  # B4: immutable 快照
        model=config.model,
        abort_requested=False,
        metadata={},
        # 依赖(mini-ADR-3 §2.1)
        deps=deps,
        # Sub-agent 派生字段(spawn_subagent tool 用,普通工具不读)
        parent_state=state,
        parent_config=config,
        parent_profile=profile,
        tool_registry=tool_registry,
        tool_orchestrator=orchestrator,
        hook_registry=hook_registry,
        # 注:model_adapter 不放 ToolUseContext,从 context.deps.model_adapter 取
        # (mini-ADR-3 §2.1 把它放在 FinRobotDeps,进程级单例)
    )

    # pre_tool_use hook(单参 ctx 签名,mini-ADR-1 v1.1)
    if hook_registry:
        ctx = _build_hook_context(
            state, deps, "pre_tool_use",
            payload={"tool_calls": tool_calls, "tool_context": tool_context},
        )
        results = await hook_registry.run("pre_tool_use", ctx)

        # mini-ADR-1 §2.6 pre_tool_use: block=True 时该工具不执行,
        # 向模型注入 synthetic tool_result(is_error=True)
        blocked_ids: dict[str, str] = {}
        for r in results:
            if r.block:
                # block 对所有 tool_calls 生效(v1 简化;v2 可加 tool_id 精确 block)
                for tc in tool_calls:
                    blocked_ids[tc.tool_use_id] = r.reason or "blocked by hook"
                break

        # modified_input(last-write-wins,mini-ADR-1 F1.1)
        for r in results:
            if r.modified_input is not None:
                # v1 简化:modified_input 是 dict[tool_use_id, dict];若 hook 返回
                # 单 dict 视为针对全部 tool_calls 同一 patch
                for tc in tool_calls:
                    tc.raw_input = {**tc.raw_input, **r.modified_input}

        if blocked_ids:
            # 合成 tool_result 写 messages,跳过 orchestrator.run
            for tc in tool_calls:
                if tc.tool_use_id in blocked_ids:
                    state.messages.append(ToolResultMessage(
                        role=Role.TOOL,
                        tool_use_id=tc.tool_use_id,
                        content=blocked_ids[tc.tool_use_id],
                        is_error=True,
                    ))
                    yield build_audit("tool_blocked_by_hook", state=state,
                                       tool_name=tc.tool_name,
                                       reason=blocked_ids[tc.tool_use_id])
            state.transition = Transition(reason="next_turn")
            return

    started = time.perf_counter()
    results = await orchestrator.run(tool_calls, tool_context)
    duration_ms = _elapsed_ms(started)

    # post_tool_use hook(每个 tool_result 单独触发一次,payload 携带 call+result)
    if hook_registry:
        for call, result in zip(tool_calls, results, strict=True):
            ctx = _build_hook_context(
                state, deps, "post_tool_use",
                payload={"tool_call": call, "tool_result": result},
            )
            await hook_registry.run("post_tool_use", ctx)
            # post_tool_use 不读 metadata / block / modified_input —— 仅观察

    # 工具失败计数(FIX homepilot bug #3)
    all_errors = bool(results) and all(r.is_error for r in results)
    any_success = any(not r.is_error for r in results)

    if all_errors:
        state.consecutive_tool_failures += 1
    elif any_success:
        state.consecutive_tool_failures = 0
        state.consecutive_failures = 0

    for call, result in zip(tool_calls, results, strict=True):
        yield ToolExecutionEndEvent(
            tool_use_id=call.tool_use_id,
            is_error=result.is_error,
            summary=result.to_text()[:200],
        )

        for action in result.ui_actions:
            yield UIActionEvent(tool_use_id=call.tool_use_id, action=action)

        state.messages.append(ToolResultMessage(
            role=Role.TOOL,
            tool_use_id=call.tool_use_id,
            content=result.to_text(),
            is_error=result.is_error,
        ))
        if result.new_messages:
            state.messages.extend(result.new_messages)

        yield build_audit("tool_execution", state=state,
                          tool_name=call.tool_name,
                          is_error=result.is_error,
                          duration_ms=result.duration_ms or duration_ms,
                          tool_extra=result.audit_payload or None)

    state.transition = Transition(reason="next_turn")
```

### 4.8.1 Helper: HookContext 构造 + cost metadata 聚合 + cost guard + deps assert

```python
def _build_hook_context(
    state: QueryState,
    deps: "FinRobotDeps",
    timing: "HookTiming",
    payload: dict,
) -> HookContext:
    """统一构造 HookContext(mini-ADR-3 §2.4 9 字段)。"""
    return HookContext(
        chain_id=state.audit_chain_id,
        session_id=state.session_id,
        fund_id=state.fund_id,
        user_id=state.user_id,
        turn=state.turn_count,
        timing=timing,
        state_snapshot=QueryStateSnapshot.from_state(state),
        deps=deps,
        payload=payload,
    )


def _apply_post_model_call_metadata(
    state: QueryState,
    results: list[HookResult],
) -> None:
    """post_model_call hook 返回后,聚合 metadata.cost_usd 到 state(F-P8-1 解法)。

    Hook 不 mutate state;loop 在此把回报数据写回。
    """
    for r in results:
        if r.metadata and "cost_usd" in r.metadata:
            state.cumulative_cost_usd += float(r.metadata["cost_usd"])


def _should_cost_break(state: QueryState, config: QueryConfig) -> bool:
    """v0.6 新增 cost circuit breaker。"""
    if config.max_cost_usd_per_turn is None:
        return False
    return state.cumulative_cost_usd >= config.max_cost_usd_per_turn


def _assert_conversation_deps(deps: "FinRobotDeps") -> None:
    """mini-ADR-3 §5 不变量 5:conversation 进入前 fail-fast。"""
    missing = [
        name for name in (
            "memory_store", "checkpoint_store", "audit_store",
            "agent_registry", "pipeline_factories", "sub_agents", "model_adapter",
        )
        if getattr(deps, name, None) is None
    ]
    if missing:
        raise ConversationDepsIncomplete(
            f"FinRobotDeps missing conversation-required fields: {missing}. "
            "Old SDK/CLI paths can pass these as None; conversation entry cannot."
        )
```

### 4.9 Helper: Max tokens 处理（model-aware escalate，无 config mutation）

```python
async def _handle_max_tokens(
    state: QueryState,
    config: QueryConfig,
) -> AsyncGenerator[StreamEvent | AuditEvent, None]:
    """两阶段恢复：

      Phase 1: Escalate（一次性，model-aware）
        — 如果 ModelRegistry 表明该模型硬上限 > 当前值，写入 state.override
        — 否则跳过（如 DeepSeek 8k 硬上限）

      Phase 2: Recovery（最多 3 次）
        — 注入 resume 消息

      Phase 3: 放弃
        — 标记 transition = "max_tokens_exhausted"
        — 由外层 query_loop 据此 return
    """

    # Phase 1: Escalate
    if not state.has_attempted_escalate:
        state.has_attempted_escalate = True
        ok, target = can_escalate(state, config)
        if ok:
            state.max_output_tokens_override = target
            state.transition = Transition(reason="max_tokens_escalate")
            yield build_audit("max_tokens_escalate", state=state, escalated_to=target)
            return
        # Escalate 无效（model 硬上限 == 当前），直接进入 Phase 2

    # Phase 2: Recovery
    if state.max_output_tokens_recovery_count < config.max_output_tokens_recovery_limit:
        state.max_output_tokens_recovery_count += 1
        state.messages.append(UserMessage(content=recovery_msg(config.language)))
        state.transition = Transition(
            reason="max_tokens_recovery",
            recovery_count=state.max_output_tokens_recovery_count,
        )
        yield build_audit("max_tokens_recovery", state=state,
                          attempt=state.max_output_tokens_recovery_count)
        return

    # Phase 3: Exhausted
    state.transition = Transition(reason="max_tokens_exhausted")
    yield ErrorEvent(
        error_type="MaxTokensExhausted",
        message=exhausted_msg(config.language),
    )
    yield build_audit("max_tokens_exhausted", state=state,
                      total_attempts=state.max_output_tokens_recovery_count,
                      escalated=state.has_attempted_escalate)
    # 注：不再 state.consecutive_failures += 1（FIX v0.1 B4：写后即丢的噪声）
    # exhausted 状态由 transition + audit event 完整记录。
```

### 4.10 错误体系

```python
# finrobot/conversation/errors.py

class APIError(Exception):
    """模型 API 调用错误的基类。"""

class RetryableAPIError(APIError):
    """已经在上游 retry 耗尽，进入熔断路径。
    包含：429 (rate limit), 529 (overload), 5xx (非 500)."""

class FatalAPIError(APIError):
    """不重试，直接退出 loop。
    包含：401/403 (auth), 400-prompt-too-long (上下文太大), 400-invalid-request."""

class DataQualityError(Exception):
    """数据相关错误（工具返回的数据不可用、provider 全部失败）。"""

class InfrastructureError(Exception):  # NOTE v0.2: 不再叫 SystemError，避免遮蔽 Python 内置
    """工程层错误（数据库 / 网络底层 / 缓存）。"""


# 由 ModelAdapter 在 stream() 内部根据 HTTP status + 上游 SDK 异常类型映射。
# Loop 只 catch 这 4 类，其他用 except Exception 走 LoopFailure 兜底路径。
```

### 4.11 ModelAdapter 契约（含 refusal normalization 要求）

```python
# finrobot/conversation/adapter.py

from typing import Protocol
from collections.abc import AsyncGenerator


class ModelAdapter(Protocol):
    """所有 model adapter 实现必须满足的契约。

    **跨 provider normalize 要求**（v0.2 D4 修复）：

    1. stop_reason 必须 normalize 成以下值之一：
       - "end_turn"      正常完成
       - "tool_use"      模型请求工具调用
       - "max_tokens"    超过 max_output_tokens 限制
       - "refusal"       模型拒答（合规、内容过滤、安全）
       - "stop_sequence" 触发 stop 序列（罕见，loop 当 end_turn 处理）

       原始 provider stop_reason 必须放入 MessageStopEvent.raw_provider_reason
       字段，写入 audit log。

    2. Refusal 信号识别（每个 provider 自实现）：
       - Anthropic: stop_reason == "refusal"
       - OpenAI:    finish_reason == "content_filter" 或 message.refusal != null
       - DeepSeek:  finish_reason == "content_filter"（与 OpenAI 一致）

    3. 错误必须 raise 成 4 类（见 errors.py），不要 raise 原始 SDK 异常。

    4. Cache control 标记位置（仅 supports_prompt_caching 模型）：
       - System prompt 末尾最后一个 text block: cache_control: ephemeral
       - 历史最近一条 assistant message 边界: cache_control: ephemeral
       (不再回避 tool_result，让 cache 在工具密集会话中也能命中)
    """

    async def stream(
        self,
        messages: list[Message],
        model: str,
        system_prompt: str,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        use_prompt_caching: bool = False,
    ) -> AsyncGenerator[StreamEvent, None]: ...


class PydanticAIAdapter(ModelAdapter):
    """v1 唯一实现，复用 FinRobot 现有 PydanticAI 配置。

    位于 finrobot/conversation/adapter.py。
    内部使用 finrobot.engine.agents.* 已经定义的 Agent 配置。

    NOTE v0.2: FinRobot CLAUDE.md 禁用 LiteLLM。多 provider 路由通过
    PydanticAI 的 model provider 机制实现（'anthropic:...', 'openai:...',
    'deepseek:...' 等），不引入 LiteLLM 层。
    """
```

### 4.12 AuditEvent（D3 修复：纯 dataclass，无 emitter）

```python
# finrobot/conversation/audit.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

AuditEventType = Literal[
    "loop_start", "loop_terminate",
    "model_call_complete", "model_error", "model_error_fatal", "model_error_other",
    "tool_execution",
    "compact",
    "max_tokens_escalate", "max_tokens_recovery", "max_tokens_exhausted",
    "circuit_breaker", "tool_circuit_breaker",
    "refusal",
    "state_transition",
    "malformed_tool_input",
]


@dataclass
class AuditEvent:
    """审计事件。纯数据对象，无副作用。

    v0.3 字段扩展（mini-ADR-2 合并）：增加 root_id / parent_chain_id / depth
    用于跨 sub-agent 聚合查询和谱系重建。

    v0.4 字段扩展（Pillar 2 v0.2 D4 对接）：增加 tool_extra
    承载 ToolResult.audit_payload 的工具业务字段（fair_value、wacc 等）。
    """
    type: AuditEventType
    chain_id: str
    root_id: str
    """聚合查询字段：WHERE root_id = ? 拉到整个 user turn 的所有 agent 事件。"""
    parent_chain_id: str | None
    """Lineage walk 字段：递归 CTE 重建谱系树。"""
    depth: int
    """Telemetry / debug 字段。"""

    session_id: str
    fund_id: str
    turn: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    """通用 payload（事件类型的固定字段）。"""

    tool_extra: dict[str, Any] | None = None
    """v0.4 新增：仅 type="tool_execution" 时使用。
       来自 ToolResult.audit_payload。让 audit log 查询"那次 user turn 用了哪些
       WACC 假设" 成为可能。其他事件类型该字段为 None。"""


def build_audit(
    type: AuditEventType,
    state: QueryState,
    *,
    tool_extra: dict[str, Any] | None = None,
    **payload: Any,
) -> AuditEvent:
    """从 state 自动填充全部身份字段（v0.4 含 tool_extra 显式参数）。

    Pillar 2 v0.2 D4 修复：tool_extra 作为命名参数传入，不与 payload kwargs
    混在一起 ** merge，避免与 tool_name / is_error / duration_ms 等标准字段冲突。
    """
    duration_ms = payload.pop("duration_ms", None)
    assert state.audit_root_id is not None  # __post_init__ 保证
    return AuditEvent(
        type=type,
        chain_id=state.audit_chain_id,
        root_id=state.audit_root_id,
        parent_chain_id=state.parent_chain_id,
        depth=state.depth,
        session_id=state.session_id,
        fund_id=state.fund_id,
        turn=state.turn_count,
        duration_ms=duration_ms,
        payload=payload,
        tool_extra=tool_extra,
    )
```

### 4.12.1 StreamEvent 类型族扩展（v0.4 新增）

```python
# finrobot/conversation/types.py

@dataclass
class UIActionEvent:
    """工具产出的 UI 渲染指令。SSE 端点收到后转发给桌面 app / web 客户端，
    LLM 看不到。详见 Pillar 2 §4.2 UIAction。"""

    tool_use_id: str
    action: "UIAction"  # 见 Pillar 2 §4.2


# StreamEvent union 扩展：
StreamEvent = (
    MessageStartEvent
    | ContentBlockStartEvent
    | ContentBlockDeltaEvent
    | ContentBlockStopEvent
    | MessageDeltaEvent
    | MessageStopEvent
    | ToolExecutionStartEvent
    | ToolExecutionEndEvent
    | UIActionEvent       # v0.4 新增
    | ErrorEvent
)
```

### 4.13 与现有 FinRobot 模块的边界

| 现有模块 | 在 Pillar 1 中的角色 |
|---|---|
| `finrobot/sdk.py` | **保留不动**。脚本 / CI 调 `agent.research()` 不走 conversation loop |
| `finrobot/server.py` | **新增 chat 路由**（`/api/chat/sessions/{id}/messages`）；旧路由保留 |
| `finrobot/engine/orchestrator.py::create_lead_agent` | **保留**（pipeline 内部用）；新 loop 调用 PydanticAIAdapter，不直接用 lead_agent |
| `finrobot/engine/pipelines/*` | **保留**。每个 pipeline 通过 conversational tool 包装暴露给 loop |
| `finrobot/engine/agents/factory.py` | **保留**。PydanticAIAdapter 复用其 sub-agent 配置 |
| `finrobot/engine/skills/registry.py` | **保留**。Pillar 8 hooks 接入 |
| `finrobot/engine/data/*` | **保留**。data tools 直接调 DataLayer |

---

## 5. v1 明确推迟的功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| Streaming tool execution | 拓扑排序 + 流式协调复杂度高，金融工具并发收益有限 | Pillar 2 v2 |
| Reactive compact | v1 用阈值 auto-compact 足够；reactive 需要 413 检测 + 二次调用 | Pillar 5 v2 |
| Context collapse | CC 基于消息分组的释放策略，FinRobot 暂无对应需求 | 不实施 |
| Fallback model | 涉及清状态、剥离签名、UI 通知；与 provider abstraction 强耦合 | Pillar 1 v2（M7-8） |
| Stop hooks 完整（blocking errors / preventContinuation） | v1 仅留 hook 调用点 | Pillar 8 |
| USD / Task budget | v1 用 max_turns + token 上限替代 | 不实施 |
| Snip / microcompact | 单一 auto-compact 足够 | 不实施 |
| Memory prefetch 协调 | v1 用同步 system prompt 注入 | Pillar 5 |
| Tool use summary（Haiku 异步） | 节省 token 但增复杂度 | v2 评估 |
| Tombstone messages | CC 的消息撤销机制，FinRobot 暂无 | 不实施 |

---

## 6. homepilot 设计缺陷 → FinRobot 实现指令

> **澄清（v0.2）**：这一节不是"修改 homepilot 代码"也不是"立刻写 FinRobot 代码"。
> 这是**写在设计文档里的实现指令**：未来 Week 1+ 开始实现 `finrobot/conversation/` 时，
> 这 7 处不要复刻 homepilot 的做法，要用本表右侧的设计。

| # | homepilot 缺陷 | 表现 | FinRobot 实现指令 | 对应测试 |
|---|---|---|---|---|
| 1 | Recovery 消息英文硬编码（`loop.py:334`） | 中文用户体验突兀 | `recovery_msg(config.language)` 双语字典 | UT-09 |
| 2 | Hook registry 参数未实现 | 死代码 | Pillar 8 协同：loop 在 5 个时机调用 `hook_registry.run(...)`，noop 实现可用 | UT-21 |
| 3 | consecutive_failures 不计工具失败 | 工具死循环不熔断 | 新增 `consecutive_tool_failures` + `tool_circuit_breaker_threshold=5` | UT-12, IT-02 |
| 4 | JSON 解析失败静默 | 工具调用 JSON 损坏当 `{}`，难调试 | fallback `{}` 但同时 yield `AuditEvent(type="malformed_tool_input")` | UT-15 |
| 5 | ToolResultMessage.role = USER | 语义错误 | 改用 `Role.TOOL`，adapter 内做 API 兼容性转换 | UT-17 |
| 6 | 异常无堆栈无分类 | `consecutive_failures += 1` 但无错误类型 | 4 类错误体系（Retryable / Fatal / DataQuality / Infrastructure），exception 信息入 AuditEvent | UT-18 ~ UT-20 |
| 7 | Auto-compact ImportError 静默 | 模块不存在静默跳过 | v1 模块必须存在，缺失视为配置错误（启动期 fail-fast） | UT-25 |

---

## 7. 测试要点

### 7.1 单元测试（v0.3: 38+ 条，含 mini-ADR 测试合并）

- UT-01..05 状态机转移路径
- UT-06..08 stop_reason 每种分支
- UT-09 双语 recovery 消息渲染
- UT-10..11 escalate model-aware（Claude 成功、DeepSeek skip）
- UT-12 工具连续失败 5 次熔断
- UT-13 模型失败 3 次熔断
- UT-14 auto-compact 阈值触发
- UT-15 JSON 解析失败 audit event
- UT-16 prompt caching 仅 supports_prompt_caching 模型启用
- UT-17 ToolResultMessage 角色为 TOOL
- UT-18..20 4 类错误分类映射
- UT-21..23 hook 5 个时机调用
- UT-24 AuditEvent chain_id 在 task 内一致
- UT-25 缺失 compact 模块 fail-fast
- UT-26..28 ModelRegistry get_capability / resolved_max_tokens / can_escalate
- UT-29 AgentProfile 不影响 loop 行为
- UT-30 cancellation 时 emit loop_terminate(reason="cancelled")
- UT-31 `create_top_level_state` 生成 root_id == chain_id、parent == None、depth == 0
- UT-32 `fork_subagent_state` 新 chain、继承 root、parent 指向父、depth +1
- UT-33 `fork_subagent_state` 在 depth >= max_depth 抛 `SubAgentDepthExceeded`
- UT-34 二层嵌套（A→B→C）后 C.root_id == A.chain_id、C.parent_chain_id == B.chain_id、depth == 2
- UT-35 fork 不继承失败计数器（10 个状态字段全部为默认值）
- UT-36 `QueryState(audit_chain_id="X")` 无 root_id 时 __post_init__ 自动 root == X
- UT-37 `QueryState(depth=11)` 直接构造抛 ValueError
- UT-38 `QueryState(depth=0, parent_chain_id="X")` 违反顶层 invariant 抛 ValueError
- UT-39 hook 7 个时机各能触发（继承 mini-ADR-1 UT-21..26）
- UT-40 hook `modified_input` last-write-wins 语义验证
- UT-41 hook `pre_tool_use` block 时合成 tool_result(is_error=True) 写入 messages

### 7.2 集成测试（5 条）

- IT-01 5 轮对话端到端
- IT-02 工具连续 5 次失败触发 tool circuit breaker
- IT-03 **Claude** 模型 max_tokens 触达后 escalate 到 64k 成功（替换 v0.1 错误的 DeepSeek 测试）
- IT-04 **DeepSeek** 模型 max_tokens 触达后 escalate 跳过、直接进 recovery，3 次后 exhausted
- IT-05 Refusal 后输出合规提示并结束

### 7.3 边界测试

- 30 轮对话（max_turns 边界）
- 单条 50KB 消息
- 并发 10 个工具调用
- Auto-compact 多次触发
- 256k 字符 tool result 不被截断
- AsyncGenerator cancellation：调用方 `.aclose()` 时 loop_terminate(reason="cancelled") 被 emit、未完成 tool task 被取消

---

## 8. 未决问题

> v0.2 已经把"影响公共接口"的 2 条提前到 Week 0 mini-ADR（不再算"未决"）。

### 8.1 Week 0 mini-ADR（已决议 ✅）

- **mini-ADR-1: Hook 时机** ✅ 已决议
  - 决议：7 个时机（`loop_start` / `pre_model_call` / `post_model_call` / `pre_tool_use` / `post_tool_use` / `pre_compact` / `loop_terminate`）
  - 执行模型：async + 顺序 + 失败默认非阻塞 + 仅 in-process callback
  - 详见 `adrs/mini-adr-1-hook-timing.md`

- **mini-ADR-2: Sub-agent chain_id 父子关系** ✅ 已决议
  - 决议：4 字段方案（chain_id + root_id + parent_chain_id + depth）
  - 主 agent: root == chain，sub-agent: 新 chain，继承 root，parent 指向父
  - `__post_init__` 强制一致性 invariants，`MAX_DEPTH_HARD_CAP = 10`
  - 详见 `adrs/mini-adr-2-subagent-chain-id.md`

### 8.2 真正未决（影响 v2 不影响 v1）

1. **Sub-agent 怎么继承 hook registry？** → Pillar 7
2. **多模型混合会话的 cache 失效策略** → v1 实施后 IT 验证
3. **Tool result 体积上限 256k 在 10-K + MD&A 场景是否够？** → Pillar 2
4. **如何让 query_loop 支持中断恢复？** → Pillar 5 与 Pillar 7 之间
5. **多租户 fund_id 二次防护放在 loop 内还是 hook 内？** → Pillar 8
6. **Refusal normalization 每 provider 的具体字符串映射** → v1 实施时记录到 `adapter.py` 的 docstring

---

## 9. 实施计划

### Week 0（mini-ADR）

- [ ] mini-ADR-1：Hook 时机
- [ ] mini-ADR-2：Sub-agent chain_id 父子关系
- [ ] 评审通过后启动 Week 1

### Week 1

- [ ] `finrobot/conversation/` 模块骨架（空文件 + import 关系）
- [ ] `types.py`：Message / ContentBlock / StreamEvent / AuditEvent
- [ ] `state.py`：QueryState + Transition + CompactTracking
- [ ] `config.py`：QueryConfig + AgentProfile
- [ ] `model_registry.py`：ModelCapability + 7 个初始模型
- [ ] `messages.py`：双语消息字典
- [ ] `errors.py`：4 类错误体系
- [ ] `adapter.py`：ModelAdapter Protocol + PydanticAIAdapter 骨架（仅 stream）
- [ ] `loop.py`：主循环 + cancellation 处理（end_turn 直接退出）
- [ ] 单元测试 UT-01..05、UT-09..11、UT-18..20、UT-30

### Week 2

- [ ] `orchestrator.py`：ToolOrchestrator（greedy partitioning）
- [ ] `loop.py`：完整 tool_use 分支 + 工具失败熔断
- [ ] `compact.py`：auto-compact 阈值触发版
- [ ] `audit.py`：AuditEvent + build_audit
- [ ] `hooks.py`：HookRegistry noop 实现（按 mini-ADR-1）
- [ ] 单元测试 UT-12..15、UT-17、UT-21..28

### Week 3

- [ ] `tools/pipeline_tools.py`：包装现有 pipelines 为 conversational tool（先做 `run_dcf` 一个）
- [ ] `tools/data_tools.py`：`get_financials` / `get_news`
- [ ] `server.py` 加 `/api/chat/sessions/{id}/messages` 路由
- [ ] Prompt caching 在 PydanticAIAdapter 内实现
- [ ] 端到端 IT-01..05
- [ ] 边界测试
- [ ] 性能 baseline 测量（5 轮对话延迟）
- [ ] 写 ADR-001 ~ ADR-005 关键决策的存档版

---

## 10. 参考资料

- **CC 源码导览**：`/Users/zhunihaoyun/Desktop/code/claude-code/src/query/`
- **homepilot 实现**：`/Users/zhunihaoyun/Desktop/code/zm/homepilot/engine/query/`
- **CLAUDE.md 约束**：`/Users/zhunihaoyun/Desktop/code/FinRobot/CLAUDE.md` 第 11 行 `No LangChain. No LangGraph. No AutoGen. No LiteLLM.`
- **原始研究报告**：
  - `docs/cc-pillars/raw/cc-pillar-1-raw.md`
  - `docs/cc-pillars/raw/homepilot-pillar-1-raw.md`
- **现有 FinRobot 关联模块**：
  - `finrobot/sdk.py`（保留）
  - `finrobot/server.py`（新增 chat 路由）
  - `finrobot/engine/orchestrator.py`（保留）
  - `finrobot/engine/pipelines/registry.py`（pipeline 注册表，被 conversation tools 复用）
  - `finrobot/engine/agents/factory.py`（PydanticAIAdapter 内部复用）
- **相关 ADR**（v1 实施期产出）：
  - ADR-001: Query Loop 选择 AsyncGenerator 而非 callback
  - ADR-002: ModelAdapter 抽象 PydanticAI 而非直绑 SDK；不引入 LiteLLM
  - ADR-003: Audit Trail 通过 union event yield 内嵌，不走 hooks
  - ADR-004: 双语 recovery message 设计
  - ADR-005: Model-aware escalate via ModelRegistry

---

## 评审 Checklist

- [ ] CC 引用的文件名行号已抽样校验（v0.1 已校验：`query.ts:241`、`325-350`）
- [ ] homepilot 引用的文件名行号已抽样校验（v0.1 已校验：`loop.py:108`）
- [ ] 所有 "FinRobot 决策" 的理由已写明
- [ ] v1 推迟功能已说明何时启动
- [ ] homepilot 7 处缺陷的实现指令明确，每条带测试 ID
- [ ] 单元测试 ≥ 30 条
- [ ] 集成测试 ≥ 5 条
- [ ] 与现有 FinRobot 模块的边界清晰
- [ ] 未决问题有明确决策时机
- [ ] CLAUDE.md 约束（无 LiteLLM）已遵守 ✓
- [ ] Cancellation 路径有 try/finally 兜底 ✓
- [ ] 所有 helper 是 async generator（无 sink=yield_ 反模式）✓
- [ ] 运行时状态全部住在 QueryState（loop 不 mutate config）✓
