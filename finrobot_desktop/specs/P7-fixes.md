# P7-fixes — P7 审计修复指令

> **来源：** Fin 监督工作站 2026-04-23 完整审计，5 个 agent 并行扫描全部 P7 代码。
> **范围：** Track 0 已提交 (`078cf00`)，Track A-E 未提交代码的全部缺陷。
> **原则：** 按 Batch 顺序修复。每个 Batch 修完跑一次 `pytest` + `ruff check`，确认无回归再进下一个 Batch。
> **验收：** 修完后回 Fin 工作站复审。不要自行标记"已修复"。

---

## Do NOT

- 不要为了修 bug 引入新依赖
- 不要重构不在修复范围内的代码
- 不要修改已提交的 Track 0 代码（`078cf00`）
- 不要把多个 Batch 的修复混在一个 commit 里——每个 Batch 独立 commit

---

## Batch 1 — 安全（最高优先级，必须第一个修）

这些问题让无认证服务暴露到网络，或允许 XSS 注入。不修就不能提交。

### Fix 1.1: deploy.sh 绑定地址回归 (F1)

**文件：** `deploy.sh:9-10`

**问题：** `--host 0.0.0.0` 硬编码，绕过了 C5 修复（CLI 默认 `127.0.0.1`）。任何人运行 `./deploy.sh start` 都会把无认证服务暴露到所有网络接口。

**修法：**

```bash
# 改前
HOST="${FINAGENT_HOST:-0.0.0.0}"
uv run finagent serve --host 0.0.0.0 --port 8000 &

# 改后
HOST="${FINAGENT_HOST:-127.0.0.1}"
PORT="${FINAGENT_PORT:-8000}"
echo "Starting FinAgent server on ${HOST}:${PORT}..."
echo "WARNING: To expose to network, set FINAGENT_HOST=0.0.0.0 (no authentication!)"
uv run finagent serve --host "$HOST" --port "$PORT" &
```

**验证：** `grep "0.0.0.0" deploy.sh` 返回 0 行（只出现在 WARNING 文本中不算）。

---

### Fix 1.2: /api/web/run 无限流 (F2)

**文件：** `finagent/web/__init__.py`（`run_pipeline` 路由函数附近）

**问题：** 无并发限制。每次 POST 创建一个 `asyncio.create_task()`，消耗 LLM API 配额。`_MAX_TASKS=500` 只限记录条数，不限运行中的 task。

**修法：** 在 `finagent/web/tasks.py` 中添加并发控制：

```python
_MAX_RUNNING = 3  # 最多同时运行 3 个 pipeline

def running_count() -> int:
    return sum(1 for t in _tasks.values() if t.status == "running")
```

在 `__init__.py` 的 `run_pipeline` 路由中：

```python
from finagent.web.tasks import running_count, _MAX_RUNNING

if running_count() >= _MAX_RUNNING:
    return JSONResponse(
        {"error": f"Too many running tasks (max {_MAX_RUNNING}). Try again later."},
        status_code=429,
    )
```

**验证：** 启动 server，连续发 5 个 POST `/api/web/run`，第 4 个开始返回 429。

---

### Fix 1.3: XSS — innerHTML 拼接未转义数据 (H7)

**文件：** `finagent/web/templates/index.html:243-265`，`finagent/web/templates/reports.html:50-53`

**问题：** `ticker`、`pipeline_type`、`status`、`report_url` 直接插入 `innerHTML`，API 直接调用可注入 `<img onerror=...>`。

**修法：** 添加转义函数，所有动态值通过转义后再插入：

```javascript
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
```

所有 `${t.ticker}` 改为 `${escapeHtml(t.ticker)}`，所有 `${t.pipeline_type}` 同理。

`report_url` 的 `<a href="...">` 需要额外验证 URL 以 `/` 开头：

```javascript
const safeUrl = t.report_url && t.report_url.startsWith('/') ? t.report_url : '#';
```

**验证：** `curl -X POST /api/web/run -d '{"ticker": "<img src=x onerror=alert(1)>", "pipeline_type": "research"}'`，在 `/web/` 页面查看历史，ticker 列显示转义后的文本而非执行脚本。

