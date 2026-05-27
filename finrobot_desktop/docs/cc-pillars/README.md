# CC Pillars — FinRobot Conversation Agent OS 设计文档总览

> **Phase 6**:FinRobot 进入 Conversation Agent OS 阶段。仿 Claude Code 架构构建对话内核(`finrobot/conversation/`),整合 FinRobot 金融能力作为 conversational tools。CLAUDE.md 战略方向已更新。

| | |
|---|---|
| **状态** | 设计阶段 v0.7 完成,等用户最终评审/批准实施 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **依据** | Explore 子 agent 并行调研 CC 源码 + homepilot 参考实现 + 多轮自审 + 用户 3 次正式 review(v0.1 → v0.6 → v0.7) |

---

## 0. 高层摘要

- **CC 源码**:`/Users/zhunihaoyun/Desktop/code/claude-code/src/` — 真实本体(未压缩 TypeScript)
- **参考实现**:`/Users/zhunihaoyun/Desktop/code/zm/homepilot/` — 同作者用 Python 仿 CC 写过一次
- **方法论**:D 方案(homepilot 为骨架 + CC 源码 cross-reference + 修复 homepilot 缺陷 + 适配金融场景)
- **总产出**:23 个 markdown 文件,~10500 行(含 mini-ADR-3 runtime context 总账)
- **重要约束**:CLAUDE.md 第 11 行 `No LangChain. No LangGraph. No AutoGen. No LiteLLM.` 全部遵守

---

## 1. 8 个 Pillar + 3 个 mini-ADR 当前版本

| # | 文档 | 版本 | 行数 | 当前状态 |
|---|---|---|---|---|
| 1 | [pillar-1-query-loop.md](pillar-1-query-loop.md) | **v0.7** | ~1500 | 主循环 hook 签名对齐 + post_model_call 无条件触发 + cost guard + ModelCallOutcome typed |
| 2 | [pillar-2-tool-system.md](pillar-2-tool-system.md) | **v0.3** | ~1100 | ToolUseContext 19 字段 + shared_semaphore + DCFResult.implied_price 真实 API |
| 3 | [pillar-3-system-prompt.md](pillar-3-system-prompt.md) | **v0.2** | ~600 | `extra_static_prefix` kwarg 支持 sub-agent prompt 注入 |
| 4 | [pillar-4-streaming-sse.md](pillar-4-streaming-sse.md) | v0.1 | 488 | 12 事件类型 + AuditEvent 端点分流(本轮未改) |
| 5 | [pillar-5-compact-memory.md](pillar-5-compact-memory.md) | **v0.3** | ~700 | refine 降 v2 + checkpoint 落盘 + 读取 + GetTaskHistoryTool |
| 6 | [pillar-6-circuit-breaker.md](pillar-6-circuit-breaker.md) | v0.1 | 166 | 整合 Pillar 1 已有 + cost-based 新增(本轮未改) |
| 7 | [pillar-7-subagent.md](pillar-7-subagent.md) | **v0.3** | ~650 | F-P7-1/2/4 修 + chunks-of-5 batch + import field 字面错修 |
| 8 | [pillar-8-hooks.md](pillar-8-hooks.md) | **v0.2** | ~550 | HookContext.deps 显式 + cost metadata 路径 + audit 拆 2 函数 |

| ADR | 文档 | 版本 | 状态 |
|---|---|---|---|
| 1 | [adrs/mini-adr-1-hook-timing.md](adrs/mini-adr-1-hook-timing.md) | **v1.2** | 加 `HookResult.metadata` + post_model_call payload 补 `model` 字段 |
| 2 | [adrs/mini-adr-2-subagent-chain-id.md](adrs/mini-adr-2-subagent-chain-id.md) | v1.0 | 4 字段谱系(chain/root/parent/depth)+ MAX_DEPTH_HARD_CAP |
| 3 | [adrs/mini-adr-3-runtime-context.md](adrs/mini-adr-3-runtime-context.md) | **v1.0** | 5 个 runtime context(deps/state/tool_ctx/hook_ctx/app_state)字段所有权总账;§3.1 共享 Semaphore 决议;§5 8 条不变量 |

---

## 2. 演进历史

