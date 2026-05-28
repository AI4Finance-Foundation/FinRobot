# FinRobot 优化与扩展路线图

> **本文档仅做规划，不代表已实施。每一项是独立可执行单元，按优先级排序，可单独跑。**
>
> 配套阅读：`docs/cc-haha-borrowables.md`（636 行调研详情，模式来源 + 代码 ref）
>
> 最后更新：本次 cc-haha 调研之后。

---

## 0. 前置原则（必读，所有项适用）

### 0.1 License 边界

cc-haha 项目基于 **2026-03-31 从 Anthropic npm registry 泄露的 Claude Code 源码**。其 LICENSE 明确声明：

- 版权归 Anthropic
- 禁止商业用途
- 禁止再发布

**对 FinRobot（Apache 2.0 + 计划开源）的硬约束：**

| 准入 | 禁止 |
|---|---|
| ✅ 阅读源码理解模式 | ❌ `cp` 任何文件到 FinRobot |
| ✅ 自写实现相同设计 | ❌ 把 cc-haha 整段代码改名后塞进 FinRobot |
| ✅ 在 commit / 文档里说明"模式参考自 cc-haha" | ❌ 在 LICENSE 里不提及来源 |
| ✅ 通过 cc-haha 验证 CC 4 模式的实现细节 | ❌ 引用 cc-haha 作为依赖 |

**所有下面的方案都按"理解 + 自写"准则。** 我（或后续 subagent）不会做"拷贝重命名"。

### 0.2 优先级矩阵

| 级别 | 含义 | 触发条件 |
|---|---|---|
| **P0** | 必须立即做，已知 bug / 阻塞 | 桌面 app 跑不起来 / 白屏 / 启动竞态 |
| **P1** | 短期完整化产品体验 | 已交付 UI，但缺少必备交互（权限审批、工作空间、用量统计） |
| **P2** | 中期，让 app 真正可分发 | 没解决 = 用户得装 uv/Python 才能跑 |
| **P3** | 长期，扩展能力（boss 可能要） | 定时任务 / IM 推送 / 手机访问 |
| **Q** | 工程质量基础设施 | 测试分散、没统一门禁 |

### 0.3 估算口径

每项的"工作量"指 **subagent 实施时间**（即派 sonnet/opus agent 跑的时长 + review 修复回合），不是人月。

---

## P0 — 当下立即做（白屏与基础架构）

### P0.1 动态端口 + `get_server_url` Tauri command

**为什么必须做：** 当前 `tauri.conf.json` 的 sidecar 启动命令把 Python 监听端口硬编码为 8321。问题：
- 8321 被占用 → sidecar 启动失败 → 白屏
- Tauri build 模式下前端 `fetch("/api/foo")` 会变成 `tauri://localhost/api/foo`，没人转发到 8321 → 所有 API 调用失败
- 我前面 commit `1545d9d` 只删了 hardcoded window URL，治标不治本

**cc-haha 的模式：**
- Rust 端用 `std::net::TcpListener::bind("127.0.0.1:0")` 获取一个内核分配的空闲端口
- 启动 sidecar 时把端口作为 CLI 参数 / 环境变量传给 Python
- Tauri 用 `#[tauri::command]` 暴露 `fn get_server_url() -> String`
- React 前端 boot 时 `await invoke("get_server_url")` 拿到 `http://127.0.0.1:<dynamic_port>`，赋给一个全局 API client 的 baseUrl
- 所有后续 fetch 用绝对 URL：`fetch(\`${apiBaseUrl}/api/foo\`)`

**FinRobot 实施步骤：**
1. `src-tauri/src/sidecar.rs`：在 `spawn_and_wait_for_ready` 里先 bind 0 拿端口，再 spawn 时传 `--port=<port>`，把 `port` 存到 `tauri::State<AppState>` 里
2. `src-tauri/src/lib.rs`：注册 `#[tauri::command] fn get_server_url(state: State<AppState>) -> String`
3. `src-tauri/binaries/finrobot-server-shared.sh`：接受 `--port` 参数透传给 `uv run finrobot serve`
4. `ui/src/api/client.ts`（新文件）：导出 `apiBaseUrl` Promise；boot 时 `invoke("get_server_url")` 解析
5. 所有现有 `fetch("/api/...")` 改为 `fetch(\`${await apiBaseUrl}/api/...\`)`，或者用 axios/ky 全局配置 baseURL
6. `vite.config.ts` 的 proxy 可以保留（dev 模式让 baseUrl 走 vite，proxy 路由到真实 port）—— 或者更简单：dev 模式也走 invoke

**工作量：** 4-6 小时（subagent + review 一回合）

**依赖：** 无

**测试：**
- 单测：Rust 的 `TcpListener::bind(0)` 拿到 port > 0
- 单测：`get_server_url()` 返回格式正确
- E2E：起两个 Tauri 实例不冲突（不同端口）
- E2E：杀掉 sidecar 后重启，新端口生效

---

### P0.2 `waitForHealth` 轮询 + AppShell bootstrap 状态机

