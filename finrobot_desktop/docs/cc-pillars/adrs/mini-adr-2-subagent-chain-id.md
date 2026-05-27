# Mini-ADR-2: Sub-agent Chain ID 父子关系

| | |
|---|---|
| **状态** | Proposed（待评审） |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **阻塞项** | Pillar 1 QueryState 字段、Pillar 7 sub-agent 实现、audit 聚合查询模型 |
| **依据** | 子 agent 对 CC `src/Tool.ts`、`src/query.ts:346-363`、`src/utils/forkedAgent.ts:452-455`、`src/tools/AgentTool/runAgent.ts` 的通读 |

---

## 0. TL;DR

**采用 4 字段方案**：`audit_chain_id` + `audit_root_id` + `parent_chain_id` + `depth`。

- 每个 query_loop（主或子）持有自己的 `audit_chain_id`
- 整个 user turn 树共享一个 `audit_root_id`（等于最顶层主 agent 的 chain_id）
- Sub-agent 用 `parent_chain_id` 反向指向父
- `depth` 提供深度限制 + 谱系层级

**不复刻 CC 的内部矛盾**（主路径继承 chainId、forked agent 新建 chainId 这种 CC 自己都没说清的混乱）。

---

## 1. Context

### 1.1 问题

主 agent 通过工具 spawn sub-agent 时，audit 链怎么标识：
- 选项 A：sub-agent 继承父 `chain_id`，加 `depth` 区分层级
- 选项 B：sub-agent 独立 `chain_id`，记录 `parent_chain_id`
- 选项 C：混合方案

### 1.2 CC 实际行为（调研结论）

CC 自己**不一致**：

```typescript
// src/query.ts:346-363 — 主路径
const queryTracking = toolUseContext.queryTracking
  ? {
      chainId: toolUseContext.queryTracking.chainId,   // ← 继承父
      depth: toolUseContext.queryTracking.depth + 1,
    }
  : {
      chainId: deps.uuid(),
      depth: 0,
    }


// src/utils/forkedAgent.ts:452-455 — fork 路径
queryTracking: {
  chainId: randomUUID(),                                // ← 新建！与上面冲突
  depth: (parentContext.queryTracking?.depth ?? -1) + 1,
}
```

调研子 agent 报告："是设计缺陷还是有意为之，需确认设计文档"——也就是说连 CC 自己都没说清楚。

**我们不复刻这个矛盾**，做我们自己更清楚的设计。

### 1.3 FinRobot 的需求

- **audit aggregation**："这次 user turn 系统总共做了什么"——一个查询拿到主 agent + 所有 sub-agent 的事件
- **lineage walk**：从任意事件能向上追溯到根
- **depth limit**：防止 sub-agent 无限递归（金融分析理论上不需要超过 2-3 层嵌套）
- **隔离 vs 关联**：sub-agent 的 audit 事件既要能独立分析（"这个 peer comparison agent 干了什么"），也要能在父子语境聚合

---

## 2. Decision

### 2.1 四字段 schema

```python
# finrobot/conversation/state.py

MAX_DEPTH_HARD_CAP = 10
"""硬上限：QueryState 任何路径构造（包括直接 QueryState(depth=...)）
   都不允许超过此值。Fork helper 的软上限通常更严（默认 3）。F2.2 修复。"""


@dataclass
class QueryState:
    # ... (其他字段见 Pillar 1 文档) ...

    # ─── Audit 谱系 ───
    audit_chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """本次 query_loop 调用的事件 ID。

    - 主 agent: 新生成的 UUID
    - Sub-agent: 新生成的 UUID（不继承父的，与父隔离）

    所有从本次 query_loop yield 的 AuditEvent 共享此 ID。
    "这个 sub-agent 干了什么"用这个 ID 查询。
    """

    audit_root_id: str | None = None
    """整棵 agent 树的根 ID。

    - 主 agent: __post_init__ 自动设置 == audit_chain_id（根 = 自己）
    - Sub-agent: 由 fork_subagent_state 显式传入父的 audit_root_id

    F2.1 修复：默认 None 让 __post_init__ 自动对齐，避免"两个不同 factory
    产生不同 UUID"的隐蔽 bug。直接 QueryState(...) 不传 root_id 也能得到
    正确的 root == chain。
    """

    parent_chain_id: str | None = None
    """直接父 query_loop 的 audit_chain_id。

    - 主 agent: None
    - Sub-agent: 父 query_loop 的 audit_chain_id
    """

    depth: int = 0
    """谱系深度。

    - 主 agent: 0
    - Sub-agent: parent.depth + 1
    """

    def __post_init__(self) -> None:
        # F2.1: audit_root_id 自动对齐为 chain_id（仅当未显式传入）
        if self.audit_root_id is None:
            self.audit_root_id = self.audit_chain_id

        # F2.2: depth 硬上限（防御性 invariant，绕过 fork helper 也拦得住）
        if self.depth > MAX_DEPTH_HARD_CAP:
            raise ValueError(
                f"QueryState.depth = {self.depth} exceeds hard cap "
                f"{MAX_DEPTH_HARD_CAP}. Use fork_subagent_state() helper "
                f"to control depth growth."
            )

        # 一致性约束（绕过 fork helper 直接构造时也得遵守）
        if self.depth == 0:
            if self.parent_chain_id is not None:
                raise ValueError("Top-level state (depth=0) must have parent_chain_id=None.")
            if self.audit_root_id != self.audit_chain_id:
                raise ValueError("Top-level state must have audit_root_id == audit_chain_id.")
        else:
            if self.parent_chain_id is None:
                raise ValueError(f"Sub-agent state (depth={self.depth}) must have parent_chain_id.")
```

