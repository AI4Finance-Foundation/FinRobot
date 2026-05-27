# Pillar 7: Sub-agent — 研究与 FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.3 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | v0.3 修 v0.2 评审 B3 + I4/I5/I6 |
| **前置** | mini-ADR-1 v1.2、mini-ADR-2、mini-ADR-3 v1.0、Pillar 1 v0.7、Pillar 2 v0.3、Pillar 3 v0.2、Pillar 5 v0.3 |
| **原始报告** | `raw/cc-pillar-7-raw.md`、`raw/homepilot-pillar-7-raw.md` |

---

## Changelog

### v0.3(2026-05-12)

修 v0.2 评审 Blocking B3 + Inconsistency I4/I5/I6:

- **B3**:§4.6 `SubAgentResult` 补 `from dataclasses import dataclass, field`(原文档只 import `dataclass`,`field(default_factory=list)` 字面错误)
- **I4**:§6 F-P7-6 v0.2 status 与 §4.6 chunks-of-5 决议矛盾——改 ✅ "chunks-of-5 自动分批,description 注明 'tasks beyond 5 are executed in additional batches'"
- **I5**:§7 UT-P7-15..17 "超过 5 抛错" 改为 "超过 5 自动按 5 分批顺序执行,最终结果按输入顺序返回";新增 UT-P7-19 验证 12 个任务跑 3 批(5+5+2)顺序保留
- **I6**:§4.6 `_run_one` 宽 `except Exception` 收窄,与 Pillar 2 §4.6 `_execute_one` 的 `except asyncio.CancelledError: raise` 模式对齐

### v0.2(2026-05-12)

应用 mini-ADR-3 + 修 v0.1 评审 high-risk 3 项:

**修复**:
- **F-P7-1**:`SpawnSubAgentTool.call` 通过 `context.parent_state` 等 6 字段访问父状态(Pillar 2 v0.3 §4.4 ToolUseContext 19 字段,后 6 为 sub-agent 派生用)。`model_adapter` 从 `context.deps.model_adapter` 取(mini-ADR-3 §2.1)
- **F-P7-2**:`spawn_subagent` 内部不再 `tool_orchestrator_class(child_registry)`,改调 `parent_orchestrator.fork_for_subagent(child_registry)`(Pillar 2 v0.3 §4.6.1),共享父 Semaphore;mini-ADR-3 §5.7 保证 `id(child._sem) == id(parent._sem)`
- **F-P7-4**:`combined_text = base.text + "---" + agent_def.system_prompt` 破坏 STATIC_BOUNDARY_MARKER 改用 `build_system_prompt(..., extra_static_prefix=agent_def.system_prompt)` —— Pillar 3 v0.2 需 patch(本 doc 标注待 patch)
- **chunks-of-5**(用户决议):`run_parallel_subagents` N>5 不抛错,按 5 一批顺序跑;`SpawnParallelTool` description 写明"按 5 一批"

**未实施(留 v0.3)**:
- F-P7-3 text 拼接读 messages last assistant 而非 content_block_delta:v0.2 简化提取保留
- F-P7-5/6/7 v0.1 §6 自审无 v0.2 阻塞

---

## 0. TL;DR

- **CC**：4 种执行路径（fork / async / sync / teammate），AgentDefinition 含 14+ 字段，AgentSummary 定时 30s fork 子 query 生成进度
- **homepilot**：1 种执行路径（sync），AgentDefinition 7 字段，Coordinator 用 asyncio.gather 并发
- **FinRobot v1**：**sync 路径为主 + parallel 子模式**（asyncio.gather）+ AgentDefinition 8 字段 + spawn_subagent 工具暴露给 LLM + mini-ADR-2 谱系字段强制注入

---

## 1. Pillar 7 的位置

Sub-agent 解锁两个 FinRobot 关键场景：
1. **Peer comparison**：用户问"对比 AAPL / MSFT / GOOGL"——主 agent spawn 3 个 sub-agent 各自做完整 equity_research，并行运行
2. **Multi-perspective IC memo**：主 agent spawn `value_analyst` / `growth_analyst` / `bear_analyst` 3 个 sub-agent 给同一标的不同立场分析，汇总成辩论式 IC memo

