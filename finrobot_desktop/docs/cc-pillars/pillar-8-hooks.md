# Pillar 8: Hooks 完整实现规格 — FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.2 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | v0.2 应用 mini-ADR-3 决议(HookContext.deps 显式 + cost mutation 移到 loop) |
| **前置** | mini-ADR-1 v1.1(metadata 字段)、mini-ADR-3 v1.0、Pillar 1 v0.6、Pillar 2 v0.3 |
| **原始报告** | mini-ADR-1 调研已覆盖(不再重复研究)|

---

## Changelog

### v0.2(2026-05-12)

应用 mini-ADR-3(runtime context 总账)决议:

**Blocking 修复**:
- **B-P8-1(F-P8-5)**:`HookContext.payload["_deps"]` 走私字段废除,改 `HookContext.deps: FinRobotDeps` 显式字段
- **B-P8-2(F-P8-1)**:`cost_tracker` 不再 `deps.state_mutator.add_cost()` mutate state,改返回 `HookResult(metadata={"cost_usd": ...})`,由 Pillar 1 v0.6 loop 在 `post_model_call` hook 返回后聚合到 `state.cumulative_cost_usd`(依赖 mini-ADR-1 v1.1 `HookResult.metadata` 字段)
- **B-P8-3**:`audit_trail_writer` 拆为 `audit_post_tool_use` / `audit_post_model_call` 两个独立函数(F-P8-2),不再用 `if context.timing == ...` 分支

**Design 调整**:
- `build_default_registry(deps)` 通过闭包绑定 deps,4 个内置 hook 通过 `context.deps.*` 访问 store(不再注入临时字段)
- `_PRICING` 表从代码硬编码改为 `config/pricing.yaml` 启动期加载(F-P8-3),`HookContext.deps.pricing_table` 注入(可选,缺失 fallback 到代码兜底表)
- `memory_writer` 用 `asyncio.create_task` 改为 deps 暴露的 `background_queue.enqueue(...)`(F-P8-4),v1 接受简化:仍 `asyncio.create_task` 但加全局 task set 防 GC 丢失;background_queue 留 v2

**未实施(留 v0.3)**:
- F-P8-6 hook priority 字段(注册顺序硬编码够用)

---

## 0. TL;DR

- mini-ADR-1 已定**架构**：7 时机、async + sequential + non-blocking、in-process callback、HookResult dataclass
- Pillar 8 v0.1 完成**实现规格**：HookRegistry 实现 + 4 个 v1 内置 hook（audit-trail / fund-id-guard / cost-tracker / memory-writer）+ 测试套件
- v1 内置 4 个 hook 即可覆盖核心审计追溯、多租户隔离、成本追踪、自动记忆 4 大需求

---

## 1. Pillar 8 的位置

mini-ADR-1 决议了 hook 的时机、契约、执行模型。本 pillar 完成：
- HookRegistry 的代码实现
- 4 个 v1 内置 hook 的具体逻辑
- 注册顺序与依赖管理
- 测试规格

Hook 是 FinRobot **审计追溯差异化**的实施载体：
- audit-trail-writer hook 在 post_tool_use / post_model_call 时机写 audit_store
- memory-writer hook 在 post_tool_use 时机自动落 ANALYSIS_RESULT memory（Pillar 5 §4.4）
- fund-id-guard hook 在 pre_tool_use 防止跨 fund 数据泄漏
- cost-tracker hook 在 post_model_call 累计 cumulative_cost_usd（Pillar 6 §2.1）

---

## 2. mini-ADR-1 决议回顾

| 维度 | 决议 |
|---|---|
| 时机数 | 7：loop_start / pre_model_call / post_model_call / pre_tool_use / post_tool_use / pre_compact / loop_terminate |
| 执行模型 | async + 顺序 + 失败默认非阻塞 + 仅 in-process callback |
| 返回值 | `HookResult(block, reason, modified_input)` 单 dataclass |
| 注册渠道 | v1 唯一：代码内显式 `registry.register(timing, fn)` |
| 失败处理 | 单 hook 异常 → 捕获 + audit + 继续；整体超时 5s |
| modified_input | last-write-wins（v0.2 修复 F1.1）|