**为什么必须做：** Python sidecar 冷启动需要 2-5 秒（uvicorn + 加载 finrobot 包 + 数据 provider 初始化）。当前 React 一启动就尝试 fetch，前几秒所有请求 404 → 用户看见空白或错误状态。

**cc-haha 的模式：**
- App 启动时 React 进入 `bootstrap` 状态
- 一个 `useHealthCheck()` hook 轮询 `/health`：最多 30 次，每次 250ms
- 期间 AppShell 渲染 loading screen（带 spinner + "启动中..."）
- 200 OK 后切到 `ready` 状态，渲染业务路由
- 超时（30 × 250ms = 7.5s）切到 `error` 状态，显示重试按钮 + 错误信息

**FinRobot 实施步骤：**
1. `ui/src/stores/bootstrapStore.ts`（新）：zustand store，状态 `bootstrap | ready | error`
2. `ui/src/hooks/useHealthCheck.ts`（新）：从 P0.1 拿 baseUrl，轮询 `/health`
3. `ui/src/layout/AppShell.tsx`：top-level 根据 bootstrapStore 渲染 `<BootstrapScreen />` / `<Outlet />` / `<ErrorScreen />`
4. `ui/src/components/BootstrapScreen.tsx`（新）：居中 logo + "正在启动 Python 后端..." + spinner + 进度（"第 N 次重试"）
5. `ui/src/components/ErrorScreen.tsx`（新）：错误展示 + "重试"按钮（重置 bootstrap state，触发新一轮 health check）+ "查看日志"链接（打开 sidecar log 文件）

**异常路径必须覆盖：**
- 后端 7.5s 内不就绪 → error 状态 + 用户可重试
- 后端 200 但 schema 异常 → 仍标记 error
- 用户重试时同时 fetch baseUrl 也失败 → 双重 retry
- 网络断了 → fetch reject → catch 后重试不 crash
- HMR 重载时不重复 bootstrap

**工作量：** 2-3 小时

**依赖：** P0.1 完成（要拿 baseUrl）

**测试：** mock /health 返回延迟 / 错误 / 慢速，断言 UI 状态切换正确

---

### P0.3 build 模式 webview 跨域 fetch（VITE_API_BASE_URL 注入）

**为什么做：** 即使 P0.1 P0.2 都到位，**Tauri build 模式仍然有坑**——`cargo tauri build` 出来的 .app，webview origin 是 `tauri://localhost`，浏览器 SOP 看 `127.0.0.1:<port>` 是跨域。

**解法（两选一）：**
- **A. 让前端永远用绝对 URL**（已经在 P0.1 做了）+ 后端开 CORS 允许 `tauri://localhost`。简单。
- **B. Tauri 注册 custom protocol `finrobot://`，在 Rust 层 proxy 到 sidecar**。复杂，但隐藏内部端口，更"原生 app"。

**推荐：A 方案。** B 是过度工程，仅在 future 需要离线 / 安全沙盒强化时才考虑。

**FinRobot 实施步骤：**
1. `finrobot/server.py`：CORS 中间件加入 `tauri://localhost` 到 allow_origins
2. `src-tauri/tauri.conf.json`：`app.security.csp` 设置允许 `connect-src 'self' http://127.0.0.1:*`
3. `ui/vite.config.ts`：保留 dev proxy（让 dev 模式也能走绝对 URL，不依赖 proxy）

**工作量：** 1 小时

**依赖：** P0.1

**测试：** 
- `cargo tauri build --no-bundle` 构建出来的 .app 跑起来能 fetch 到 sidecar API
- CSP 不放过广义 `http://*`（只允许 127.0.0.1）

---

## P1 — 短期完整化（前端体验）

### P1.1 权限审批 UI（工具调用授权）

**为什么做：** LLM 调用工具时，某些操作要用户确认。例：
- "我要把这份 DCF 报告导出到 ~/Downloads/" — 需要文件系统授权
- "我要发邮件汇总这次分析" — 需要外部 API 授权
- "我要删掉 NVDA 的旧 artifact" — 破坏性操作

cc-haha 在 CC 那种 Bash / Edit 上有授权弹窗，**模式直接借鉴**。

**FinRobot 应用场景：**
| 工具类型 | 默认行为 | 高危行为 |
|---|---|---|
| 只读（query_financial_data, run_dcf）| 自动允许，不弹窗 | — |
| 写本地文件（导出 Excel）| 弹窗 once / always-allow / deny | — |
| 删除（删 artifact）| 弹窗 confirm，no always-allow | — |
| 外部 API（发邮件，IM 推送）| 弹窗 + 显示要发到哪个账号 | — |

**UI 模式（cc-haha 启发）：**
```
┌─────────────────────────────────────────────────────────┐
│  🔐 FinRobot 想做：导出 AAPL DCF 报告                    │
│                                                         │
│  目标：~/Downloads/AAPL_DCF_2026-05-13.xlsx             │
│  来源工具：export_excel                                 │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ ☐ 该工具未来都允许（自动 trust）                │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│           [拒绝]  [仅此次允许]  [允许并记住]            │
└─────────────────────────────────────────────────────────┘
```

