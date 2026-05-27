# Mini-ADR-1: Hook 时机与执行契约

| | |
|---|---|
| **版本** | v1.2 |
| **状态** | Accepted(v1.0 评审通过 / v1.1 加 metadata 字段 / v1.2 补 post_model_call payload model 字段) |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **阻塞项** | Pillar 1 公共接口、Pillar 2 工具系统、Pillar 8 hooks 完整实现 |
| **依据** | 子 agent 对 CC `src/hooks/`、`src/query/stopHooks.ts`、`src/services/tools/toolExecution.ts` 的深度通读 |

---

## Changelog

### v1.2(2026-05-12)
- B4(v0.6/v0.3/v0.2 串评审):§2.6 post_model_call payload schema 补 `model: str` 字段(Pillar 1 v0.7 主循环 / Pillar 8 v0.2 cost_tracker 均依赖此字段读 `payload["model"]`,原 v1.1 表只列 stop_reason / usage / duration_ms,与实现不一致)

### v1.1(2026-05-12)
- mini-ADR-3 触发:`HookResult` 加 `metadata: dict[str, Any] | None = None` 字段。用于 hook **不能直接 mutate state** 但需要把数据流回 loop 的场景(典型:cost-tracker 通过 metadata["cost_usd"] 把成本回报给 query_loop 聚合)。

### v1.0(2026-05-12)
- 初版:7 时机、async + 顺序 + 非阻塞、HookResult 三字段(block / reason / modified_input)、各时机 payload schema、F1.1~F1.4 自审修复

---

## 0. TL;DR

**v1 实施 7 个 hook 时机**（CC 有 13+ 个，砍掉 6 个属于权限 / 子 agent / UI 范畴的）。

**执行模型**：async + 顺序（按注册顺序）+ 失败默认非阻塞 + 仅 in-process callback。

**返回值**：单 dataclass `HookResult`，可携带 `block / reason / modified_input` 三类信号。

---

## 1. Context

Pillar 1（query loop）需要在循环关键时点暴露扩展点，否则后续 Pillar 8 必须返工 loop 公共接口。

我们调研 CC 后发现：

- CC 有 **13+ hook 事件**：PreToolUse / PostToolUse / PostToolUseFailure / Stop / SubagentStop / TeammateIdle / TaskCompleted / SessionStart / SessionEnd / PermissionRequest / PermissionDenied / UserPromptSubmit / Setup（外加更多边缘事件）
- CC hooks **并行执行**（`Promise.all`），按完成顺序返回
- CC 支持 4 类 hook 实现：command（子进程）、prompt（LLM）、agent（fork）、http（fetch）、callback（in-process）
- CC 使用 exit code 2 = blocking 这套 Unix 风格协议
- CC 支持 async hook（return immediately, response collected next turn）

直接全盘复刻不现实，且许多事件（PermissionRequest、TeammateIdle 等）在 FinRobot 暂无对应需求。

---

## 2. Decision

### 2.1 V1 实施的 7 个 hook 时机

| # | 时机名 | 在 loop 内的位置 | 触发条件 | 一次 turn 最多调用次数 |
|---|---|---|---|---|
| 1 | `loop_start` | `query_loop` 入口最前 | 永远 | 1 次（整个 query_loop 1 次） |
| 2 | `pre_model_call` | 模型调用前 | 每轮 1 次 | 等于 turn_count |
| 3 | `post_model_call` | 模型调用结果累积完成、stop_reason 已确定后 | 每轮 1 次（无论 stop_reason） | 等于 turn_count |
| 4 | `pre_tool_use` | 进入 tool execution 分支后、调用 orchestrator.run() 之前 | stop_reason == tool_use | 每个 tool_use_block 1 次 |
| 5 | `post_tool_use` | orchestrator.run() 返回后、ToolResultMessage 落入 state.messages 之前 | 同上 | 每个 tool 结果 1 次 |
| 6 | `pre_compact` | auto-compact 触发前 | 阈值到达 | 0 或 1 次/轮 |
| 7 | `loop_terminate` | 任何 break / return 路径 | loop 退出 | 1 次（最终） |