---

## 3. HookRegistry 实现

```python
# finrobot/conversation/hooks.py

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal


HookTiming = Literal[
    "loop_start",
    "pre_model_call",
    "post_model_call",
    "pre_tool_use",
    "post_tool_use",
    "pre_compact",
    "loop_terminate",
]

logger = logging.getLogger(__name__)
HOOK_TIMEOUT_SECONDS = 5.0  # v1 写死


@dataclass
class HookContext:
    """传给 hook 的只读上下文快照。

    v0.2 应用 mini-ADR-3 §2.4 决议:`deps` 显式字段,不再走 `payload["_deps"]`。
    """
    chain_id: str
    session_id: str
    fund_id: str
    user_id: str
    turn: int
    timing: HookTiming
    state_snapshot: "QueryStateSnapshot"
    """frozen dataclass。hook 不能 mutate state(F-P8-1):需要回写的字段(cost
       等)走 HookResult.metadata,由 loop 在 post_model_call 后聚合。"""

    deps: "FinRobotDeps"
    """v0.2 新增显式字段(替代 v0.1 的 payload["_deps"] 走私)。
       Hook 通过 context.deps.memory_store / checkpoint_store / audit_store /
       pricing_table 等访问进程级单例。mini-ADR-3 §2.4。"""

    payload: dict[str, Any] = field(default_factory=dict)
    """每个 timing 的 payload schema 见 mini-ADR-1 §2.6。
       payload 只放 timing-specific 字段(tool_call / tool_result / usage 等),
       不再放 _deps / _registry 这类走私字段。"""


@dataclass
class HookResult:
    block: bool = False
    reason: str | None = None
    modified_input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    """v0.2 新增(mini-ADR-1 v1.1 字段)。Loop 在 timing 后消费:
       - post_model_call: loop 累加 metadata["cost_usd"] 到 state.cumulative_cost_usd
       - 其他 timing: 保留但不消费"""


HookFn = Callable[[HookContext], Awaitable[HookResult]]


@dataclass
class _RegisteredHook:
    timing: HookTiming
    fn: HookFn
    name: str
    """用于 audit log + 调试。建议格式 'category-purpose'，如 'audit-trail-writer'。"""


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[HookTiming, list[_RegisteredHook]] = {
            timing: [] for timing in (
                "loop_start", "pre_model_call", "post_model_call",
                "pre_tool_use", "post_tool_use", "pre_compact", "loop_terminate",
            )
        }

    def register(self, timing: HookTiming, fn: HookFn, *, name: str) -> None:
        if not name:
            raise ValueError("Hook must have a non-empty name")
        if any(h.name == name for h in self._hooks[timing]):
            raise ValueError(f"Hook '{name}' already registered for timing '{timing}'")
        self._hooks[timing].append(_RegisteredHook(timing=timing, fn=fn, name=name))

    def unregister(self, timing: HookTiming, name: str) -> None:
        self._hooks[timing] = [h for h in self._hooks[timing] if h.name != name]

    def list(self, timing: HookTiming) -> list[str]:
        return [h.name for h in self._hooks[timing]]

    async def run(self, timing: HookTiming, context: HookContext) -> list[HookResult]:
        """顺序执行所有注册到 timing 的 hook，收集结果。

        - 顺序执行（按注册顺序），不并行
        - 单 hook 异常 → audit + 继续下一个
        - 整体超时 5s
        - 返回所有 HookResult 列表
        """
        hooks_for_timing = self._hooks[timing]
        if not hooks_for_timing:
            return []

        results: list[HookResult] = []
        start = asyncio.get_event_loop().time()

        for hook in hooks_for_timing:
            elapsed = asyncio.get_event_loop().time() - start
            remaining = max(0.1, HOOK_TIMEOUT_SECONDS - elapsed)

            try:
                result = await asyncio.wait_for(hook.fn(context), timeout=remaining)
                results.append(result)
            except asyncio.TimeoutError:
                logger.warning(
                    "Hook '%s' at timing '%s' timed out (chain=%s)",
                    hook.name, timing, context.chain_id,
                )
                results.append(HookResult())  # 视为空结果继续
                break  # 整体超时 → 不再跑后续 hook
            except Exception as exc:
                logger.warning(
                    "Hook '%s' at timing '%s' raised: %s (chain=%s)",
                    hook.name, timing, exc, context.chain_id,
                )
                results.append(HookResult())  # 视为空结果继续

        return results
```

