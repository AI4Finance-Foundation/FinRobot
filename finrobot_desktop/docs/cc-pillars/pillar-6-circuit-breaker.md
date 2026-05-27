# Pillar 6: Circuit Breaker — 整合文档

| | |
|---|---|
| **版本** | 0.1 草案 |
| **日期** | 2026-05-12 |
| **状态** | 由 Pillar 1 + Pillar 2 实施覆盖；本 doc 仅做整合 + 补充 |
| **前置** | Pillar 1 v0.4、Pillar 2 v0.2、Pillar 5 v0.1 |

---

## 0. 为什么 Pillar 6 不需要独立调研

Circuit Breaker 的本质是"**累计失败超过阈值时拒绝继续，防止资源浪费**"。这个机制在 FinRobot 内**已经分散在多个 Pillar 中实施完毕**：

- Pillar 1 §4.6：`consecutive_failures` 模型 API 失败计数 + 熔断
- Pillar 1 §4.6：`consecutive_tool_failures` 工具失败计数 + 熔断（修复 homepilot bug）
- Pillar 1 §4.9：`max_output_tokens_recovery_count` 回收次数上限
- Pillar 5 §4.2：`CompactTracking.consecutive_failures` 压缩失败计数 + 熔断

CC 本身也没有"统一的 circuit breaker 模块"——它是分散在 query loop、compact、API retry 各处的不同计数器。

本 doc 的作用：**整合视图 + 补 FinRobot 特有缺失**。

---

## 1. 现有熔断盘点

| 计数器 | 位置 | 默认阈值 | 增加条件 | 重置条件 | 触发后 |
|---|---|---|---|---|---|
| `consecutive_failures` | Pillar 1 QueryState | 3 | 模型 API 失败、max_tokens 回收耗尽 | 工具调用成功 | `ErrorEvent` + loop terminate |
| `consecutive_tool_failures` | Pillar 1 QueryState | 5 | 所有工具 is_error 的 turn | 任一工具成功的 turn | `ErrorEvent` + loop terminate |
| `max_output_tokens_recovery_count` | Pillar 1 QueryState | 3 | max_tokens recovery 进入 | escalate 后不重置 | 进入 exhausted 路径 |
| `compact_tracking.consecutive_failures` | Pillar 5 CompactTracking | 3 | compact 异常 / 摘要空 | compact 成功 | `should_auto_compact` 返回 False（不再尝试） |

---

## 2. FinRobot 特有补充

### 2.1 Cost-based Circuit Breaker（v1 新增）

CC 有 `getTotalCost() >= maxBudgetUsd` 检查（`QueryEngine.ts:971-1002`），但 FinRobot v1 在多租户场景下需要**per-fund cost cap**。

```python
# finrobot/conversation/state.py（扩展）

@dataclass
class QueryState:
    # ... existing fields ...
    cumulative_cost_usd: float = 0.0
    """累计本次 user turn 的 LLM cost（USD）。
    每次 model_call_complete 后由 post_model_call hook 增加。"""

# finrobot/conversation/config.py（扩展）

@dataclass
class QueryConfig:
    # ... existing fields ...
    max_cost_usd_per_turn: float | None = None
    """单次 user turn cost 上限。None = 不检查。
    建议生产值：0.50 USD（覆盖一份典型研究备忘录），客户可配。"""
```

```python
# finrobot/conversation/loop.py（Pillar 1 v0.x sync）

def _should_cost_break(state, config) -> bool:
    if config.max_cost_usd_per_turn is None:
        return False
    return state.cumulative_cost_usd >= config.max_cost_usd_per_turn
```

加入 `query_loop` 的 pre-loop guards：

```diff
 while True:
     if state.should_stop_max_turns(config.max_turns):
         yield build_audit("loop_terminate", state=state, reason="max_turns")
         return
+    if _should_cost_break(state, config):
+        yield ErrorEvent(
+            error_type="CostCircuitBreaker",
+            message=cost_break_msg(config.language, state.cumulative_cost_usd, config.max_cost_usd_per_turn),
+        )
+        yield build_audit("loop_terminate", state=state, reason="cost_exhausted",
+                          cost_used=state.cumulative_cost_usd)
+        return
     # ... existing guards ...
```

### 2.2 Provider-level rate limit aware backoff（v2 推迟）

`RetryableAPIError`（Pillar 1 §4.10）当前仅触发 `consecutive_failures += 1`。CC 在 retry 内有 `withRetry` 的指数退避 + jitter。

FinRobot v1 不在 loop 层做退避——上游 PydanticAIAdapter 透传 retry。

v2 evaluate：在 ModelAdapter 内集成 `Retry-After` 头解析。

### 2.3 用户主动取消（已覆盖）

Pillar 1 v0.3 §4.6 try/finally GeneratorExit 处理 cancellation——这本身就是一种"用户驱动的 circuit breaker"。

---

## 3. 双语熔断消息

```python
# finrobot/conversation/messages.py（扩展）

_MSG.update({
    "zh": {
        # ... existing keys ...
        "cost_circuit_breaker": "本次对话累计消耗 ${used:.2f}，超过配额 ${limit:.2f}。已停止以防资源浪费。",
    },
    "en": {
        # ... existing keys ...
        "cost_circuit_breaker": "Conversation accumulated ${used:.2f} cost, exceeding ${limit:.2f} budget. Stopped to prevent resource waste.",
    },
})

def cost_break_msg(lang: str, used: float, limit: float) -> str:
    return _MSG[lang]["cost_circuit_breaker"].format(used=used, limit=limit)
```

---

## 4. 测试要点

- **UT-P6-01..03**：3 个 Pillar 1 计数器在阈值触发（已在 Pillar 1 UT-12/13 覆盖）
- **UT-P6-04**：compact 失败 3 次后 `should_auto_compact` 返回 False（Pillar 5 UT 覆盖）
- **UT-P6-05**：cost-based circuit breaker 触发（新增）
- **UT-P6-06**：`max_cost_usd_per_turn = None` 时永不触发 cost break
- **UT-P6-07**：双语 cost break msg 正确渲染
- **IT-P6-01**：注入累计 cost 超过 0.50 → loop terminate + AuditEvent 携带 cost_used

---

## 5. 未决问题

1. **Cost 计算精度**：v1 用 PydanticAIAdapter 返回的 usage × per-model 单价表（硬编码字典）。v2 evaluate Anthropic / OpenAI 真实账单 API
2. **Per-tenant 总预算**（跨 user turn 累计）：v1 不支持，仅 per-turn。v2 加 fund-level monthly budget
3. **Cost 通知给客户端**：v1 仅在 audit log，不发 SSE。v2 evaluate 实时 cost 显示

---

## 6. 实施计划

**与 Pillar 1 v0.x 同步进行**（cost circuit breaker 是 Pillar 1 主循环的小补丁）：

- [ ] QueryState 加 `cumulative_cost_usd` 字段
- [ ] QueryConfig 加 `max_cost_usd_per_turn` 字段
- [ ] Pillar 1 主循环加 `_should_cost_break` 守卫
- [ ] 双语 cost_break_msg
- [ ] post_model_call hook 内累加 cost（需要 model registry per-token 单价表）
- [ ] UT-P6-05..07
- [ ] IT-P6-01

工程量 < 1 天，与 Pillar 1 v0.5 一起合并。

---

## 7. 参考资料

- Pillar 1 v0.4 §4.6 + §4.9（已有熔断机制）
- Pillar 5 v0.1 §4.2（compact 熔断）
- CC `QueryEngine.ts:971-1002`（cost cap 参考）