mini-ADR-2 已经决议了 chain_id / root_id / parent_chain_id / depth 谱系。本 pillar 完成 spawn 机制、AgentDefinition、context 隔离、结果回收、错误处理。

---

## 2. 调研结论摘要

### 2.1 CC（详见 `raw/cc-pillar-7-raw.md`）

- `Agent` 工具入参：description / prompt / subagent_type / model / run_in_background 等
- 4 路径：sync（阻塞）/ async（后台 task）/ teammate（独立进程）/ fork（cache 共享）
- AgentDefinition: agentType / getSystemPrompt / model / tools / maxTurns / permissionMode / background / isolation / hooks / skills / mcpServers / 等 14+
- `createSubagentContext` 字段级控制隔离 / 共享
- AgentSummary 30s 定时 fork 子 query 生成进度
- 主路径继承 chain_id，fork 路径新建（内部矛盾，mini-ADR-2 记录）

### 2.2 homepilot（详见 `raw/homepilot-pillar-7-raw.md`）

- 单 `spawn_agent()` 函数，AsyncGenerator
- AgentDefinition 7 字段：agent_type / system_prompt / tools / disallowed_tools / model / max_turns / description
- YAML frontmatter + Markdown 加载
- 父消息不传，子全新 QueryState
- `resolve_agent_tools` 用 ["*"] 或显式列表过滤
- Coordinator 用 `asyncio.gather` 并发多 worker

---

## 3. 决策对照表

| 维度 | CC | homepilot | **FinRobot 决策** | 理由 |
|---|---|---|---|---|
| 执行路径数 | 4 | 1 | **2（sync + parallel batch）** | sync 单 spawn，parallel = 一次 spawn 多个 sub-agent |
| Spawn 入口 | `Agent` 工具 | `spawn_agent()` 函数 | **`spawn_subagent` 工具 + 框架函数** | 工具暴露给 LLM；框架函数供 Coordinator 用 |
| AgentDefinition 字段 | 14+ | 7 | **8** | 7 + 1 (FinRobot 特有 `analyst_style` 锚到 Pillar 3 风格) |
| 加载方式 | 装饰器 + 目录 | YAML + Markdown | **YAML + Markdown**（沿用 homepilot） | 与现有 agents/ 目录一致 |
| 父消息传递 | Fork 传 / 普通不传 | 不传 | **不传（v1）+ fork 模式 v2 评估** | v1 简化 |
| Tool 子集 | denied/allowed agents + assemble | resolve_agent_tools | **resolve_agent_tools（同 homepilot）** | 直接 |
| Chain_id 谱系 | 主继承 / fork 新建（矛盾） | 无 | **mini-ADR-2 4 字段方案（无矛盾）** | 已决议 |
| 并发 | Async task | asyncio.gather | **asyncio.gather + max_subagents 上限** | 防止失控（默认 max=5）|
| AgentSummary | 30s 定时 | 无 | **v1 不做，v2 评估** | 复杂度高，桌面 app 直接看流即可 |
| Hook 继承 | frontmatter + 父 hooks | 不传 | **sub-agent 继承父 hook_registry（默认）+ AgentDefinition 可加 disable_hooks** | 审计追溯需要 |
| Memory 隔离 | 不传到 sub-agent | 同 | **传 memory_store（多租户 fund_id 决定可见性）** | sub-agent 仍属同 fund |
| 失败传染 | sync 抛、async 不中断兄弟 | 不中断兄弟 | **不中断兄弟**（asyncio.gather + return_exceptions=True） | 一个 peer 分析失败不该影响其他 |

---

## 4. FinRobot 实现规格

### 4.1 模块结构