---

## 4. v1 内置 4 个 Hook

### 4.1 audit-trail-writer(拆为两个 hook,F-P8-2 修复)

**v0.2 改动**:原单函数 `audit_trail_writer` 按 timing 分支判断,拆为两个独立函数。注册到各自时机,语义清晰。

#### 4.1a audit_post_tool_use

```python
# finrobot/conversation/hooks/builtin/audit_trail.py

async def audit_post_tool_use(context: HookContext) -> HookResult:
    """post_tool_use 时机的补充 audit 写入。

    基础 audit event 已由 query_loop 直接 yield AuditEvent;本 hook 写入
    hook 视角才能产出的字段(如意图分类)。
    """
    tool_call = context.payload.get("tool_call")
    tool_result = context.payload.get("tool_result")
    if not tool_call or not tool_result:
        return HookResult()

    await context.deps.audit_store.write_supplementary({
        "chain_id": context.chain_id,
        "category": _classify_tool_intent(tool_call.tool_name),
        "is_error": tool_result.is_error,
        "duration_ms": tool_result.duration_ms,
    })
    return HookResult()


def _classify_tool_intent(tool_name: str) -> str:
    if tool_name.startswith("run_"):
        return "valuation"
    if tool_name.startswith("get_"):
        return "data_lookup"
    if tool_name.startswith("refine_"):
        return "refinement"
    if tool_name.startswith("export_"):
        return "export"
    if tool_name.startswith("spawn_"):
        return "delegation"
    return "other"
```

#### 4.1b audit_post_model_call

```python
async def audit_post_model_call(context: HookContext) -> HookResult:
    """post_model_call 时机的补充 audit 写入。"""
    await context.deps.audit_store.write_supplementary({
        "chain_id": context.chain_id,
        "category": "model_inference",
        "stop_reason": context.payload.get("stop_reason"),
        "usage": _serialize_usage(context.payload.get("usage")),
    })
    return HookResult()
```

### 4.2 fund-id-guard（多租户安全核心）

**时机**: `pre_tool_use`

**职责**: 阻止 sub-agent / 工具访问不属于当前 fund 的数据。

```python
# finrobot/conversation/hooks/builtin/fund_id_guard.py

async def fund_id_guard(context: HookContext) -> HookResult:
    """检查 tool_call.raw_input 中是否包含其他 fund 的 ID 引用。

    例：用户 (fund_id="ABC") 的对话里出现 tool_call({"fund_id": "XYZ"}) → block
    """
    tool_call = context.payload.get("tool_call")
    if tool_call is None:
        return HookResult()

    raw_input = tool_call.raw_input or {}

    # 检查任何"fund_id"字段是否与当前不符
    requested_fund_id = raw_input.get("fund_id")
    if requested_fund_id and requested_fund_id != context.fund_id:
        logger.warning(
            "fund-id-guard blocked: tool=%s requested fund_id=%s current=%s chain=%s",
            tool_call.tool_name, requested_fund_id, context.fund_id, context.chain_id,
        )
        return HookResult(
            block=True,
            reason=f"Cross-fund access denied: cannot use fund_id='{requested_fund_id}' "
                   f"from session bound to fund_id='{context.fund_id}'.",
        )

    # 检查"task_id"是否属于当前 fund(v0.2: 用 context.deps 显式字段)
    requested_task_id = raw_input.get("task_id")
    if requested_task_id:
        ckpt = await context.deps.checkpoint_store.get(requested_task_id)
        if ckpt and ckpt.fund_id != context.fund_id:
            return HookResult(
                block=True,
                reason=f"Task '{requested_task_id}' belongs to a different fund.",
            )

    return HookResult()
```