| 评审轮 | 触发问题 | 输出版本 |
|---|---|---|
| 用户 v0.1 评审 Pillar 1 | 16 处(B 4 + D 6 + Cleanup 6) | Pillar 1 v0.2 |
| 用户 v0.1 评审 Pillar 2 | 17 处(B 4 + D 7 + Cleanup 6) | Pillar 2 v0.2 |
| 自审 Pillar 3-8 v0.1 | 31 处 | 登记到各 pillar §6 |
| **用户 v0.5/v0.2/v0.1 评审**(2026-05-12) | 6 Blocking + 3 High Risk:hook 接口断裂 / post_model_call 缺 / ModelCallOutcome 状态机 bug / ToolUseContext 缺谱系 / Task Checkpoint 与现实差距 / RunDCFTool 字段错 / F-P7-1/2 / run_parallel 命名 / ic_memo style 缺 | mini-ADR-3 + Pillar 1 v0.6 + Pillar 2 v0.3 + Pillar 5 v0.2 + Pillar 7 v0.2 + Pillar 8 v0.2 |
| **用户 v0.6/v0.3/v0.2 评审**(2026-05-12) | 4 Blocking(post_model_call 失败路径漏 / DATA_QUALITY 内外矛盾 / field import 缺 / mini-ADR-1 payload 表缺 model)+ 9 Inconsistency + 8 Cleanup | **当前**:Pillar 1 v0.7 + Pillar 5 v0.3 + Pillar 7 v0.3 + Pillar 3 v0.2 + mini-ADR-1 v1.2 |

---

## 3. 原始调研报告(Raw)

| Pillar | CC 报告 | homepilot 报告 |
|---|---|---|
| 1 | raw/cc-pillar-1-raw.md (575) | raw/homepilot-pillar-1-raw.md (584) |
| 2 | raw/cc-pillar-2-raw.md (347) | raw/homepilot-pillar-2-raw.md (349) |
| 3 | raw/cc-pillar-3-raw.md (180) | raw/homepilot-pillar-3-raw.md (176) |
| 4 | raw/cc-pillar-4-raw.md (157) | raw/homepilot-pillar-4-raw.md (159) |
| 5 | raw/cc-pillar-5-raw.md (198) | raw/homepilot-pillar-5-raw.md (184) |
| 7 | raw/cc-pillar-7-raw.md (143) | raw/homepilot-pillar-7-raw.md (114) |

Pillar 6 / 8 是整合性 pillar,无独立 raw(前者由 Pillar 1+5 综合;后者由 mini-ADR-1 调研覆盖)。

---

## 4. 关键架构选择(v0.7 串后口径)

### 4.1 CLAUDE.md 强约束(**不可妥协**)

- **No LangChain. No LangGraph. No AutoGen. No LiteLLM.** — 全 8 pillars 遵守
- 多 provider 通过 PydanticAI 原生(`anthropic:` / `openai:` / `deepseek:`),不引入更高层抽象

### 4.2 Runtime Context 字段所有权(mini-ADR-3 决议)

| 载体 | 字段数 | 生命周期 | 关键决议 |
|---|---|---|---|
| FinRobotDeps | 11(4 现有 + 7 新增) | 进程级单例 | sub-agent 共享同一引用 |
| QueryState | 17 | 每次 query_loop 调用 | mini-ADR-2 4 字段谱系 |
| ToolUseContext | 19 | 每个 tool batch | 后 6 字段对普通工具不可见(§5.8 不变量) |
| HookContext | 9 | 每次 hook.run | `deps` 显式 + 不能 mutate state |
| engine.app_state | 2 | FastAPI lifespan | 只持 deps + hook_registry |

### 4.3 共享 Semaphore(mini-ADR-3 §3.1 决议)

同一 root user turn 下,主 agent + 所有 sub-agent 的 tool execution 共用同一 `asyncio.Semaphore(max=10)`。深嵌套慢一点可接受,失控并发不可接受。`ToolOrchestrator.fork_for_subagent` 用构造参数 `shared_semaphore` 复用父 Sem;不变量 `id(child._sem) == id(parent._sem)` 由 UT 强制断言。

### 4.4 决策汇总