```
finrobot/conversation/subagent/        # 新增
├─ __init__.py
├─ types.py                            # AgentDefinition（FinRobot 版）
├─ loader.py                           # YAML + Markdown 加载（沿用 homepilot 模式）
├─ spawner.py                          # spawn_subagent() 框架函数
├─ coordinator.py                      # 并发 batch + asyncio.gather
└─ summary.py                          # 结果汇总辅助
```

### 4.2 AgentDefinition

```python
# finrobot/conversation/subagent/types.py

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AgentDefinition:
    agent_type: str
    """唯一标识符。对应 agents/{agent_type}.md 文件。"""

    system_prompt: str
    """系统提示词（从 Markdown 正文加载）。"""

    description: str = ""
    """给 LLM 看的描述，spawn_subagent 工具用此选择合适的 sub-agent。"""

    tools: list[str] = field(default_factory=lambda: ["*"])
    disallowed_tools: list[str] = field(default_factory=list)

    model: str | None = None
    """None = 继承父 model。"""

    max_turns: int | None = None
    """None = 用 QueryConfig 默认 30。"""

    # ─── FinRobot 特有 ───

    analyst_style: Literal["value", "growth", "quant", "education", "ic_memo"] | None = None
    """如果设置，覆盖父 AgentProfile.analyst_style。
    例：spawn 'bear_analyst' 时强制 analyst_style='value'（保守视角）。
    None = 继承父。"""

    disable_hooks: bool = False
    """如果 True，sub-agent 不继承父的 hook_registry（仅 audit_trail hook 保留）。
    v1 默认 False（全继承），仅在性能调优场景关闭。"""
```

### 4.3 加载（YAML frontmatter + Markdown）

约定目录：`finrobot/agents/`（项目级）+ `~/.finrobot/agents/`（用户级，v2）

文件示例 `finrobot/agents/peer_comparator.md`:

```markdown
---
agent_type: peer_comparator
description: 给定 1 个标的 + 多个 peer ticker，输出 peer comparison 表 + 相对估值结论
tools: ["run_comps", "get_financials", "compare_tickers"]
disallowed_tools: ["export_report_excel", "add_to_watchlist"]
model: anthropic:claude-sonnet-4-6
max_turns: 15
analyst_style: value
---

你是 peer comparator sub-agent。输入：主标的 + peer 列表。

工作流：
1. 用 run_comps 拉取主标的的同行业 multiples
2. 对每个 peer 用 get_financials 验证数据可得
3. 用 compare_tickers 生成对比矩阵
4. 输出结构化结论：valuation premium/discount + 关键差异点

输出格式：4-section 简报（valuation_summary / peer_metrics / differentiation / verdict）。
```

加载逻辑（沿用 homepilot loader.py 模式）：

```python
# finrobot/conversation/subagent/loader.py

import yaml
from pathlib import Path


def load_agent_from_path(path: Path) -> AgentDefinition:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path}: missing YAML frontmatter")

    parts = raw.split("---", maxsplit=2)
    if len(parts) < 3:
        raise ValueError(f"{path}: malformed frontmatter")

    metadata = yaml.safe_load(parts[1])
    body = parts[2].strip()

    return AgentDefinition(
        agent_type=metadata.get("agent_type", path.stem),
        system_prompt=body,
        description=metadata.get("description", ""),
        tools=metadata.get("tools", ["*"]),
        disallowed_tools=metadata.get("disallowed_tools", []) or metadata.get("disallowed-tools", []),
        model=metadata.get("model"),
        max_turns=metadata.get("max_turns"),
        analyst_style=metadata.get("analyst_style"),
        disable_hooks=metadata.get("disable_hooks", False),
    )


def load_agents_from_directory(directory: Path) -> dict[str, AgentDefinition]:
    return {
        (a := load_agent_from_path(p)).agent_type: a
        for p in directory.glob("*.md")
    }
```

### 4.4 spawn_subagent 框架函数

