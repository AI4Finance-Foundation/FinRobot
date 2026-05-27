# Pillar 5: Auto-compact + Memory + Task Checkpoint — 研究与 FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.3 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | v0.3 清 v0.2 评审 I2 / I3 refine 残留 |
| **前置** | mini-ADR-1 v1.2、mini-ADR-3 v1.0、Pillar 1 v0.7、Pillar 2 v0.3、Pillar 3 v0.2 |
| **原始报告** | `raw/cc-pillar-5-raw.md`、`raw/homepilot-pillar-5-raw.md` |

---

## Changelog

### v0.3(2026-05-12)

清 v0.2 评审 Inconsistency I2 / I3 残留:
- **I2**:§4.6 对接表删 `Pillar 2 refine_dcf tool | 由本 pillar apply_dcf_refinement 支撑` 一行(与 §4.5.4 refine 降 v2 决议矛盾)
- **I3**:§9 Week 5 实施计划删 `Pillar 2 RefineDCFTool 实现 + UT-P5-23..25`、改 IT 范围为 IT-P5-01..02 + IT-P5-04(对齐 §7 测试要点已删除项)
- 顺手:§4.1 模块结构删 `refine.py`、§3 决策对照表"解锁 refine_dcf"措辞改"checkpoint 落盘+读取"

### v0.2(2026-05-12)

应用 mini-ADR-3 + 修评审 Blocking 5(用户决议):

**重大降级**:
- **refine_dcf / apply_dcf_refinement / Pipeline.set_prefilled_outputs / set_assumptions_override → 全部移到 v2**(用户决议 2026-05-12)
  - 理由:局部重算需要 pipeline step dependency graph + assumption impact matrix + prefill/replay 协议三者一起落地,**不是 checkpoint store 单方面能解决**
  - 当前 `Pipeline.execute(deps, ticker, progress, lang, **kwargs)` 真签名(`base.py:121`)没有 self.name / set_prefilled_outputs;`PipelineResult` 没有 task_id / ticker(`base.py:375`)
  - **v1 保留**:checkpoint store **落盘 + 读取**(用于 audit / UI 历史复用 / 跨 session 查询);refine 不做

**保留**:
- Auto-compact 全量(§4.2)
- MemoryStore + 5 类 memory + ANALYSIS_RESULT 自动写入(§4.3 / §4.4)
- TaskCheckpoint 数据结构 + SQLiteCheckpointStore CRUD(§4.5)

**修改**:
- task_id 由 **wrapper tool 在 conversation/tool 层合成** `{chain_id}:{ticker}:{pipeline_name}`(mini-ADR-3 §6 决议),不再要求 PipelineResult / Pipeline 新增字段
- `TaskCheckpoint.step_outputs` 字段保留(用于历史展示),但 `assumptions` / `is_complete` 字段意义降级为"记录"而非"refine input"
- 删除 `apply_dcf_refinement` 函数 + `RefineDCFTool` 工具
- `CheckpointStore` 接口新增 `save_pipeline_result(task_id, ..., result: PipelineResult)` 高层方法(Pillar 2 v0.3 §4.8 wrapper 调用),内部解构 `result.structured_data` 落盘
- 4 个内置 hook 通过 `context.deps.*` 访问 store(Pillar 8 v0.2 配合)

---

## 0. TL;DR

- **CC**：5 种压缩策略（snip / microcompact / autocompact / context collapse / reactive compact）+ memdir 文件系统 + KAIROS / Team 模式
- **homepilot**：单 LLM 摘要策略 + MemoryStore Protocol（InMemoryStore）+ 无 task checkpoint
- **FinRobot v1**：
  - **2 种压缩策略**：阈值触发 LLM 摘要（autocompact）+ Pillar 1 已有的 max_tokens recovery（共同覆盖 80% 场景）
  - **MemoryStore Protocol**（沿用 homepilot 接口）+ SQLite 后端（多租户友好）
  - **Task Checkpoint 系统**——解锁 Pillar 2 v0.2 D6（refine_dcf）
- **明确推迟**：Reactive compact、Context collapse、Cached microcompact、KAIROS、Team mode、auto memory 写入