### 2.2 V1 不实施的时机（明确推迟）

| 时机 | 推迟原因 | 计划在 |
|---|---|---|
| `permission_request` / `permission_denied` | v1 工具权限模型简化为"全 allow"，无 prompt | Pillar 8 v2 |
| `subagent_start` / `subagent_stop` | Pillar 7 范围 | Pillar 7 |
| `user_prompt_submit` | 不在 loop 内，在 chat endpoint | Server 路由层 |
| `session_start` / `session_end`（CC 含义） | 一个 user-visible session 跨多个 query_loop 调用；session 级 hook 应该在更上层 | Pillar 8 v2 |
| `post_tool_use_failure` | 与 `post_tool_use` 合并，由 result.is_error 区分 | 不单独实施 |
| `teammate_idle` / `task_completed` | CC 特有的多 agent 协作概念，FinRobot v1 不涉及 | 不实施 |
| `setup` / `file_changed` / `cwd_changed` | CC 是 IDE 内场景，FinRobot 是金融分析场景，不需要 | 不实施 |
| `post_compact` | v1 用 `pre_compact` 足够；compact 完成后立即进入下一轮 model_call，已经被 `pre_model_call` 覆盖 | 不实施 |

### 2.3 执行契约

```python
# finrobot/conversation/hooks.py

from dataclasses import dataclass
from typing import Literal, Protocol
from collections.abc import Awaitable, Callable

HookTiming = Literal[
    "loop_start", "pre_model_call", "post_model_call",
    "pre_tool_use", "post_tool_use",
    "pre_compact", "loop_terminate",
]


@dataclass
class HookContext:
    """传给 hook 的只读上下文快照。Hook 不允许修改 state 直接，只能通过返回值表态。"""

    chain_id: str
    session_id: str
    fund_id: str
    turn: int
    state_snapshot: QueryStateSnapshot  # 不可变 view of QueryState
    # 时机特定字段（F1.2 / F1.4：每个时机的 payload schema 见 §2.7）
    payload: dict[str, Any]


@dataclass
class HookResult:
    """Hook 返回值。简单结构，避免 CC 的多字段并存。"""

    block: bool = False
    """True 时按时机不同有不同语义：
       - pre_model_call: loop 立即 terminate(reason="hook_stopped")
       - pre_tool_use:   该工具不执行，向模型返回 synthetic tool_result(is_error=True)
       - pre_compact:    跳过本次 compact，loop 继续（warning 入 audit）
       - 其他时机:        block=True 无效，记录 warning
    """

    reason: str | None = None
    """block=True 时必填，写入 audit + 给模型/用户看。"""

    modified_input: dict | None = None
    """仅 pre_tool_use 时机有效。非 None 时替换工具的 raw_input。
       其他时机赋值视为 warning（v1 不报错，v2 可能升级为错误）。

       多 hook 同一时机注册时的语义（F1.1 澄清）：
       - **last-write-wins**：所有 hooks 看到的是同一个 HookContext snapshot，
         不感知彼此的修改。loop 收集 list[HookResult] 后，取最后一个
         modified_input != None 的值作为最终输入。
       - 这是有意简化：v1 不支持"链式 hook 改 input"。如果需要顺序变换，
         注册一个 hook 内部串联多个变换函数。
    """

    metadata: dict[str, Any] | None = None
    """v1.1 新增（mini-ADR-3 §2.4 触发）：hook 给 query_loop 的回报字段。

    用于 hook **不能直接 mutate state** 但需要把数据流回 loop 的场景。loop 在
    `run(timing, ctx)` 返回后，根据 timing 决定如何消费 metadata：

    - post_model_call: loop 累加 `state.cumulative_cost_usd += sum(r.metadata["cost_usd"]
      for r in results if r.metadata and "cost_usd" in r.metadata)` —— cost-tracker
      hook 用此路径（Pillar 8 v0.2 §4.3 F-P8-1 修复）
    - 其他 timing: v1 metadata 字段保留但 loop 不消费；hook 之间不共享 metadata。

    Hook 之间不传递 metadata（与 modified_input 同样：所有 hook 看同一 snapshot）。
    """


HookFn = Callable[[HookContext], Awaitable[HookResult]]
"""所有 hook 必须是 async function。Sync hook 包成 async。"""


class HookRegistry:
    """In-process hook 注册表。v1 唯一实现。"""

    def register(self, timing: HookTiming, fn: HookFn, *, name: str = "") -> None: ...
    def list(self, timing: HookTiming) -> list[HookFn]: ...
    async def run(self, timing: HookTiming, context: HookContext) -> list[HookResult]:
        """按注册顺序顺序执行，收集所有结果。

        - 顺序执行（不并行）
        - 单个 hook 失败 → 默认非阻塞，记 audit + 继续下一个
        - 整体超时 = max(每个 hook 5s) — v1 写死，v2 可配
        - 返回 list[HookResult]，调用方据此决定行为
        """
```

