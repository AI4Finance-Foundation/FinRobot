# mini-ADR-3: Runtime Context 边界统一

| | |
|---|---|
| **版本** | 1.0 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | 待评审 → 通过后阻塞 Pillar 1 v0.6 / Pillar 2 v0.3 / Pillar 5 v0.2 / Pillar 7 v0.2 / Pillar 8 v0.2 启动 |
| **触发** | v0.5 评审定位"4 个起点(mini-ADR-2 / Pillar 2 / Pillar 8 / 真实 pipeline contract)定下来后没回头同步,产生跨 pillar 接口断裂" |
| **依据** | 用户 review(blocking 4 / 5 / 6 + high risk F-P7-1 / F-P7-2)+ 真实代码核对 |

---

## 0. TL;DR

5 个 runtime 数据载体——**FinRobotDeps / QueryState / ToolUseContext / HookContext / engine.app_state**——之前**没有总账**,每个 pillar 各拍各的字段,导致:

- Pillar 1 主循环用 `hook_registry.run(timing, state, config)`,Pillar 8 实际签名是 `run(timing, context: HookContext)` —— hook 系统不可实现
- Pillar 2 ToolUseContext 缺 4 个谱系字段(mini-ADR-2 的 root_id / parent / depth + deps),sub-agent 工具落不下来
- Pillar 5 假设的 FinRobotDeps 字段(`user_id / fund_id / sub_agents / checkpoint_store / pipeline_factories`)**实际不存在** —— 现实 deps.py 只有 4 个字段
- Pillar 7 spawn_subagent 工具想从 `context.deps.parent_state` 取父状态 —— deps 字段表里根本没有这条

**本 ADR 决议**:**一张主表 + 一张派生表 + 一张 lifecycle 表** 把字段所有权钉死,任何 pillar 想加字段必须修本 ADR,不能就地塞。

**预期影响**:动 FinRobotDeps 真实 dataclass(+ 7 字段)、新建 ToolUseContext / HookContext 设计(纸面)、Pillar 1 主循环 hook 调用接口全部对齐 Pillar 8 实际签名。

---

## 1. 病灶根源

| 数据载体 | 当前位置 | 实际字段数 | spec 里被引用的字段数 | gap |
|---|---|---|---|---|
| **FinRobotDeps** | `finrobot/engine/deps.py:11`(真实存在)| **4** | **11+** | 缺 7 个新增字段 |
| **QueryState** | Pillar 1 §4.3(纸面)| 17 | 17 | 一致 ✓ |
| **ToolUseContext** | Pillar 2 §4.4(纸面)| 9 | **15+** | 缺 6 个 sub-agent 相关字段 |
| **HookContext** | Pillar 8 §3(纸面)| 7 | 8 | 缺 deps |
| **engine.app_state** | server lifespan(真实)| 视实现 | 未文档化 | 未覆盖 |

**为什么会发生**:Pillar 8 / Pillar 5 / Pillar 7 是**并行写的**(不是串行),都假设"我用的字段一定在 deps 里",没有人维护"deps 真实长什么样"的总账。Pillar 1 主循环是**最后**才动 hook 调用——但 hook 签名已经定型,主循环必须迁就,不能让 hook 迁就主循环。

---

## 2. 决议:四张字段所有权表

### 2.1 FinRobotDeps —— 顶层依赖容器

**生命周期**:server lifespan 启动时构造一次,所有 query_loop 调用 / 工具调用 / hook 共享同一实例。

**新版字段表**(`finrobot/engine/deps.py` 需扩展):