| 主题 | 决策 | Pillar |
|---|---|---|
| Agent loop | AsyncGenerator + 状态机 + ModelCallOutcome typed + 双语 recovery + model-aware escalate | 1 v0.7 |
| Hook 接口 | `run(timing, ctx: HookContext)` 单参 + 7 时机 + async 顺序 + 非阻塞 + metadata 回流路径 | 1+8, mini-ADR-1 v1.2 |
| Tool 抽象 | BaseTool class + Pydantic schema + per-input 并发安全 + greedy partitioning | 2 v0.3 |
| ToolUseContext | 19 字段(13 普通 + 6 sub-agent 派生);普通工具不读后 6 | 2 v0.3 + mini-ADR-3 |
| Tool 体积上限 | 默认 64K,filings 类显式 256K | 2 |
| Pipeline 包装 | 不暴露内部步骤;ToolResult 携带 ui_actions + audit_payload | 2 |
| Sub-agent | sync + chunks-of-5 parallel batch(N>5 自动分批,不抛错)+ fork_for_subagent 共享 Sem | 7 v0.3 |
| 谱系字段 | chain / root / parent / depth 4 字段(mini-ADR-2)| 全 |
| System Prompt | 7 层装配 + STATIC_BOUNDARY_MARKER 用于 prompt caching + `extra_static_prefix` 支持 sub-agent | 3 v0.2 |
| Analyst 风格 | 5 个:value / growth / quant / education / ic_memo | 1+3 |
| 双语 | 全程支持 zh / en | 1+3+5 |
| 传输协议 | 标准 SSE(不上 WebSocket)+ fetch ReadableStream | 4 |
| Event 类型 | 12 个(基础流 9 + UIAction + ToolProgress + Done) | 4 |
| AuditEvent | 端点侧分流(写 audit_store,不发客户端);chain/root/parent/depth + tool_extra | 1+4+5+8 |
| Compact | 单一阈值 LLM 摘要 + Pillar 1 max_tokens recovery 协同 | 5 |
| Memory | SQLite + 5 类(含 ANALYSIS_RESULT 自动写) | 5 |
| Task Checkpoint | v0.3:**落盘 + 读取保留**;refine 局部重算 v2 启动(三件套齐备后) | 5 v0.3 |
| Circuit Breaker | 4 独立计数器(模型 / 工具 / recovery / compact)+ cost 上限 | 6 + 1 v0.7 |
| Cost tracking | post_model_call hook 无条件触发(每轮 1 次,含失败路径)+ HookResult.metadata 回流 | 1 v0.7 + 8 v0.2 |
| Hooks | 7 时机 + 4 个内置(audit_post_tool_use / audit_post_model_call / fund_id_guard / cost_tracker / memory_writer) | 8 v0.2 |
| 多租户隔离 | fund_id 贯穿 state / context / memory / checkpoint + fund_id_guard hook | 1-8 |

### 4.5 跨 pillar 执行图

```
用户消息 → /api/chat 端点
    ↓
    构建 AgentProfile + AssembledSystemPrompt(Pillar 3 v0.2)
    ↓
    构造 QueryState(mini-ADR-2 谱系)+ QueryConfig + 复用 FinRobotDeps(mini-ADR-3 §2.1)
    ↓
    query_loop(Pillar 1 v0.7)
    ├─ loop_start hook
    ├─ (循环)
    │   ├─ pre-loop guards: max_turns / circuit_breaker / tool_circuit / cost_break
    │   ├─ pre_compact hook → do_compact(Pillar 5)
    │   ├─ pre_model_call hook(可 block)
    │   ├─ _run_model_call → ModelCallOutcome + payload(usage/stop_reason/duration_ms)
    │   ├─ post_model_call hook **无条件**(成功+失败)→ cost-tracker.metadata → loop 聚合
    │   ├─ outcome 分支:
    │   │   ├─ FATAL_ERROR / INFRASTRUCTURE → return
    │   │   ├─ RETRYABLE_ERROR / DATA_QUALITY → continue(下轮 circuit guard 兜底)
    │   │   └─ COMPLETED → stop_reason 分支
    │   ├─ stop_reason==tool_use:
    │   │   ├─ 构造 ToolUseContext 19 字段(mini-ADR-3 §2.3)
    │   │   ├─ pre_tool_use hook → fund-id-guard(可 block,合成 tool_result)
    │   │   ├─ ToolOrchestrator.run(共享 Sem ≤ 10)
    │   │   │   ├─ Pipeline wrapper(audit_payload + surrogate task_id)
    │   │   │   └─ spawn_subagent / spawn_parallel_subagents(chunks-of-5)
    │   │   ├─ yield UIActionEvent → SSE 端点
    │   │   └─ post_tool_use hook(每 tool_result 1 次)→ memory_writer / audit_post_tool_use
    │   ├─ stop_reason==max_tokens → escalate(model-aware)→ recovery ≤3 → exhausted
    │   └─ stop_reason==refusal → loop_terminate
    └─ loop_terminate hook
    ↓
    SSE 端点分流:StreamEvent → 客户端;AuditEvent → audit_store
```

---

## 5. 实施路线图(13 周)