**实施步骤：**
1. 后端 `finrobot/permissions/` 新模块：
   - `models.py`：`Permission = "allow_once" | "allow_always" | "deny"`
   - `store.py`：每个 (user_id, tool_name, scope) 的策略落 `~/.finrobot-desktop/permissions.json`
   - 钩进 tool execution：每次 tool call 前检查 store，无策略 → 暂停 + 询问前端
2. SSE 协议加 `permission_request` 事件类型 → 前端弹窗 → 用户回 → 后端继续
3. 前端 `ui/src/components/PermissionDialog.tsx`：modal 显示工具名 + 参数 + 来源 + 3 个按钮
4. Store 持久化的 always-allow 在设置页可撤销

**工作量：** 8-12 小时

**依赖：** P0.1 + P0.2

**测试：**
- mock 工具调用触发 permission_request
- 用户点"允许并记住"后下次同工具不弹窗
- 用户点"拒绝"后工具返回 is_error=True，agent 继续不 crash
- 设置页能列出所有 always-allow 并撤销

---

### P1.2 多 ticker 工作空间（借鉴 git worktree workspace）

**为什么做：** cc-haha 用 git worktree 让一个 CC 工作台同时管 N 个项目。FinRobot 的对应概念是"一个分析师同时跟踪 N 个 ticker"。

**当前 FinRobot 状态：** Library 页有"工作空间分组"（zustand + localStorage），但只是 ticker list 的分组。没真正的"打开一组 ticker，并排看，并行算"的工作流。

**cc-haha 的模式（移植到 FinRobot）：**

| cc-haha | FinRobot |
|---|---|
| 一个 CC project = 一个 git repo | 一个 FinRobot "工作空间" = 一组 ticker + 一份 dashboard 布局 |
| 项目间切换不共享 context | 工作空间间切换不共享 ticker / artifact |
| 同时多开 CC 跑多项目 | 同时多开 ticker（双栏 / 三栏并列） |
| Worktree 隔离分支 | "假设场景"隔离：同 ticker 两套不同 DCF 假设并存 |

**UI 模式：**
```
┌─────────────────────────────────────────────────────────────────┐
│ 工作空间：半导体批量分析（5 ticker） │ 切换▾                       │
│ AAPL · NVDA · AMD · AVGO · INTC                                 │
├─────────────────────────────────────────────────────────────────┤
│ [并排视图] [瀑布视图] [对比视图]                                  │
│                                                                 │
│  ┌─AAPL─────────┐ ┌─NVDA─────────┐ ┌─AMD──────────┐            │
│  │ DCF: $185    │ │ DCF: $920    │ │ DCF: $170    │            │
│  │ P/E: 28x     │ │ P/E: 65x     │ │ P/E: 42x     │            │
│  │ ...          │ │ ...          │ │ ...          │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│                                                                 │
│ 工作空间批量操作：[一键全跑 DCF] [一键导出对比报告]               │
└─────────────────────────────────────────────────────────────────┘
```

**实施步骤：**
1. 扩 `workspaceStore.ts`：除 tickers list 外，加 `layout: "side-by-side" | "waterfall" | "compare"`，加 `assumption_set_overrides: dict[ticker, DCFInputs]`
2. 新页面 `WorkspaceView.tsx` 在 Library 里点工作空间时打开
3. 并排视图：CSS Grid，每列一个 ticker 的简版 Stocks page
4. 对比视图：行=指标，列=ticker，单元格用 SourcedNumber
5. 批量操作：调用每个 ticker 的对应 endpoint，串行（避免 rate limit）显示进度
6. "假设场景"独立 artifact：一个 ticker 在工作空间 A 跑的 DCF 不影响工作空间 B

**工作量：** 12-16 小时

**依赖：** P0.1-3 完成 + Library 页已有的基础

**测试：** 工作空间创建/重命名/删除、布局切换、批量进度、对比视图字段对齐

---

### P1.3 Token 用量统计

**为什么做：** 金融分析师对成本敏感（boss 看每月 API bill 会问"谁用了多少"）。cc-haha 有 token usage 面板。

**统计粒度（推荐）：**
- 每会话累计 input/output tokens + cost
- 每工具调用单独 attribute（DCF 用了多少 tokens？peer_research sub-agent 用了多少？）
- 按 model 拆分（DeepSeek vs Claude vs OpenAI）
- 按日 / 周 / 月聚合
- 跨工作空间汇总

**实施步骤：**
1. 后端 `finrobot/usage/` 新模块：
   - `models.py`：`UsageEvent = {timestamp, session_id, model, input_tokens, output_tokens, cost_usd, tool_name?}`
   - `store.py`：每个事件 append 到 `~/.finrobot-desktop/usage.jsonl`（复用 audit 的 JSONL 模式）
   - 价格表：`pricing.json` 里 model_id → input_price / output_price per 1K
2. Hook 进 `/chat` 端点：每次 pydantic_ai 返回时拿 token count，写一条 UsageEvent
3. Hook 进 pipeline 调用：tool execution end 时也写一条（attribute 到工具）
4. 新路由 `/api/usage`：list / aggregate by day/week/month/model/tool
5. 前端 Settings 页加 "用量" tab：折线图 / 柱状图（用现有 recharts）+ 表格 + 导出 CSV