| 字段 | 类型 | 现状 | 来源 | 用途 |
|---|---|---|---|---|
| `data_layer` | `DataLayer` | ✅ 现有 | server lifespan | 所有 data tools / pipeline |
| `settings` | `FinRobotSettings` | ✅ 现有 | env vars | 全局配置 |
| `skill_runtime` | `SkillRegistry \| None` | ✅ 现有 | bootstrap | skill 检索 |
| `report_cache` | `dict[str, dict]` | ✅ 现有 | runtime | UI report 端点 |
| `memory_store` | `MemoryStore` | 🆕 **新增** | server lifespan(SQLiteMemoryStore) | Pillar 5 memory CRUD |
| `checkpoint_store` | `CheckpointStore` | 🆕 **新增** | server lifespan(SQLiteCheckpointStore) | Pillar 5 checkpoint 落盘 |
| `audit_store` | `AuditStore` | 🆕 **新增** | server lifespan | hook 写补充 audit / 查询 |
| `agent_registry` | `dict[str, AgentDefinition]` | 🆕 **新增** | bootstrap 加载 `finrobot/agents/*.md` | Pillar 7 spawn_subagent tool |
| `pipeline_factories` | `dict[str, Callable]` | 🆕 **新增** | `get_pipeline_factories()` 已有,移到 deps | Pillar 2 wrapper tool |
| `sub_agents` | `dict[str, Agent]` | 🆕 **新增** | bootstrap 构造 PydanticAI agents | factory(agents=...) 用 |
| `model_adapter` | `ModelAdapter` | 🆕 **新增** | server lifespan(PydanticAIAdapter) | spawn_subagent 用 |

**字段总数:4 现有 + 7 新增 = 11**

**不放进 FinRobotDeps**(刻意排除):
- `user_id / fund_id / session_id` —— 这些是**会话级**而非进程级,放 QueryState
- `parent_state / parent_config` —— 这些是**调用级**而非进程级,放 ToolUseContext
- `hook_registry` —— v1 全局唯一,但放 deps 会导致 sub-agent fork 时需要带它走,改放在**调用栈**(query_loop 的参数)

**FastAPI lifespan 构造样例**(给实施者参考,不是规格):

```python
async def lifespan(app):
    settings = FinRobotSettings.from_env()
    data_layer = DataLayer(...)
    memory_store = SQLiteMemoryStore(settings.memory_db_path)
    checkpoint_store = SQLiteCheckpointStore(settings.checkpoint_db_path)
    audit_store = SQLiteAuditStore(settings.audit_db_path)
    skill_runtime = SkillRegistry(...)
    agent_registry = load_agents_from_directory(Path("finrobot/agents/"))
    sub_agents = build_pydantic_agents(settings)
    pipeline_factories = get_pipeline_factories()
    model_adapter = PydanticAIAdapter(sub_agents=sub_agents)

    deps = FinRobotDeps(
        data_layer=data_layer, settings=settings,
        skill_runtime=skill_runtime, report_cache={},
        memory_store=memory_store, checkpoint_store=checkpoint_store,
        audit_store=audit_store, agent_registry=agent_registry,
        pipeline_factories=pipeline_factories, sub_agents=sub_agents,
        model_adapter=model_adapter,
    )
    app.state.deps = deps
    yield
```

**风险**:旧 SDK / CLI / 测试用 `FinRobotDeps(data_layer=..., settings=...)` 短构造的位置会全部因缺 mandatory 字段崩。**缓解**:7 个新字段在 dataclass 里全部给默认值(`memory_store: MemoryStore | None = None` 等),让旧路径仍能构造。Conversation loop 启动时 assert 不为 None(fail-fast),旧 pipeline 路径不用这些字段,None 也无影响。

### 2.2 QueryState —— 单次 query_loop 调用的运行时状态

**生命周期**:每次 user turn(主 agent)/ spawn(sub-agent)新构造一份。loop 结束销毁。可序列化用于 cancellation recovery(v2)。

**字段表**(Pillar 1 §4.3 现状,不改):

| 字段类别 | 字段 | 备注 |
|---|---|---|
| 会话身份 | `session_id / user_id / fund_id` | **从 server route 注入构造**(不是从 deps 抓)|
| Audit 谱系 | `audit_chain_id / audit_root_id / parent_chain_id / depth` | mini-ADR-2 |
| 消息历史 | `messages: list[Message]` | loop 内 mutate |
| 计数 | `turn_count / consecutive_failures / consecutive_tool_failures / cumulative_cost_usd` | |
| Recovery | `max_output_tokens_recovery_count / max_output_tokens_override / has_attempted_escalate` | |
| 其他 | `compact_tracking / transition / total_usage / started_at` | |