---

## 1. Pillar 5 的位置

Pillar 5 是 **3 个独立子系统**的承载，它们的共同特征是"跨 turn 的状态管理"：

1. **Auto-compact**：长会话 token 上限管理
2. **Memory**：跨 user-turn 的用户记忆
3. **Task Checkpoint**：单个 pipeline 的可恢复中间状态

为什么放在一起：
- Compact 决定 messages 什么时候被压缩
- Memory 决定哪些跨 turn 信息要保留到 system prompt
- Task 决定 pipeline 中间产物怎么存

3 者都涉及"持久化设计"，且互相影响（compact 不能丢掉 task checkpoint，memory 不应该被 compact 摘要进 messages）。

---

## 2. 调研结论摘要

### 2.1 CC（详见 `raw/cc-pillar-5-raw.md`）

- 5 种压缩策略各司其职：snip 删消息、microcompact 清工具结果、autocompact LLM 摘要、context collapse 中段折叠、reactive compact 413 错误救援
- memdir 文件系统：`~/.claude/projects/{git-root}/memory/`，3 种模式（auto / KAIROS / team）
- MemoryType: user / feedback / project / reference
- 写入靠用户 `/remember` 或 `saveMemory()` 主动调用
- 无自动过期机制
- Task 概念：用于后台 agent 追踪（LocalAgentTask 等），不是单 turn checkpoint

### 2.2 homepilot（详见 `raw/homepilot-pillar-5-raw.md`）

- 单一 full-summarization 策略：阈值 `context_window - 20K - 13K`，LLM 整段摘要为 1 条 UserMessage
- MemoryStore Protocol + InMemoryStore（dict 后端）
- MemoryEntry 字段：user_id / memory_type / name / content / description / created_at / updated_at
- 无 task checkpoint
- 无 reactive、无 LLM relevance、无 PostgreSQL 后端

---

## 3. 决策对照表

| 维度 | CC | homepilot | **FinRobot 决策** | 理由 |
|---|---|---|---|---|
| 压缩策略数 | 5 | 1 | **2** | 1 (autocompact) + Pillar 1 已有 max_tokens recovery |
| 触发方式 | proactive + reactive | proactive only | **proactive only（v1）** | reactive 复杂，v1 阈值预防足够 |
| 阈值公式 | `window - 13K - 20K` | `window - 13K - 20K` | **`window - 13K - 20K`** | 沿用 |
| 摘要算法 | LLM streaming | LLM complete | **LLM complete**（非流式） | 简化 |
| 失败熔断 | 3 次 | 3 次 | **3 次** | 一致 |
| 摘要 prompt 语言 | EN | EN | **按 config.language 双语** | FinRobot 多语言一致性 |
| Memory 后端 | 文件系统 | dict | **SQLite（v1）+ PostgreSQL v2** | 多租户隔离 + 持久 |
| Memory 类型 | user/feedback/project/reference | 同 | **同 + 新增 `analysis_result`** | 金融特有：保留 user turn 的 valuation 摘要 |
| Memory 写入 | 手动 + /remember | 外部 API 显式 | **3 路径**：（1）显式 tool `save_memory`（2）`post_tool_use` hook 自动写 analysis_result（3）/remember 命令 | 自动化金融场景 |
| Memory 相关性筛选 | LLM-based | 最近 N 条 | **最近 N 条 + relevance scoring v2** | v1 简单 |
| Memory 注入位置 | system prompt + user_context | system prompt | **Pillar 3 §4.4 build_memory 层** | 已在 Pillar 3 预留 |
| **Task Checkpoint** | 后台 agent task（不是单 turn）| 无 | **新增：TaskCheckpoint 系统** | **解锁 Pillar 2 D6（refine_dcf）** |

---

## 4. FinRobot 实现规格

### 4.1 模块结构