**工作量：** 6-8 小时

**依赖：** 无（独立）

**注意：** pydantic_ai 的 `run_stream` 返回的 result 对象上有 `usage()` 方法（`RequestUsage`），里面有 `request_tokens` 和 `response_tokens`。直接读。

---

## P2 — 中期分发与跨平台

### P2.1 Python 解释器 + 依赖打包进 .app

**为什么做：** 当前 `binaries/finrobot-server-shared.sh` 假设用户已装 `uv`。**这不是真正的桌面 app**——分析师下载 .dmg 双击就要能跑。

**cc-haha 的方案：**
- `desktop/sidecars/` 下放每个平台一个完整的 Python runtime + finrobot venv
- macOS arm64 / x86_64 / Windows x64 各一份
- 用 `python-build-standalone`（[github.com/indygreg/python-build-standalone](https://github.com/indygreg/python-build-standalone)）—— 这是 portable Python 的事实标准
- 配合 PyInstaller 把 venv 冻结成单一目录

**推荐方案（按优先级）：**

**A. python-build-standalone + venv 拷贝**（推荐）
- 下载对应平台的 standalone Python tarball（~30MB 压缩，~80MB 解压）
- 解压到 `src-tauri/sidecars/<host_triple>/python/`
- 创建 venv 并 `pip install finrobot`
- 整个目录 ~150MB（含 yfinance / pandas / pydantic 等所有依赖）
- 优势：完全 portable，不依赖系统 Python，跨平台一致
- 劣势：bundle 大

**B. PyInstaller --onedir**
- 把 finrobot + 解释器冻结成一个目录
- 体积小（~80MB）
- 劣势：PyInstaller 对动态 import 处理脆弱（pandas / pydantic-ai 都有动态 import），需要写 spec 文件

**C. PyInstaller --onefile**
- 单一可执行
- 体积最小（~60MB）
- 劣势：启动慢（每次解压到 /tmp）+ 动态 import 更脆弱

**FinRobot 推荐 A。** 理由：pydantic_ai + yfinance + 自己的 finrobot 代码 import 关系复杂，PyInstaller 容易漏文件。standalone Python + venv 是最稳的。

**实施步骤：**
1. `src-tauri/scripts/prepare-python-sidecar.sh`：
   - 检测 host triple
   - 下载对应 [python-build-standalone release](https://github.com/indygreg/python-build-standalone/releases)
   - 解压到 `src-tauri/sidecars/<triple>/python/`
   - 创建 venv：`python/bin/python -m venv venv`
   - 安装 finrobot：`venv/bin/pip install -e ../../../../`（editable 安装当前项目）
2. `src-tauri/binaries/finrobot-server-<triple>.sh`：调用 sidecars 里的 venv python 跑 `uvicorn`，不再依赖系统 uv
3. `tauri.conf.json` `bundle.resources` 把 `sidecars/<triple>/` 包进 .app
4. `build.rs` 在 Cargo build 时调 prepare-python-sidecar.sh

**工作量：** 8-12 小时

**依赖：** P0.1（端口配置已干净）+ P2.2（macOS 必须 sign Python 二进制）

**测试：** 
- 在没装 Python 的 mac 上 `cargo tauri build`+ 把 .app 拷到没装 uv 的同事电脑双击能跑
- 体积 < 200MB（gzip）

---

### P2.2 macOS ad-hoc sign（让 Python 二进制能在 macOS 跑）

**为什么必须做：** macOS 12+ 上，任何未签名的二进制运行时会被 SIP 拒绝（killed: 9 / signal: trace trap）。PyInstaller / python-build-standalone 生成的 Python 解释器都是"未签名"或"签名失效"。

**cc-haha 的流程：**
```bash
# 1. 移除原签名（如果有）
codesign --remove-signature path/to/python

# 2. ad-hoc 签名（不需要 Apple Developer 账号）
codesign --sign - --force --timestamp=none \
    --entitlements entitlements.plist \
    path/to/python

# ⚠️ 不能用 --deep，否则会改变 CDHash 破坏 Keychain ACL
```

**FinRobot 实施步骤：**
1. `src-tauri/scripts/sign-macos.sh`：递归签 sidecars/<triple>/python/ 下所有 binary（`python3`、所有 `.so`、`.dylib`）
2. `entitlements.plist`：开 `com.apple.security.cs.allow-unsigned-executable-memory`（pydantic / numpy 这类有 JIT 的库需要）
3. 集成进 `cargo tauri build` 的 build hook
4. 验证：`spctl -a -vv path/to/python` 应该返回 "rejected" 但不是 SIGKILL；`codesign -dv path/to/python` 显示签名信息

**工作量：** 3-4 小时

**依赖：** P2.1（要有 Python 二进制可签）

**测试：** macOS 上 .app 拷到全新机器双击能跑（不被 SIP kill）

---

### P2.3 跨平台 Python helper

**为什么做：** macOS / Windows / Linux 三平台启动 Python sidecar 时有微妙差异（路径分隔符、可执行扩展名、用户目录位置、权限模型）。cc-haha 用 `runtime/mac_helper.py` + `win_helper.py` 把这些差异封装。

**应抽出的差异点：**

| 概念 | macOS | Windows | Linux |
|---|---|---|---|
| 用户数据目录 | `~/Library/Application Support/FinRobot` | `%APPDATA%\FinRobot` | `~/.config/finrobot` 或 `$XDG_CONFIG_HOME/finrobot` |
| 临时目录 | `/tmp` | `%TEMP%` | `/tmp` |
| Python 可执行 | `python` (no ext) | `python.exe` | `python` |
| 进程信号 | SIGTERM / SIGKILL | TerminateProcess / WM_CLOSE | SIGTERM / SIGKILL |
| Auto-start 注册 | Launch Agent plist | Registry Run key 或 Startup folder | systemd user service |

**实施步骤：**
1. `finrobot/platform/` 新模块：
   - `paths.py`：`get_user_data_dir()`, `get_cache_dir()`, `get_log_dir()` 自动适配
   - `process.py`：跨平台 spawn / kill
   - `autostart.py`：注册 auto-launch（macOS launchd / Windows registry）
2. Tauri 端的 sidecar wrapper script 也要分平台：
   - `binaries/finrobot-server-aarch64-apple-darwin.sh`（bash）
   - `binaries/finrobot-server-x86_64-apple-darwin.sh`（bash）
   - `binaries/finrobot-server-x86_64-pc-windows-msvc.bat`（batch）
   - `binaries/finrobot-server-x86_64-unknown-linux-gnu.sh`（bash）

**工作量：** 6-8 小时

**依赖：** P2.1

---

### P2.4 macOS 签名 + 公证（用户能不点"允许打开"就跑）

**为什么做：** P2.2 的 ad-hoc 签名只让 Python 二进制能跑，**整个 .app 仍是未公证的，用户首次打开会被 Gatekeeper 拦**（"打不开，因为开发者不能验证"）。

**完整方案：**

| 项 | 要求 | 成本 |
|---|---|---|
| Apple Developer 账号 | $99/年 | 必须 |
| Developer ID Application 证书 | 在账号里申请 | 包含 |
| notarytool（替代旧 altool）| Xcode 13+ 自带 | 免费 |

**流程：**
1. 用 Developer ID 签整个 .app：
   ```bash
   codesign --deep --force --options=runtime \
       --sign "Developer ID Application: <Your Name> (TEAMID)" \
       --entitlements entitlements.plist \
       FinRobot.app
   ```
2. 打包 zip 提交公证：
   ```bash
   xcrun notarytool submit FinRobot.zip \
       --apple-id you@example.com \
       --team-id TEAMID \
       --password app-specific-password \
       --wait
   ```
3. 公证成功后 staple 到 .app：
   ```bash
   xcrun stapler staple FinRobot.app
   ```

**注意：** 跟 P2.2 的 ad-hoc 签名 sidecar Python **不冲突**——外层 .app 用 Developer ID 签，内层 sidecar 用 ad-hoc 签（因为 ad-hoc 签的 Python 不影响外层 .app 的公证，只要不 `--deep`）。

**实施步骤：**
1. 自己申请 Apple Developer 账号
2. 配置 .env：`APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_SIGNING_IDENTITY`
3. `src-tauri/scripts/sign-and-notarize-macos.sh`：完整流程
4. 集成进 GitHub Actions（见 P2.6）

**工作量：** 4-6 小时（实施）+ 1-2 周（Apple 账号审批等候期 + 公证回合）

**依赖：** P2.1, P2.2

---

### P2.5 Windows 代码签名

**为什么做：** Windows SmartScreen 对未签名应用警告"未识别的应用"，用户得点两层确认才能跑。

**两种证书：**

| 类型 | 用法 | 成本 | SmartScreen 表现 |
|---|---|---|---|
| **EV (Extended Validation)** | 硬件 dongle 或 HSM | $300-700/年 | 立即被信任，无警告 |
| **OV (Organization Validation)** | 软件证书 | $100-400/年 | 需要积累若干次下载才被信任 |

**推荐：** 先用 OV 上线，等用户量起来再升 EV。

**流程：**
1. 买证书（DigiCert / Sectigo / SignPath / SSL.com 都行）
2. 用 `signtool` 签 `.msi` 或 `.exe`：
   ```cmd
   signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 \
       /f cert.pfx /p password FinRobot-setup.exe
   ```
3. 集成进 GitHub Actions

**工作量：** 3-4 小时（实施）+ 1-2 周（证书审批）

**依赖：** 无

---

### P2.6 GitHub Actions release pipeline

**为什么做：** 没有 release 流水线，每次发版要手动构建 macOS / Windows / Linux 三平台，签名 + 公证 + 上传 release page，几小时手工。

**cc-haha 的 `.github/workflows/release-desktop.yml`（参考模式）：**
- 触发：tag push 匹配 `v*.*.*`
- 前置：`quality:gate --mode pr` preflight，失败不发
- Matrix：macOS-arm64, macOS-x86_64, windows-x64, linux-x64
- 每个 matrix job：checkout → 装 toolchain（Rust + Node + Python build-standalone）→ `cargo tauri build` → 签名 → upload artifact
- 最终 job：从 `release-notes/v{tag}.md` 读 release body → 创建 GitHub Release → 上传 4 个产物

**FinRobot 实施步骤：**

1. **`.github/workflows/release-desktop.yml`**：仿 cc-haha 结构，**自写**（不抄 yaml）

2. **`scripts/release.ts`**（或 `.sh`）：
   - 接受版本号 v 参数
   - 更新 `pyproject.toml` version
   - 更新 `package.json` version
   - 更新 `Cargo.toml` version
   - 校验 `release-notes/v<version>.md` 存在
   - `git add . && git commit -m "chore: release v<version>" && git tag v<version> && git push origin main --tags`
   - 触发 GitHub Actions

3. **Secrets 配置**：
   - `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_SPECIFIC_PASSWORD`
   - `APPLE_CERTIFICATE_BASE64`, `APPLE_CERTIFICATE_PASSWORD`（导出 Developer ID 证书 → base64）
   - `WINDOWS_CERTIFICATE_BASE64`, `WINDOWS_CERTIFICATE_PASSWORD`
   - 在 GitHub Settings → Secrets → Actions 加

4. **`release-notes/` 目录**：每个版本一个 `v<x.y.z>.md`，内容是 user-facing changelog

5. **支持 macOS universal binary**（可选）：合并 arm64 + x86_64 为单一 .app，用 `lipo` 命令

**工作量：** 8-12 小时（一次性配好基础设施）

**依赖：** P2.1, P2.2, P2.4, P2.5

**测试：** 推一个测试 tag `v0.0.1-test`，看 4 个产物 release 出来能跑

---

## P3 — 长期扩展（boss 可能要的）

### P3.1 定时任务（cron-style 监控）

**为什么做：** 分析师工作流里有大量"被动等"场景：
- 每天开盘前自动跑关注列表的 catalyst 扫描
- 每周一汇总持仓 DCF 跟随市场变化的 implied price
- 财报日前后自动跑 earnings analysis
- 监控某个 ticker 价格穿越关键位通知

cc-haha 有"定时任务"模块，**模式可借**。

**模式：**

```
┌─ 定时任务管理 ─────────────────────────────────────────┐
│ [+ 新建任务]                                            │
│                                                        │
│ 📅 每天开盘前扫描催化剂           最近运行：3h 前 ✅    │
│    cron: 0 8 * * 1-5                                   │
│    任务：对工作空间「半导体」执行 find_catalysts        │
│    [暂停] [立即执行] [查看历史]                         │
│                                                        │
│ 📅 周一汇总 DCF                   最近运行：2 天前 ⚠️   │
│    cron: 0 9 * * 1                                     │
│    任务：对工作空间「我的高确信」批量跑 DCF             │
│    [暂停] [立即执行] [查看历史]                         │
└────────────────────────────────────────────────────────┘
```

**实施步骤：**
1. 后端 `finrobot/scheduler/`：
   - 用 `apscheduler` 库（成熟 + cron-style）
   - `models.py`：ScheduledTask = {id, name, cron, workspace_id, action, last_run, last_status}
   - `store.py`：落 `~/.finrobot-desktop/scheduled_tasks.json`
   - 启动时从 store 加载 + 注册到 APScheduler
2. 路由 `/api/scheduler/tasks` CRUD
3. 前端 Settings 页加 "定时任务" tab

**坑：** Tauri app 关闭后定时任务跑不了。**两个方案：**
- A. 用户得保持 app 开着（轻量）
- B. 装一个 system service / launchd plist（重量）

P3 先做 A，B 是 P4+。

**工作量：** 8-12 小时

**依赖：** P0-P2 完成

---

### P3.2 H5 远程访问（手机 / 局域网）

**为什么做：** 分析师出差时，台式机上跑着 FinRobot，手机想看实时分析结果。cc-haha 有"H5 远程访问"——本地 server 在局域网内开放，用 IP 访问 web UI。

**安全模型（关键）：**
- 不能直接把 8321 暴露到公网——会被扫
- 局域网内 + 一次性 token 才安全
- 公网访问要走隧道（Cloudflare Tunnel / Tailscale），不直接 expose

**实施步骤：**
1. 后端 `finrobot/server.py`：加 `--allow-remote` flag。默认 bind `127.0.0.1`，允许时 bind `0.0.0.0`
2. 加 token 鉴权：`Authorization: Bearer <token>` 头。token 在 desktop app 启动时生成（写 user data dir），通过 QR code 给手机
3. 前端 Settings 页：[远程访问] 开关 + QR code + "撤销 token"
4. 移动端入口：现有的 React build 已经响应式（Tailwind），手机访问基本能用。可以做个简化版"只读"模式（不让手机点 [跑 DCF] 触发跑数小时的工作）

**工作量：** 6-8 小时

**依赖：** P0-P1 完成（用户体验稳定）

---

### P3.3 IM adapter（飞书 / 钉钉 / 微信 / Telegram）

**为什么做：** cc-haha 有 4 个 IM adapter——把 AI 结果推到 IM。FinRobot 的对应场景：
- DCF 跑完自动推 IC Memo 到飞书群
- 催化剂扫描发现重大事件 → 钉钉 @ 分析师
- 周报 / 月报定时推送
- Boss 在飞书问 "AAPL 怎么看？" → adapter 转发到 FinRobot → 答复返回 IM

**统一接口设计：**

```python
# finrobot/adapters/base.py
class IMAdapter(ABC):
    async def send_text(self, channel: str, text: str) -> None: ...
    async def send_card(self, channel: str, card: dict) -> None: ...
    async def send_file(self, channel: str, path: Path, filename: str) -> None: ...
    async def listen(self, callback: Callable[[Message], Awaitable[None]]) -> None: ...
```

**实施顺序（按 FinRobot 用户群覆盖度）：**
1. **飞书（Lark）** — 国内 buy-side 主要 IM，优先
2. **钉钉** — sell-side 投行多用
3. **Telegram** — 海外 / 个人投资者
4. **微信** — 个人号是灰区，**只做企业微信**（合规）

**每个 adapter 工作量：**
- 飞书：4-6h（API 文档清晰）
- 钉钉：4-6h（API 文档清晰）
- Telegram：2-3h（最简单，bot API 就行）
- 企业微信：6-8h（鉴权流程繁琐）

**总工作量：** 16-23 小时

**依赖：** P0-P1 完成 + 后端 webhook 接收能力（要把 IM 收到的消息转回 FinRobot 处理）

**注意：** 这是 **P3 末位**，因为：
- 用户没明确要求
- 每个 adapter 都要单独申请开发者权限 + 配置
- IM 协议变动频繁，维护成本高

---

## Q — 工程质量基础设施

### Q.1 AGENTS.md

**为什么做：** cc-haha 的 AGENTS.md（13KB）是给 AI coding agent 看的"项目导览"——比 README 更技术、更详细。FinRobot 也有未来 AI agent（包括我）二次维护的需求。

**内容结构（借鉴 cc-haha）：**

```markdown
# Repository Guidelines

## Project Structure & Module Organization
- finrobot/: Python 包，分模块说明
- ui/: React 前端，说明 src/ 各子目录意图
- src-tauri/: Rust 桌面壳
- docs/: 设计 + 路线图
- tests/: 各层测试

## Build, Test, and Development Commands
- bun run start / npm run dev / uv run finrobot serve 各自什么场景
- 三层质量门（pr / gate / smoke）

## Desktop Release Workflow
- tag → CI → release 全流程
- 本地打包脚本

## Docs Workflow Notes
- VitePress / mkdocs 文档站

## Coding Style & Naming Conventions
- Python: ruff format + mypy strict
- TS: tsc strict + ESLint
- 命名约定（PascalCase / camelCase / snake_case 各自场景）

## Testing Guidelines
- 单测 / 集成 / e2e 分层
- 异常路径必测

## Commit & PR Guidelines
- Conventional commits
- PR 描述模板
- review checklist

## Security & Configuration Tips
- .env.example
- 密钥管理
```

**实施步骤：**
1. 写 `AGENTS.md` 在 FinRobot 根目录
2. 写 `CONTRIBUTING.md`（互补）

**工作量：** 3-4 小时

**依赖：** 无

---

### Q.2 三层质量门

**为什么做：** cc-haha 的 `bun run quality:pr` / `quality:gate` / `quality:smoke` 是工程质量的核心机制。FinRobot 现状：测试分散，没统一入口，没强制门禁。

**三层定义（借鉴 cc-haha）：**

| 层 | 触发场景 | 包含 | 时长 |
|---|---|---|---|
| **smoke** | 本地手测 | 单 ticker 跑 DCF 端到端 | < 30s |
| **pr** | 每次 PR | 所有单测 + lint + tsc + ruff + mypy + smoke | 2-5 min |
| **gate** | release 前 | pr + 集成测试 + 多 model live | 15-30 min |

**实施步骤：**
1. `scripts/quality-pr.sh`：
   ```bash
   set -e
   echo "=== Python: ruff ==="
   uv run ruff check finrobot/ tests/
   echo "=== Python: mypy ==="
   uv run mypy finrobot/
   echo "=== Python: pytest ==="
   uv run pytest tests/ -q
   echo "=== Frontend: tsc ==="
   cd ui && npx tsc -b
   echo "=== Frontend: vitest ==="
   npm run test
   echo "=== Frontend: build ==="
   npm run build
   cd ..
   echo "=== Tauri: cargo check ==="
   cd src-tauri && cargo check
   ```

2. `scripts/quality-smoke.sh`：起 server → curl 几个端点 → curl /chat 一个简单问题 → assert response

3. `scripts/quality-gate.sh`：pr + 集成测试 + 多 model（DeepSeek / Anthropic / OpenAI 各跑一遍）

4. 配 GitHub Actions：PR 跑 quality:pr，main push 跑 gate

5. pre-commit hook：跑 quality:pr 的子集（lint + tsc）

**工作量：** 4-6 小时

**依赖：** Q.1（AGENTS.md 写好后才知道命令该叫什么）

---

### Q.3 Coverage ratchet

**为什么做：** Coverage 只升不降的"棘轮"机制——每次 PR 强制覆盖率 ≥ 上次。防止"测试越加越少"的腐烂。

**cc-haha 的实现：**
- `artifacts/coverage/` 存历史 baseline
- PR 时跑 coverage 对比，低于 baseline 报错
- 允许显式 override（需要 PR 描述里写理由）

**FinRobot 实施步骤：**
1. Python：用 `coverage.py`，存 `.coverage` baseline 到 git
2. TypeScript：用 `vitest --coverage`，存 `coverage-baseline.json`
3. `scripts/check-coverage.sh`：对比当前 vs baseline，低于报错
4. CI 跑 check-coverage，失败 block merge

**工作量：** 3-4 小时

**依赖：** Q.2

---

## 附录 A：不做的事（明确否决）

| 项 | 不做的理由 |
|---|---|
| **直接 cp cc-haha 任何源码** | License 不兼容，违反 Apache 2.0 责任链 |
| **换 npm → Bun** | 前端只占 15% 工作量，迁移成本 > 收益。参考会话讨论 |
| **换 React → Vue / Svelte** | 团队已 P1-P5 React 投入，无价值。坚持 React |
| **Computer Use 集成（CC 那种）** | 金融场景用不到。审计上反而成负担 |
| **OAuth Provider 集成（个人微信 / Google 等）** | 没必要也不合规（企业微信 / SSO 单独考虑） |
| **MCP server 角色** | FinRobot 是 MCP client（用别的 MCP server 提供数据），不做 server。除非以后变成 marketplace 才需要 |

---

## 附录 B：执行顺序建议

**第一波（P0 全做完，让 app 真正能用）：**
1. P0.1 动态端口 + Tauri command（**最先做**，其他都依赖）
2. P0.2 waitForHealth bootstrap
3. P0.3 CORS + 绝对 URL fetch

**第二波（P1 短期完整化）：**
4. P1.3 Token 用量统计（最独立，可单飞）
5. P1.1 权限审批 UI（依赖 P0.2 的 bootstrap）
6. P1.2 多 ticker 工作空间（最复杂，留到 P1 最后）

**第三波（P2 让 app 能分发）：**
7. P2.1 Python 解释器打包（**P2 全部依赖**）
8. P2.2 macOS ad-hoc sign
9. P2.3 跨平台 helper
10. P2.4 macOS 公证（Apple 账号审批等候期可以同时进行别的）
11. P2.5 Windows 签名
12. P2.6 GitHub Actions release pipeline

**第四波（P3 扩展）：**
- P3.1 定时任务（最独立）
- P3.2 H5 远程访问
- P3.3 IM adapter（4 个 IM 按用户优先级，从飞书开始）

**横向（Q 工程质量）：**
- Q.1 AGENTS.md：跟 P0 同步做
- Q.2 三层质量门：跟 P0 同步做
- Q.3 Coverage ratchet：P0 完成后

---

## 附录 C：跟 cc-haha 对应的文件 ref

供你想"查原版怎么写"时用：

| FinRobot 项 | cc-haha 参考 |
|---|---|
| P0.1 动态端口 | `desktop/src-tauri/src/lib.rs`（get_server_url command） |
| P0.2 waitForHealth | `desktop/src/hooks/useHealthCheck.ts` |
| P1.1 权限审批 | `src/components/` 里 PermissionDialog 类组件 |
| P1.2 多项目 | `src/screens/` 里 ProjectManager / WorktreeManager |
| P1.3 Token 用量 | `src/components/TokenUsagePanel` |
| P2.1 Python 打包 | `desktop/sidecars/` 目录 + `desktop/scripts/build-macos-arm64.sh` |
| P2.2 ad-hoc sign | `desktop/scripts/` 里 sign-* 脚本 |
| P2.3 跨平台 helper | `runtime/mac_helper.py` + `win_helper.py` |
| P2.6 GH Actions release | `.github/workflows/release-desktop.yml` |
| P3.1 定时任务 | `src/scheduler/` |
| P3.2 H5 访问 | `src/server/` 的 remote-access 模块 |
| P3.3 IM adapter | `adapters/{feishu,dingtalk,telegram,wechat}/` |
| Q.1 AGENTS.md | `AGENTS.md` 根目录 |
| Q.2 三层质量门 | `package.json` scripts + `scripts/quality-*.ts` |

详细 line-level ref 见 `docs/cc-haha-borrowables.md`。

---

**本文档版本：** v1 · 撰写于 cc-haha 调研后  
**配套调研：** `docs/cc-haha-borrowables.md`（636 行模式分析）  
**License 承诺：** 所有借鉴项以"模式参考 / 自写实现"为准，commit message 注明来源