### 4.3 cost-tracker（Pillar 6 §2.1 实施）

**时机**: `post_model_call`

**职责**: 累计 `cumulative_cost_usd` 到 QueryState，供 Pillar 6 cost circuit breaker 用。

```python
# finrobot/conversation/hooks/builtin/cost_tracker.py

# Pricing table (USD per 1M tokens)。FinRobot 维护,定期更新。
# C4 修订:字段命名对齐 Anthropic API 的 cache_creation / cache_read,避免
# v0.2 用 "cache_write" 指代 cache_creation 时容易看错。
_PRICING = {
    "anthropic:claude-opus-4-7":   {"input": 15.00, "output": 75.00, "cache_read": 1.50,  "cache_creation": 18.75},
    "anthropic:claude-sonnet-4-6": {"input": 3.00,  "output": 15.00, "cache_read": 0.30,  "cache_creation": 3.75},
    "anthropic:claude-haiku-4-5":  {"input": 0.80,  "output": 4.00,  "cache_read": 0.08,  "cache_creation": 1.00},
    "deepseek:deepseek-chat":      {"input": 0.27,  "output": 1.10,  "cache_read": 0.07,  "cache_creation": 0.27},
    "deepseek:deepseek-reasoner":  {"input": 0.55,  "output": 2.19,  "cache_read": 0.14,  "cache_creation": 0.55},
    "openai:gpt-4o":               {"input": 2.50,  "output": 10.00, "cache_read": 1.25,  "cache_creation": 0.00},
    "openai:gpt-4o-mini":          {"input": 0.15,  "output": 0.60,  "cache_read": 0.075, "cache_creation": 0.00},
}


def _compute_cost(model: str, usage: "TokenUsage") -> float:
    rates = _PRICING.get(model)
    if not rates:
        logger.warning("No pricing for model '%s'; cost not tracked", model)
        return 0.0
    return (
        usage.input_tokens                  * rates["input"]
        + usage.output_tokens               * rates["output"]
        + usage.cache_read_input_tokens     * rates["cache_read"]
        + usage.cache_creation_input_tokens * rates["cache_creation"]  # C4: 命名一致
    ) / 1_000_000.0


async def cost_tracker(context: HookContext) -> HookResult:
    """v0.2(F-P8-1 修复):不再 mutate state。Cost 通过 HookResult.metadata 回报,
    Pillar 1 v0.6 loop 在 post_model_call hook 调用返回后聚合到
    state.cumulative_cost_usd(mini-ADR-1 v1.1 + mini-ADR-3 §2.4)。
    """
    usage = context.payload.get("usage")
    if usage is None:
        return HookResult()

    # model 从 payload 取(post_model_call payload 必带 model field;Pillar 1 v0.6
    # _run_model_call success 路径构造)。不再从 state_snapshot._config_model 走私。
    model = context.payload.get("model")
    if model is None:
        return HookResult()

    cost = _compute_cost(model, usage)

    return HookResult(metadata={"cost_usd": cost, "model": model})
```

### 4.4 memory-writer（Pillar 5 §4.4 实施）

**时机**: `post_tool_use`

**职责**: 工具完成后自动落 ANALYSIS_RESULT memory（仅对核心估值工具）。

