# RENDER-DESIGN-NOTES — FinRobot 对话渲染设计笔记

> **目的**：把"对话渲染"这一层的设计标准沉淀为长期资产。本次重构的 Phase 1–6 都按本文执行；后续新增的对话相关组件也以本文为参照。
>
> **方法**：读 `vercel/ai-chatbot` (20.3k⭐, Vercel 官方 AI SDK 参考实现) 的源码 + 读 `cc-haha` (4.2k⭐, Claude Code 反编译) 的架构图 + 提炼可借鉴模式。
>
> **日期**：2026-05-14。基于 `@ai-sdk/react ^3.0.182` + `ai` v5 idiom (`DefaultChatTransport` / `UIMessage` / `isToolUIPart`)。

---

## 0. 边界与法务护栏 (硬约束，禁触)

### 0.1 cc-haha 是 leak-based，**只学不抄**

`/Users/zhunihaoyun/Desktop/code/cc-haha` 的 LICENSE 明确禁止：商业使用、再发布、竞争性使用。本文引用 cc-haha 时**禁止 cp 任何源代码**——包括 `.tsx`、`.ts`、`.rs`、`.py`。

合规做法：
- 读 `docs/images/0[1-8]-*.png` 8 张架构图，**提炼设计原则**而不是图像本身
- 读 `src/components/`、`src/tools/` 的**组织方式**，不抄具体实现
- 任何"借鉴"必须在 FinRobot 仓库下用我们自己的语言重写

参见仓库内已存在的 [docs/cc-haha-borrowables.md](cc-haha-borrowables.md) 第 1 节"License 兼容性"结论，本文沿用。

### 0.2 vercel/ai-chatbot 是 Next.js RSC 模板，**不是 SPA**

部分文件用了 RSC / Server Actions / SWR，**我们的 Vite + Tauri SPA 不能直接照搬**。每段引用都标注 ✓/⚠️/✗ 三档(见 §11)。

### 0.3 本文不引入 Artifact 实现

Phase 1 强约束："不要做半成品 artifact canvas"。本文 §6 仅记录设计模式作为 P3+ 候选，不在本次 6 阶段范围内实现。

---

## 1. 组件分层与拆分原则 (从 vercel/ai-chatbot 学到的)

Vercel 的分层是**两级原语 + 一级业务**：

```
components/
├── ai-elements/        # 第 1 级：unstyled 原语，可在多个项目复用
│   ├── code-block.tsx       (shiki + cache + 异步高亮 subscriber)
│   ├── conversation.tsx     (StickToBottom 滚动锁)
│   ├── message.tsx          (基础消息容器)
│   ├── reasoning.tsx        (流式 reasoning，使用 Streamdown)
│   ├── tool.tsx             (Tool 调用 7 状态机)
│   ├── prompt-input.tsx     (输入框 + 附件)
│   └── ...
└── chat/               # 第 2 级：业务消费层，依赖第 1 级
    ├── messages.tsx         (用 ai-elements 拼成消息列表)
    ├── message.tsx          (PreviewMessage：组合 message-actions + reasoning + tool)
    ├── message-actions.tsx  (复制 / 编辑 / 投票)
    ├── message-editor.tsx   (用户消息编辑 submit handler)
    ├── multimodal-input.tsx (业务输入区，含模型选择 / 附件)
    ├── diffview.tsx         (用 ProseMirror 渲染 diff)
    └── artifact.tsx         (Artifact canvas)
```

**核心设计决策**：

| 决策 | 为什么 |
|---|---|
| **两层原语 + 业务** | ai-elements 不知道"FinRobot"，可作为通用 chat UI 在任何 React 项目使用；业务层(chat/)做 fund_id/ticker/Pipeline 这些 FinRobot 私货 |
| **每个文件单一职责** | `message-actions.tsx` 只管 hover toolbar；`message-editor.tsx` 只管编辑 submit 逻辑；不在 `message.tsx` 里塞一切 |
| **memo 加自定义比较** | `message-actions.tsx` 用 `memo(..., (prev, next) => prev.vote === next.vote && prev.isLoading === next.isLoading)`——只比关心的 prop，不让 SWR 异步刷新触发整条消息 re-render |
| **状态 hook 化** | `useMessages()` 返回 `{ containerRef, endRef, isAtBottom, scrollToBottom, hasSentMessage, reset }`，组件只是消费者 |

**FinRobot 适用版**：