### 2.4 失败处理

- 单个 hook raise 异常 → 捕获、写 `AuditEvent("hook_failure", hook_name=..., error=...)`、**继续**下一个 hook
- 整体 hook 阶段超时（v1: 5 秒）→ 未完成的 hook task cancel、已完成结果保留、写 audit warning
- 多个 hook 都返回 `block=True` → 取**第一个**为生效结果（按注册顺序）
- 多个 hook 返回 `modified_input` → 后注册的 hook 看到前一个的修改（链式），最终结果是最后一个 hook 写入的版本

### 2.5 注册渠道

V1 唯一支持：**代码内显式注册**

```python
# 例：FinRobot 启动时
hooks = HookRegistry()
hooks.register("post_tool_use", audit_trail_writer, name="audit-trail")
hooks.register("pre_tool_use", fund_id_guard, name="fund-id-guard")
hooks.register("post_model_call", token_cost_tracker, name="cost-tracker")
```

V1 **不支持**：
- 配置文件驱动（YAML / JSON）
- Shell command hook
- HTTP webhook
- LLM-based hook（用 Claude/DeepSeek 写 hook 逻辑）
- 动态运行时注册（session 内加 hook）

这些都推迟到 Pillar 8 v2 评估。理由：v1 内部 hook 已经够覆盖审计追溯、cost tracking、fund 隔离等核心需求；外部 hook 增加 attack surface 和 debug 复杂度，不值得。

### 2.6 各时机 payload schema（F1.2 / F1.4 修复）

每个时机的 `HookContext.payload` 字段是固定的（不是"自由 dict"）。Hook 实现者按下表读取，loop 实现者按下表填充：

| 时机 | payload 必含字段 | 备注 |
|---|---|---|
| `loop_start` | 无（仅 state_snapshot） | — |
| `pre_model_call` | `model: str`、`max_tokens: int`、`use_caching: bool` | 反映本次实际请求参数 |
| `post_model_call` | `model: str`、`stop_reason: str \| None`、`usage: TokenUsage \| None`、`duration_ms: int` | v1.2:补 `model` 字段(cost_tracker 依赖)。**stop_reason / usage 在失败路径可为 None**——loop 必须无条件触发(每轮 1 次,不区分 outcome),失败时 stop_reason 用 ModelCallOutcome.value 兜底 |
| `pre_tool_use` | `tool_call: ToolCallRequest`（含 tool_use_id / name / raw_input） | 单 tool 一次 |
| `post_tool_use` | `tool_call: ToolCallRequest`、`tool_result: ToolResult`、`duration_ms: int` | 含 is_error |
| `pre_compact` | `current_token_count: int`、`threshold: int` | — |
| `loop_terminate` | `terminate_reason: str`、`final_usage: TokenUsage` | terminate_reason ∈ {end_turn, max_turns, circuit_breaker, tool_circuit_breaker, hook_stopped, refusal, fatal_api_error, cancelled, exception} |