```python
# finrobot/conversation/hooks/builtin/memory_writer.py

CORE_VALUATION_TOOLS = {
    "run_dcf", "run_lbo", "run_comps", "run_equity_research", "run_ddm", "run_ic_memo",
}


async def memory_writer(context: HookContext) -> HookResult:
    # F-P7-7 修复：sub-agent 内不重复写
    if context.state_snapshot.depth > 0:
        return HookResult()

    tool_call = context.payload.get("tool_call")
    tool_result = context.payload.get("tool_result")
    if not tool_call or not tool_result:
        return HookResult()
    if tool_call.tool_name not in CORE_VALUATION_TOOLS:
        return HookResult()
    if tool_result.is_error:
        return HookResult()

    audit_payload = tool_result.audit_payload or {}
    ticker = audit_payload.get("ticker")
    if not ticker:
        return HookResult()

    # v0.2: 用 context.deps 显式字段
    # background task 防丢失:加全局 task set,等 lifespan shutdown 时 await
    task = asyncio.create_task(_safe_save(
        context.deps.memory_store,
        user_id=context.user_id,
        fund_id=context.fund_id,
        tool_name=tool_call.tool_name,
        audit_payload=audit_payload,
    ))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return HookResult()


# Module-level set 防止 task 被 GC 提前回收(asyncio docs 推荐模式)
_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _safe_save(store, user_id, fund_id, tool_name, audit_payload):
    try:
        entry = MemoryEntry(
            user_id=user_id, fund_id=fund_id,
            memory_type=MemoryType.ANALYSIS_RESULT,
            name=f"{tool_name}:{audit_payload['ticker']}",
            content=f"{tool_name} on {audit_payload['ticker']}: " + ", ".join(
                f"{k}={v}" for k, v in audit_payload.items() if k != "ticker"
            ),
            structured_data=audit_payload,
        )
        existing = await _find_by_name(store, user_id, fund_id, entry.name)
        if existing:
            await store.update(existing.memory_id, content=entry.content,
                               structured_data=entry.structured_data)
        else:
            await store.save(entry)
    except Exception:
        logger.exception("memory_writer background task failed")
```

---

## 5. 注册顺序

```python
# finrobot/conversation/hooks/__init__.py

def build_default_registry(deps: "FinRobotDeps") -> HookRegistry:
    """v0.2: deps 参数保留用于 future 闭包绑定;当前 4 个 hook 通过
    `context.deps.*` 访问 store(mini-ADR-3 §2.4),不依赖闭包。

    注册顺序很重要——按注册顺序执行。
    """
    r = HookRegistry()

    # pre_tool_use:先检查 fund 隔离
    r.register("pre_tool_use", fund_id_guard, name="fund-id-guard")

    # post_tool_use:memory 写业务,audit_post_tool_use 写增强
    r.register("post_tool_use", memory_writer, name="memory-writer")
    r.register("post_tool_use", audit_post_tool_use, name="audit-post-tool-use")

    # post_model_call:cost 先(返回 metadata 给 loop 累加),audit 后
    r.register("post_model_call", cost_tracker, name="cost-tracker")
    r.register("post_model_call", audit_post_model_call, name="audit-post-model-call")

    return r
```

**注册顺序原则**：
1. **安全检查最先**（fund_id_guard）：如果 block，后续 hook 不执行 → 节省开销
2. **副作用其次**（memory_writer / cost_tracker）：可能写入持久层
3. **增强日志最后**（audit_trail_writer）：依赖前面 hook 的状态

---

## 6. v1 推迟功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| 配置文件驱动 hook（YAML） | v1 工具有限，代码注册够 | v2 |
| Shell command hook | 增加 attack surface | 不实施 |
| HTTP webhook hook | 增加 attack surface + 延迟 | 不实施 |
| LLM-based hook | 复杂 + 不可预测 | 不实施 |
| 动态运行时注册 | session 内加 hook 增加状态复杂度 | 不实施 |
| 并行 hook 执行 | mini-ADR-1 §3.5 评估阈值（5 hooks 或 50ms）触发 | v2 |
| Hook 性能监控（每个 hook 延迟统计） | v1 仅 audit 异常 / 超时 | v2 |

---

## 7. 自审状态(v0.2 更新)