### 2.2 主 agent 启动

```python
def create_top_level_state(
    session_id: str, user_id: str, fund_id: str
) -> QueryState:
    chain_id = str(uuid.uuid4())
    return QueryState(
        session_id=session_id,
        user_id=user_id,
        fund_id=fund_id,
        audit_chain_id=chain_id,
        audit_root_id=chain_id,   # ← 主 agent: root == 自己
        parent_chain_id=None,
        depth=0,
    )
```

### 2.3 Sub-agent fork（Pillar 7 实现位置，本 ADR 仅锁接口）

```python
def fork_subagent_state(
    parent_state: QueryState,
    *,
    initial_messages: list[Message],
    max_depth: int = 3,
) -> QueryState:
    if parent_state.depth >= max_depth:
        raise SubAgentDepthExceeded(
            f"Cannot spawn sub-agent at depth {parent_state.depth + 1}, "
            f"max_depth = {max_depth}."
        )

    return QueryState(
        # ─── 从父继承（身份 + 谱系根） ───
        session_id=parent_state.session_id,
        user_id=parent_state.user_id,
        fund_id=parent_state.fund_id,
        audit_root_id=parent_state.audit_root_id,
        parent_chain_id=parent_state.audit_chain_id,

        # ─── 不继承（重置） ───
        audit_chain_id=str(uuid.uuid4()),  # 新 chain（与父隔离）
        depth=parent_state.depth + 1,
        messages=initial_messages,
        # turn_count, consecutive_failures, consecutive_tool_failures,
        # max_output_tokens_recovery_count, has_attempted_escalate,
        # max_output_tokens_override, compact_tracking, transition, total_usage
        # 全部走 QueryState dataclass 默认值（即 0 / None / 空）
    )
```

**F2.3 修复**：明确"Fork 不继承"清单：

| 字段 | 父行为 | 子初值 | 理由 |
|---|---|---|---|
| `turn_count` | 累计中 | 0 | sub-agent 是新 loop，turn 重新计数 |
| `consecutive_failures` | 任意 | 0 | sub-agent 内失败不该熔断父 |
| `consecutive_tool_failures` | 任意 | 0 | 同上 |
| `max_output_tokens_recovery_count` | 任意 | 0 | recovery quota 独立 |
| `has_attempted_escalate` | 任意 | False | escalate 状态独立 |
| `max_output_tokens_override` | 任意 | None | 子可独立 escalate |
| `compact_tracking` | 任意 | None | compact 历史不传递 |
| `transition` | 任意 | None | 转移状态不传递 |
| `total_usage` | 累计中 | TokenUsage() | usage 独立累计；查询合计用 root_id 聚合 |
| `messages` | 父对话 | 调用方传入 | 显式控制 sub-agent 看到的初始 context |

### 2.4 AuditEvent 携带的字段

每个 AuditEvent 写入 audit store 时包含：

```python
@dataclass
class AuditEvent:
    type: AuditEventType
    chain_id: str          # 来自 state.audit_chain_id
    root_id: str           # 来自 state.audit_root_id（用于聚合查询）
    parent_chain_id: str | None  # 来自 state.parent_chain_id（用于 lineage walk）
    depth: int             # 来自 state.depth
    session_id: str
    fund_id: str
    turn: int
    timestamp: datetime
    duration_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
```