**不放进 QueryState**(刻意排除):
- `config` —— config 是构造时输入,不该和运行时状态混
- `tool_registry / orchestrator / adapter` —— 这些是注入到 loop 的依赖,不是状态
- `deps` —— deps 是进程级,不该绑到 turn 级 state 上

### 2.3 ToolUseContext —— 工具调用上下文

**生命周期**:`_handle_tool_use` 内,每个 batch 构造一份(或每个 tool call 用同一份);工具调用结束销毁。

**完整字段表**(把 Pillar 2 §4.4 9 字段 + 6 sub-agent 字段合并):

| 字段 | 类型 | 来源 | 用途 |
|---|---|---|---|
| `session_id` | `str` | from state | 多会话隔离 |
| `user_id` | `str` | from state | 工具按用户隔离 |
| `fund_id` | `str` | from state | 多租户隔离 + fund-id-guard hook |
| `audit_chain_id` | `str` | from state | 当前事件 ID |
| `audit_root_id` | `str` | from state | mini-ADR-2 谱系聚合 |
| `parent_chain_id` | `str \| None` | from state | mini-ADR-2 谱系树 |
| `depth` | `int` | from state | mini-ADR-2 谱系深度 |
| `role` | `Literal["user", "agent"]` | "user" 主对话 / "agent" sub-agent 内 | 工具内可识别调用方角色 |
| `messages` | `tuple[Message, ...]` | `tuple(state.messages)` | 不可变快照,工具无法 mutate |
| `model` | `str` | from config | 工具 introspect 当前模型 |
| `abort_requested` | `bool` | runtime | 工具检查取消信号 |
| `metadata` | `dict[str, Any]` | runtime | 自由扩展 |
| `deps` | `FinRobotDeps` | from caller | 显式字段(不再用 `payload["_deps"]` 走私)|
| **`parent_state`** | `QueryState` | from caller(spawn 时用) | 🆕 spawn_subagent tool 需要 |
| **`parent_config`** | `QueryConfig` | from caller | 🆕 spawn 继承配置 |
| **`parent_profile`** | `AgentProfile` | from caller | 🆕 spawn 继承 profile + 可被 agent_def 覆盖 |
| **`tool_registry`** | `ToolRegistry` | from caller | 🆕 spawn 派生子 registry(`resolve_agent_tools`)|
| **`tool_orchestrator`** | `ToolOrchestrator` | from caller | 🆕 spawn 借用父 Semaphore(F-P7-2)|
| **`hook_registry`** | `HookRegistry \| None` | from caller | 🆕 spawn 继承(除非 `disable_hooks`)|

**字段总数:13 现有 + 6 新增(均为 sub-agent 派生用)= 19**

**6 个新增字段全部 readonly**(`@dataclass(frozen=True)`),只在 spawn_subagent tool 内被读取,**普通工具不应碰**。普通工具如果 mutate 这些字段是 bug。

**构造源**(query_loop 内,Pillar 1 v0.6 §4.8 重写):

```python
tool_context = ToolUseContext(
    session_id=state.session_id, user_id=state.user_id, fund_id=state.fund_id,
    audit_chain_id=state.audit_chain_id,
    audit_root_id=state.audit_root_id,
    parent_chain_id=state.parent_chain_id,
    depth=state.depth,
    role="user" if state.depth == 0 else "agent",
    messages=tuple(state.messages),
    model=config.model,
    deps=deps,                          # 从 query_loop 参数注入
    parent_state=state,                 # 给 spawn_subagent tool 用
    parent_config=config,
    parent_profile=profile,
    tool_registry=tool_registry,
    tool_orchestrator=tool_orchestrator,
    hook_registry=hook_registry,
)
```

### 2.4 HookContext —— Hook 回调上下文

**生命周期**:`hook_registry.run(timing, context)` 调用前由 query_loop / `_handle_tool_use` 构造,hook 执行完销毁。