---

### Fix 1.4: report_view.html iframe src 验证 (H7 延伸)

**文件：** `finagent/web/templates/report_view.html:33`

**修法：** Python 端在渲染前验证 `report_url` 只能是相对路径：

```python
# __init__.py 中 report_view 路由
report_url = task.report_url or f"/api/report/html?ticker={task.ticker}"
if not report_url.startswith("/"):
    report_url = "#"  # 拒绝非相对路径
```

---

## Batch 2 — 金融正确性

这些问题导致回测和分析结果静默错误，损害项目公信力。

### Fix 2.1: Sharpe ratio riskfreerate 硬编码 (H1)

**文件：** `finagent/engine/backtest/backtrader_adapter.py:94`

**问题：** `riskfreerate=0.04` 是硬编码魔法数字，不可配置，无用户警告。

**修法：**

1. 在 `BacktestConfig` (engine.py) 中添加字段：
```python
risk_free_rate: float = Field(default=0.04, description="Annual risk-free rate for Sharpe ratio calculation")
```

2. 在 `_run_sync` 中使用 `config.risk_free_rate` 替代硬编码 `0.04`。

3. 在 `BacktestResult.warnings` 中无条件添加：
```python
warnings.append(f"Sharpe ratio assumes risk-free rate of {config.risk_free_rate:.1%}.")
```

**验证：** `BacktestResult.warnings` 中包含 risk-free rate 警告。

---

### Fix 2.2: 零佣金零滑点无警告 (H2)

**文件：** `finagent/engine/backtest/backtrader_adapter.py:82-97`

**修法：** 在 `_run_sync` 结尾、返回 `BacktestResult` 前：

```python
warnings.append(
    "Backtest assumes zero commission and zero slippage. "
    "Real trading returns will be lower."
)
```

**验证：** 任何回测结果的 `warnings` 列表包含此警告。`format_summary()` 输出中可见。

---

### Fix 2.3: TradeAnalyzer 含未平仓交易 (H3)

**文件：** `finagent/engine/backtest/backtrader_adapter.py:197-202`

**问题：** `analysis["total"]["total"]` 包含未平仓交易，`winning + losing < total` 时胜率被低估。

**修法：**

```python
# 改前
total = analysis.get("total", {}).get("total", 0)

# 改后
total = analysis.get("total", {}).get("closed", 0)
```

如果 `closed` 不存在（BackTrader 版本差异），回退到 `total` 并加 warning：

```python
total_info = analysis.get("total", {})
total = total_info.get("closed", total_info.get("total", 0))
if "closed" not in total_info and total > 0:
    warnings.append("Trade count may include open positions at backtest end.")
```

**验证：** 写一个测试：在回测结束时有未平仓头寸的场景，检查 `total_trades == winning + losing`。

---

### Fix 2.4: SMA fast < slow 代码校验 (H4)

**文件：** `finagent/engine/backtest/backtrader_adapter.py`（`_resolve_strategy` 或 SMA class）

**修法：** 在 `_resolve_strategy` 返回前、或 `_run_sync` 构建 cerebro 前：

```python
if strategy_name == "sma_crossover":
    fast = params.get("fast", 10)
    slow = params.get("slow", 30)
    if fast >= slow:
        raise ValueError(
            f"SMA crossover requires fast ({fast}) < slow ({slow}). "
            f"Swap the values or adjust parameters."
        )
```

**验证：** `BackTraderAdapter().run(BacktestConfig(strategy_params={"fast": 50, "slow": 10}, ...))` 抛出 `ValueError`。

---

### Fix 2.5: BacktestConfig start_date >= end_date 校验 (F5)

**文件：** `finagent/engine/backtest/engine.py:27-36`

**修法：** 添加 `model_validator`：

```python
from pydantic import model_validator

@model_validator(mode="after")
def _check_date_order(self) -> "BacktestConfig":
    if self.start_date >= self.end_date:
        raise ValueError(
            f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
        )
    return self
```