Hook 实现者拿到不在表中的 key → 视为 "v2 兼容字段"，可读可忽略。loop 实施时必须覆盖表中所有 key。

### 2.7 `pre_tool_use` 被 block 时的合成消息（F1.3 修复）

当某个 hook 对 `pre_tool_use` 返回 `block=True`：

```python
# 该 tool 不进入 orchestrator.run()
# 直接合成 ToolResultMessage 写入 state.messages，让模型看到失败

synthetic_result = ToolResultMessage(
    role=Role.TOOL,
    tool_use_id=call.tool_use_id,
    content=f"[Hook blocked] {blocking_hook.reason or 'No reason provided'}",
    is_error=True,
)
state.messages.append(synthetic_result)
yield build_audit("tool_blocked_by_hook",
                  state=state,
                  tool_name=call.tool_name,
                  hook_reason=blocking_hook.reason)
```

模型在下一轮看到这个 tool_result，按"工具失败"的语义处理。Hook 不需要单独通知模型——靠合成的 tool_result 即可。

### 2.8 Loop 内调用点（精确位置）

```python
async def query_loop(state, config, ..., hook_registry):
    # Hook #1: loop_start
    if hook_registry:
        await hook_registry.run("loop_start", build_hook_context(state, ...))

    try:
        while True:
            # ... guards ...

            # Hook #6: pre_compact（只在 auto-compact 触发时）
            if await should_auto_compact(state, config):
                if hook_registry:
                    results = await hook_registry.run("pre_compact", build_hook_context(state, ...))
                    if any(r.block for r in results):
                        yield build_audit("compact_skipped_by_hook", state=state,
                                          reason=next(r.reason for r in results if r.block))
                    else:
                        await do_compact(state, model_adapter, config)
                else:
                    await do_compact(state, model_adapter, config)

            # Hook #2: pre_model_call
            if hook_registry:
                results = await hook_registry.run("pre_model_call",
                                                  build_hook_context(state, model=config.model, ...))
                if any(r.block for r in results):
                    blocking = next(r for r in results if r.block)
                    yield ErrorEvent(error_type="HookBlocked", message=blocking.reason)
                    yield build_audit("loop_terminate", state=state, reason="hook_stopped")
                    return

            # ... model call ...

            # Hook #3: post_model_call
            if hook_registry:
                await hook_registry.run("post_model_call",
                                        build_hook_context(state, stop_reason=stop_reason, ...))

            # ... stop_reason 分支 ...

            if stop_reason == "tool_use" or tool_use_blocks:
                # Hook #4: pre_tool_use（每个工具一次）
                all_tool_calls = [...]
                tools_to_execute: list[ToolCallRequest] = []  # F1.5: 不迭代 mutate

                if hook_registry:
                    for call in all_tool_calls:
                        results = await hook_registry.run("pre_tool_use",
                                                          build_hook_context(state, tool_call=call))
                        # last-write-wins：取最后一个 modified_input != None 的值（F1.1）
                        for r in results:
                            if r.modified_input is not None:
                                call.raw_input = r.modified_input
                        # 检查 block
                        blocking = next((r for r in results if r.block), None)
                        if blocking:
                            # 合成失败 tool_result（见 §2.7）
                            inject_blocked_tool_result(state, call, blocking.reason)
                        else:
                            tools_to_execute.append(call)
                else:
                    tools_to_execute = all_tool_calls

                # 执行剩余 tool
                results = await orchestrator.run(tools_to_execute, tool_context)

                # Hook #5: post_tool_use（每个工具结果一次）
                if hook_registry:
                    for call, result in zip(tool_calls, results, strict=True):
                        await hook_registry.run("post_tool_use",
                                                build_hook_context(state, tool_call=call, tool_result=result))

                # ... 写入 messages ...

    finally:
        # Hook #7: loop_terminate（无论怎么退出）
        if hook_registry:
            await hook_registry.run("loop_terminate", build_hook_context(state, terminate_reason=...))
```