```python
# finrobot/conversation/subagent/spawner.py

from collections.abc import AsyncGenerator

from finrobot.conversation.state import fork_subagent_state, QueryState
from finrobot.conversation.config import QueryConfig
from finrobot.conversation.loop import query_loop


def resolve_agent_tools(
    parent_registry: ToolRegistry,
    agent_def: AgentDefinition,
) -> ToolRegistry:
    """根据 agent_def.tools + disallowed_tools 从父 registry 派生子 registry。"""
    child = ToolRegistry()
    if agent_def.tools == ["*"]:
        for t in parent_registry.list_tools():
            if t.name not in agent_def.disallowed_tools:
                child.register(t)
    else:
        for tool_name in agent_def.tools:
            if tool_name in agent_def.disallowed_tools:
                continue
            tool = parent_registry.get(tool_name)
            if tool is None:
                continue  # 容忍未注册（不抛错，避免 sub-agent 启动失败）
            child.register(tool)
    return child


async def spawn_subagent(
    agent_def: AgentDefinition,
    prompt: str,
    *,
    parent_state: QueryState,
    parent_config: QueryConfig,
    parent_profile: "AgentProfile",
    parent_tool_registry: ToolRegistry,
    parent_orchestrator: ToolOrchestrator,       # v0.2: 改类型,不是 _class
    deps: "FinRobotDeps",                         # v0.2 新增:走 mini-ADR-3 §2.1
    hook_registry: "HookRegistry | None" = None,
    max_depth: int = 3,
) -> AsyncGenerator[StreamEvent | AuditEvent, None]:
    """启动 sub-agent(v0.2:全部依赖从 parent 派生/共享,F-P7-1/F-P7-2/F-P7-4 修复)。

    谱系(mini-ADR-2 + mini-ADR-3 §3):
      - QueryState fork_subagent_state(新 chain / 继承 root / parent 指向父 / depth+1)
      - FinRobotDeps 直接复用(进程级单例)
      - ToolOrchestrator fork_for_subagent(共享父 Semaphore,mini-ADR-3 §3.1)
    """
    # 1. Fork QueryState(mini-ADR-2)
    child_state = fork_subagent_state(
        parent_state=parent_state,
        initial_messages=[UserMessage(content=prompt)],
        max_depth=max_depth,
    )

    # 2. 派生 child profile(agent_def 字段覆盖)
    child_profile = AgentProfile(
        analyst_style=agent_def.analyst_style or parent_profile.analyst_style,
        market=parent_profile.market,
        fund_id=parent_profile.fund_id,
        fund_style=parent_profile.fund_style,
        covered_tickers=parent_profile.covered_tickers,
    )

    # 3. 装配 system prompt(F-P7-4 修复:走 extra_static_prefix 进 prompt builder
    #    静态部分,不破坏 STATIC_BOUNDARY_MARKER。需要 Pillar 3 v0.2 patch)
    assembled = build_system_prompt(
        child_profile,
        language=parent_config.language,
        memory_store=deps.memory_store,
        user_id=parent_state.user_id,
        extra_static_prefix=agent_def.system_prompt,  # ← Pillar 3 v0.2 加此参数
    )

    child_config = QueryConfig(
        model=agent_def.model or parent_config.model,
        system_prompt=assembled.text,
        max_turns=agent_def.max_turns or parent_config.max_turns,
        circuit_breaker_threshold=parent_config.circuit_breaker_threshold,
        tool_circuit_breaker_threshold=parent_config.tool_circuit_breaker_threshold,
        max_output_tokens_recovery_limit=parent_config.max_output_tokens_recovery_limit,
        temperature=parent_config.temperature,
        language=parent_config.language,
        use_prompt_caching=parent_config.use_prompt_caching,
        max_cost_usd_per_turn=parent_config.max_cost_usd_per_turn,
    )

    # 4. 派生子 tool registry
    child_registry = resolve_agent_tools(parent_tool_registry, agent_def)

    # 5. 派生子 orchestrator —— F-P7-2 修复:共享父 Semaphore(mini-ADR-3 §3.1)
    child_orchestrator = parent_orchestrator.fork_for_subagent(child_registry)
    # 不变量(mini-ADR-3 §5.7,UT 必须断言):
    assert id(child_orchestrator._sem) == id(parent_orchestrator._sem)

    # 6. 决定 hook_registry
    child_hooks = None if agent_def.disable_hooks else hook_registry

    # 7. 跑子 query_loop —— 复用 deps,model_adapter 从 deps 取
    async for event in query_loop(
        state=child_state,
        config=child_config,
        deps=deps,                                     # v0.2:复用,不重建
        profile=child_profile,
        model_adapter=deps.model_adapter,              # v0.2:从 deps 取
        tool_orchestrator=child_orchestrator,
        tool_registry=child_registry,
        hook_registry=child_hooks,
    ):
        yield event
```

