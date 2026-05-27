# Pillar 4: 流式 SSE + 事件协议 — 研究与 FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.1 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | 调研 + 综合 + 自审一轮 |
| **前置** | Pillar 1 v0.4（query_loop yield 类型）、Pillar 2 v0.2（UIAction、ToolExecutionEvent）|
| **原始报告** | `raw/cc-pillar-4-raw.md`、`raw/homepilot-pillar-4-raw.md` |

---

## 0. TL;DR

- **CC**：WebSocket + JSON-Lines，23+ 消息类型，双向（权限请求 / 中断），text_delta 100ms 缓冲 + full-so-far snapshot
- **homepilot**：标准 SSE，9 事件类型，单向，fetch + ReadableStream 前端
- **FinRobot v1**：**标准 SSE**（不上 WebSocket）+ **12 事件类型**（homepilot 9 + UIActionEvent + ToolProgressEvent + 显式 done）+ AuditEvent 在端点侧分流（不发客户端）+ ReadableStream 前端
- **关键决策**：v1 不做双向（权限请求 / 中断）——这两个能力对应"全 allow + max_turns 卡"的 v1 设计是冗余的

---

## 1. Pillar 4 的位置

Pillar 4 决定 `query_loop` yield 的事件**怎么序列化、怎么传输、客户端怎么消费**。所有 pillar 的"事件流"概念在此落地为具体协议。

与其他 pillar 的联结：
- **Pillar 1** 决定 query_loop 产出 `StreamEvent | AuditEvent` 联合流
- **Pillar 2** 引入 `UIActionEvent`（已合入 Pillar 1 v0.4）
- **Pillar 8** 的 hooks 不直接产出事件——hook 副作用通过 AuditEvent 间接体现

---

## 2. 调研结论摘要

### 2.1 CC（详见 `raw/cc-pillar-4-raw.md`）

- 传输：**WebSocket**（不是 SSE！）
- 编码：JSON-Lines（每行一条 JSON，`\n` 分隔）
- 双向：业务消息 + control_request/response 共用 WS
- 23+ 消息类型，含 hook 生命周期、task 后台、auth、rate limit 等
- 文本增量：100ms 缓冲 + **full-so-far 快照**（重连客户端不丢内容）

### 2.2 homepilot（详见 `raw/homepilot-pillar-4-raw.md`）

- 传输：**标准 SSE**（`event: <name>\ndata: <json>\n\n`）
- 9 事件类型，Pydantic discriminated union
- 单向（无控制层）
- 前端：fetch + ReadableStream（不用 EventSource）
- 无 `id` / retry 字段、无缓冲

---

## 3. CC vs homepilot vs FinRobot 决策对照

| 维度 | CC | homepilot | **FinRobot 决策** | 理由 |
|---|---|---|---|---|
| 传输协议 | WebSocket | SSE | **SSE** | v1 无双向需求；SSE 更易调试 / 代理友好 / 浏览器原生支持 |
| 编码 | JSON-Lines | 标准 SSE 格式 | **标准 SSE** | `event:` + `data:` + `\n\n` 终止 |
| 双向控制 | ✅ | ❌ | **❌ v1 不做** | 权限全 allow，无 interrupt 需求；v2 上 WS |
| 事件类型数 | 23+ | 9 | **12** | homepilot 9 + UIActionEvent + ToolProgressEvent + DoneEvent |
| `id` 字段 | uuid + session_id | 无 | **uuid 字段（事件载荷内）** | 客户端去重；不用 SSE `id:` 协议字段（避开 EventSource 默认重连）|
| 文本缓冲 | 100ms full-so-far | 无 | **v1 直接 yield，v2 评估 full-so-far** | 简化；如果用户报告闪烁再加 |
| 前端 | ccrClient WS | fetch + ReadableStream | **fetch + ReadableStream** | 与 homepilot 一致；FastAPI 标准 |
| AuditEvent 转发 | 通过 hooks 间接 | 不分流 | **端点侧 isinstance 分流，AuditEvent 异步写 audit store** | 核心差异化 |
| 错误事件 | error 字段 + result 类型 | ErrorEvent | **ErrorEvent + DoneEvent 包裹**（成对出现）| 客户端能区分"完成 vs 中途断开" |
| 进度事件 | SDKToolProgressMessage | 无 | **ToolProgressEvent**（Pillar 2 § "on_progress 未决议"延迟实施前，先占位 schema）| 长 pipeline 体验 |
| 重连机制 | session_id resume | 无 | **v1 无；v2 加 session_id resume + 自上次 turn 续 stream** | 桌面 app 网络断了重连场景 |

---

## 4. FinRobot 实现规格