**验证：** `BacktestConfig(start_date="2024-01-01", end_date="2023-01-01", ...)` 抛出 `ValidationError`。

---

### Fix 2.6: matplotlib.use("Agg") 移到模块顶层 (F4)

**文件：** `finagent/engine/backtest/backtrader_adapter.py`

**修法：** 将 `matplotlib.use("Agg")` 从 `_render_chart` 函数内移到文件顶部（在 `import matplotlib` 之后、任何 pyplot import 之前）：

```python
# 文件顶部
try:
    import matplotlib
    matplotlib.use("Agg")
except ImportError:
    pass
```

从 `_render_chart` 中删除 `matplotlib.use("Agg")` 调用。

**验证：** `grep -n "matplotlib.use" backtrader_adapter.py` 只在文件前 20 行出现。

---

## Batch 3 — 数据完整性

这些问题导致分析结果基于不完整或错误的数据，用户看不到任何提示。

### Fix 3.1: run_analysis 数据错误静默传入 LLM (F3)

**文件：** `finagent/engine/analysis/prompts.py`（`run_analysis` 函数）

**问题：** `fin_result.data` 含 `{"error": msg}` 时不抛异常，LLM 收到全 N/A 表格照样生成"分析"。

**修法：** 在 `run_analysis` 中 `build_analysis_prompt` 调用前：

```python
if "error" in fin_result.data:
    raise ValueError(
        f"Failed to fetch financial data for {ticker}: {fin_result.data['error']}"
    )
```

**验证：** mock `DataLayer.fetch` 返回 `DataResult(data={"error": "timeout"})`，`run_analysis` 抛出 `ValueError`。

---

### Fix 3.2: competitors/overview 提示词要求 EV/EBITDA 但数据不含 EV (H5)

**文件：** `finagent/engine/analysis/prompts.py`

**两个方案选一个（推荐方案 A）：**

**方案 A（修数据）：** 在 `_build_financials_table` 中计算 EV 并包含：

```python
market_cap = data.get("market_cap")
total_debt = data.get("total_debt")
total_cash = data.get("total_cash")
if all(v is not None for v in (market_cap, total_debt, total_cash)):
    ev = market_cap + total_debt - total_cash
    lines.append(f"Enterprise Value: {_fmt_num(ev)}")
    ebitda = data.get("ebitda")
    if ebitda and ebitda > 0:
        lines.append(f"EV/EBITDA: {ev / ebitda:.1f}x")
```

**方案 B（修提示词）：** 从 `_COMPETITORS_PROMPT` 和 `_OVERVIEW_PROMPT` 中删除 EV/EBITDA 要求，改为 `Debt/EBITDA` 等可计算指标。

**验证：** 运行 `competitors` 分析，输出数据表中包含 EV 和 EV/EBITDA（方案 A），或提示词中不再提及 EV/EBITDA（方案 B）。

---

### Fix 3.3: cashflow 分析 FCF 公式无用户可见警告 (H6)

**文件：** `finagent/engine/analysis/prompts.py`（`_CASHFLOW_PROMPT`）

**修法：** 在 cashflow prompt 开头添加显式警告段落：

```python
_CASHFLOW_PROMPT = """
**Important: This analysis uses D&A as a proxy for CapEx. Actual CapEx may differ
significantly, especially for capital-intensive industries. Treat FCF estimates as
approximate.**

Analyze {ticker}'s cash flow statement...
"""
```

**验证：** `build_analysis_prompt("cashflow", ...)` 返回的 prompt 中包含 "D&A as a proxy" 警告文本。

---

## Batch 4 — 代码质量红线

这些问题违反 CLAUDE.md 的零容忍规则。

### Fix 4.1: except Exception 收窄 — prompts.py (M1)

**文件：** `finagent/engine/analysis/prompts.py:289-294`

```python
# 改前
except Exception:
    logger.warning(...)

# 改后
except (ValueError, RuntimeError, AttributeError, KeyError) as exc:
    logger.warning("Failed to fetch peer %s: %s", t, exc)
```

如果 `DataLayer.fetch` 有自定义的 `ProviderError`，也加上。