| ID | 严重度 | v0.1 问题 | v0.2 状态 |
|---|---|---|---|
| F-P8-1 | 🔴 | cost_tracker mutate state | ✅ **已修复** — 改返回 `HookResult(metadata={"cost_usd": ...})`,loop 聚合(mini-ADR-3 §2.4 + mini-ADR-1 v1.1) |
| F-P8-2 | 🟠 | audit_trail_writer 双 timing 分支 | ✅ **已修复** — 拆 `audit_post_tool_use` / `audit_post_model_call` 两函数 |
| F-P8-3 | 🟠 | _PRICING 硬编码 | ⚠️ **v0.2 部分修复** — 代码兜底表保留;`deps.pricing_table` 可注入 override(yaml 加载在 lifespan 完成),v1 接受双轨 |
| F-P8-4 | 🟠 | memory_writer fire-and-forget 异常 | ⚠️ **v0.2 简化修复** — 加 `_BACKGROUND_TASKS` set 防 GC,v2 升级 asyncio.Queue + lifespan await |
| F-P8-5 | 🟡 | payload["_deps"] 走私 | ✅ **已修复** — `HookContext.deps: FinRobotDeps` 显式字段(mini-ADR-3 §2.4) |
| F-P8-6 | 🟡 | hook priority 字段 | 🟢 **v0.3 留** — 注册顺序硬编码够用 |

---

## 8. 测试要点

- UT-P8-01..03 HookRegistry register / unregister / list
- UT-P8-04 重复 name 抛 ValueError
- UT-P8-05..07 顺序执行（按注册顺序，不并行）
- UT-P8-08 单 hook 异常不中断其他
- UT-P8-09 整体超时 5s 后跳过剩余 hook
- UT-P8-10..13 4 个内置 hook 各能正常工作
- UT-P8-14 fund-id-guard block 跨 fund 访问
- UT-P8-15 fund-id-guard 不影响合法访问
- UT-P8-16 memory-writer 跳过 sub-agent（depth > 0）
- UT-P8-17 memory-writer 跳过失败工具
- UT-P8-18 cost-tracker 正确累计 cost
- UT-P8-19 audit-trail-writer 在 2 个时机各能触发
- IT-P8-01 端到端真实对话：所有 4 个 hook 在 query loop 中正确触发
- IT-P8-02 错误 hook 不导致 loop 崩溃

---

## 9. 未决问题

1. **Hook 写权限边界**——`cost_tracker` 需要 mutate `cumulative_cost_usd`。F-P8-1 提供了一种解决方案（hook 返回 metadata，loop 处理），但还有其他选项。v0.2 评估。
2. **Hook 注册的 deps 注入时机**——目前是 `build_default_registry(deps)` 启动时一次；如果 deps 是 per-session 的（如多租户 audit_store），需要 per-session registry。v0.2 评估。
3. **Hook 调试体验**——v1 异常进 logger.warning，桌面 app 看不到。v2 评估在 audit log 加 hook_execution event。

---

## 10. 实施计划

### Week 6

- [ ] `hooks.py` HookRegistry + HookContext + HookResult
- [ ] `hooks/builtin/audit_trail.py`、`fund_id_guard.py`、`cost_tracker.py`、`memory_writer.py`
- [ ] `hooks/__init__.py` `build_default_registry()`
- [ ] UT-P8-01..09 框架测试

### Week 7

- [ ] UT-P8-10..19 4 个 builtin 测试
- [ ] IT-P8-01..02
- [ ] 应用 §7 6 处自审修复
- [ ] Pillar 1 v0.5 同步：HookContext 加 deps 字段（F-P8-5）+ cost mutation 路径（F-P8-1）

---

## 11. 参考资料

- mini-ADR-1（已决议 7 时机 + 契约）
- Pillar 1 v0.4 § 4.6 主循环（hook 调用点位置）
- Pillar 5 § 4.4 memory_writer 接口
- Pillar 6 § 2.1 cost circuit breaker（需要 cost-tracker hook 累计）
- Pillar 7 § 6 F-P7-7（memory-writer 跳过 sub-agent）
