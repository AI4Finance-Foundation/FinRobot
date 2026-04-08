> **状态：✅ 已完成（2026-04-01）**
>
> 实现文件：
> - Python 端：`finagent/server.py`（SSE 端点），`finagent/engine/pipelines/base.py`（streaming 支持）
> - Electron：`desktop/electron/main.ts`（主进程 + Python 进程管理 + loading UI）
> - React：`desktop/src/components/ResearchView.tsx`、`DCFView.tsx`、`CompsView.tsx`、`ErrorBoundary.tsx`
> - Hooks：`desktop/src/hooks/usePipelineStream.ts`
> - 工程：`desktop/.eslintrc.json`、`desktop/.prettierrc`、`.github/workflows/ci.yml`
>
> 验收标准通过情况：6/6（修复 D1-D3、S1-S5 后全部通过）。

---

# P1c — Desktop App（Electron + React）

**状态**：📋 待实现
**前置条件**：P1.5 ✅
**目标**：让非工程师用户（买方研究员、独立分析师）无需 CLI 即可使用 FinAgent

---

## 为什么 P1c 是现在最重要的

P1.5 之后 FinAgent 有了真实的代码价值（确定性金融计算）。
但 CLI 工具把目标用户（金融从业者，不是工程师）挡在门外。
Desktop app 是让"给懂金融但不想写代码的人"这一定位变为现实的关键一步。

**不做 P1c 的代价**：开源后只有工程师能用，目标用户完全触达不到。

---

## 范围

### 包含
- Electron 主进程 + React 渲染进程（TypeScript）
- FinAgent Python 进程通过 SSE（Server-Sent Events）与 Electron 通信
- 三个核心界面：
  1. **研究界面**：输入 ticker → 显示 equity research 报告（流式输出）
  2. **DCF 界面**：输入参数 → 显示 DCF 结果 + 敏感性分析表格
  3. **Comps 界面**：输入 ticker + peers → 显示倍数对比表
- macOS `.app` 打包（主要目标平台）
- Windows `.exe`（次要，如果不增加太多复杂度）

### 不包含
- 用户账号系统（P3+）
- 云端部署（P3+）
- 移动端（P4+）
- 实时行情（需要专业数据源，P2b+）
- 组合管理（超出范围）

---

## 架构决策

### 通信方式：SSE（不是 IPC）

```
Electron Main Process
    └── 启动 Python FinAgent server（subprocess）

React Renderer
    └── fetch('http://127.0.0.1:8000/stream/research?ticker=AAPL')
        └── EventSource → 流式接收 pipeline 步骤输出
```

**为什么 SSE 不是 Electron IPC**：
- SSE 复用现有 FastAPI server，改动最小
- 未来 Web 版可以直接复用同一 server
- IPC 需要 contextBridge + preload script，增加维护复杂度

### Python 进程管理

```typescript
// main.ts
const server = spawn('python', ['-m', 'finagent', 'serve', '--port', '8000'])
app.on('will-quit', () => server.kill())
```

**依赖问题**：用户机器上不一定有 Python + 依赖包。
**方案**：使用 `uv` 作为 sidecar，打包时附带 `uv` 二进制 + `pyproject.toml`，首次启动时 `uv run finagent serve`（uv 自动创建虚拟环境）。
不用 PyInstaller（体积过大，启动慢）。

### FastAPI 端：新增 SSE 端点

```python
# server.py 新增
@app.get("/stream/research")
async def stream_research(ticker: str):
    async def generate():
        async for event in run_equity_research_streaming(ticker):
            yield f"data: {event.model_dump_json()}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

现有 `/chat` 端点保持不变（向后兼容）。

---

## 实现顺序

### File 1：FastAPI SSE 端点（`finagent/server.py` 修改）

新增三个 streaming 端点：
- `GET /stream/research?ticker=AAPL`
- `GET /stream/dcf?ticker=AAPL`
- `GET /stream/comps?ticker=AAPL&peers=MSFT,GOOG`

每个端点发送 `PipelineEvent` SSE 事件：
```python
class PipelineEvent(BaseModel):
    step: str           # 当前步骤名
    status: str         # "running" | "completed" | "failed"
    text: str           # 当前输出文本（可能是流式增量）
    structured: dict | None  # 结构化结果（步骤完成时）
    progress: float     # 0.0–1.0