---

## 3. Consequences

### 3.1 正向

- Pillar 1 公共接口锁定：`HookRegistry | None` 作为可选注入
- 7 个时机覆盖 v1 全部审计 / 追溯 / 兜底需求
- 同步执行 + 简单失败语义降低调试难度
- `HookResult` 单类型避免 CC 的多字段堆叠混乱
- audit trail 系统（Pillar 1 内嵌）可以作为第一个真实 hook 用户验证整套机制

### 3.2 负向 / 限制

- 顺序执行可能比并行慢——但单 hook 通常 < 50ms，7 个时机 × 数个 hook 最多增加 < 1 秒
- 不支持配置文件驱动 hook → 用户想加 hook 需要写 Python 代码（v1 OK，因为目标用户不是终端用户而是 FinRobot 自己）
- 不支持 shell hook → 与 CC 的开源用户场景不一致（FinRobot 不暴露 hook 配置给最终用户）

### 3.3 中性

- `post_tool_use_failure` 合并到 `post_tool_use`（用 `is_error` 区分）→ 测试需覆盖两种 result
- `post_compact` 省略 → 后续 turn 的 `pre_model_call` 已经能感知 compact 后状态，无信息损失

### 3.4 性能注（F1.6 修复）

`HookContext.state_snapshot` 包含 `messages: tuple[Message, ...]`，每次 hook 调用前从 `QueryState` 拷贝。

性能估算：
- 30 turn × 单轮 ~100 messages × 7 hook timings × 平均 2 个 hook = 42,000 次 message 拷贝
- 但 tuple 是浅拷贝（不复制 Message 对象本身，只复制引用），实际开销 < 5ms / 整次 query_loop
- 仍然 acceptable

**Hook 实现者警示**：
- 不要在 `pre_tool_use` / `post_tool_use`（高频时机）的 hook 内迭代 messages 全量
- 高频 hook 应该在 100 微秒内返回，否则会成为吞吐量瓶颈
- 如果需要历史聚合（如 cumulative cost），实现层维护自己的累计器，不要每次从 messages 重算

### 3.5 v2 触发条件（F1.7 修复）

如果以下任一条件成立，v2 必须重新评估"顺序 vs 并行执行"：

- 单个时机注册的 hook 数 > 5（生产场景中很可能）
- 单个 hook 的 p99 延迟 > 50ms（如外部 HTTP webhook hook）
- 用户报告 hook 拖慢对话响应（端到端 latency 增加 > 200ms）

到时切换到 `asyncio.gather` 并行 + 等长超时即可。但 v1 不预防性引入。

---

## 4. Alternatives Considered

### 4.1 全盘复刻 CC 13 hook 事件

**拒绝原因**：6 个事件（permission / teammate / setup 等）在 FinRobot v1 无对应业务场景；引入只增加测试矩阵和接口复杂度，无任何 v1 价值。

### 4.2 并行执行 hook（仿 CC）

**拒绝原因**：v1 hook 是 in-process callback，typical < 50ms，串行总开销可接受。并行带来的复杂度（race condition、错误聚合、cancellation）不值得。v2 evaluate。

### 4.3 单一 `on_event(event_type, ...)` 通用接口

**拒绝原因**：失去类型安全。`HookContext.payload: dict[str, Any]` 已经是必要妥协；如果再把时机也变成 string，连静态分析都做不了。固定 timing literal + 时机特定 payload 是最小灵活性。

### 4.4 让 hook 可以注入新消息到 state.messages