### 4.1 模块结构

```
finrobot/conversation/streaming/      # 全部新增
├─ __init__.py
├─ sse.py                              # format_sse_event / format_sse_done
├─ endpoint.py                         # /api/chat/sessions/{id}/messages SSE 端点
└─ events.py                           # 12 个 StreamEvent 子类型
```

### 4.2 事件类型清单（12 个）

```python
# finrobot/conversation/streaming/events.py

from dataclasses import dataclass
from typing import Any, Literal


# ─── 模型流原始事件（来自 ModelAdapter） ───

@dataclass
class MessageStartEvent:
    type: Literal["message_start"] = "message_start"
    model: str = ""
    usage: "TokenUsage | None" = None


@dataclass
class ContentBlockStartEvent:
    type: Literal["content_block_start"] = "content_block_start"
    index: int = 0
    content_block: dict[str, Any] = None  # {"type": "text"} or {"type": "tool_use", ...}


@dataclass
class ContentBlockDeltaEvent:
    type: Literal["content_block_delta"] = "content_block_delta"
    index: int = 0
    delta: dict[str, Any] = None  # {"type": "text_delta", "text": "..."} 或 input_json_delta


@dataclass
class ContentBlockStopEvent:
    type: Literal["content_block_stop"] = "content_block_stop"
    index: int = 0


@dataclass
class MessageDeltaEvent:
    type: Literal["message_delta"] = "message_delta"
    delta: dict[str, Any] = None
    usage: "TokenUsage | None" = None


@dataclass
class MessageStopEvent:
    type: Literal["message_stop"] = "message_stop"
    stop_reason: str = ""
    raw_provider_reason: str | None = None  # 来自 Pillar 1 §4.11 ModelAdapter 契约


# ─── 工具执行事件（来自 query_loop._handle_tool_use） ───

@dataclass
class ToolExecutionStartEvent:
    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_use_id: str = ""
    tool_name: str = ""


@dataclass
class ToolExecutionEndEvent:
    type: Literal["tool_execution_end"] = "tool_execution_end"
    tool_use_id: str = ""
    tool_name: str = ""
    is_error: bool = False
    summary: str = ""  # to_text() 前 200 字符
    duration_ms: int = 0


@dataclass
class ToolProgressEvent:
    """v1 schema 占位；实际触发时机待 Pillar 1 v0.x on_progress 决议。"""
    type: Literal["tool_progress"] = "tool_progress"
    tool_use_id: str = ""
    stage: str = ""
    elapsed_ms: int = 0
    extra: dict[str, Any] | None = None


# ─── 桌面 app UI 渲染（来自 Pillar 2） ───

@dataclass
class UIActionEvent:
    type: Literal["ui_action"] = "ui_action"
    tool_use_id: str = ""
    action: dict[str, Any] = None  # UIAction.payload


# ─── 错误与终止 ───

@dataclass
class ErrorEvent:
    type: Literal["error"] = "error"
    error_type: str = ""
    message: str = ""
    retryable: bool = False


@dataclass
class DoneEvent:
    type: Literal["done"] = "done"
    terminate_reason: str = ""  # "end_turn" / "max_turns" / "circuit_breaker" / ...
    final_usage: "TokenUsage | None" = None


StreamEvent = (
    MessageStartEvent | ContentBlockStartEvent | ContentBlockDeltaEvent
    | ContentBlockStopEvent | MessageDeltaEvent | MessageStopEvent
    | ToolExecutionStartEvent | ToolExecutionEndEvent | ToolProgressEvent
    | UIActionEvent | ErrorEvent | DoneEvent
)
```

### 4.3 SSE 序列化

```python
# finrobot/conversation/streaming/sse.py

import json
from dataclasses import asdict
from typing import Any


def format_sse_event(event: StreamEvent) -> str:
    """把 StreamEvent dataclass 序列化为 SSE 帧。"""
    event_type = event.type
    data = json.dumps(asdict(event), ensure_ascii=False, default=_json_default)
    return f"event: {event_type}\ndata: {data}\n\n"


def format_sse_done(terminate_reason: str, final_usage: Any = None) -> str:
    done_data = {"type": "done", "terminate_reason": terminate_reason}
    if final_usage:
        done_data["final_usage"] = asdict(final_usage)
    return f"event: done\ndata: {json.dumps(done_data, ensure_ascii=False)}\n\n"


def _json_default(o: Any) -> Any:
    """处理非默认 JSON 可序列化对象（datetime / Pydantic 等）。"""
    if hasattr(o, "model_dump"):  # Pydantic v2
        return o.model_dump()
    if hasattr(o, "isoformat"):  # datetime
        return o.isoformat()
    return str(o)
```