```
finrobot/conversation/compact/        # 新增
├─ __init__.py
├─ threshold.py                       # calculate_compact_threshold
├─ compactor.py                       # compact_messages 主体
├─ prompts.py                         # 双语摘要 prompt
└─ tracking.py                        # CompactTracking dataclass

finrobot/conversation/memory/         # 新增
├─ __init__.py
├─ types.py                           # MemoryEntry + MemoryType
├─ store.py                           # MemoryStore Protocol + SQLiteStore
├─ writer.py                          # 自动写入逻辑（hook 接入）
└─ prompt_layer.py                    # 为 Pillar 3 提供 build_memory()

finrobot/conversation/checkpoint/     # 新增（核心创新）
├─ __init__.py
├─ types.py                           # TaskCheckpoint + CheckpointStore Protocol
├─ store.py                           # SQLiteCheckpointStore
└─ refine.py                          # apply_refinement (Pillar 2 refine_dcf 用)
```

### 4.2 Auto-compact

```python
# finrobot/conversation/compact/threshold.py

OUTPUT_BUFFER_TOKENS = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 13_000

def calculate_compact_threshold(
    context_window: int,
    output_buffer: int = OUTPUT_BUFFER_TOKENS,
    autocompact_buffer: int = AUTOCOMPACT_BUFFER_TOKENS,
) -> int:
    effective = max(0, context_window - output_buffer)
    return max(0, effective - autocompact_buffer)


def should_auto_compact(
    current_tokens: int,
    threshold: int,
    tracking: CompactTracking,
    max_consecutive_failures: int = 3,
) -> bool:
    if tracking.consecutive_failures >= max_consecutive_failures:
        return False
    return current_tokens >= threshold


# finrobot/conversation/compact/compactor.py

async def do_compact(
    state: QueryState,
    model_adapter: ModelAdapter,
    config: QueryConfig,
) -> None:
    """In-place 修改 state.messages，把历史压成单条 summary UserMessage。"""

    try:
        if len(state.messages) <= 2:
            return  # 太少，跳过

        summary_text = await _generate_summary(
            state.messages, model_adapter, config.model, config.language
        )
        if not summary_text.strip():
            state.compact_tracking.consecutive_failures += 1
            logger.warning("Compact produced empty summary")
            return

        # 保留最近 1 条用户消息（如果有）以维持对话连续
        last_user_msg = next(
            (m for m in reversed(state.messages) if isinstance(m, UserMessage)),
            None,
        )
        summary_msg = UserMessage(
            content=f"{_compact_prefix(config.language)}\n{summary_text}\n{_compact_suffix(config.language)}"
        )

        new_messages = [summary_msg]
        if last_user_msg and last_user_msg is not state.messages[-1]:
            new_messages.append(last_user_msg)

        state.messages = new_messages
        state.compact_tracking.compacted = True
        state.compact_tracking.consecutive_failures = 0

    except (ProviderError, APIError) as exc:
        state.compact_tracking.consecutive_failures += 1
        logger.warning("Compact failed: %s", exc)


async def _generate_summary(messages, model_adapter, model, language):
    sys_prompt = _compact_system_prompt(language)
    content_blocks, _, _ = await model_adapter.complete(
        messages=messages,
        model=model,
        system_prompt=sys_prompt,
        max_tokens=OUTPUT_BUFFER_TOKENS,
    )
    return "".join(b.text for b in content_blocks if isinstance(b, TextBlock))
```

**双语 prompt**：

```python
# finrobot/conversation/compact/prompts.py

_PROMPTS = {
    "zh": {
        "system": """你是对话压缩助手。把当前对话历史压缩成一份结构化摘要。

必须保留：
- 用户提出的所有问题和具体需求
- 工具调用的关键结果（数字、ticker、计算结论）
- 模型给出的关键判断和推理过程
- 待办事项和未完成的工作

可以省略：
- 详细的中间推理
- 重复的解释和上下文
- 已经被新结论覆盖的早期分析

格式：分主题列出"用户意图"、"已完成分析"、"关键数据"、"待办事项"四节。
保持事实精确，不要编造细节。""",
        "prefix": "[本次会话历史摘要]",
        "suffix": "[请继续之前的对话，注意所有上述摘要内容]",
    },
    "en": {
        "system": """You are a conversation summarization assistant. Compact the conversation history into a structured summary.

Must preserve:
- All user questions and specific requirements
- Key tool call results (numbers, tickers, computational conclusions)
- Model's key judgments and reasoning
- Pending todos and unfinished work

May omit:
- Detailed intermediate reasoning
- Repeated explanations and context
- Early analysis already superseded by new conclusions

Format: List four sections: 'User Intent', 'Completed Analysis', 'Key Data', 'Pending Items'.
Stay factually precise. Do not fabricate details.""",
        "prefix": "[Conversation history summary]",
        "suffix": "[Please continue the conversation above with full awareness of this summary.]",
    },
}


def _compact_system_prompt(language: str) -> str:
    return _PROMPTS[language]["system"]


def _compact_prefix(language: str) -> str:
    return _PROMPTS[language]["prefix"]


def _compact_suffix(language: str) -> str:
    return _PROMPTS[language]["suffix"]
```