### 4.5 spawn_subagent 工具（LLM 可调用）

```python
# finrobot/conversation/tools/subagent_tools.py

from pydantic import BaseModel, Field


class SpawnSubAgentArgs(BaseModel):
    agent_type: str = Field(description="Sub-agent type (must be registered). E.g. 'peer_comparator', 'bear_analyst'")
    prompt: str = Field(description="Initial prompt to pass to the sub-agent")


class SpawnSubAgentTool(BaseTool[SpawnSubAgentArgs]):
    name = "spawn_subagent"
    description = (
        "Spawn a specialized sub-agent to handle a focused sub-task. "
        "Available agent_types: peer_comparator, bear_analyst, value_analyst, "
        "growth_analyst, esg_analyst. Returns the sub-agent's final analysis."
    )
    input_model = SpawnSubAgentArgs
    concurrency_safe_default = False  # 一个 turn 内只 spawn 一次（v1）；v2 加 batch 工具

    async def call(self, args, context):
        agent_def = context.deps.agent_registry.get(args.agent_type)
        if agent_def is None:
            return ToolResult(
                data=f"Unknown agent_type '{args.agent_type}'. Available: "
                      + ", ".join(context.deps.agent_registry.keys()),
                is_error=True,
            )

        # 收集 sub-agent 所有事件 → 提取最终 assistant 消息作为返回
        # v0.2(F-P7-1 修复):context 直接持有 parent_state/config/profile/registry/
        # orchestrator/hook_registry 六字段(Pillar 2 v0.3 §4.4 ToolUseContext 19 字段)
        # model_adapter / memory_store 从 context.deps 取(mini-ADR-3 §2.1)
        collected_events: list[StreamEvent | AuditEvent] = []
        final_messages: list[str] = []
        async for event in spawn_subagent(
            agent_def=agent_def,
            prompt=args.prompt,
            parent_state=context.parent_state,
            parent_config=context.parent_config,
            parent_profile=context.parent_profile,
            parent_tool_registry=context.tool_registry,
            parent_orchestrator=context.tool_orchestrator,
            deps=context.deps,
            hook_registry=context.hook_registry,
        ):
            collected_events.append(event)
            if hasattr(event, "type") and event.type == "content_block_delta":
                if event.delta.get("type") == "text_delta":
                    final_messages.append(event.delta.get("text", ""))

        return ToolResult(
            data="".join(final_messages),
            audit_payload={
                "subagent_type": args.agent_type,
                "event_count": len(collected_events),
            },
        )
```

### 4.6 并行 batch（Coordinator）