### 2.5 查询模型

**"这个 sub-agent 干了什么"**：
```sql
SELECT * FROM audit_events
WHERE chain_id = :chain_id
ORDER BY timestamp ASC;
```

**"这次 user turn 系统总共做了什么"**：
```sql
SELECT * FROM audit_events
WHERE root_id = :root_id
ORDER BY timestamp ASC;
-- 主 agent 事件 + 所有层级的 sub-agent 事件全部命中
```

**"重建 lineage 树"**：
```sql
-- 从某个 chain_id 向上追溯
WITH RECURSIVE lineage AS (
  SELECT chain_id, parent_chain_id, depth
  FROM agent_chains WHERE chain_id = :leaf_chain_id
  UNION ALL
  SELECT c.chain_id, c.parent_chain_id, c.depth
  FROM agent_chains c
  JOIN lineage l ON c.chain_id = l.parent_chain_id
)
SELECT * FROM lineage ORDER BY depth ASC;
```

需要在 audit store 维护一个轻量的 `agent_chains` 视图（chain_id → parent_chain_id 映射），可以从 AuditEvent 实时聚合得到。

---

## 3. Consequences

### 3.1 正向

- **聚合查询简单**：单字段 `root_id` 就能拉所有相关事件
- **隔离分析也简单**：单字段 `chain_id` 就能看单个 agent 的事件
- **谱系可重建**：parent_chain_id 链表完整
- **避免 CC 的内部矛盾**：fork 一致、主一致，规则简单清晰
- **depth 字段独立**：不和聚合 ID 耦合，可以独立做深度限制

### 3.2 负向

- 比单字段（只有 chain_id）多 3 个字段——但 audit log 已经按 timestamp 索引，多 3 个 indexed 列开销可控
- Sub-agent 内的 audit 事件需要带 4 个谱系字段，单条事件序列化体积略增（~80 字节）

### 3.3 中性

- 并发 spawn 多个 sub-agent 时，它们之间是兄弟关系（同 parent_chain_id），audit 中可以区分
- Sub-agent 不继承 parent 的失败计数器——这是有意设计，避免传染熔断

### 3.4 并发 sub-agent 的 audit 时序（F2.4 修复）

并发 spawn 多个 sub-agent 时（如 5 个 peer 并行分析），它们的事件几乎同时写入 audit store。仅靠 timestamp（毫秒精度）可能出现：

- 同毫秒内的事件相对顺序不确定
- 同一 sub-agent 内连续两个事件 timestamp 完全相同

**v1 接受这个不精确**：
- 单个 sub-agent 内的顺序通过 turn_count 字段已经精确
- 跨 sub-agent 顺序在金融分析场景不重要（peer 分析顺序无业务含义）
- 聚合查询 `WHERE root_id = ?` 仍然正确

**v2 evaluate**：在 AuditEvent 加 `sequence_id: int`（递增整数，按 root_id 内单调），需要 audit store 维护原子计数器。届时按真实需求决定。

---

## 4. Alternatives Considered

### 4.1 选项 A：sub-agent 继承父 chain_id + depth

**拒绝原因**：
- 单个 chain_id 混杂主 + 子事件，"看 sub-agent 自己干了什么"必须靠 depth 过滤——查询复杂
- 多个并发 sub-agent 共享 chain_id 时无法区分谁是谁
- CC 的主路径就是这个方案，但 fork 路径自己又否决了——CC 内部都觉得不对

### 4.2 选项 B：sub-agent 独立 chain_id + 只有 parent_chain_id

**拒绝原因**：
- "看整棵树"必须递归 walk parent_chain_id，audit store 必须支持 recursive CTE 或多次查询
- 对 100+ 行/秒的实时 telemetry 是不可接受的查询模式

### 4.3 选项 C（本 ADR 决定）：root_id + chain_id + parent_chain_id + depth

**采用**：兼具 A 和 B 的优势，唯一代价是多 1 个字段（root_id），但这个字段是高频聚合查询的关键，值得。

### 4.4 仅用 trace_id + span_id（OpenTelemetry 兼容）

**部分采纳但不完全替代**：
- 我们可以在 audit log 中**额外**写入 OTel-compatible trace_id / span_id（用 root_id 当 trace_id，chain_id 当 span_id，parent_chain_id 当 parent_span_id）——免费送一个 OTel 兼容路径
- 但 audit_root_id 等业务字段保留显式存在，方便业务侧理解和查询
- 实施细节留给 Pillar 8