### 4.3 Memory 系统

```python
# finrobot/conversation/memory/types.py

from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import StrEnum
import uuid


class MemoryType(StrEnum):
    USER = "user"             # 用户身份 / 偏好 / 专业度
    FEEDBACK = "feedback"     # 用户对 agent 的反馈
    PROJECT = "project"       # 当前研究项目状态
    REFERENCE = "reference"   # 外部资源指针
    ANALYSIS_RESULT = "analysis_result"
    """FinRobot 新增：保留 user turn 的 valuation 摘要。
    e.g. {ticker: 'AAPL', fair_value: 185, wacc: 0.083, date: '...'}"""


@dataclass
class MemoryEntry:
    user_id: str
    fund_id: str  # FinRobot 多租户字段
    memory_type: MemoryType
    name: str
    content: str
    description: str | None = None
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    structured_data: dict | None = None
    """FinRobot 新增：ANALYSIS_RESULT 类型用，存原始结构化值便于 query。"""


# finrobot/conversation/memory/store.py

from typing import Protocol


class MemoryStore(Protocol):
    async def save(self, entry: MemoryEntry) -> str: ...
    async def get(self, memory_id: str) -> MemoryEntry | None: ...
    async def list_by_user(
        self,
        user_id: str,
        fund_id: str,
        memory_type: MemoryType | None = None,
        max_entries: int = 20,
        max_chars: int = 25_000,
    ) -> list[MemoryEntry]: ...
    async def update(self, memory_id: str, **kwargs) -> None: ...
    async def delete(self, memory_id: str) -> None: ...


class SQLiteMemoryStore:
    """v1 实现。多租户字段 fund_id 用于隔离查询。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        # WAL mode + 索引（fund_id, user_id, memory_type, updated_at）
        # 与 Pillar 1 v0.3 N5 修复一致的并发安全
        ...

    async def save(self, entry):
        await self._ensure_init()
        # INSERT；返回 memory_id
        ...

    async def list_by_user(self, user_id, fund_id, memory_type=None,
                            max_entries=20, max_chars=25_000):
        # WHERE fund_id=? AND user_id=? AND (memory_type=? OR ? IS NULL)
        # ORDER BY updated_at DESC LIMIT max_entries
        # 应用层 char budget
        ...
```

### 4.4 自动写入（FinRobot 特色）

```python
# finrobot/conversation/memory/writer.py

async def auto_save_analysis_result(
    store: MemoryStore,
    user_id: str,
    fund_id: str,
    tool_name: str,
    tool_extra: dict,
) -> None:
    """在 post_tool_use hook 中调用，自动为 pipeline 工具落 ANALYSIS_RESULT memory。

    例：run_dcf 完成 → audit_payload={"ticker": "AAPL", "fair_value": 185, ...}
        → 自动写一条 ANALYSIS_RESULT memory
        → 下次用户问 AAPL，system prompt 会注入"上次分析: fair_value 185"
    """
    if tool_name not in {"run_dcf", "run_lbo", "run_comps", "run_equity_research"}:
        return  # 只对核心估值工具自动写

    ticker = tool_extra.get("ticker")
    if not ticker:
        return

    entry = MemoryEntry(
        user_id=user_id,
        fund_id=fund_id,
        memory_type=MemoryType.ANALYSIS_RESULT,
        name=f"{tool_name}:{ticker}",
        content=f"{tool_name} on {ticker}: " + ", ".join(
            f"{k}={v}" for k, v in tool_extra.items() if k != "ticker"
        ),
        structured_data=tool_extra,
    )

    # 同 name 已存在则 update 不 insert（最新的覆盖历史）
    existing = await _find_by_name(store, user_id, fund_id, entry.name)
    if existing:
        await store.update(existing.memory_id, content=entry.content,
                           structured_data=entry.structured_data,
                           updated_at=entry.updated_at)
    else:
        await store.save(entry)
```