```python
# finrobot/conversation/subagent/coordinator.py

import asyncio
from dataclasses import dataclass, field  # v0.3 B3:补 field


@dataclass
class SubAgentResult:
    agent_type: str
    prompt: str
    text: str = ""
    is_error: bool = False
    error_message: str | None = None
    events: list = field(default_factory=list)


async def run_parallel_subagents(
    tasks: list[tuple[AgentDefinition, str]],
    *,
    batch_size: int = 5,
    **spawn_kwargs,
) -> list[SubAgentResult]:
    """并发 spawn 多个 sub-agent,按 `batch_size` 一批顺序执行(v0.2 chunks-of-5)。

    用户决议(2026-05-12):N>5 不抛错,按 5 一批跑。理由:工具语义叫 parallel batch,
    LLM 给 N 个任务应能落地,超 5 报错会让调用体验脆。

    并发上限实际还是受 Pillar 2 §4.6 共享 Semaphore(max=10)约束(mini-ADR-3 §3.1),
    所以一批 5 sub-agent × 每个 sub 调 X 个 tool 在全局 10 slot 池里排队 —— 这是
    设计选择的可接受代价(确定性 > 吞吐)。

    一个 sub-agent 失败不传染其他批 / 其他兄弟。
    """
    async def _run_one(agent_def, prompt):
        # v0.3 I6:收窄 except(原 `except Exception` 会吞 CancelledError /
        # KeyboardInterrupt / SystemExit,sub-agent 不能正常 cancel)
        # 与 Pillar 2 §4.6 _execute_one 模式对齐
        result = SubAgentResult(agent_type=agent_def.agent_type, prompt=prompt)
        try:
            text_parts = []
            async for event in spawn_subagent(
                agent_def=agent_def, prompt=prompt, **spawn_kwargs
            ):
                result.events.append(event)
                if hasattr(event, "type") and event.type == "content_block_delta":
                    if event.delta.get("type") == "text_delta":
                        text_parts.append(event.delta.get("text", ""))
            result.text = "".join(text_parts)
        except asyncio.CancelledError:
            raise  # 让取消正常传播
        except (
            ProviderError, ValidationError, RuntimeError, ValueError,
            SubAgentDepthExceeded,
        ) as exc:
            result.is_error = True
            result.error_message = f"{type(exc).__name__}: {exc}"
        return result

    all_results: list[SubAgentResult] = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        coros = [_run_one(ad, p) for ad, p in batch]
        batch_results = await asyncio.gather(*coros)
        all_results.extend(batch_results)
    return all_results


class SpawnParallelArgs(BaseModel):
    tasks: list[dict] = Field(
        description=(
            "List of {agent_type, prompt} dicts. No upper limit on count: "
            "tasks beyond 5 are executed in additional batches of 5 sequentially."
        )
    )


class SpawnParallelTool(BaseTool[SpawnParallelArgs]):
    name = "spawn_parallel_subagents"
    description = (
        "Spawn N sub-agents in parallel-batched fashion. Tasks are executed in "
        "batches of 5 (subsequent batches start after the previous batch "
        "completes). Useful for peer comparison or multi-perspective analysis. "
        "Returns all results in input order. Global tool concurrency cap of 10 "
        "still applies across the entire spawn tree."
    )
    input_model = SpawnParallelArgs
    concurrency_safe_default = False

    async def call(self, args, context):
        if not args.tasks:
            return ToolResult(
                data="No tasks provided.",
                is_error=True,
            )

        agent_tasks = []
        for t in args.tasks:
            agent_def = context.deps.agent_registry.get(t["agent_type"])
            if agent_def is None:
                return ToolResult(
                    data=f"Unknown agent_type '{t['agent_type']}'. Available: "
                          + ", ".join(context.deps.agent_registry.keys()),
                    is_error=True,
                )
            agent_tasks.append((agent_def, t["prompt"]))

        # v0.2(F-P7-1):context 直接持有派生字段,deps 持有 store / adapter
        results = await run_parallel_subagents(
            agent_tasks,
            batch_size=5,
            parent_state=context.parent_state,
            parent_config=context.parent_config,
            parent_profile=context.parent_profile,
            parent_tool_registry=context.tool_registry,
            parent_orchestrator=context.tool_orchestrator,
            deps=context.deps,
            hook_registry=context.hook_registry,
        )

        # 汇总：每个 sub-agent 的结果作为单独 section
        summary_parts = []
        for r in results:
            summary_parts.append(
                f"### Sub-agent: {r.agent_type}\n"
                + (f"Error: {r.error_message}" if r.is_error else r.text)
            )

        return ToolResult(
            data="\n\n---\n\n".join(summary_parts),
            audit_payload={
                "subagent_count": len(results),
                "agent_types": [r.agent_type for r in results],
                "success_count": sum(1 for r in results if not r.is_error),
            },
        )
```