**完整字段表**:

| 字段 | 类型 | 来源 | 用途 |
|---|---|---|---|
| `chain_id` | `str` | `state.audit_chain_id` | hook 查 audit |
| `session_id` | `str` | `state.session_id` | |
| `fund_id` | `str` | `state.fund_id` | fund_id_guard 用 |
| `user_id` | `str` | `state.user_id` | memory_writer 用 |
| `turn` | `int` | `state.turn_count` | |
| `timing` | `HookTiming` | 调用方 | hook 区分时机 |
| `state_snapshot` | `QueryStateSnapshot` | `QueryStateSnapshot.from_state(state)` | **frozen 浅拷贝**,hook 只读 |
| `deps` | `FinRobotDeps` | from caller | 🆕 显式字段(取消 `payload["_deps"]`)|
| `payload` | `dict[str, Any]` | per-timing schema | mini-ADR-1 §2.6 各时机 payload |

**字段总数:8 现有 + 1 新增 = 9**

**QueryStateSnapshot** 是新的不可变类型(frozen dataclass),用于安全把 state 传给 hook。**hook 永远不能 mutate state** —— 这是 mini-ADR-1 §3.3 已定的规则。cost-tracker 等需要修改 cumulative_cost 的 hook 改为:

- Hook 返回 `HookResult(metadata={"cost_usd": 0.0042})`
- query_loop 收集所有 hook results 后,**自己** update `state.cumulative_cost_usd += sum(...)`

这要求 mini-ADR-1 §2.5 `HookResult` dataclass 加 `metadata: dict[str, Any] | None = None` 字段(在本 ADR 通过后,**先 patch mini-ADR-1**,再开 Pillar 8 v0.2)。

### 2.5 engine.app_state —— FastAPI 应用级状态

**生命周期**:server 启动时填充,关闭时清理。

**字段**:
- `app.state.deps: FinRobotDeps` —— 主依赖
- `app.state.hook_registry: HookRegistry` —— 全局唯一 hook 注册表(per-route 不重建)

**不放进 app_state**:任何 per-request / per-session 的状态。Server route 在每次 `/api/chat/sessions/{id}/messages` 请求时从 path/header 抽取 session_id / user_id / fund_id,构造 QueryState,**不**写回 app_state。

---

## 3. 派生规则(主 → sub-agent)

Sub-agent spawn 时,4 个 context 的派生方式:

| Context | 派生方式 |
|---|---|
| **FinRobotDeps** | **不变,直接复用父引用**(进程级单例,sub-agent 共享同一 deps) |
| **QueryState** | `fork_subagent_state(parent_state, initial_messages, max_depth)` —— mini-ADR-2 §2.3,新 chain / 继承 root / parent 指向父 / depth+1 / 全部计数器归零 |
| **ToolUseContext** | sub-agent 内构造新的 ToolUseContext,字段来源:`session/user/fund_id` 不变,谱系字段从 **child state** 取(role 必为 "agent"),其余从 child config / child profile / child registry / child orchestrator 取 |
| **HookContext** | 同理,child state 派生;**deps 不变**(继承父引用) |

**Sub-agent orchestrator 派生**(解 F-P7-2):

```python
# 不再新建 orchestrator,改为:
child_orchestrator = parent_orchestrator.fork_for_subagent(child_registry)
```

### 3.1 共享 Semaphore 决议(正式)

**同一 root user turn 下,主 agent 与所有 sub-agent 的 tool execution 共用同一个 `asyncio.Semaphore(max_concurrency=10)`**。深嵌套场景下慢一点可接受,失控并发不可接受。

理由:金融工具里 data/cache/provider 调用密集,确定性 > 吞吐。极端场景(主 LLM `spawn_parallel_subagents(5)` × 每个 sub 调 5 个 tool = 25 tool 抢 10 slot)会排队,这是设计上的可接受代价。

**跨 event loop 不支持**:`asyncio.Semaphore` 绑定到创建它的 event loop;sub-agent 必须运行在同一 loop 内。v1 单 event loop,实施期在 `fork_for_subagent` docstring 写明此限制。