通过 Pillar 8 `post_tool_use` hook 注册：

```python
async def memory_writer_hook(context: HookContext) -> HookResult:
    tool_call = context.payload["tool_call"]
    tool_result = context.payload["tool_result"]
    if not tool_result.is_error:
        await auto_save_analysis_result(
            store=context.deps.memory_store,
            user_id=context.state_snapshot.user_id,
            fund_id=context.state_snapshot.fund_id,
            tool_name=tool_call.tool_name,
            tool_extra=tool_result.audit_payload,
        )
    return HookResult()

hooks.register("post_tool_use", memory_writer_hook, name="memory-writer")
```

### 4.5 Task Checkpoint(v0.2:落盘 + 读取保留,refine 降 v2)

**v0.2 调整说明**:Pillar 2 v0.3 §4.8 `RunDCFTool` 已经在 audit_payload + UIAction 用
`{chain_id}:{ticker}:dcf` surrogate task_id(mini-ADR-3 §6 决议)。本节定义 checkpoint
**落盘 + 读取**接口,供 UI 历史复用 / audit 查询 / 跨 session 检索。

**refine 局部重算降级到 v2**(用户决议 2026-05-12)。理由:
- 当前 `Pipeline.execute` 真签名(`base.py:121`)是 `(deps, ticker, progress, lang, **kwargs)`,
  没有 `self.name / set_prefilled_outputs / set_assumptions_override`
- `PipelineResult`(`base.py:375`)只有 `steps / structured_data / failed_validations / warnings`,
  没有 task_id / ticker
- 局部重算需要:(a) Pipeline step dependency graph (b) assumption impact matrix (c) prefill/replay 协议 —— 三者要一起落地,不是 checkpoint 单方面解决

#### 4.5.1 数据结构(保留 v0.1 设计)