### 4.4 SSE 端点

```python
# finrobot/conversation/streaming/endpoint.py

from collections.abc import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    engine = Depends(get_engine),
) -> StreamingResponse:

    session = await engine.session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not your session")

    # 拼装 system prompt（Pillar 3）
    profile = await engine.profile_store.get(current_user["fund_id"])
    assembled = build_system_prompt(profile, language=body.language or "zh",
                                     memory_store=engine.memory_store,
                                     user_id=current_user["id"])

    config = QueryConfig(
        model=session.model,
        system_prompt=assembled.text,
        # 透传 caching 元信息给 PydanticAIAdapter
        _static_prefix_length=assembled.static_prefix_length,
        max_turns=engine.config.max_turns,
        language=body.language or "zh",
    )

    # 加入用户消息
    session.state.messages.append(UserMessage(content=body.content))

    async def event_generator() -> AsyncGenerator[str, None]:
        terminate_reason = "unknown"
        final_usage = None
        try:
            async for event in query_loop(
                state=session.state,
                config=config,
                model_adapter=engine.model_adapter,
                tool_orchestrator=engine.tool_orchestrator,
                tool_registry=engine.tool_registry,
                hook_registry=engine.hook_registry,
            ):
                # 关键：在端点侧分流——AuditEvent 走 audit store，不发客户端
                if isinstance(event, AuditEvent):
                    await engine.audit_store.write(event)
                    if event.type == "loop_terminate":
                        terminate_reason = event.payload.get("reason", "unknown")
                    continue

                # StreamEvent 转 SSE 帧
                yield format_sse_event(event)

                # 检查 cancellation（客户端断开后 starlette 会通知）
                # FastAPI / starlette 在 await yield 时检测客户端断开

            final_usage = session.state.total_usage

        except Exception as exc:
            logger.exception("Error in query loop for session %s", session_id)
            yield format_sse_event(ErrorEvent(
                error_type=type(exc).__name__,
                message=str(exc),
            ))
            terminate_reason = "exception"
        finally:
            yield format_sse_done(terminate_reason, final_usage)
            await engine.session_store.save(session)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 防止 nginx 缓冲
        },
    )
```

### 4.5 前端消费（参考实现）

```javascript
// finrobot/desktop/src/api/chat-stream.js (or equivalent)

async function sendMessage(sessionId, content, onEvent) {
  const resp = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${getToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // SSE 帧以 \n\n 分隔
    const frames = buf.split('\n\n');
    buf = frames.pop() || '';  // 不完整的帧留到下次

    for (const frame of frames) {
      const lines = frame.split('\n');
      let eventType = '';
      let dataStr = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) eventType = line.slice(7);
        else if (line.startsWith('data: ')) dataStr = line.slice(6);
      }
      if (!dataStr) continue;

      try {
        const event = JSON.parse(dataStr);
        event._event_type = eventType;  // 冗余但方便
        onEvent(event);
      } catch (e) {
        console.error('SSE parse error', e, dataStr);
      }
    }
  }
}
```

事件分发（桌面 app 业务层）：

```js
function handleEvent(event) {
  switch (event.type) {
    case 'content_block_delta':
      if (event.delta.type === 'text_delta')
        appendToCurrentMessage(event.delta.text);
      break;
    case 'tool_execution_start':
      showToolIndicator(event.tool_use_id, event.tool_name, 'running');
      break;
    case 'tool_execution_end':
      updateToolIndicator(event.tool_use_id, event.is_error ? 'failed' : 'done');
      break;
    case 'ui_action':
      // Pillar 2 渲染指令分发
      dispatchUIAction(event.action);
      break;
    case 'error':
      showError(event.message);
      break;
    case 'done':
      finalize(event.terminate_reason, event.final_usage);
      break;
  }
}
```

### 4.6 与 Pillar 1 / Pillar 2 的对接

| 上游 yield | 下游处理 |
|---|---|
| `MessageStartEvent` ~ `MessageStopEvent`（来自 model_adapter） | 透传到 SSE |
| `ToolExecutionStartEvent` / `EndEvent`（来自 _handle_tool_use） | 透传 |
| `UIActionEvent`（来自 _handle_tool_use yield result.ui_actions） | 透传 |
| `ErrorEvent` | 透传 |
| `AuditEvent` | **端点侧拦截**：写 audit store，不发客户端 |

---