### 4.7 v1 内置 sub-agent 清单

`finrobot/agents/`:
- `peer_comparator.md`（已示例 §4.3）
- `bear_analyst.md` — 找标的的所有 bear case
- `value_analyst.md` — 用 value style 重新评估
- `growth_analyst.md` — 用 growth style 重新评估
- `esg_analyst.md` — ESG 风险分析（可选 v1.5）

每个文件 15-30 行 YAML + Markdown，加载到 AgentRegistry。

---

## 5. v1 推迟功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| Async / 后台执行 | sync 足够覆盖 v1 场景；async 增加状态追踪复杂度 | v2 |
| Teammate / 跨进程 | CC IDE 工作流特有，FinRobot 不需要 | 不实施 |
| Fork 路径（cache 共享） | 字节匹配实现复杂度高；FinRobot v1 cache 命中靠 system prompt 静态前缀已足够 | v2 evaluate |
| AgentSummary 定时进度 | 桌面 app 直接看流式输出即可；30s 摘要是 IDE 场景需求 | 不实施 |
| Sub-agent 自定义 frontmatter hooks | v1 仅继承父 hook | v2 |
| Sub-agent 独立 MCP servers | v1 不做 MCP | v2 |
| Skills 预加载 | v1 不做 skills | v2 |
| Worktree isolation | git 隔离场景特有 | 不实施 |
| Sub-agent 资源 quota（独立 cost cap） | v1 sub-agent cost 计入父 turn cost | v2 evaluate |

---

## 6. 自审 7 处

| ID | 严重度 | 问题 | 修复方向 |
|---|---|---|---|
| F-P7-1 | 🔴 | `SpawnSubAgentTool.call` 通过 `context.deps.parent_state` 访问父状态——但 Pillar 2 的 `ToolUseContext.deps` 没有 `parent_state` 字段 | v0.2: ToolUseContext 增加 `parent_state` 或专用 `subagent_context` 字段 |
| F-P7-2 | 🔴 | `spawn_subagent` 内部新建 `child_orchestrator = tool_orchestrator_class(child_registry)`——这等于丢失 Semaphore 全局上限（Pillar 2 v0.2 B3 修复刚获得） | v0.2: 父 orchestrator 暴露 `share_semaphore_with(child)` 方法，sub-agent 用同一 Semaphore |
| F-P7-3 | 🟠 | `text_for_llm` 拼接逻辑——只用 `content_block_delta` 的 text_delta 重建文本，但 sub-agent 可能产出 tool_use blocks，不会进入这里 | v0.2: 改用 sub-agent 最终 messages 的 last assistant message 文本提取 |
| F-P7-4 | 🟠 | `combined_text = f"{base.text}\n\n---\n\n{agent_def.system_prompt}"`——这破坏了 Pillar 3 的 STATIC_BOUNDARY_MARKER 位置（marker 现在出现在 base 中间） | v0.2: 用 build_system_prompt 的扩展 API `extra_static_prefix` 把 agent_def.system_prompt 嵌入静态部分 |
| F-P7-5 | 🟡 | `analyst_style` 字段在 AgentDefinition + AgentProfile 两处定义——可能产生不一致 | v0.2: AgentDefinition 不存 analyst_style，由调用方在 spawn 时显式传入 |
| F-P7-6 | 🟡 | parallel batch 上限 5 硬编码——超过抛错——LLM 可能不知道 | ✅ **v0.3 已修复**(用户决议 chunks-of-5):§4.6 `run_parallel_subagents` 实现 chunks-of-5 自动分批,N>5 不抛错按 5 一批顺序跑;`SpawnParallelTool.description` 明文 "tasks beyond 5 are executed in additional batches of 5 sequentially"。**不**加 field validator(那会与"不抛错"矛盾)。|
| F-P7-7 | 🟡 | sub-agent 的 audit log 写入是否触发 Pillar 5 的 memory_writer_hook？——可能导致每个 sub-agent 都写一份 analysis_result memory，冗余 | v0.2: memory_writer_hook 加 `if depth > 0: return` 跳过 sub-agent |