```python
# finrobot/conversation/checkpoint/types.py

@dataclass
class TaskCheckpoint:
    task_id: str
    """复合 ID:`{audit_chain_id}:{ticker}:{pipeline_name}`(由 wrapper tool 合成)"""

    user_id: str
    fund_id: str
    audit_chain_id: str

    pipeline_name: str
    ticker: str

    # ─── 各步骤产物(v0.2:用于历史展示;refine 用途降 v2)───
    step_outputs: dict[str, Any] = field(default_factory=dict)
    """key: step_name(如 "fetch_financials" / "dcf_calc" / "narrative");
       value: structured_data 中对应 key 的内容,**序列化为 JSON-safe dict**。

       C3 修订:`result.structured_data: dict[str, object]` 实际可能含三种值:
       - Pydantic BaseModel: 用 `obj.model_dump(mode="json")` 序列化
       - plain dict/list/primitive: 直接 deepcopy 落盘
       - 其他对象: `_safe_serialize(obj)` 兜底转 dict(str representation)

       `SQLiteCheckpointStore.save_pipeline_result` 内部按上述三分支实现。

       v0.2 用途:UI 复用历史结果展示 / audit 重建上下文。
       v2 用途:refine 局部重算的上游产物来源(需要还原 Pydantic 类型,
              v2 用 `structured_class_name` 字段配合 registry 反序列化)。"""

    # ─── 假设参数(v0.2: 仅"记录"价值)───
    assumptions: dict[str, Any] = field(default_factory=dict)
    """记录跑这次 pipeline 时用的假设。
       v0.2: 用户审计回顾"这次跑的什么 WACC";不用于 refine。
       v2:    refine 时 diff 此字段判断哪些 step 需重算。"""

    # ─── 状态 ───
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    """默认 24 小时过期。"""

    is_complete: bool = False
    """**v0.2 仅记录,实际恒为 True**(C1 修订):因为 v0.2 没有 partial save 路径,
       `save_pipeline_result` 只在 pipeline 完整跑完后调用。False 路径 v2 引入
       per-step incremental save 后才有意义。"""

    warnings: list[str] = field(default_factory=list)
    """v0.2 新增:PipelineResult.warnings + failed_validations 的合并,落盘供 UI 复用。"""


class CheckpointStore(Protocol):
    """v0.2: 接口聚焦于"落盘 + 读取";v2 加 refine 用方法。"""

    async def save_pipeline_result(
        self,
        *,
        task_id: str,
        user_id: str,
        fund_id: str,
        audit_chain_id: str,
        pipeline_name: str,
        ticker: str,
        result: "PipelineResult",
    ) -> None:
        """高层方法,Pillar 2 v0.3 §4.8 wrapper 调用。

        内部:从 result.structured_data 解构每个 step 输出,Pydantic .model_dump()
        序列化,生成 TaskCheckpoint 并持久化。is_complete=True。expires_at=now+24h。
        warnings 字段合并 result.warnings + result.failed_validations。"""

    async def save(self, ckpt: TaskCheckpoint) -> None:
        """底层 save。"""

    async def get(self, task_id: str) -> "TaskCheckpoint | None": ...

    async def list_by_user(
        self,
        user_id: str,
        fund_id: str,
        pipeline_name: str | None = None,
        ticker: str | None = None,
        limit: int = 50,
    ) -> list["TaskCheckpoint"]:
        """UI 列表用。按 fund_id + user_id 隔离;可选过滤 pipeline / ticker。"""

    async def delete(self, task_id: str) -> None: ...

    async def cleanup_expired(self) -> int:
        """**懒清理**:`save_pipeline_result` 内部按采样率触发(C2 修订)。

        实施约定:`SQLiteCheckpointStore._CLEANUP_SAMPLE_RATE = 10`,
        即每 10 次 `save_pipeline_result` 调用触发 1 次 `cleanup_expired` 扫描。
        - 选 10 而非每次:避免每次写都扫全表(SQLite 上数万 row 时延迟显著)
        - 选 10 而非 100:多租户场景下用户活跃度参差,10 足够把 expired 控制在 < 24h+10 个 turn 内清掉
        - 在 lifespan startup 时主动调一次,清掉上次进程留下的过期 row

        返回删除数量。"""
```

#### 4.5.2 Wrapper tool 接入(配合 Pillar 2 v0.3 §4.8)

```python
# Pillar 2 v0.3 §4.8 RunDCFTool.call 已展示:
#   await context.deps.checkpoint_store.save_pipeline_result(
#       task_id=surrogate_task_id,
#       user_id=context.user_id, fund_id=context.fund_id,
#       audit_chain_id=context.audit_chain_id,
#       pipeline_name="dcf", ticker=args.ticker.upper(),
#       result=result,
#   )
```

#### 4.5.3 历史查询 tool(v0.2 新增,可选)

```python
class GetTaskHistoryArgs(BaseModel):
    pipeline_name: str | None = None
    ticker: str | None = None
    limit: int = 10


class GetTaskHistoryTool(BaseTool[GetTaskHistoryArgs]):
    name = "get_analysis_history"
    description = "List previous analyses (DCF/LBO/comps/...) by ticker or pipeline. Read-only."
    input_model = GetTaskHistoryArgs
    concurrency_safe_default = True

    async def call(self, args, context):
        items = await context.deps.checkpoint_store.list_by_user(
            user_id=context.user_id, fund_id=context.fund_id,
            pipeline_name=args.pipeline_name, ticker=args.ticker,
            limit=args.limit,
        )
        # 紧凑文本(给 LLM)
        lines = [
            f"- {c.pipeline_name} on {c.ticker} at {c.updated_at:%Y-%m-%d %H:%M}: "
            f"task_id={c.task_id}{' [WARN]' if c.warnings else ''}"
            for c in items
        ]
        return ToolResult(
            data=items,
            text_for_llm="\n".join(lines) or "No prior analyses found.",
            audit_payload={"count": len(items)},
        )
```