---

## 5. Implementation Notes

### 5.1 测试要点

- **UT-27**: `create_top_level_state` 生成 root_id == chain_id、parent_chain_id == None、depth == 0
- **UT-28**: `fork_subagent_state` 生成新 chain_id、root_id 继承、parent_chain_id == 父 chain_id、depth + 1
- **UT-29**: `fork_subagent_state` 在 depth >= max_depth 时抛 `SubAgentDepthExceeded`
- **UT-30**: 二层嵌套（A → B → C）后，C 的 root_id == A.chain_id，C.parent_chain_id == B.chain_id，depth == 2
- **UT-30b** (F2.3): `fork_subagent_state` 不继承父的失败计数器、recovery_count、has_attempted_escalate 等运行时状态字段（全部为 0/None/默认）
- **UT-30c** (F2.1): `QueryState(audit_chain_id="X")` 不传 audit_root_id 时，__post_init__ 自动设置 audit_root_id == "X"
- **UT-30d** (F2.2): `QueryState(depth=11, ...)` 直接构造时 __post_init__ 抛 ValueError（hard cap 10）
- **UT-30e** (F2.2): `QueryState(depth=0, parent_chain_id="X")` 直接构造时 __post_init__ 抛 ValueError（顶层不能有 parent）
- **IT-06**: spawn 2 个并发 sub-agent，audit log 能查到 root_id 相同、chain_id 不同的两组事件

### 5.2 Max depth 默认值

V1: `max_depth = 3`

理由：
- 金融分析典型嵌套 ≤ 2 层（主 agent → peer 分析 → 单 peer 深入）
- 3 层留给未来"meta-orchestration"场景（如 IC memo 多视角辩论）
- 超过 3 层几乎肯定是 prompt 设计有问题，应该被 fail-fast 暴露而不是悄悄烧 token

### 5.3 Audit Store schema 建议（实施期再细化）

```sql
CREATE TABLE audit_events (
    id BIGSERIAL PRIMARY KEY,
    chain_id UUID NOT NULL,
    root_id UUID NOT NULL,
    parent_chain_id UUID NULL,
    depth INT NOT NULL,
    session_id TEXT NOT NULL,
    fund_id TEXT NOT NULL,
    turn INT NOT NULL,
    type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    duration_ms INT NULL,
    payload JSONB NOT NULL,

    INDEX idx_chain_time (chain_id, timestamp),
    INDEX idx_root_time (root_id, timestamp),
    INDEX idx_session_time (session_id, timestamp),
    INDEX idx_fund_time (fund_id, timestamp)
);
```

`idx_root_time` 是核心查询路径（取整次 user turn 全部事件）。

### 5.4 与 Pillar 8 hooks 的协同

`HookContext.chain_id` 来自当前 state.audit_chain_id（即当前 query_loop 的，不是 root 也不是 parent）。

如果某个 hook 想做 "跨 sub-agent 聚合"（如"统计本次 user turn 总 LLM cost"），它能拿到 `state.audit_root_id`，自行查询 audit store。Loop 不直接提供"汇总"——这是观测系统的职责。

---

## 6. 状态字段更新摘要（影响 Pillar 1 文档第 4.3 节）

Pillar 1 v0.2 的 `QueryState` 当前只有 `audit_chain_id` 一个谱系字段。本 ADR 决议后，需要增加 3 个字段：

```diff
 @dataclass
 class QueryState:
     # ... existing fields ...

     audit_chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
+    audit_root_id: str = field(default_factory=lambda: str(uuid.uuid4()))
+    parent_chain_id: str | None = None
+    depth: int = 0
```

并新增工厂函数 `create_top_level_state()` 和 `fork_subagent_state()`（位置：`state.py`）。

Pillar 1 文档下次修订（v0.3）时同步该 diff。

---

## 7. 评审 Checklist

- [ ] 主 agent 启动时 root_id == chain_id 这个等式被理解
- [ ] Sub-agent 不继承父 chain_id（与 CC fork 路径一致，但有意为之而非偶然）
- [ ] 并发 sub-agent 之间 chain_id 互相独立，audit 可区分
- [ ] depth 字段独立于聚合 ID，仅用于深度限制
- [ ] max_depth = 3 在 v1 写死、v2 可配
- [ ] AuditEvent 携带 4 字段（chain + root + parent + depth）
- [ ] 查询路径 idx_root_time 覆盖最高频访问
- [ ] Pillar 1 v0.3 同步 QueryState 字段更新