```

测试：用 `curl -N 'http://127.0.0.1:8000/stream/research?ticker=AAPL'` 验证 SSE 流正确输出。

### File 2：Electron 项目初始化（`desktop/` 目录）

```
desktop/
├── package.json          # electron, react, typescript, vite
├── electron/
│   ├── main.ts           # 主进程：窗口管理 + Python 进程管理
│   └── preload.ts        # contextBridge（如果需要）
└── src/
    ├── App.tsx
    ├── components/
    │   ├── ResearchView.tsx
    │   ├── DCFView.tsx
    │   └── CompsView.tsx
    └── hooks/
        └── usePipelineStream.ts  # SSE 连接 + 状态管理
```

**不使用 Create React App**。使用 `electron-vite`（快速 HMR，TypeScript 支持）。

### File 3：`usePipelineStream.ts` hook

```typescript
function usePipelineStream(endpoint: string, params: Record<string, string>) {
  const [events, setEvents] = useState<PipelineEvent[]>([])
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'failed'>('idle')

  const start = useCallback(() => {
    const url = new URL(`http://127.0.0.1:8000${endpoint}`)
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
    const es = new EventSource(url.toString())
    es.onmessage = (e) => {
      const event = JSON.parse(e.data) as PipelineEvent
      setEvents(prev => [...prev, event])
      if (event.status === 'completed' || event.status === 'failed') {
        setStatus(event.status)
        es.close()
      }
    }
  }, [endpoint, params])

  return { events, status, start }
}
```

### File 4：`ResearchView.tsx`（主界面）

- Ticker 输入框 + "Run Analysis" 按钮
- Pipeline 步骤进度条（5步）
- 流式文本输出区域
- 结构化结果卡片（当步骤完成时渲染）：
  - WACC 结果卡（显示 cost_of_equity, cost_of_debt, wacc）
  - DCF 结果卡（implied_price, sensitivity 热力图）
  - 倍数对比表（EV/EBITDA, P/E）

### File 5：打包配置

```json
// package.json
{
  "scripts": {
    "dev": "electron-vite dev",
    "build": "electron-vite build && electron-builder",
    "dist:mac": "electron-builder --mac",
    "dist:win": "electron-builder --win"
  }
}
```

`electron-builder` 配置：
- macOS: `.dmg` + `.app`
- 打包 `uv` 二进制（extraResources）
- 首次启动时 `uv sync` + `uv run finagent serve`

---

## 验收标准

1. **启动**：双击 `.app` 图标，10秒内界面出现，无需用户安装任何依赖
2. **研究界面**：输入 "AAPL"，点击 Run，30秒内看到 5 步流式输出 + 最终报告
3. **DCF 界面**：输入参数后看到 implied price + 5×5 敏感性分析表格（数字是代码计算的）
4. **Comps 界面**：输入 "AAPL" + peers "MSFT,GOOG,META"，看到倍数对比表
5. **关闭 app**：Python server 进程也随之退出（不残留）
6. **错误处理**：yfinance 数据不可用时，界面显示具体错误信息，不崩溃

---

## 不可替代性检查

"如果删掉 Desktop app，给用户 CLI 命令，能得到一样的结果吗？"

从**功能**角度：能（CLI 已经可以输出同样的分析）。
从**用户触达**角度：不能——目标用户（金融分析师）不会用 CLI。

Desktop app 的价值不是计算，是**触达**。这是成立的。

---

## 已知风险

| 风险 | 可能性 | 影响 | 缓解方案 |
|------|--------|------|----------|
| uv sidecar 在 Windows 上路径问题 | 中 | 高 | 优先 macOS，Windows 作为 P1c.1 |
| Electron 打包体积过大（>200MB） | 低 | 中 | 用 electron-vite 优化，考虑 Tauri 作为备选 |
| SSE 连接被防火墙拦截 | 低 | 中 | 允许用户配置端口 |
| Python 进程启动时间 >10s | 中 | 高 | 后台预热，loading 界面 |

---

## 开始前的检查清单

- [ ] `finagent serve` 在本地可以正常启动
- [ ] `GET /chat` 端点返回正确响应
- [ ] Node.js 18+ 已安装
- [ ] `npm install -g electron-vite` 或通过项目 devDeps 安装