#### 4.5.4 ~~Refine 实现~~(降级到 v2)

> v0.1 的 `apply_dcf_refinement` 函数 + `RefineDCFTool` 工具 + `Pipeline.set_prefilled_outputs` /
> `set_assumptions_override` 方法**全部移到 v2**。Pillar 2 v0.3 §4.8 `UIAction(show_assumption_panel)`
> 的 `refine_available=False`,UI 不暴露 refine 入口。
>
> v2 启动条件(三者齐备):
> 1. Pipeline step 加 `depends_on: list[str]` 字段声明依赖图
> 2. 每个 pipeline 给出 assumption impact matrix(哪个假设字段影响哪些 step)
> 3. Pipeline.execute 加 `prefilled_outputs` / `assumptions_override` kwargs
>
> 详见 §5 v1 推迟功能表。

### 4.6 与 Pillar 1 / 3 的对接

| 改动 | 详细 |
|---|---|
| Pillar 1 `should_auto_compact()` 实现 | 调用本 pillar `calculate_compact_threshold + should_auto_compact` |
| Pillar 1 `do_compact()` 实现 | 调用本 pillar `compactor.do_compact` |
| Pillar 3 `build_memory()` 函数 | 调用本 pillar `MemoryStore.list_by_user`，按 ANALYSIS_RESULT 优先级排序 |
| ~~Pillar 2 refine_dcf tool~~ | ~~由本 pillar apply_dcf_refinement 支撑~~ → **v2 启动**(三件套 dependency graph + impact matrix + prefill/replay 协议齐备后) |
| Pillar 8 `memory_writer_hook` | 注册到 `post_tool_use` 时机 |

---

## 5. v1 推迟功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| Reactive compact | v1 阈值预防足够；413 错误金融场景罕见 | v2 |
| Microcompact (cached / time-based) | CC 是 Anthropic 内部 prompt cache 优化，FinRobot v1 不依赖 | 不实施 |
| Context Collapse | 复杂度高，收益不明 | v2 evaluate |
| Snip | 消息粒度删除，v1 用 compact 替代 | 不实施 |
| KAIROS 日记 / Team Memory | FinRobot 不是个人助手场景 | 不实施 |
| LLM-based memory relevance | v1 用最近 N 条 + ANALYSIS_RESULT 优先 | v2 |
| `/remember` 用户命令 | v1 自动写就够 | v2 |
| Memory 版本控制 | 写时直接 update 覆盖 | v2 |
| **Refine 局部重算(所有 pipeline)** | **mini-ADR-3 §6 决议:全部降 v2**(用户决议 2026-05-12)。需要 Pipeline step dependency graph + assumption impact matrix + prefill/replay 协议三者齐备 | v2 |
| PostgreSQL 后端 | v1 SQLite 多租户够用 | v2 + scale |
| Checkpoint 跨会话 | v1 24 小时 expire，单会话；跨会话 v2 | v2 |

---

## 6. 自审状态(v0.2 更新)

| ID | 严重度 | v0.1 问题 | v0.2 状态 |
|---|---|---|---|
| F-P5-1 | 🔴 | do_compact mutate state.messages 与 HookContext.state_snapshot 冲突 | ⚠️ **v0.3 留** — Pillar 1 v0.6 主循环已保证 compact 调用前不构造 snapshot;但 compact 后下一轮 hook 拿到的是新 messages,与 v0.1 担心一致。需要 Pillar 1 v0.7 明文 emit `compact_event` AuditEvent + 不变量"compact 在 hook 调用前" |
| F-P5-2 | 🔴 | hook 内 fire-and-forget 写入丢失 | ⚠️ **v0.2 简化** — 配合 Pillar 8 v0.2 `_BACKGROUND_TASKS` set 防 GC;v2 升级 asyncio.Queue + lifespan shutdown await |
| F-P5-3 | 🟠 | step_outputs: dict[str, Any] 类型逃逸 | 🟢 **v0.2 接受** — v0.2 §4.5.1 落盘是 `Pydantic.model_dump()`,反序列化时按 step_name 用 registry 还原。refine 降 v2 后,类型完整性 v2 处理 |
| F-P5-4 | 🟠 | apply_dcf_refinement 依赖图 | ✅ **v0.2 解** — refine 整体降 v2,本问题无关 |
| F-P5-5 | 🟡 | cleanup_expired 无定时器 | ✅ **v0.2 解** — `save_pipeline_result` 内部触发懒清理(每 N 次写 1 次扫描) |
| F-P5-6 | 🟡 | max_chars 硬编码 | 🟢 **v0.3 留** — v0.2 不阻塞 |
| F-P5-7 | 🟡 | compact 后 total_usage 不重置 | 🟢 **v0.3 留** — compact 时 audit event 加 `tokens_freed`,应用层 cost tracker 修正(Pillar 8 v0.2 cost-tracker 已用 metadata 路径) |

