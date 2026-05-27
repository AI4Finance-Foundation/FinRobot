# Raw Research: homepilot Sub-agent (Pillar 7)

**来源**: Explore 子 agent 通读 homepilot `engine/agent/spawner.py`、`engine/agent/coordinator.py`
**日期**: 2026-05-12

---

## A. spawn_agent 签名

`engine/agent/spawner.py:65-74`:

```python
async def spawn_agent(
    agent_def: AgentDefinition,
    prompt: str,
    parent_registry: ToolRegistry,
    model_adapter: "ModelAdapter",
    orchestrator: "ToolOrchestrator",
    parent_model: str,
    session_id: str,
    user_id: str,
) -> AsyncGenerator[StreamEvent, None]:
```

输出：异步生成器，逐个产生 StreamEvent。

---

## B. AgentDefinition

`engine/agent/types.py:16-35`:

```python
@dataclass
class AgentDefinition:
    agent_type: str
    system_prompt: str
    tools: list[str] = field(default_factory=lambda: ["*"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    max_turns: int | None = None
    description: str = ""
```

加载：YAML frontmatter + Markdown 正文（`engine/agent/loader.py:28-90`）。

字段映射：`name → agent_type`, `disallowed-tools → disallowed_tools`

装载：`bootstrap_engine()` 从 `agents/` 目录读取。

---

## C. Context 隔离

**父消息不传**：子 agent 全新 QueryState，初始 `[UserMessage(content=prompt)]`

**ToolUseContext**: 每次工具执行时在 query_loop 内新建。

**工具集** (`resolve_agent_tools` spawner.py:33-62):
- `tools=["*"]`: 从父 registry 复制全部，去掉 disallowed
- `tools=["foo","bar"]`: 仅明确列出的
- 返回独立 ToolRegistry，父不受影响

---

## D. 执行

**主 agent → spawn_agent** 路径：
- 通过 Coordinator (`coordinator.py:run_coordinator()` / `_run_worker()`)
- WorkerTask 包装 `(agent_def, prompt)`
- `asyncio.gather()` 并发多个 worker

**消息状态隔离**：每个 spawn_agent 独占 QueryState。

---

## E. 结果回收

**流式回传**: spawn_agent 是 AsyncGenerator，caller 收集所有 events 到 `WorkerResult.events: list[StreamEvent]`

**失败**: `_run_worker` try-except，失败返 `WorkerResult(events=[partial], error=str(exc))`。asyncio.gather 不取消其他 worker。

---

## F. 关键代码

| 功能 | 位置 |
|---|---|
| spawn_agent | `engine/agent/spawner.py:65-108` |
| resolve_agent_tools | `engine/agent/spawner.py:33-62` |
| run_coordinator | `engine/agent/coordinator.py:99-130` |
| _run_worker | `engine/agent/coordinator.py:61-96` |
| AgentDefinition | `engine/agent/types.py:16-35` |
| load_agent_from_text | `engine/agent/loader.py:28-90` |

---

## G. 与 CC 差异

| 维度 | CC | homepilot |
|---|---|---|
| 执行路径 | 4 种（fork/async/sync/teammate） | 1 种（sync） |
| 定义加载 | 装饰器 + 目录 | YAML + Markdown |
| 父消息传递 | Fork 路径传 | 不传 |
| Compact / Memory | 集成 | 占位 |

---

## H. 未理解

1. orchestrator 参数冗余（spawner.py:70）— 传入立即被替换为新建
2. 工具内调用 spawn_agent 的模式未见示例
3. Hook registry 不传给 sub-agent
4. Memory store 隔离