**实施约定**(Pillar 2 v0.3 §4.6 `ToolOrchestrator` 必须支持):

```python
class ToolOrchestrator:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_concurrency: int = MAX_CONCURRENCY,
        shared_semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._registry = registry
        self._max_concurrency = max_concurrency
        # shared_semaphore 非 None 则直接借用,确保 sub-agent 与父共享池
        self._sem = shared_semaphore if shared_semaphore is not None \
                    else asyncio.Semaphore(max_concurrency)

    def fork_for_subagent(self, child_registry: ToolRegistry) -> "ToolOrchestrator":
        """派生 sub-agent 用的子 orchestrator,与父共享 Semaphore。

        WARNING: 子必须运行在与父同一 event loop 内,否则 Semaphore 行为未定义。

        Invariant: id(child._sem) == id(parent._sem) — Pillar 2 / 7 UT 必须断言。
        """
        return ToolOrchestrator(
            registry=child_registry,
            max_concurrency=self._max_concurrency,
            shared_semaphore=self._sem,
        )
```

**不使用 `__new__` 绕过 `__init__`**:未来 `ToolOrchestrator.__init__` 增字段时 `__new__` 路径必漏初始化;构造参数 `shared_semaphore` 是 long-term safe 写法。

---

## 4. 与现实代码的 gap(必须做的修改)

下面这张表是**实施期**(Week 1+)必须做的真实文件改动,**本 ADR 通过后立即可启动**:

| 文件 | 改动 | 估行数 | 触发原因 |
|---|---|---|---|
| `finrobot/engine/deps.py` | 加 7 个字段(均带默认值 None) | +15 | 2.1 表 |
| `finrobot/server.py` lifespan | 构造 7 个新 store / registry / adapter,填入 deps | +30 | 2.1 lifespan 示例 |
| `finrobot/sdk.py` 构造 | 短构造路径(只传 data_layer + settings)依旧可用 | 0(默认值兜底) | 兼容旧路径 |
| `finrobot/engine/pipelines/registry.py` | `get_pipeline_factories()` 已存在,无改动,只是被 deps.pipeline_factories 引用 | 0 | — |
| `finrobot/engine/models/financial.py:248` | `DCFResult.implied_price` 字段名**不动** | 0 | Pillar 2 wrapper 改去适配它 |
| `finrobot/conversation/tool/context.py` | 新建,按 2.3 字段表 | ~100 | 新模块 |
| `finrobot/conversation/hooks.py` | HookContext 加 deps 字段(原 spec 已写但用 payload 走私,改显式) | +5 | 2.4 表 |
| Pillar 1 主循环 hook 调用 | 全部改成 `run(timing, context: HookContext)` | ~30 | Blocking 1 |

---

## 5. 不变量(invariants,实施期必须 assert)