---

## 7. 测试要点

- UT-P5-01..04 阈值计算（不同 context_window + override）
- UT-P5-05..07 compact 算法（小于阈值 / 大于阈值 / 失败熔断）
- UT-P5-08..10 双语 compact prompt
- UT-P5-11..14 MemoryStore CRUD（save / get / list / update / delete）
- UT-P5-15 多租户隔离（fund_id 不同看不到对方 memory）
- UT-P5-16..18 ANALYSIS_RESULT 自动写入（hook 触发 / 重复 update / 异常隔离）
- UT-P5-19..22 TaskCheckpoint CRUD + 过期 + 懒清理
- ~~UT-P5-23..25 refine_dcf~~(v0.2 删除,refine 降 v2)
- UT-P5-26..28(v0.2 新增):`save_pipeline_result` 端到端落盘 + `list_by_user` 多租户过滤 + `GetTaskHistoryTool` 工具调用
- IT-P5-01 长会话(30 turn)触发 compact → 后续 turn 正常
- IT-P5-02 跨 user turn 的 memory 注入(第 2 个 user turn 在 system prompt 看到第 1 个 turn 的 ANALYSIS_RESULT)
- ~~IT-P5-03 refine 性能~~(v0.2 删除)
- IT-P5-04(v0.2 新增):RunDCFTool 跑完后 GetTaskHistoryTool 能查到该 task_id;list_by_user 跨 fund 隔离

---

## 8. 未决问题

1. **Memory 隐私 / 删除权**——用户能否在前端看到 / 删除自己的 memory？v1 仅程序入口，v2 加 UI
2. **Memory 跨 fund 迁移**——分析师跳槽到另一基金时 USER 类 memory 是否能转移？v1 不支持
3. **Checkpoint 与 audit log 的去重**——audit log 已经记录每步 LLM 输出，checkpoint 再存一份是否冗余？决议：audit 是审计读，checkpoint 是 refine 写，职责不同，保留双份
4. **Compact 后是否 invalidate cache_control 标记**——Pillar 3 v0.1 §4.5 已经讨论；compact 改 messages 必然 cache miss，无需特殊处理

---

## 9. 实施计划

### Week 4

- [ ] `compact/` 全模块 + UT-P5-01..10
- [ ] `memory/types.py` + `memory/store.py` SQLiteStore + UT-P5-11..15

### Week 5

- [ ] `memory/writer.py` + `post_tool_use` hook 注册 + UT-P5-16..18
- [ ] `checkpoint/` 全模块 + UT-P5-19..22
- [ ] ~~Pillar 2 RefineDCFTool 实现 + UT-P5-23..25~~ → **v2 启动**(mini-ADR-3 §6 决议)
- [ ] UT-P5-26..28 + IT-P5-04(v0.2 新增,落盘 / list_by_user / GetTaskHistoryTool)
- [ ] IT-P5-01..03

### Week 6

- [ ] Pillar 3 `build_memory()` 真实接入 SQLiteStore
- [ ] 性能 baseline（refine 速度 vs full re-run）

---

## 10. 参考资料

- CC: `src/services/compact/`、`src/memdir/`
- homepilot: `engine/compact/`、`engine/memory/`
- 前置：Pillar 1 v0.4、Pillar 2 v0.2、Pillar 3 v0.1
- 原始报告：`raw/cc-pillar-5-raw.md`、`raw/homepilot-pillar-5-raw.md`