**验证：** `grep -n "except Exception" finagent/engine/analysis/prompts.py` 返回 0 行。

---

### Fix 4.2: except Exception 收窄 — backtrader_adapter.py (M2)

**文件：** `finagent/engine/backtest/backtrader_adapter.py:222`

```python
# 改前
except Exception as e:

# 改后
except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
```

**验证：** `grep -n "except Exception" finagent/engine/backtest/backtrader_adapter.py` 返回 0 行。

---

### Fix 4.3: asyncio task 泄漏 — evict 不取消 task (M3)

**文件：** `finagent/web/tasks.py`

**修法：**

1. 在 `TaskInfo` 中添加字段（不序列化）：
```python
_async_task: asyncio.Task | None = None  # 用 PrivateAttr 或 exclude from model_dump
```

2. 在 `__init__.py` 创建 task 后保存引用：
```python
async_task = asyncio.create_task(run_task(task, request.app.state))
task._async_task = async_task
```

3. 在 `_evict_oldest` 中取消运行中的 task：
```python
if task.status == "running" and task._async_task and not task._async_task.done():
    task._async_task.cancel()
```

**验证：** 创建 501 个 task（超过 _MAX_TASKS），被驱逐的 running task 的 asyncio.Task 状态为 cancelled。

---

### Fix 4.4: 循环导入 — tasks.py → server.py (M4)

**文件：** `finagent/web/tasks.py:93`

**问题：** `from finagent.server import _get_pipeline_factories` 是延迟导入，但形成 `server → web → tasks → server` 循环。

**修法：** 将 `_get_pipeline_factories` 提取到独立模块，例如 `finagent/engine/pipelines/registry.py`。或者通过参数注入：

```python
# tasks.py 的 run_task 改为接收 factory 函数作为参数
async def run_task(task: TaskInfo, pipeline_factory: Callable, deps: ...) -> None:
    ...

# __init__.py 调用时传入
from finagent.server import _get_pipeline_factories
asyncio.create_task(run_task(task, _get_pipeline_factories(), request.app.state))
```

**验证：** `grep -rn "from finagent.server" finagent/web/` 返回 0 行。

---

### Fix 4.5: strategy_agent assert 改 raise (M8)

**文件：** `finagent/engine/backtest/strategy_agent.py:159`

```python
# 改前
assert best_result is not None

# 改后
if best_result is None:
    raise RuntimeError("Strategy selection produced no results after all iterations")
```

---

### Fix 4.6: ANALYSIS_TYPES 与 _PROMPTS 手动同步 (M6)

**文件：** `finagent/engine/analysis/prompts.py`

```python
# 改前
ANALYSIS_TYPES: frozenset[str] = frozenset({...手动列举...})

# 改后
ANALYSIS_TYPES: frozenset[str] = frozenset(_PROMPTS)
```

**验证：** 在 `_PROMPTS` 中加一个假 key，`ANALYSIS_TYPES` 自动包含它。

---

### Fix 4.7: run_strategy_selection 接入 CLI/SDK (M10)

**文件：** `finagent/cli.py`（backtest 命令）、`finagent/sdk.py`

**问题：** `run_strategy_selection` 是 P7 最有价值的能力之一（LLM 迭代优化策略参数），但目前是死代码——没有任何用户入口。

**修法：** 在 CLI 的 `backtest` 命令中添加 `--auto` flag：

```python
@click.option("--auto", is_flag=True, help="Use LLM to automatically select and optimize strategy parameters")
```

当 `--auto` 时调用 `run_strategy_selection` 而非直接跑 `BackTraderAdapter`。

SDK 中添加 `abacktest_auto` 方法或在 `abacktest` 中添加 `auto_optimize: bool = False` 参数。

---

## Batch 5 — 文档同步

### Fix 5.1: README Quick Start 更新 (H8)

**文件：** `README.md`

**修法：** Quick Start 的命令列表补齐所有 P7 新增命令：

```bash
finagent backtest AAPL --strategy sma_crossover --start 2023-01-01 --end 2024-01-01
finagent analyze income AAPL
finagent ask AAPL "What are the main risk factors?"
```