```
ui/src/components/chat/
├── primitives/             # 第 1 级：unstyled，套 finrobot.html 暗色 token
│   ├── Markdown.tsx
│   ├── CodeBlock.tsx
│   ├── Conversation.tsx    (滚动锁)
│   ├── MessagePrimitive.tsx
│   ├── ToolPrimitive.tsx
│   └── Reasoning.tsx
├── toolRenderers/          # 第 2 级：每个 toolName 一个组件
│   ├── index.ts            (注册表 + getToolRenderer)
│   ├── GenericTool.tsx     (fallback)
│   ├── ReadFileTool.tsx
│   ├── BashTool.tsx
│   ├── WriteFileTool.tsx
│   ├── WebSearchTool.tsx
│   ├── GrepTool.tsx
│   ├── TodoWriteTool.tsx
│   └── PipelineTool.tsx    (FinRobot 专属)
└── (业务层落在 layout/RightChatPanel.tsx 内部)
   - MessageList / MessageBubble / AssistantContent
   - 调用 primitives + toolRenderers
   - 管 fund_id / ticker / MODE 切换的私货
```

---

## 2. Markdown 渲染最佳实践

### 2.1 Vercel 用什么

`components/ai-elements/reasoning.tsx` **使用 Streamdown 而不是直接用 react-markdown**：

> "Uses Streamdown library for rendering with plugins supporting code, math, mermaid diagrams, and CJK characters"