---

## 7. 测试要点

- UT-P7-01..05 AgentDefinition 加载（YAML / Markdown / 字段映射 / 文件缺失 / 格式错误）
- UT-P7-06..08 resolve_agent_tools（["*"] / 显式列表 / 黑名单）
- UT-P7-09..11 spawn_subagent fork 后字段：root_id 继承、parent 指向、depth+1
- UT-P7-12 sub-agent system prompt 包含 agent_def.system_prompt
- UT-P7-13 sub-agent 不继承父失败计数器（Pillar 5 同测）
- UT-P7-14 max_depth=3 触发 SubAgentDepthExceeded
- UT-P7-15..17 parallel batch:3 个并发完成 / 1 个失败不影响兄弟 / 0 任务抛错(empty list 校验)
- **UT-P7-19**(v0.3 新增,I5):12 个任务跑 3 批 chunks-of-5(5 + 5 + 2),最终结果列表与输入顺序一致;每批之间 Semaphore 不漏(全局并发 ≤ 10)
- UT-P7-18 sub-agent disable_hooks=True 不调用 post_tool_use hook
- IT-P7-01 peer comparison 端到端：spawn 3 peer_comparator → 收集所有结果 → 主 agent 汇总
- IT-P7-02 sub-agent audit chain 完整：root_id 在所有事件中一致
- IT-P7-03 sub-agent 内的 sub-agent（depth 2）能正常运行

---

## 8. 未决问题

1. **Sub-agent 在 prompt cache 命中策略**——v1 不做 fork 路径，cache 主要靠 system prompt 静态前缀；sub-agent 与主 agent 共享 cache 吗？需要 v0.2 验证
2. **`ToolUseContext.deps` 需要扩展哪些字段供 spawn_subagent_tool 用**——是 deps 字段还是单独 `subagent_context` 字段？F-P7-1
3. **Sub-agent 内部的 cost 累计** 是单独计入 sub-agent state 还是聚合到父 state？v1 决议聚合到父（保留 audit 单视图），v2 evaluate
4. **AgentDefinition heat reload**——开发时改 .md 文件后是否重启？v1 启动时加载一次

---

## 9. 实施计划

### Week 5

- [ ] `subagent/types.py` AgentDefinition
- [ ] `subagent/loader.py` YAML + Markdown
- [ ] `subagent/spawner.py` resolve_agent_tools + spawn_subagent
- [ ] 内置 `agents/peer_comparator.md` + `bear_analyst.md` + `value_analyst.md`
- [ ] UT-P7-01..14

### Week 6

- [ ] `subagent/coordinator.py` run_parallel_subagents
- [ ] `tools/subagent_tools.py` SpawnSubAgentTool + SpawnParallelTool
- [ ] ToolUseContext 扩展 `parent_state` / `subagent_context`
- [ ] Pillar 2 §6 同步：F-P7-1 解
- [ ] UT-P7-15..18
- [ ] IT-P7-01..03

### Week 7

- [ ] 桌面 app 子 agent 可视化（嵌套子卡片）
- [ ] Audit query：`WHERE root_id = ?` 显示整棵 sub-agent 树
- [ ] Pillar 5 `memory_writer_hook` 加 depth 守卫（F-P7-7）

---

## 10. 参考资料

- CC: `src/tools/AgentTool/AgentTool.tsx`、`src/utils/forkedAgent.ts`、`src/services/AgentSummary/`
- homepilot: `engine/agent/spawner.py`、`engine/agent/coordinator.py`
- 前置：mini-ADR-2、Pillar 1 v0.4、Pillar 2 v0.2、Pillar 3 v0.1、Pillar 5 v0.1
- 原始报告：`raw/cc-pillar-7-raw.md`、`raw/homepilot-pillar-7-raw.md`