## 5. v1 推迟功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| WebSocket 升级 | v1 无双向需求（无 interrupt / 权限对话） | v2 评估 |
| 文本 full-so-far snapshot 缓冲 | v1 直接 yield，简化；若用户报告闪烁再加 | v2 评估 |
| Session resume / reconnect | 需要 session_id + last_event_id 追踪 + 状态持久化 | v2 评估 |
| Backpressure 应用层流控 | FastAPI / uvicorn 已处理 TCP 层；应用层暂无需要 | v2 评估 |
| Compact boundary 事件 | Pillar 5 决定是否暴露给客户端 | Pillar 5 联调 |
| Hook lifecycle 事件 | hooks v1 是 in-process noop，不需要客户端可见 | Pillar 8 v2 |
| Auth / rate_limit 状态事件 | 端点层用 HTTP status 处理足够 | v2 评估 |
| Streamlined 输出模式 | CC 简化客户端模式，FinRobot 不需要 | 不实施 |
| Post-turn summary | Pillar 7 sub-agent 决定 | Pillar 7 |

---

## 6. 自审 5 处

| ID | 严重度 | 问题 | 修复方向 |
|---|---|---|---|
| F-P4-1 | 🟠 | `format_sse_event` 用 `asdict(event)` 把 dataclass 转 dict，但 `TokenUsage` 等嵌套对象需要自定义序列化逻辑——`asdict` 对 Pydantic / datetime 无效 | v0.2: 用 `dataclasses.asdict(event, dict_factory=...)` + 自定义 factory，或者改用 Pydantic dataclass 全程 |
| F-P4-2 | 🟠 | 端点侧 `if isinstance(event, AuditEvent): ... continue` 是黑盒过滤——如果将来 query_loop yield 新类型（如 RegisterToolEvent），端点不知道该不该发 | v0.2: 显式 `StreamEvent` union 类型 + `isinstance(event, get_args(StreamEvent))` 检查，未知类型走 audit / 丢弃路径 |
| F-P4-3 | 🟡 | `_json_default` 对 Pydantic v2 用 `model_dump()`，但如果 model 还没初始化（lazy validation）会出错 | v0.2: 加 try/except 包装 |
| F-P4-4 | 🟡 | `cancellation` 处理依赖 starlette 内部行为——客户端断开时 `query_loop.aclose()` 是否被调用？需要验证 | v0.2: 显式 `async with AsyncGeneratorContextManager(query_loop(...)) as gen` 模式 + IT 测试客户端断开行为 |
| F-P4-5 | 🟡 | `DoneEvent.terminate_reason` 默认值是 "unknown"——意味着代码路径有缺漏时客户端看到 unknown 而非具体原因 | v0.2: 改为必填 + endpoint 在所有路径明确设置 |

---

## 7. 测试要点

- UT-P4-01..09：9 个事件类型各能序列化为正确 SSE 帧（event 名 + data JSON）
- UT-P4-10：AuditEvent 不出现在 SSE 流，而是写入 audit store
- UT-P4-11：UIActionEvent 透传
- UT-P4-12：异常时 DoneEvent 仍 yield（finally 路径）
- UT-P4-13：客户端断开时 query_loop.aclose() 被触发（cancellation 传播）
- IT-P4-01：端到端真实对话——5 轮 + 工具 + UIAction，前端能完整接收
- IT-P4-02：大消息（200 行）实时显示，无卡顿
- IT-P4-03：错误注入——验证 ErrorEvent + DoneEvent 成对出现

---

## 8. 未决问题

1. **`TokenUsage` 跨 pillar 序列化标准**——目前各 pillar 用不同表示，需统一（建议 Pydantic model + `model_dump_json()`）
2. **`session_id` 是否进每个事件**——客户端单一会话场景不需要；多会话场景需要。v1 不加（节省字节）
3. **是否给每个事件加 timestamp**——audit 已经有，stream 重复增加体积。v1 不加

---

## 9. 实施计划

### Week 3

- [ ] `streaming/events.py`：12 个事件 dataclass
- [ ] `streaming/sse.py`：序列化函数
- [ ] `streaming/endpoint.py`：SSE 路由 + AuditEvent 分流
- [ ] UT-P4-01..13
- [ ] IT-P4-01..03

### Week 4

- [ ] 桌面 app 前端事件处理器（chat-stream.js）
- [ ] UIAction 分发桥接到 canvas（与 Pillar 2 联动）
- [ ] Cancellation 路径 IT 测试

---

## 10. 参考资料

- CC: `src/server/directConnectManager.ts`、`src/entrypoints/sdk/coreSchemas.ts`
- homepilot: `server/streaming/sse.py`、`server/api/chat.py`
- 前置：Pillar 1 v0.4 §4.12.1 StreamEvent union、Pillar 2 v0.2 UIAction
- 原始报告：`raw/cc-pillar-4-raw.md`、`raw/homepilot-pillar-4-raw.md`
