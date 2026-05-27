# Raw Research: homepilot Streaming + Event Protocol (Pillar 4)

**来源**: Explore 子 agent 通读 homepilot `server/streaming/sse.py`、`server/api/chat.py`、`server/static/test.html`、`engine/types.py`
**日期**: 2026-05-12

---

## A. 入口

```python
@router.post("/{session_id}/messages")
async def send_message(
    session_id: str,
    request: Request,
    body: SendMessageRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
```

位置：`server/api/chat.py:137-217`，返回 FastAPI `StreamingResponse`，media_type `text/event-stream`。

---

## B. 事件类型清单（9 类）

定义在 `engine/types.py:124-187`：

| 事件 | 字段 | 含义 |
|---|---|---|
| `MessageStartEvent` | type="message_start", model, usage? | 消息开始 |
| `ContentBlockStartEvent` | type, index, content_block | 内容块启动（text 或 tool_use）|
| `ContentBlockDeltaEvent` | type, index, delta | 增量（text_delta 或 input_json_delta）|
| `ContentBlockStopEvent` | type, index | 内容块停止 |
| `MessageDeltaEvent` | type, delta={}, usage? | 消息级增量 |
| `MessageStopEvent` | type, stop_reason | 停止原因 |
| `ToolExecutionStartEvent` | type, tool_use_id, tool_name | 工具开始 |
| `ToolExecutionEndEvent` | type, tool_use_id, tool_name, is_error | 工具结束 |
| `ErrorEvent` | type, error_type, message | 错误 |

Pydantic discriminated union。

---

## C. 帧格式

```python
# server/streaming/sse.py:15-42
def format_sse_event(event: StreamEvent) -> str:
    event_type = event.type
    data = event.model_dump_json()
    return f"event: {event_type}\ndata: {data}\n\n"

def format_sse_done() -> str:
    return "event: done\ndata: {}\n\n"
```

**例**：
```
event: message_start
data: {"type":"message_start","model":"claude-3-5-sonnet-20241022","usage":null}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

event: done
data: {}
```

无 `id:` 字段、无 retry 指令。

---

## D. 前端消费（test.html）

**fetch + ReadableStream**（**不**用 EventSource）：

```javascript
const reader = resp.body.getReader();
const decoder = new TextDecoder();
let buf = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  const lines = buf.split('\n');
  buf = lines.pop() || '';
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    let ev = JSON.parse(line.slice(6));
    // dispatch...
  }
}
```

**事件分发**：
- `content_block_delta` + `delta.type==="text_delta"` → 追加文本
- `tool_execution_start` → 创建 `.agent-tool` 指示器（running）
- `tool_execution_end` → 状态 done / failed
- `message_stop` + `stop_reason==="tool_use"` → 新 turn 分隔符
- `error` → 追加错误信息

工具 UI：左边框样式 + 颜色状态（黄/绿/红）。

---

## E. 错误处理

```python
# server/api/chat.py:192-207
async def event_generator() -> AsyncGenerator[str, None]:
    try:
        async for event in query_loop(...):
            yield format_sse_event(event)
    except Exception:
        logger.exception("Error in query loop for session %s", session_id)
    finally:
        yield format_sse_done()

return StreamingResponse(
    event_generator(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    },
)
```

异常路径：写 log + 仍 yield done。前端断开时 reader 循环自然退出。

---

## F. 与 CC 差异

| 维度 | CC | homepilot |
|---|---|---|
| 协议 | WebSocket + JSON-Lines | 标准 SSE |
| 事件类型 | 23+ | 9 |
| 双向控制 | ✅（权限请求、中断）| ❌（单向）|
| 文本快照 | full-so-far snapshot | 纯 delta |
| `id` 字段 | uuid + session_id | 无 |
| 缓冲 | 100ms text_delta 合并 | 无 |
| 前端 | 自定义 ccrClient | fetch + ReadableStream |

---

## G. 未理解的部分

1. 工具结果展示——`showToolEnd()` 只更新状态不显示结果
2. 长会话内存泄漏（toolEls 字典）
3. usage 累计：MessageStartEvent / MessageDeltaEvent 何时填充

---

## 总结

标准 SSE（FastAPI `StreamingResponse` + Pydantic Discriminated Union）。9 类型够覆盖核心场景。前端用 ReadableStream 而非 EventSource（自定义 header / auth 友好）。整体凝聚，43 行 SSE 序列化代码。