**拒绝原因**：会让 state 变化路径不可预测，违背 "state 只在 loop 内被 mutate" 原则。如果 hook 需要影响后续 model call，应该走 `pre_model_call` + `block=True` 然后由 loop 上层重新调度，而不是直接改 state。

---

## 5. Implementation Notes

### 5.1 测试要点

- **UT-21**: 7 个时机都能被注册和触发（基础 happy path）
- **UT-22**: hook 抛异常时 loop 不崩溃，错误入 audit
- **UT-23**: hook 顺序执行（按注册顺序）
- **UT-24**: `pre_tool_use` 的 `modified_input` 链式生效
- **UT-25**: `pre_model_call` 的 `block=True` 让 loop terminate
- **UT-26**: hook 整体超时后 cancel 未完成的 hook
- **IT**: audit_trail_writer 作为内置 hook，端到端验证审计事件流

### 5.2 调用频率上限

| 时机 | 单次 user turn 最大次数（约束） |
|---|---|
| loop_start | 1 |
| pre_model_call / post_model_call | max_turns = 30 |
| pre_tool_use / post_tool_use | 每轮工具数 × 30 ≈ 数百 |
| pre_compact | auto-compact 频率 × 30，通常 ≤ 3 |
| loop_terminate | 1 |

`pre_tool_use` / `post_tool_use` 是高频时机，hook 实现必须性能敏感（< 10ms 目标）。

### 5.3 与 audit trail 的耦合

`AuditEvent` 是 loop 直接 yield 的产物，不通过 hook。`post_tool_use` hook 是一个**可选的额外渠道**给业务侧加更多 audit 维度（如"这个工具属于哪个金融产品类别"这种应用层信息），但 **基础 audit 不依赖 hook**。

这是有意设计：audit trail 是 FinRobot 核心差异化，不能因为某个客户没注册 hook 就丢失。

---

## 6. 状态字段添加到 QueryStateSnapshot

为了让 hook 拿到只读状态视图，需要新增：

```python
# finrobot/conversation/state.py

@dataclass(frozen=True)
class QueryStateSnapshot:
    """传给 hook 的只读视图。从 QueryState 派生，所有字段不可修改。"""

    session_id: str
    user_id: str
    fund_id: str
    audit_chain_id: str
    turn_count: int
    consecutive_failures: int
    consecutive_tool_failures: int
    max_output_tokens_recovery_count: int
    has_attempted_escalate: bool
    messages: tuple[Message, ...]  # tuple 而非 list 强化不可变
    total_usage: TokenUsage

    @classmethod
    def from_state(cls, state: QueryState) -> "QueryStateSnapshot":
        return cls(
            session_id=state.session_id,
            user_id=state.user_id,
            fund_id=state.fund_id,
            audit_chain_id=state.audit_chain_id,
            turn_count=state.turn_count,
            consecutive_failures=state.consecutive_failures,
            consecutive_tool_failures=state.consecutive_tool_failures,
            max_output_tokens_recovery_count=state.max_output_tokens_recovery_count,
            has_attempted_escalate=state.has_attempted_escalate,
            messages=tuple(state.messages),
            total_usage=state.total_usage,
        )
```

每次调用 hook 前 `from_state(state)` 重新生成。性能损失：拷贝 messages tuple，30 轮对话每轮 ~100 条消息 = 3000 次拷贝，估计 < 1ms。可接受。

---

## 7. 评审 Checklist

- [ ] 7 个时机覆盖 v1 全部需求
- [ ] `block` / `modified_input` 语义对每个时机都明确
- [ ] 失败处理路径（异常 / 超时）明确
- [ ] 与 audit trail 系统的边界清晰（audit 不依赖 hook）
- [ ] 测试要点 UT-21 ~ UT-26 写入 Pillar 1 文档
- [ ] Pillar 1 文档第 8.1 节"Week 0 mini-ADR"标记为已决议