| 周次 | 主要内容 |
|---|---|
| Week 0 | FinRobotDeps 真实 dataclass 扩 7 字段 + lifespan 构造 + 旧 SDK / CLI 兼容性回归 |
| Week 1 | Pillar 1 骨架(state / config / types / adapter / loop 主循环 + ModelCallOutcome) |
| Week 2 | Pillar 1 完整 + Pillar 2 ToolRegistry / Orchestrator + UT |
| Week 3 | Pillar 2 wrapper tools(先 run_dcf 真实 API)+ Pillar 3 prompt 装配 + Pillar 4 SSE 端点 |
| Week 4 | Pillar 5 compact + memory + checkpoint 落盘 + Pillar 6 cost breaker |
| Week 5 | Pillar 7 spawn_subagent + fork_for_subagent + chunks-of-5 |
| Week 6 | Pillar 8 hook 框架 + 4 个内置 hook |
| Week 7 | 端到端 IT(loop + tool + sub-agent + hook + checkpoint 一条龙) |
| Week 8-10 | 桌面 app 联调 + UIAction 渲染 + 性能调优 |
| Week 11-12 | 完整测试套件 + 边界 + 文档 |
| Week 13 | 第一个 design partner |

**单元测试目标:≥ 200 条;集成测试 ≥ 25 条**

---

## 6. v0.7 串后的剩余债务

### Open(实施期内必处理)

1. **Pillar 1 §4.13 / §6 / §7 / §8 / §9** 历史注释/版本号残留(C8) — 实施期一次性扫
2. **Pillar 3 §6 6 处自审** v0.3 处理
3. **Pillar 4 v0.1 5 处自审** + Pillar 4 全文按 mini-ADR-3 字段复核
4. **on_progress 进度信号机制** — Pillar 2 §8 未决,等 Pillar 1 v0.8 联调时定
5. **Pillar 8 _PRICING yaml 加载** — F-P8-3 v0.2 简化 fallback,v0.3 完整接 yaml

### Deferred(明确推迟到 v2)

- **refine_dcf 局部重算** —— 需要 (a) Pipeline step dependency graph (b) assumption impact matrix (c) prefill/replay 协议 三件套齐备(mini-ADR-3 §6 决议)
- **Streaming tool execution** —— 拓扑 + 流式协调复杂度高
- **MCP 集成** —— audit guarantees 不明
- **Tool fallback model / Reactive compact / Context collapse / KAIROS** —— v1 简化

### Won't fix(v1 不做)

- 详见各 pillar §5 推迟功能表

---

## 7. 用户最终评审建议(本次启动实施前)

按"如果错了影响最大"排序:

1. **mini-ADR-3 §2 / §3 / §5** —— runtime context 总账;Week 0 真实 deps.py 扩字段会按这张表做
2. **Pillar 1 v0.7 §4.6 / §4.7** —— ModelCallOutcome 状态机 + post_model_call 无条件触发 + DATA_QUALITY 当 retryable
3. **Pillar 2 v0.3 §4.4 / §4.6 / §4.8** —— 19 字段 ToolUseContext + fork_for_subagent + RunDCFTool 真实 API
4. **Pillar 5 v0.3 §4.5** —— checkpoint 保留 + refine 降 v2 措辞
5. **Pillar 7 v0.3 §4.6** —— chunks-of-5 实现 + spawn_subagent 共享 Sem
6. **Pillar 8 v0.2 §4.3** —— cost_tracker metadata 路径 + _PRICING 表
7. **mini-ADR-1 v1.2 §2.6** —— payload schema 与所有实现位置对照

每条找到问题 → 标记 → v0.8 / v0.4 / ... 串迭代。

---

## 8. CLAUDE.md 协同

CLAUDE.md 第 11 行依赖黑名单**继续生效**:
```
No LangChain. No LangGraph. No AutoGen. No LiteLLM.
```

Strategic Direction(Phase 6 Conversation Agent OS)+ Rule 10(greenfield 模块节奏例外)适用于 `finrobot/conversation/` 开发。

---

## 9. 下一步

- 用户评审本 v0.7 串 → 若通过,**Week 0 启动**:
  1. `finrobot/engine/deps.py` 加 7 字段(默认 None,旧路径兼容)
  2. `finrobot/server.py` lifespan 构造 7 个 store / registry / adapter,填入 deps
  3. `finrobot/conversation/` 目录骨架
- 实施期持续:每完成一个 pillar,实际跑通 → 反向修订对应文档 → 不让代码与文档脱节

---

## 10. 联系点

- 实施期主参考:各 pillar `§4` 实现规格 + `§7` 测试要点
- 跨 pillar 决策追踪:本 README §4
- runtime context 字段所有权:mini-ADR-3
- 自审 / 评审追溯:各 pillar `§6` / `Changelog`

---

*本文档 + 8 个 pillar + 3 个 mini-ADR + 12 个 raw 共同构成 FinRobot Conversation Agent OS 阶段(Phase 6)v0.7 串后的完整设计 corpus。*