**Streamdown** ([github.com/vercel/streamdown](https://github.com/vercel/streamdown), 5.2k⭐) 关键事实：
- **drop-in 替换 react-markdown**(API 兼容)
- **专为 AI streaming 设计**：通过 `remend` 优雅处理未闭合块(unterminated code fences / unclosed tables / unclosed `$$`)
- 内置 GFM(表格/任务列表/删除线)、KaTeX、Mermaid、CJK
- 用 shiki 做代码高亮 + 缓存
- 用 `rehype-harden` 做安全清洗

**这是我们 Phase 1 的关键发现**：相比"手装 react-markdown + remark-gfm + remark-math + rehype-katex + rehype-sanitize"五包栈，**Streamdown 一个包覆盖 90% 需求**且专门解决了我们 Phase 1 担心的"流式中未闭合块闪烁"问题。

### 2.2 决策点：Streamdown vs 手装栈

| | Streamdown | 手装栈 |
|---|---|---|
| 包数 | 1(`streamdown`) | 5(`react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex` + `rehype-sanitize`) |
| 流式未闭合块 | **内建 remend** | 自己处理 |
| 代码高亮 | shiki(内建) | 自接 |
| 数学 | KaTeX(内建，按需) | 自接 rehype-katex |
| Mermaid | 内建插件 | 自接 |
| 安全清洗 | rehype-harden | rehype-sanitize |
| 主题 | shadcn CSS var | 自配 |
| **可控性** | 中(它给你 reasonable defaults) | 高(你完全控制 plugin chain) |
| **学习成本** | 低 | 中 |

**结论**(留 Phase 1 决策)：先 POC 装 Streamdown，跑 demo route 喂 5 种内容；如果它的主题/插件钩子不够 finrobot.html 暗色对齐，回落手装栈。**手装栈作为 fallback 永远在，不会被堵死**。

### 2.3 通用最佳实践 (两种栈都适用)

- **不要 rehype-raw**：LLM 输出的裸 HTML 当文本显示，不渲染，攻击面更小
- **memo 边界 = source string**：用 `useMemo(() => parseMarkdown(text), [text])`，文本不变就不重 parse
- **代码块拆出独立组件**：Markdown 解析出来 `<code>` 节点交给独立 `<CodeBlock>` 而不是内联渲染——避免 markdown 重 parse 时高亮也重跑
- **块级 vs 行内 code**：用 `inline` prop 区分；行内不走 shiki(浪费)
- **数学公式 lazy load**：检测 `$` 才动态 import KaTeX

---

## 3. 代码块组件的完整形态

### 3.1 Vercel 的 CodeBlock 设计 (`components/ai-elements/code-block.tsx`)

组件分解：

```
CodeBlock              ← 入口，props { code, language, showLineNumbers }
  └── CodeBlockContainer        (overflow + content-visibility)
        ├── CodeBlockHeader     (可选 header bar)
        │     ├── CodeBlockTitle
        │     ├── CodeBlockFilename
        │     └── CodeBlockActions
        │           ├── CodeBlockCopyButton
        │           └── CodeBlockLanguageSelector
        └── CodeBlockContent    (高亮逻辑 + 缓存)
              └── CodeBlockBody (memoized <pre><code> 渲染)
```

### 3.2 关键设计决策

| 模式 | 为什么 |
|---|---|
| **异步高亮 + subscriber 模式** | 先渲染原始 token(纯文本)，shiki 后台加载后通过 subscriber 通知重新渲染。**流式过程中不阻塞**。 |
| **双层缓存** | highlighter level(每个 language 一个 highlighter 实例缓存) + token level(相同 code+language 命中后不重新高亮) |
| **bitwise 检测样式** | shiki 的 fontStyle 是位掩码，`& 1` italic / `& 2` bold / `& 4` underline。不要 if-else 三次 |
| **CSS counter 行号** | `counter-reset: line; ... counter-increment: line; content: counter(line);`——不在 React 树里塞索引 key，避免重渲染 |
| **content-visibility** | `content-visibility: auto;` 让浏览器对屏幕外的代码块跳过 paint，长聊天滚动流畅 |
| **copy 按钮带视觉反馈** | 点击后图标变 ✓ 1.5s，给确认信号 |

### 3.3 FinRobot 适用版

```tsx
// 概念草稿，不是最终代码
<CodeBlock
  code={code}
  language="python"
  filename="dcf.py"          // 可选，从 markdown ```python:dcf.py 的扩展语法解析
  showLineNumbers={prefs.showLineNumbers}
  maxLines={30}              // 超过自动折叠，加 "Show all 142 lines" 按钮
  variant="chat"             // 区分聊天 vs report 上下文的尺寸
/>
```

**必备能力**：
- 右上角：语言徽章(`python`) + 复制按钮(✓ 反馈) + 折叠按钮
- 行号(按 store 偏好开关)
- 流式中未闭合 ``` ``` → 显示原文 + 一个虚线边框提示"streaming"
- 超 30 行折叠，按钮展开
- 高亮配色对齐 finrobot.html 暗色调(可能要写一个 shiki theme JSON)

---

## 4. 流式渲染 + 滚动锁定的协调机制

### 4.1 Vercel 的方案 ✗ 不直接复用

`components/ai-elements/conversation.tsx` 用 **`StickToBottom`** 库 + Tailwind native overflow，不是 virtuoso。

```typescript
import { StickToBottom } from "use-stick-to-bottom"
// <StickToBottom> wraps the messages container
```

**StickToBottom 关键能力**：
- 用户在底部 → 新消息自动滚到底
- 用户滚上去看历史 → 不强抢回底部
- 提供 `isAtBottom` / `scrollToBottom` API

**但它不是虚拟滚动**——长对话(1000+)仍然 mount 所有消息。Vercel 模板的消息列表没做虚拟化。

### 4.2 我们的方案 = StickToBottom + react-virtuoso 二选一

| | StickToBottom | react-virtuoso |
|---|---|---|
| 体积 | ~3 kB | ~20 kB |
| 虚拟化 | 否 | 是 |
| 流式锁底 | 内建 | `followOutput="auto"` |
| 变高度自适应 | 浏览器 native | ResizeObserver 内建 |
| 1000 条性能 | 卡 | 流畅 |

**结论**：Phase 5 装 **react-virtuoso**(它的 `followOutput="auto"` 等价 StickToBottom 的锁底，且自带虚拟化)。

### 4.3 useMessages hook 的抽象

`vercel/ai-chatbot` 在 `hooks/use-messages.ts` 把滚动状态抽离成 hook：

```typescript
const {
  containerRef,        // 给外层 div
  endRef,              // 给最底部 sentinel
  isAtBottom,          // 显示"滚到底"按钮的条件
  scrollToBottom,      // 点击"滚到底"按钮
  hasSentMessage,      // 用户已发送过消息 → 决定是否要 padding
  reset,               // 切换 chat 时重置
} = useMessages({ status })
```

**FinRobot 适用版**：写 `useChatScroll` hook，封装 virtuoso ref + isAtBottom + scrollToBottom，让 RightChatPanel 只是消费者。

### 4.4 流式不闪烁的几个关键点

| 现象 | 根因 | 解法 |
|---|---|---|
| 每个 token 都触发整条消息重 parse | 没 memo | `MessageBubble` 包 `React.memo`，深比较 message.id + message.parts 长度 + 最后 part 的内容长度 |
| 代码块未闭合时反复重排 | naive 解析器把后续 token 全吞进 `<pre>` | Streamdown 的 remend 解决；或自己在 parser 加未闭合检测 |
| 表格半截渲染丑 | 行未对齐 | 检测到 table 但分隔符行未到 → 不渲染表格，显示原始 markdown |
| 公式半截渲染崩 | KaTeX 拒绝不闭合 `$$` | try/catch，失败回落显示原始 `$$...` 字符 |

---

## 5. 消息级交互 (hover action bar) 的设计模式

### 5.1 Vercel 的 message-actions.tsx 设计

**用户消息**：hover 显示 `[编辑] [复制]`。编辑按钮只在传了 `onEdit` 时才渲染——可选式 prop pattern。

**Assistant 消息**：hover 显示 `[复制] [👍] [👎]`。投票按钮基于 `vote` 状态条件 disabled：
```typescript
disabled={vote?.isUpvoted}                    // 已赞→赞 disabled
disabled={vote && !vote.isUpvoted}            // 已踩→踩 disabled
```

**复制**：用 `usehooks-ts` 的 `useCopyToClipboard`(可选库)，或 navigator.clipboard。

**投票**：调 `/api/vote` + SWR 乐观更新 + toast 反馈。

### 5.2 编辑重发的实现 (`message-editor.tsx`)

```typescript
async function submitEditedMessage({ message, replacement, setMessages, regenerate }) {
  // 1. 删后续消息
  await deleteTrailingMessages(message.id)
  // 2. 更新这条消息的 parts
  setMessages(msgs => [
    ...msgs.slice(0, idx),
    { ...message, parts: [{ type: 'text', text: replacement }] },
  ])
  // 3. 触发 regenerate
  regenerate()
}
```

**关键设计**：编辑不是一个组件，是一个 **async function** + setMessages 调用。组件层只渲染 `<textarea>` + "保存"按钮，点击 → 调用这个函数。

### 5.3 FinRobot 适用版

| 交互 | 实现 |
|---|---|
| 复制 plain text | `navigator.clipboard.writeText(extractText(message.parts))` |
| 复制 Markdown 源 | 同上但保留 markdown 语法 |
| 编辑重发 | 学 Vercel 的 `submitEditedMessage` 模式 |
| 重新生成 | `useChat.regenerate()` 现有能力 |
| 引用回复 | 把选中文本前缀 `> ` + 换行塞进输入框 |
| 反馈(👍/👎) | 本地 `votesStore.set(messageId, 'up'/'down')`(zustand)，**不上报后端** |
| 锚点跳转 | `<MessageBubble id={`msg-${message.id}`}>` + URL hash 监听 + 跳转时 outline 高亮 2s |

**hover action bar 的位置**：消息气泡右上角浮层(absolute positioned)，只在 `:hover` 时显示。**touch device 显示需另想**(可能小屏长按)。

---

## 6. Artifact 抽离的判断逻辑和实现路径

**⚠️ Phase 1–6 不实现。本节仅为 P3+ 设计储备。**

### 6.1 Vercel 的判断逻辑 (`components/chat/artifact.tsx` + `data-stream-handler.tsx`)

判断"是否抽离为 artifact"**不在前端**——是**后端**通过 SSE 发送特殊的 `data-*` part 类型：

```
data-id      → 设 artifactId
data-title   → 设标题
data-kind    → text / code / sheet / image
data-clear   → 清空
data-finish  → 完成
```

前端 `DataStreamHandler` 监听这些 part 类型，调 SWR 缓存 + 触发 artifact UI 渲染。

### 6.2 FinRobot 不直接用这个模式

我们用 Tauri SPA，没有 SSE artifact 流，也没有 SWR。**正确的 FinRobot 路径**：

| 判断点 | 阈值/规则 |
|---|---|
| 超长代码 (>100 行) | 抽离到 `/library/{ticker}?artifact=` 链接，气泡里只放摘要 + 按钮 |
| 超长 markdown (>2000 字) | 同上 |
| Pipeline 产物有 `artifact_id` | 已有现成机制，沿用 |
| HTML/SVG/Mermaid 预览 | P3+：在右栏弹一个抽屉式预览面板 |
| 表格 (>20 行 / 列 > 8) | P3+：变成可排序/搜索的 DataTable 组件 |

**Phase 1-6 范围内**：只做"Pipeline artifact_id 链接"这一项(本来就有)，其他延后。

---

## 7. Tool 调用差异化设计 (从 cc-haha 学到的)

### 7.1 cc-haha 的 tools/ 组织 (设计模式 only，不抄代码)

`/Users/zhunihaoyun/Desktop/code/cc-haha/src/tools/` 下每个工具是**一个独立文件夹**：

```
src/tools/
├── BashTool/
├── FileEditTool/
├── FileReadTool/
├── FileWriteTool/
├── GlobTool/
├── GrepTool/
├── TodoWriteTool/
├── WebFetchTool/
├── AgentTool/                  ← 子 agent
├── EnterPlanModeTool/          ← 模式切换
├── AskUserQuestionTool/        ← 用户交互
├── NotebookEditTool/
├── ScheduleCronTool/
├── ReviewArtifactTool/
└── ...
```

**关键设计原则**：

| 原则 | 落地 |
|---|---|
| **每个 tool 是一个目录** | tool 自身的逻辑(input schema/permission/render)放在一起 |
| **render 是 tool 自带的方法** | 不是中心化注册表去查表，而是 tool 自己声明"我怎么渲染" |
| **input/output/error 三态独立渲染** | `FileEditToolDiff` / `FileEditToolUseRejectedMessage` / `FileEditToolUpdatedMessage` 各是一个组件 |

### 7.2 cc-haha 的 components/ 工具相关组件

```
src/components/
├── FileEditToolDiff.tsx                    (diff 视图，用 'diff' lib + StructuredDiffList)
├── FileEditToolUpdatedMessage.tsx          (编辑成功后展示)
├── FileEditToolUseRejectedMessage.tsx      (用户拒绝时展示)
├── FallbackToolUseErrorMessage.tsx         (通用错误)
├── FallbackToolUseRejectedMessage.tsx      (通用拒绝)
├── AgentProgressLine.tsx                   (sub-agent 多步进度)
├── CompactSummary.tsx                      (上下文压缩展示)
├── ContextVisualization.tsx                (context 用量)
├── HighlightedCode.tsx                     (语法高亮，Ink TUI)
└── StructuredDiff*.tsx                     (diff 结构化渲染)
```

**学到的模式**：

| 模式 | FinRobot 翻译 |
|---|---|
| **diff 用 `diff` 库 + 自己的 StructuredDiffList 渲染** | 不用 ProseMirror(Vercel 的方案太重)；用 `diff` 库出 hunks，自己写 `<DiffHunk>` 渲染红绿色块 |
| **Suspense + use(promise) 加载 diff** | 我们用 React 19 的 use hook + Suspense 处理异步 diff |
| **被拒绝/失败有独立组件** | 不是给同一个 ToolCard 加 `state === 'error'` 分支，而是 `WriteFileTool` / `WriteFileToolRejected` / `WriteFileToolError` 分开 |
| **Fallback 组件兜底** | 没注册的 tool 走 `FallbackToolUseErrorMessage` / `FallbackToolUseRejectedMessage`——通用 + 不丢消息 |

### 7.3 Vercel ai-elements/tool.tsx 的 7 状态机

```typescript
type ToolState =
  | 'approval-requested'   // 等用户授权
  | 'approval-responded'   // 用户已响应授权
  | 'input-streaming'      // 输入参数流式中
  | 'input-available'      // 输入完成，等待执行
  | 'output-available'     // 执行完成
  | 'output-denied'        // 用户拒绝
  | 'output-error'         // 执行错误
```

**我们现在的 ToolCard.tsx 只有 4 状态**(pending/running/complete/error)，**缺少授权流的两个状态**。

**FinRobot 翻译**：
- Phase 3 ToolPrimitive 至少支持 5 状态：`pending / running / success / error / denied`
- 授权流(approval-requested / approval-responded) 留作 P3+(我们后端目前没有 user-approval gate，但 P6 Conversation Agent OS spec 里有 `fund_id_guard`，未来可能要)

### 7.4 ToolRenderer 注册表的最终形态

参考 cc-haha 的"每个 tool 一个目录"+ Vercel 的"两层原语"，FinRobot 形态：

```typescript
// ui/src/components/chat/toolRenderers/index.ts

import { GenericTool } from './GenericTool'
import { ReadFileTool } from './ReadFileTool'
import { BashTool } from './BashTool'
// ... 其余

const TOOL_RENDERERS = new Map<string, ToolRenderer>([
  // 通用
  ['read_file', ReadFileTool],
  ['Read', ReadFileTool],                  // 别名
  ['bash', BashTool],
  ['Bash', BashTool],
  ['write_file', WriteFileTool],
  ['Write', WriteFileTool],
  ['Edit', WriteFileTool],
  ['web_search', WebSearchTool],
  ['WebSearch', WebSearchTool],
  ['grep', GrepTool],
  ['Grep', GrepTool],
  ['todo_write', TodoWriteTool],
  ['TodoWrite', TodoWriteTool],
  // FinRobot 专属
  ['run_research', PipelineTool],
  ['run_dcf', PipelineTool],
  ['run_lbo', PipelineTool],
  ['run_ic_memo', PipelineTool],
  ['run_earnings_analysis', PipelineTool],
])

export function getToolRenderer(toolName: string): ToolRenderer {
  return TOOL_RENDERERS.get(toolName) ?? GenericTool
}
```

**每个 ToolRenderer 的契约**：

```typescript
interface ToolRendererProps {
  toolCallId: string
  toolName: string
  args: Record<string, unknown>
  result?: unknown                          // 整个对象，不只是 summary
  errorText?: string
  state: 'pending' | 'running' | 'success' | 'error' | 'denied'
  startTime?: number                        // 计算耗时
}
```

---

## 8. 权限确认与多步规划

### 8.1 cc-haha 架构图 06-permission-security.png 学到的

(基于读图后的设计原则提炼，无图像本身)

权限确认是一个**独立的状态机**，不是简单的"弹窗 → Y/N"：
- 每次 tool 调用前 → 查 permission policy(allow/ask/deny)
- 如果 ask → 工具 part 进入 `approval-requested` 状态
- 用户响应 → `approval-responded` → 再次走 policy → 进入 input-available
- 用户拒绝 → `output-denied` + tool result 包装一个 rejection
- 全程**冻结主消息流**，不允许并发 tool 调用

**FinRobot 现状**：后端 `finrobot/engine/orchestrator.py` 没有用户授权 gate，所有 tool 自动跑。**Phase 1-6 不实现授权 UI**，但 ToolPrimitive 留出 `denied` 状态位以备 P3+。

### 8.2 多步规划 (TodoWrite) 的展示设计

cc-haha 的 `TodoWriteTool` 在 src/tools/ 下；展示形式是一个**复选框列表**：
- ☐ pending
- ◐ in_progress (一次只一个)
- ☑ completed

**Vercel ai-chatbot 没有 TodoWrite 工具**(它是 Next.js demo，不是 agent harness)。

**FinRobot 适用版**(Phase 3 实现)：
```
TodoWriteTool 渲染：
┌────────────────────────────────────┐
│ 🗒  Todo (3/5)                     │
│ ☑ 拉 AAPL 2024 年报数据             │
│ ☑ 计算 WACC                        │
│ ◐ 跑 DCF 敏感性                    │
│ ☐ 生成 IC memo                     │
│ ☐ 导出 Excel                       │
└────────────────────────────────────┘
```

进度统计在 header(完成数 / 总数)。

### 8.3 cc-haha 架构图 04-multi-agent.png

Sub-agent 调用的展示模式：
- 父消息流里出现一个**"agent invocation"卡片**(类似 tool 卡)
- 卡片内嵌一个**折叠的子对话**(默认折叠，点开看 sub-agent 完整推理)
- 完成后顶部一行 summary

**FinRobot 现状**：后端 P6 spec 设计了 sub-agent，但 UI 完全没接。Phase 1-6 不实现 sub-agent UI(后端代码也没合)，但留下 `<AgentToolRenderer>` 作为占位。

---

## 9. 性能优化模式

### 9.1 Memoization 三层

**第 1 层：父级 message map 的 key 稳定**
```tsx
{messages.map((m, i) => (
  <PreviewMessage
    key={m.id}                          // 永远用 message.id
    message={m}
    isLoading={status === 'streaming' && i === messages.length - 1}
    // ...
  />
))}
```

**第 2 层：每个组件 React.memo + 自定义比较**
```typescript
const PureMessageActions = (props) => { ... }
export const MessageActions = memo(PureMessageActions, (prev, next) => {
  // 只比关心的 prop，跳过 setMessages 这种 stable callback
  if (prev.vote !== next.vote) return false
  if (prev.isLoading !== next.isLoading) return false
  return true
})
```

**第 3 层：Markdown / CodeBlock 用 useMemo 缓存 parse 结果**
```typescript
const parsed = useMemo(() => parseMarkdown(text), [text])
```
**关键**：`text` 不变就不重 parse。流式新 token 进来时，**整条消息的 text 都变了**——所以这层 memo 只在该消息**完成**后才有效。流式中的优化靠 Streamdown 的内部增量解析。

### 9.2 content-visibility 优化

Vercel 的 CodeBlockContainer 用 `content-visibility: auto;`(CSS)——浏览器对屏幕外的代码块跳过 paint/layout。**长聊天滚动时关键**。

```css
.code-block-container {
  content-visibility: auto;
  contain-intrinsic-size: auto 200px;     /* 预估高度，避免滚动跳变 */
}
```

### 9.3 虚拟滚动阈值

`react-virtuoso` 阈值我们定 **>30 条** (上次讨论)：
- ≤30 条：直接 map(virtuoso overhead 不值)
- \>30 条：换 virtuoso，`followOutput="auto"`

### 9.4 流式状态的最后一条 vs 历史条

`messages.tsx`:
```tsx
isLoading={status === 'streaming' && messages.length - 1 === index}
```
**只有最后一条**收到 `isLoading=true`——历史条永远 stable，触发不了重 render(memo 比较通过)。

---

## 10. FinRobot 专属需要自己设计的部分

外部库**不会有**的能力，必须自己写：

### 10.1 Pipeline 工具卡 (核心差异点)

`run_dcf` / `run_research` / `run_lbo` / `run_ic_memo` / `run_earnings_analysis` 这五个是 FinRobot 专属，没有任何参考库覆盖。

**设计要点**：
```
┌──────────────────────────────────────┐
│ 🧮 run_dcf (AAPL)   [运行中] 12.3s   │  ← 工具名 + ticker + 状态 + 耗时
├──────────────────────────────────────┤
│ ✓ 1. 数据采集            (3.2s)      │  ← 6 步 pipeline 进度
│ ✓ 2. 财务建模            (4.1s)      │
│ ◐ 3. WACC 计算           ...          │  ← 当前步骤
│ ☐ 4. DCF 敏感性                       │
│ ☐ 5. 估值汇总                         │
│ ☐ 6. 报告生成                         │
├──────────────────────────────────────┤
│ ✓ Code-Computed                       │  ← 守住"数字由代码算出"信号
│ 📎 打开完整报告 (artifact #abc123)    │  ← 已有的 artifact 链接
└──────────────────────────────────────┘
```

**数据来源**：后端 `run_pipeline` 工具的 result 里要含 `steps: [{name, duration, status}]`。**Phase 3 要协调后端把这个字段加上**，否则 UI 只能显示总耗时。

### 10.2 ContextBar 上下文 chip

`uiStore.ts:80-86` 已经定义了 `ContextBundle.mentions: ContextItem[]`，但 `RightChatPanel` 没读取。

**设计**：输入框上方一行 chips：
```
[📁 dcf.py] [📊 AAPL] [📝 IC memo draft]  ← 用户加的 @file 引用
                       发送
[                                       ]
```
- Chip 可点击展开预览
- Chip 可 × 移除
- 输入时 `@` 触发 CommandPalette 选 chip 源

Phase 4 实现。

### 10.3 MODE A/B 切换

`uiStore.ts:91` 定义了 `AgentMode = 'A' | 'B'`(A=叙事/LLM agent, B=计算/pipeline)。UI 还没暴露。

**设计**：输入框右下角一个 toggle，A 模式时模型 selector 显示，B 模式时隐藏(改成 pipeline selector)。

Phase 6 实现。

### 10.4 fund_id / ticker 切换的会话隔离

`RightChatPanel.tsx:49-60` 已经按 ticker 隔离 session(sessionMapRef Map)。这个机制是 FinRobot 独有，外部库不会有。**不动**。

### 10.5 "Code-Computed" 徽章

`ToolCard.tsx:137-147` 现有的 ✓ Code-Computed 徽章是 FinRobot 信念的视觉锚——**所有 pipeline tool 必带，所有非 pipeline tool 不带**。

不要被外部库的 status badge 设计带偏。

---

## 11. 代码可以直接抄的清单 (三档分级)

**校准说明**：vercel/ai-chatbot 是 Next.js RSC + Server Actions，部分文件不能照搬到 Vite + Tauri SPA。下表按 ✓/⚠️/✗ 三档标注。**cc-haha 全部为 ⚠️**(license 不兼容，零代码复制，只学模式)。

| 文件 / 模式 | 来源 | 档位 | 用途 | 我们的版本 |
|---|---|---|---|---|
| `components/chat/message.tsx` | vercel | ✓ | 单消息容器 + tool 分发 | Phase 3 拆 `MessageBubble` + `AssistantContent` |
| `components/chat/messages.tsx` | vercel | ✓ | 消息列表 + 滚动锁 | Phase 5 用 virtuoso 重写 |
| `components/chat/message-actions.tsx` | vercel | ✓ | hover action bar(复制/编辑/投票) | Phase 4 写 `MessageActions.tsx` |
| `components/chat/message-editor.tsx` | vercel | ✓ | submitEditedMessage async fn | Phase 4 同名函数 |
| `components/chat/message-reasoning.tsx` | vercel | ✓ | reasoning 折叠 + 自动开关 | Phase 1 换掉 `ReasoningCollapsible` |
| `components/ai-elements/code-block.tsx` | vercel | ✓ | shiki + 异步 + 缓存 + copy | Phase 2 写 `CodeBlock.tsx` |
| `components/ai-elements/conversation.tsx` | vercel | ⚠️ | StickToBottom 锁底 | 我们用 virtuoso 的 `followOutput`，**学模式不抄代码** |
| `components/ai-elements/tool.tsx` | vercel | ✓ | 工具状态机 + collapsible | Phase 3 写 `ToolPrimitive.tsx`(简化到 5 状态) |
| `components/ai-elements/reasoning.tsx` | vercel | ✓ | 流式 reasoning + Streamdown | Phase 1 直接采纳 |
| `components/ai-elements/prompt-input.tsx` | vercel | ⚠️ | 输入框 + 附件 | 学 PromptInputProvider 状态提升模式，**附件流要改**(我们走 FastAPI 而非 Server Actions) |
| `hooks/use-messages.ts` | vercel | ✓ | 滚动状态 hook | Phase 5 写 `useChatScroll.ts` |
| `components/chat/diffview.tsx` | vercel | ✗ | ProseMirror diff | **太重**，我们用 `diff` 库 + 自写 `<DiffHunk>` |
| `components/chat/data-stream-handler.tsx` | vercel | ✗ | RSC + SWR + artifact stream | **Next.js-only**，我们 useChat 的 parts 已经够用 |
| `components/chat/artifact.tsx` | vercel | ✗ | Server Action artifact runtime | **Phase 1-6 不实现**，P3+ 候选 |
| `components/chat/multimodal-input.tsx` | vercel | ⚠️ | 业务输入区 | 学结构，但模型 selector / 附件流要走我们的 API |
| **Streamdown 库本身** | vercel/streamdown | ✓ | markdown + GFM + math + mermaid + 流式 | Phase 1 POC 装它 |
| **`use-stick-to-bottom`** | npm | ✗ | 滚动锁 | 我们换成 react-virtuoso，**它的能力被 virtuoso 包含了** |
| cc-haha tool 目录组织 | cc-haha | ⚠️ | 每个 tool 一个文件夹 | 我们用 `toolRenderers/{ToolName}.tsx` 单文件 |
| cc-haha 7 状态机 | cc-haha | ⚠️ | tool 调用生命周期 | 简化到 5 状态(去掉 approval-*)，写在 ToolPrimitive 里 |
| cc-haha 06-permission-security 图 | cc-haha | ⚠️ | 授权状态机 | **P3+ 候选**，本次不实现 |
| cc-haha 04-multi-agent 图 | cc-haha | ⚠️ | sub-agent 折叠卡片 | **P3+ 候选**，留 `<AgentToolRenderer>` 占位 |

---

## 12. 不抄、自己写的清单

以下能力**没有任何外部参考可用**，必须 FinRobot 自己设计实现：

| 能力 | 在哪 | 阶段 |
|---|---|---|
| **PipelineTool 6 步进度卡** | `toolRenderers/PipelineTool.tsx` | Phase 3 |
| **"Code-Computed" 徽章语义** | `ToolPrimitive` + `PipelineTool` | Phase 3 |
| **ContextBar @file / @ticker chip** | 输入框上方 + `uiStore.mentions` | Phase 4 |
| **MODE A/B 切换 toggle** | 输入框右下角 | Phase 6 |
| **fund_id / ticker 会话隔离** | `RightChatPanel.tsx` 已有，不动 | — |
| **artifact_id → /library 链接** | `ToolPrimitive` 已有，不动 | — |
| **finrobot.html 暗色 token 映射** | 写一份 shiki theme JSON + Tailwind class map | Phase 1 |
| **模型 tag + cost 累计** | `StatusBar` 接 `useChat.usage` | Phase 6 |
| **金融场景的工具命名 (run_dcf 等)** | `toolRenderers/index.ts` 注册表 | Phase 3 |
| **数据来源 sources 数组渲染** | `PipelineTool` 内部(后端返回 `result.sources`) | Phase 3 |
| **多源交叉校验警告 (P3 N7)** | 已有 `WarningBanner` 组件，工具卡内联展示 | Phase 3 |

---

## 13. 阶段对照表 (Phase 0 产出 → Phase 1-6 落地)

| Phase | 关键决策依据 (本文章节) | 主要文件 |
|---|---|---|
| **Phase 1** Markdown + XSS | §2 (Streamdown POC), §5.3 (XSS) | `Markdown.tsx`、删 `MarkdownLite.tsx` + `utils/markdown.ts`、改 `ResearchSummary.tsx` |
| **Phase 2** 代码块 + math + mermaid | §3 (CodeBlock), §2 (Streamdown 内建) | `CodeBlock.tsx` 或直接消费 Streamdown |
| **Phase 3** Tool 卡注册表 | §1 分层, §7 注册表, §10.1 PipelineTool | `toolRenderers/*` |
| **Phase 4** 消息交互 + 引用 + 锚点 | §5 hover action bar, §10.2 ContextBar | `MessageActions.tsx`、`useEditMessage.ts` |
| **Phase 5** 虚拟滚动 + 光标 + perf | §4 滚动锁, §9 memo | virtuoso 接入、`useChatScroll.ts` |
| **Phase 6** 模型 tag + cost + DoD | §10.3 MODE 切换, §10 cost 接 usage | StatusBar 改造、测试补齐 |

---

## 14. 决策记录 (Open Decisions)

需要在 Phase 1 实际开干前再次确认的项：

| # | 决策 | 选项 | 倾向 |
|---|---|---|---|
| D1 | Markdown 栈 | Streamdown(一包) vs react-markdown 五包栈 | **Streamdown POC 优先**；不行回落手装栈 |
| D2 | 滚动锁 | StickToBottom vs react-virtuoso | virtuoso(自带虚拟化) |
| D3 | Diff 渲染 | `diff` lib + 自写 vs ProseMirror | `diff` + 自写(轻) |
| D4 | 代码高亮 | shiki(via Streamdown) vs prismjs | shiki(已被 Streamdown 默认携带) |
| D5 | Tool 状态数 | 5 (我们 minimal) vs 7 (Vercel full) | 5(暂无授权流) |
| D6 | reasoning 默认 | 默认折叠 vs 流式中默认展开 | **流式中默认展开**，完成后 1s 自动折叠(Vercel 模式) |

---

*本文档为 FinRobot UI 重构 Phase 0 产出，作为 Phase 1-6 的执行依据 + 长期设计标准沉淀。*