1. **deps 单例**:同一进程内 FinRobotDeps 只构造一次,所有 sub-agent 共享同一引用。`id(child_context.deps) == id(parent_context.deps)`
2. **谱系一致**:在任何 ToolUseContext / HookContext 中,`audit_chain_id / audit_root_id / parent_chain_id / depth` 必须与构造它的 QueryState 完全一致(不能"半派生")
3. **frozen 快照**:`HookContext.state_snapshot` 是 frozen dataclass,hook 内任何赋值操作必须 raise FrozenInstanceError
4. **messages tuple**:`ToolUseContext.messages` 必须是 `tuple` 不能是 `list`,工具内 `context.messages.append(...)` 必须报错(AttributeError 自然报)
5. **conversation 用字段 fail-fast**:query_loop 启动时 assert `deps.memory_store / checkpoint_store / audit_store / agent_registry / pipeline_factories / sub_agents / model_adapter` 全部非 None,缺失立即抛 `ConversationDepsIncomplete`,不允许进入主循环
6. **sub_agents 在 sub-agent fork 路径不重新构造**:借父 model_adapter 即可
7. **共享 Semaphore 身份**(§3.1 决议):`parent_orchestrator.fork_for_subagent(child_registry)` 返回的 child 必须满足 `id(child._sem) == id(parent._sem)`。这是 Pillar 2 v0.3 UT-P2-XX 和 Pillar 7 v0.2 UT-P7-XX 都必须断言的硬约束。任何深嵌套层级(主 → A → B → C)的 orchestrator 链上 `_sem` 引用必须全部指向同一 `asyncio.Semaphore` 对象
8. **ToolUseContext 6 个 sub-agent 派生字段对普通工具不可见**(v1.0 评审 I1 新增):
   - 字段:`parent_state` / `parent_config` / `parent_profile` / `tool_registry` / `tool_orchestrator` / `hook_registry`
   - 仅 `spawn_subagent` / `spawn_parallel_subagents` 两个工具允许访问;**普通工具**(`run_dcf` / `get_financials` / `compare_tickers` / `export_*` / ...)的 `call(args, context)` 实现内**不得访问**任何一个
   - 违规后果:绕过主循环 hook 链、绕过 LLM 触发额外 spawn、可能形成不可见的循环依赖
   - 执行约束(v1 实施期任选一种,工程上等价):
     - (a) **代码审查纪律**:PR 模板加 checklist"工具实现是否访问了 context.tool_registry/tool_orchestrator/hook_registry/parent_*",静态 grep 在 CI 上跑
     - (b) **运行时守卫**:`BaseTool.__init_subclass__` 注入 `context` proxy,proxy 对 6 字段返回 raise AttributeError,仅当 tool.name in {"spawn_subagent", "spawn_parallel_subagents"} 时透明放过
     - (c) **类型分层**(v2+):拆 `SubAgentToolContext(ToolUseContext)` 子类,只有 spawn 系工具的 input_model 标 `_requires_subagent_context = True`,framework 据此构造对应 context
   - v1 推荐 (a)+(b) 组合;v2 评估 (c)

---

## 6. 五版本串怎么用这个 ADR

ADR 通过后开五个版本串的**唯一引用源**:

| 版本 | 引用本 ADR 的位置 | 改动概要 |
|---|---|---|
| **Pillar 1 v0.6** | §2.2(QueryState 不变)、§2.3(ToolUseContext 19 字段构造)、§2.4(HookContext 9 字段构造)、§3(派生规则)| (a)hook 调用全改 `run(timing, ctx)` 签名;(b)加 post_model_call hook;(c)加 cost pre-loop guard;(d)`_run_model_call` 改 typed `ModelCallOutcome` 返回;(e)`_handle_tool_use` 构造 19 字段 ToolUseContext |
| **Pillar 2 v0.3** | §2.3(ToolUseContext 完整字段)、§3(orchestrator.fork_for_subagent)| (a)ToolUseContext §4.4 改 19 字段(其中 6 个 sub-agent 用);(b)ToolOrchestrator 加 `fork_for_subagent` 方法;(c)§4.8 RunDCFTool 改用 `DCFResult.implied_price`,`structured_data["dcf_calc"]` 按 Pydantic model 处理;(d)Pillar 3 AgentProfile.analyst_style 加 `ic_memo` literal |
| **Pillar 5 v0.2** | §2.1(deps.checkpoint_store / memory_store)、§3(deps 复用)| (a)refine_dcf 整段移到 v2 不实施;(b)checkpoint store 落盘 + 读取保留;(c)task_id 由 wrapper tool 在 audit_payload 内合成 `{chain_id}:{ticker}:{pipeline_name}`,不再要求 PipelineResult 加字段;(d)`apply_dcf_refinement` 删除 |
| **Pillar 7 v0.2** | §2.3(ToolUseContext 6 sub-agent 字段)、§3(派生规则)、§3.fork_for_subagent | (a)F-P7-1 通过 ToolUseContext 6 字段解;(b)F-P7-2 通过 orchestrator.fork_for_subagent 解;(c)`run_parallel_subagents` 实现 chunks-of-5 batch(不抛错);(d)F-P7-4 system prompt 装配走 Pillar 3 `extra_static_prefix` API |
| **Pillar 8 v0.2** | §2.4(HookContext.deps 字段)、§2.4 cost mutation 路径 | (a)HookContext 加显式 deps 字段,删 `payload["_deps"]`;(b)cost-tracker 改为返回 `HookResult(metadata={"cost_usd": ...})`,不再 mutate state;(c)F-P8-1 / F-P8-5 同时解;(d)`build_default_registry` 接收 deps 参数,4 个 hook 通过闭包绑定 |
| **mini-ADR-1 patch** | §2.4 cost mutation 触发 | HookResult dataclass 加 `metadata: dict[str, Any] \| None = None` 字段 |

