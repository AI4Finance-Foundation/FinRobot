# Raw Research: CC Streaming + Event Protocol (Pillar 4)

**来源**: Explore 子 agent 通读 CC `src/server/`、`src/entrypoints/sdk/coreSchemas.ts`、`src/cli/transports/ccrClient.ts`、`src/query.ts`
**日期**: 2026-05-12

> 子 agent 原始研究笔记，未经编辑。

---

## A. 入口

**WebSocket + JSON-Lines（不是纯 SSE）**：
- 位置：`src/server/directConnectManager.ts:40-213`
- `DirectConnectSessionManager.connect()` 建立 WS
- `onMessage` 回调处理流出事件，每行一条 JSON 消息（`\n` 分隔）
- 双向：业务消息 + control_request/response 共用同一 WS

**返回类型**：
```
StdoutMessage = SDKMessage | SDKStreamlinedTextMessage | SDKStreamlinedToolUseSummaryMessage
              | SDKPostTurnSummaryMessage | SDKControlResponse | SDKControlRequest
              | SDKControlCancelRequest | SDKKeepAliveMessage
```

**启动 / 中止 / 取消**：
- 启动：`sendMessage(SDKUserMessage)`
- 中止：`sendInterrupt()` → `control_request: { subtype: 'interrupt' }`
- 取消：`sendErrorResponse(requestId, error)` → `control_response: { subtype: 'error' }`
- 断线：`ws.close()` → `callbacks.onDisconnected()`

---

## B. 事件类型清单（23+ 类型）

从 `coreSchemas.ts:1854-1881` 的 SDKMessageSchema：

| 类型 | 用途 |
|---|---|
| `SDKAssistantMessage` | 完整 API 响应 |
| `SDKUserMessage` | 用户输入或合成消息 |
| `SDKPartialAssistantMessage` (type='stream_event') | 原始 API 流事件 |
| `SDKToolUseSummaryMessage` | 工具累计摘要 |
| `SDKResultMessage` (subtype='success'/'error_*') | query() 最终结果 |
| `SDKSystemMessage` (subtype='init') | 会话初始化 |
| `SDKCompactBoundaryMessage` | 上下文压缩标记 |
| `SDKStatusMessage` | 会话状态（'compacting' 等） |
| `SDKAPIRetryMessage` | API 重试事件 |
| `SDKLocalCommandOutputMessage` | 本地命令输出 |
| `SDKHookStartedMessage` / `SDKHookProgressMessage` / `SDKHookResponseMessage` | Hook 生命周期 |
| `SDKToolProgressMessage` | 工具进度（elapsed_time_seconds） |
| `SDKAuthStatusMessage` | 认证状态 |
| `SDKTaskStartedMessage` / `SDKTaskProgressMessage` / `SDKTaskNotificationMessage` | 后台任务 |
| `SDKSessionStateChangedMessage` | 会话全局状态 |
| `SDKFilesPersistedEventSchema` | 文件上传完成 |
| `SDKRateLimitEventSchema` | 速率限制 |
| `SDKElicitationCompleteMessage` | MCP 用户输入完成 |
| `SDKPromptSuggestionMessage` | 下轮预测提示 |
| `SDKStreamlinedTextMessage` / `SDKStreamlinedToolUseSummaryMessage` | 简化输出 |
| `SDKPostTurnSummaryMessage` | 转轮摘要 |

---

## C. 帧格式

**JSON-Lines（每行一个 JSON）**：

```
{"type":"stream_event","event":{...},"uuid":"...","session_id":"...","parent_tool_use_id":null}
{"type":"assistant","message":{...},"uuid":"...","session_id":"..."}
```

**关键字段**：
- `type`：消息类型（一级字段，不是 SSE event）
- `uuid`：幂等去重 ID
- `session_id`：会话标识
- `parent_tool_use_id`：工具调用链关联
- **无** SSE `id` / `retry`

**文本增量合并** (`ccrClient.ts:141-203`)：
- text_delta 累积至同一 content_block
- 每 flush（~100ms 间隔）排出 **full-so-far 文本快照**（非增量）
- 重连客户端收到自包含快照

---

## D. 客户端订阅

```js
ws.addEventListener('message', event => {
  const lines = data.split('\n').filter(l => l.trim())
  for (const line of lines) {
    const parsed = jsonParse(line)
    if (parsed.type === 'control_request') {
      callbacks.onPermissionRequest(parsed.request, parsed.request_id)
    } else {
      callbacks.onMessage(parsed)
    }
  }
})
```

**重连**：WS 无内置，客户端实现指数退避 + session_id 保持，`--resume <session_id>` 恢复。

---

## E. 工具执行子协议

1. **工具开始**：`SDKAssistantMessage` 包含 `ToolUseBlock[]`
2. **工具执行中**（可选）：`SDKToolProgressMessage { tool_use_id, elapsed_time_seconds, ... }`
3. **工具完成**：
   - 摘要：`SDKToolUseSummaryMessage { summary, preceding_tool_use_ids }`
   - 紧跟工具结果消息后

**摘要生成**（`query.ts:54, 1058`）：`createToolUseSummaryMessage()`，由 Haiku 异步生成。

---

## F. 背压 / 缓冲

**CC 内部**（`ccrClient.ts:275-284`）：
```typescript
private streamEventBuffer: SDKPartialAssistantMessage[] = []
private streamEventTimer: ReturnType<typeof setTimeout> | null = null
```

- text_delta 合并 100ms 内多个 delta
- 每个 flush 排出 full-so-far 文本快照
- 触发：缓冲满 / 定时器 / message_stop / error

**客户端端**：WS TCP 缓冲区天然背压。

---

## G. 关键代码定位

| 功能 | 文件:行 |
|---|---|
| WS 入口 | `src/server/directConnectManager.ts:50-123` |
| 事件类型定义 | `src/entrypoints/sdk/coreSchemas.ts:1256-1881` |
| 消息序列化 | `src/cli/transports/ccrClient.ts:141-203` |
| 控制协议 | `src/entrypoints/sdk/controlSchemas.ts:552-620` |
| query loop yield | `src/query.ts:230, 337, 643, 824, 1021, 1150, 1386` |

---

## H. 未理解的部分

1. 内部 Message 类型定义位置（`types/message.js` 在仓库不存在）
2. Post-Turn Summary 生成的具体路径
3. Streamlined 模式激活条件
4. 为何 WS 而非 EventSource：答案是需要双向控制（权限请求、中断）

---

## 总结

CC 用 **WebSocket + JSON-Lines** 传输，23+ 类型，双向通道支持权限请求和中断。**文本增量 full-so-far 快照**让中途重连客户端获得完整上下文。