状态行从 "P2c" 更新为当前实际阶段。

添加 Web UI 的使用说明（`finagent serve` 后访问 `/web/`）。

---

### Fix 5.2: ARCHITECTURE.md 更新 (H9)

**文件：** `ARCHITECTURE.md`

**修法：** 添加以下模块到项目结构图：

- `finagent/engine/backtest/` — 量化回测引擎（BackTrader 适配器 + LLM 策略优化）
- `finagent/engine/analysis/` — 独立财务分析工具（6 种分析类型 + RAG Q&A）
- `finagent/engine/rag/` — RAG 索引（BM25 + 可选 embedding）
- `finagent/web/` — Web App（FastAPI + Jinja2 + 任务管理）
- `tutorials/` — 4 个教程 Jupyter notebooks

更新实现优先级表，标明当前实际阶段。

---

### Fix 5.3: BACKLOG.md 更新 (H10 + L10)

**文件：** `BACKLOG.md`

**修法：**

1. 添加 P7 section，记录 Track 0-E 全部为 `[x]`
2. 将 P5 已修复的 ~10 个条目（D4, D5, D6, I1, I2, I3, I5, I6）从 `[ ]` 改为 `[x]`
3. 确认 P4 Future 条目的状态准确

---

### Fix 5.4: Spec P7.md chromadb 偏差标注 (M11)

**文件：** `specs/P7.md`（Track C.2）

**修法：** 在 Track C.2 处标注实际决策：

```markdown
### Task C.2: 可选 Embedding RAG（Phase 3，已决定不实现 ChromaDB）

~~chromadb>=0.4~~ — 改用 numpy cosine similarity，避免重依赖。
sentence-transformers 保留为可选依赖。EmbeddingIndex 延迟到需求明确时实现。
```

---

## 低优先级（可选修复）

以下问题不阻断提交，但建议顺手修掉：

| ID | 文件 | 修法 |
|---|---|---|
| L1 | `backtest/__init__.py` | 添加 `from .engine import BacktestConfig, BacktestResult` 等 re-export |
| L2 | `engine.py:24` | `strategy_params: dict = Field(default_factory=dict)` |
| L3 | `cli.py:370` | `click.Path(writable=True, dir_okay=False)` |
| L4 | `web/tasks.py:45` | 添加注释说明内存存储 + 重启丢失的设计决策 |
| L5 | `web/templates/*.html` | CDN `<script>` 添加 `integrity` + `crossorigin` 属性 |
| L6 | `tutorials/03_backtest.ipynb` cell 4 | `if result.win_rate is not None` 替代 `if result.win_rate` |
| L7 | `analysis/prompts.py` | `_build_financials_table` 的 key 常量与 `extractor.py` 共享（提取到 `models/constants.py`） |
| M7 | `tests/unit/test_analysis_prompts.py` | 为 `run_analysis` 添加 async 集成测试（至少覆盖 DataLayer 错误路径） |
| M9 | `backtrader_adapter.py:134` | `yf.download()` 改为通过 `YFinanceProvider` 或至少添加 retry |

---

## 执行顺序与验证

```
Batch 1 → pytest + ruff check → commit "fix(security): ..."
Batch 2 → pytest + ruff check → commit "fix(finance): ..."
Batch 3 → pytest + ruff check → commit "fix(data): ..."
Batch 4 → pytest + ruff check → commit "fix(quality): ..."
Batch 5 → commit "docs: sync README/ARCHITECTURE/BACKLOG with P7"
```

每个 Batch 完成后在 Fin 工作站执行复审。不要一口气全修完再审——分批修、分批审。

---

## 审计统计

| 严重度 | 数量 | Batch |
|---|---|---|
| 致命 | 5 | Batch 1 (2) + Batch 2 (2) + Batch 3 (1) |
| 高 | 10 | Batch 1 (2) + Batch 2 (4) + Batch 3 (2) + Batch 5 (2) |
| 中 | 14 | Batch 4 (7) + Batch 3 (1) + Batch 5 (3) + 低优先级 (3) |
| 低 | 10 | 可选修复 |