---

## 7. 未决问题(本 ADR 不解,留 v0.6 实施时再判)

1. **deps.audit_store 接口**:`write_supplementary()` / `query_by_root_id()` / `query_by_chain_id()` 三个方法是 v1 必需;具体 schema 在 Pillar 8 v0.2 写 audit_trail_writer 时定
2. ~~ToolOrchestrator.fork_for_subagent 是否真共享 Semaphore~~ ✅ **已决议见 §3.1**:共享同一 Semaphore;跨 event loop 不支持(v1 单 event loop);`fork_for_subagent` docstring 写警告;不变量 §5.7 强制 `id(child._sem) == id(parent._sem)`
3. **sub_agents dict 的 key 命名**:`equity_research_lead / equity_research_analysis / dcf_param / dcf_validator / ...` 现有命名已有,不在本 ADR 改;但 conversation 层引用时需要保证 key 稳定
4. **PydanticAIAdapter 内部怎么从 sub_agents 选 agent**:v0.6 实施时定,本 ADR 不限定

---

## 8. 决议确认

通过条件:
- [ ] FinRobotDeps 新增 7 字段表(2.1)无遗漏
- [ ] ToolUseContext 19 字段(2.3)能同时满足:普通工具 / wrapper tool / spawn_subagent tool 三种调用场景
- [ ] HookContext 9 字段(2.4)能让 4 个内置 hook 全部用显式字段(无 payload 走私)
- [ ] 不变量 6 条(§5)实施期可机器验证(assert / dataclass frozen / type check)
- [ ] 5 版本串改动表(§6)逐条对得上现状

通过后立即并行启动:
1. Pillar 1 v0.6(优先,主循环是其他 pillar 的承载)
2. Pillar 8 v0.2(同时,因 1 依赖其 HookContext + HookResult.metadata)
3. mini-ADR-1 patch(同时,1 行 + Pillar 8 v0.2 用得到)
4. Pillar 2 v0.3 / Pillar 7 v0.2 / Pillar 5 v0.2 在 1+2 出 v0.6/v0.2 草稿后启动

---

## 9. 参考

- mini-ADR-1(Hook 时机)—— 本 ADR 触发其 HookResult.metadata 字段 patch
- mini-ADR-2(Sub-agent chain)—— 本 ADR §2.2 / §2.3 谱系字段全部来自此 ADR
- Pillar 1 v0.5 §4.4 / §4.6 / §4.8 —— 本 ADR §2.2 / §2.3 / §6 引用
- Pillar 2 v0.2 §4.4 / §4.8 —— 本 ADR §2.3 / §6 引用
- Pillar 5 v0.1 §4.5 —— 本 ADR §6 决议 refine 降 v2
- Pillar 7 v0.1 §4.4 / §4.5 / §6 —— 本 ADR §3 / §6 引用
- Pillar 8 v0.1 §3 / §4.3 —— 本 ADR §2.4 / §6 引用
- 真实代码核对:
  - `finrobot/engine/deps.py:11-18`(4 字段现状)
  - `finrobot/engine/pipelines/base.py:121-181`(Pipeline.execute 真签名)
  - `finrobot/engine/pipelines/base.py:375-379`(PipelineResult 真字段)
  - `finrobot/engine/models/financial.py:248`(`DCFResult.implied_price`)
  - `finrobot/engine/pipelines/dcf.py:101`(`create_dcf_pipeline(agents)` factory)
