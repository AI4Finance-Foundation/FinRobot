# P2c — 补齐 FinRobot 基线（图表 + 报告 + 数据处理 + 催化剂分析 + Desktop UI）

**状态**：📋 待实现
**前置条件**：P2a ✅
**对标基准**：FinRobot `finrobot_equity/` 模块（commit 5f5a381）
**目标**：让 FinAgent 的 equity research 端到端体验追平 FinRobot 并在金融计算质量上超越。不留技术债。

---

## 为什么 P2c 是现在最重要的

FinAgent 后端有了确定性计算（WACC/DCF/multiples，已超越 FinRobot），有了多数据源（FMP/Finnhub/SEC/yfinance），但**用户看到的只有 CLI 文本和一个骨架 Desktop App**。

FinRobot 已经有：
- 23+ 种图表（matplotlib）
- 多页 HTML + PDF 报告
- 3 年 forecast engine
- 催化剂分析 + 新闻情感分析
- Football field 估值综合图
- 数据清洗函数

**如果 FinAgent 开源时在输出质量上不如 FinRobot，项目就没有存在理由。** P2c 的目标是补齐这些差距。

---

## 范围

### 前置依赖：多年数据获取（P2c 的地基）

当前 provider 的 `fetch(ticker, "financials")` 只返回**单年** `DataResult`。但 `data_processor.py` 需要 5 年历史数据。

**解决方案**：在 DataLayer 新增 `fetch_historical()` 方法：

```python
# finagent/engine/data/layer.py — 新增
async def fetch_historical(
    self, data_type: str, ticker: str, years: int = 5, **kwargs
) -> list[DataResult]:
    """获取多年历史数据。

    FMP: 使用 ?limit={years} 参数（API 原生支持）
    Finnhub: 逐年调用 fetch() 并汇总
    yfinance: t.income_stmt 返回多年数据，extractor 拆成 list
    """
```

每个 provider 需要适配：
- **FMP**：`/income-statement/{ticker}?limit=5` — API 原生支持，改动最小
- **Finnhub**：`/stock/financials?symbol={ticker}&freq=annual` — 返回多年数据
- **yfinance**：`t.income_stmt` 返回 DataFrame（多列=多年），extractor 拆成 `list[DataResult]`

**实现顺序**：这是 Phase A 的 File 0（在 clean.py 之前），因为 data_processor.py 依赖它。

---

### 后端：7 个模块 + 1 个前置

#### 模块 0 — 多年数据获取（`data/layer.py` 修改 + providers 适配）

新增 `DataLayer.fetch_historical()`，每个 provider 加 `fetch_historical()` 或让 `fetch()` 支持 `years` kwarg。

#### 模块 1 — 数据清洗 + 处理增强（`compute/data_processor.py` 新建）

FinRobot 的 `financial_data_processor.py`（513 行）能做：
- 从 FMP 原始数据提取历史指标（Revenue, COGS, SG&A, EBITDA, EPS, PE）
- 计算 margins（Gross, Operating, EBITDA, SGA Ratio）
- 计算 YoY growth rates
- 3 年确定性 forecast（基于用户输入的 growth assumptions）
- CAGR 计算
- `clean_financial_number()` — 处理 commas, parentheses(负数), 字符串转 float
- 多字段名兼容（`costOfRevenue` / `costOfGoodsSold` / `totalCostOfSales`）

FinAgent 必须覆盖所有上述能力。数据清洗函数定义在 `clean.py`（模块 7），`data_processor.py` 导入使用。

```python
# finagent/engine/compute/data_processor.py
from finagent.engine.compute.clean import clean_financial_number, normalize_field_names

def extract_historical_metrics(
    financial_data: list[FinancialData],  # 多年数据
    price_data: PriceHistory | None = None,  # PE 计算需要价格
    years: int = 5,
) -> HistoricalMetrics:
    """From raw data, compute: Revenue Growth YoY, Gross/EBITDA/Operating margins,
    EPS, PE ratio, SGA ratio, CAGR."""
    ...

def forecast_financials(
    historical: HistoricalMetrics,
    revenue_growth_assumptions: list[float],  # e.g. [0.08, 0.07, 0.06] for 3 years
    margin_assumptions: MarginAssumptions,
) -> ForecastResult:
    """Deterministic 3-year forecast. User controls assumptions, code does math."""
    ...
```

新增 Pydantic models（`models/financial.py`）：
```python
class HistoricalMetrics(BaseModel):
    years: list[int]                    # [2021, 2022, 2023, 2024, 2025]
    revenue: list[float]
    revenue_growth_yoy: list[float | None]  # first year is None
    cogs: list[float]
    gross_profit: list[float]
    gross_margin: list[float]
    sga: list[float]
    sga_ratio: list[float]
    ebitda: list[float]
    ebitda_margin: list[float]
    operating_income: list[float]
    operating_margin: list[float]
    net_income: list[float]
    eps: list[float]
    pe_ratio: list[float | None]        # 需要 price_data 输入；无价格数据时全部 None
    cagr_revenue: float | None          # 5-year CAGR
    ticker: str
    price_data_available: bool = False  # 标记 PE 数据来源是否可靠

class MarginAssumptions(BaseModel):
    gross_margin_target: float | None = None   # None = use historical average
    ebitda_margin_target: float | None = None
    sga_ratio_target: float | None = None

class ForecastAssumptions(BaseModel):
    """记录 forecast 使用了什么假设，可追溯。"""
    revenue_growth_rates: list[float]
    gross_margin: float
    ebitda_margin: float
    sga_ratio: float
    tax_rate: float = 0.21

class ForecastResult(BaseModel):
    years: list[int]                    # [2026, 2027, 2028]（纯 int，"E" 标记由展示层添加）
    revenue: list[float]
    ebitda: list[float]
    net_income: list[float]
    eps: list[float]
    assumptions: ForecastAssumptions    # 类型化假设，不是 dict
```

#### 模块 2 — 图表生成引擎（`engine/charts/` 新建目录）

FinRobot 有 23+ 种图表，FinAgent P2c 覆盖 9 种核心图表（第 10 种 `irr_sensitivity` 留给 P2d）：

```
engine/charts/
├── __init__.py
├── base.py              # ChartConfig(统一配色、字体、尺寸) + render_to_base64()
├── revenue_ebitda.py    # Revenue & EBITDA 柱状图（历史 + 预测，预测用虚线/阴影区分）
├── margin_trend.py      # Gross/EBITDA/Operating margin 折线图
├── peer_comparison.py   # EV/EBITDA peer 对比柱图（target 用高亮色）
├── sensitivity.py       # DCF 敏感性热力图（WACC × TG，颜色编码）
├── football_field.py    # 多方法估值范围对比（横向柱状图）
├── price_chart.py       # 52 周价格折线图 + volume 柱图
├── eps_pe.py            # EPS & PE Ratio 双轴图
├── waterfall.py         # 估值 waterfall 图（Revenue → EBITDA → EV → Equity → Price）
├── radar.py             # P2c 范围 — 多维度财务雷达图（Growth/Profitability/Leverage/Efficiency/Valuation）
└── irr_sensitivity.py   # P2d 范围 — LBO IRR 敏感性矩阵（本阶段不实现）
```

统一使用 matplotlib，配色方案：深蓝 (#1a365d) + 金色 (#d4a843) + 灰色 (#6b7280)，专业金融报告风格。

每个图表函数签名：
```python
def render(data: SomeModel, config: ChartConfig | None = None) -> bytes:
    """Returns PNG bytes. Can be embedded in HTML via base64."""
```

**图表数据传递类型**（同时用于后端渲染和 SSE 传给前端）：

```python
class ChartDataPoint(BaseModel):
    """单个图表的数据。后端 matplotlib 和前端 recharts 都消费同一个数据结构。"""
    chart_type: Literal[
        "revenue_ebitda", "margin_trend", "peer_comparison",
        "sensitivity", "football_field", "price", "eps_pe",
        "waterfall", "radar"
    ]
    data: list[dict[str, float | str | None]]  # 格式因 chart_type 而异，见下表
    title: str
    x_label: str = ""
    y_label: str = ""

class StepChartData(BaseModel):
    """一个 pipeline 步骤产出的所有图表数据。"""
    charts: list[ChartDataPoint] = []
```

**每种 chart_type 的 data 契约**：

| chart_type | data 中每个 dict 的 expected keys | 示例 |
|---|---|---|
| `revenue_ebitda` | `{year: int, revenue: float, ebitda: float, is_forecast: bool}` | `{"year": 2024, "revenue": 394e9, "ebitda": 130e9, "is_forecast": false}` |
| `margin_trend` | `{year: int, gross_margin: float, ebitda_margin: float, operating_margin: float}` | `{"year": 2024, "gross_margin": 0.46, ...}` |
| `peer_comparison` | `{ticker: str, ev_ebitda: float, pe_ratio: float, is_target: bool}` | `{"ticker": "AAPL", "ev_ebitda": 22.5, "is_target": true}` |
| `sensitivity` | `{wacc: float, tg: float, implied_price: float \| null}` | `{"wacc": 0.09, "tg": 0.025, "implied_price": 245.0}` |
| `football_field` | `{method: str, low: float, mid: float, high: float}` | `{"method": "DCF", "low": 210, "mid": 245, "high": 280}` |
| `price` | `{date: str, close: float, volume: float}` | `{"date": "2024-01-15", "close": 185.3, "volume": 5.2e7}` |
| `eps_pe` | `{year: int, eps: float, pe_ratio: float \| null}` | `{"year": 2024, "eps": 6.42, "pe_ratio": 28.3}` |
| `waterfall` | `{label: str, value: float, is_total: bool}` | `{"label": "PV FCFs", "value": 159.5e9, "is_total": false}` |
| `radar` | `{dimension: str, value: float, benchmark: float}` | `{"dimension": "Growth", "value": 0.8, "benchmark": 0.6}` |

这张表是后端和前端的共享契约。后端 matplotlib `render()` 和前端 recharts 组件都按此格式消费数据。

#### 模块 3 — 报告模板引擎（`engine/reports/` 新建目录）

```
engine/reports/
├── __init__.py
├── html_renderer.py     # HTML 多页报告生成器
├── templates/
│   ├── equity_research.html   # 5 页 Jinja2 模板
│   ├── comps.html             # Comps 单页模板
│   └── dcf.html               # DCF 单页模板
└── pdf_renderer.py      # HTML → PDF（weasyprint 或 reportlab）
```

HTML 报告结构（对标 FinRobot 的 5 页模板）：
- **Page 1: 概览** — Ticker, 公司名, tagline, 关键指标卡片(Price, Market Cap, PE, EV/EBITDA), 推荐(Buy/Hold/Sell)
- **Page 2: 财务摘要** — 历史指标表格 + Revenue/EBITDA 图表 + Margin 趋势图 + 3 年 forecast
- **Page 3: 估值** — DCF 结果 + 敏感性热力图 + Comps 对比表 + Football field 图
- **Page 4: 催化剂 + 风险** — 催化事件列表 + 影响评估 + 风险清单
- **Page 5: 附录** — 详细财务报表 + 数据来源标注 + 免责声明

图表用 base64 内嵌 HTML。

#### 模块 4 — 催化剂分析（`engine/compute/catalyst.py` 新建）

FinRobot 的 `catalyst_analyzer.py`（410 行）能做：
- 6 类催化事件识别（product_launch / earnings / regulatory / acquisition / management / market）
- 情感分析（含分析师动作短语识别）
- 影响评估（1-5 级）
- 概率估算
- 催化事件排名

FinAgent 实现方式不同（不用关键词匹配，用 LLM 结构化输出）：

```python
class CatalystEvent(BaseModel):
    category: Literal["product_launch", "earnings", "regulatory", "acquisition", "management", "market"]
    headline: str
    sentiment: Literal["positive", "negative", "neutral"]
    impact_score: int = Field(ge=1, le=5)
    probability: float = Field(ge=0, le=1)
    reasoning: str

class CatalystAnalysis(BaseModel):
    events: list[CatalystEvent]
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    key_catalysts: list[str]  # top 3
```

LLM（通过 PydanticAI output_type）负责从新闻中提取结构化的 `CatalystAnalysis`。代码负责排序、过滤、格式化。

#### 模块 5 — 估值综合 + Football Field（`engine/compute/valuation_synthesis.py` 新建）

FinRobot 能做多方法加权平均 + football field 数据。FinAgent 必须覆盖并超越：

```python
class ValuationMethod(BaseModel):
    name: str                    # "DCF", "EV/EBITDA Comps", "P/E Comps"
    low: float                   # 估值范围下限（implied price）
    mid: float                   # 中间值
    high: float                  # 上限
    confidence: float = Field(ge=0, le=1)  # 置信度权重
    source: str                  # "FinAgent DCF (WACC 9.3%, TG 2.5%)"

class ValuationSynthesis(BaseModel):
    methods: list[ValuationMethod]
    weighted_price: float        # 加权平均目标价
    current_price: float
    upside_downside: float       # (weighted - current) / current
    # football_field 数据直接从 methods 派生（low/mid/high 已在 ValuationMethod 中），不另存 dict
```

#### 模块 6 — 新闻获取 + 情感分析（`engine/compute/news.py` 新建）

不复制 FinRobot 的 FinNLP 7 渠道爬虫（维护负担大、数据源不稳定）。
用 FMP News API + Finnhub News API（已有 provider，需扩展 capabilities 加 `"news"` 数据类型）获取原始新闻，LLM 做分类和情感分析。

**数据流**：
```
FMP/Finnhub provider.fetch(ticker, "news")  →  RawNewsItem（标题+URL+日期）
        ↓
news.py: classify_news(raw_items, agent)    →  LLM 做分类+情感（PydanticAI output_type=NewsItem）
        ↓
catalyst.py: analyze_catalysts(news_items)  →  CatalystAnalysis
```

```python
# finagent/engine/compute/news.py

class RawNewsItem(BaseModel):
    """从 provider 获取的原始新闻，未经 LLM 处理。"""
    title: str
    source: str
    published: datetime
    url: str

class NewsItem(BaseModel):
    """经 LLM 分类和情感分析后的新闻。"""
    title: str
    source: str
    published: datetime
    url: str
    category: Literal["earnings", "product", "regulatory", "macro", "analyst", "management", "other"]
    sentiment: Literal["positive", "negative", "neutral"]
    importance: int = Field(ge=1, le=5)
    summary: str

async def fetch_news(data_layer: DataLayer, ticker: str) -> list[RawNewsItem]:
    """从 FMP/Finnhub 获取原始新闻（走现有 provider 链式回退）。"""
    ...

async def classify_news(
    raw_items: list[RawNewsItem],
    agent: Agent,
    deps: FinAgentDeps,
) -> list[NewsItem]:
    """用 LLM 对原始新闻做分类 + 情感分析。"""
    ...
```

**FMP/Finnhub provider 需要扩展**：在 `capabilities()` 中加 `"news"`，`fetch()` 中加 `data_type == "news"` 分支。

**返回类型说明**：Provider 的 `fetch()` 仍然返回 `DataResult`（不改接口）。`DataResult.data` 中存 `{"news_items": [{"title": "...", "source": "...", ...}, ...]}`。`news.py` 的 `fetch_news()` 负责从 `DataResult.data["news_items"]` 转换为 `list[RawNewsItem]`。这样 provider 接口不变，类型转换在 compute 层完成。

#### 模块 7 — 数据清洗层（`engine/compute/clean.py` 新建）

```python
def clean_financial_number(value: str | float | int | None) -> float | None:
    """
    Handles:
    - Commas: "1,234,567" → 1234567.0
    - Parentheses (negative): "(1,234)" → -1234.0
    - Currency symbols: "$1,234" → 1234.0
    - Percentage: "12.5%" → 0.125
    - N/A, None, empty string → None
    - Already numeric → pass through
    """

# 多字段名兼容映射
FIELD_ALIASES = {
    "cost_of_revenue": ["costOfRevenue", "costOfGoodsSold", "totalCostOfSales", "cost_of_goods_sold"],
    "sga": ["sellingGeneralAndAdministrative", "sgaExpense", "selling_general_administrative"],
    "depreciation_amortization": ["depreciationAndAmortization", "depreciation", "da"],
    # ... 完整映射
}

def normalize_field_names(data: dict, aliases: dict = FIELD_ALIASES) -> dict:
    """Try all aliases for each canonical field name. First match wins."""
```

### 前端：Desktop UI 补完

#### 技术栈升级
- 安装 Tailwind CSS 4 + recharts + zustand
- 现有手写 CSS → Tailwind 渐进迁移
- useState → Zustand store（全局：ticker, 分析历史, 设置, 主题）

#### 多面板 Workspace 布局
```
┌─────────────────────────────────────────────────────┐
│ FinAgent  [Research] [DCF] [Comps] [Settings]  ⚙️   │
├────────────────────────┬────────────────────────────┤
│                        │                            │
│  分析结果（左）        │   图表 + 数据面板（右）   │
│  · 流式文本输出        │   · Revenue/EBITDA 图      │
│  · 步骤进度            │   · Sensitivity 热力图     │
│  · 推荐摘要卡片        │   · Peer 对比图           │
│                        │   · Football field         │
│                        │   · 财务数据表格           │
├────────────────────────┴────────────────────────────┤
│  Pipeline 进度条: ████████░░ Step 3/5 Valuation...   │
└─────────────────────────────────────────────────────┘
```

#### 图表渲染策略（双套实现，显式接受代价）

**事实**：同一张图需要两套实现：
- **HTML/PDF 报告** → Python matplotlib（生成静态 PNG，base64 内嵌）
- **Desktop 实时界面** → React recharts（交互式：hover、缩放）

**这意味着工作量翻倍**（9 种图表 × 2 套 = 18 个文件），且需要维护两套代码的视觉一致性。

**为什么不统一成一套**：
- 只用 matplotlib：Desktop 里嵌 base64 PNG 无法交互（hover、缩放），用户体验差
- 只用 recharts：HTML/PDF 报告无法嵌入 React 组件，需要额外的无头浏览器渲染

**降低维护成本的策略**：
- 两套实现共享同一个 `ChartConfig`（配色、字体），定义在 `engine/charts/base.py`
- 每种图表的**数据准备逻辑**只写一次（在 Python 端），前端只接收 JSON 数据并渲染
- 后端 matplotlib 图表的测试覆盖数据正确性，前端 recharts 只测渲染不崩溃

#### Settings 页面
- API Key 管理（FMP / Finnhub / Anthropic / DeepSeek / OpenAI）
- Model 选择
- 数据源优先级
- SEC User-Agent
- 存储到 electron-store + Electron `safeStorage` API 加密 API keys（`electron-store` 默认不加密，必须显式使用 `safeStorage.encryptString()` 加密敏感值后再存入）

#### 报告预览 + 下载
- 每个分析结果页底部："View Full Report" → 在新窗口中打开 HTML 报告
- "Download PDF" → 调用 `/api/export/pdf` 端点
- "Download Excel" → 调用 `/api/export/excel` 端点（留给 P2d）

### 不包含（P2d）
- LBO pipeline（FinRobot 没有，属于超越而非追平）
- IC Memo pipeline（同上）
- Earnings analysis pipeline（同上）
- spreadsheet_gen（Excel 输出带公式）
- SEC 10-K 深度解析 + RAG
- Backtesting（Backtrader 集成或等价）

---

## 实现顺序

### Phase A：后端数据处理 + 计算

**File 0a**: `finagent/engine/data/layer.py`（修改）
- 新增 `DataLayer.fetch_historical(data_type, ticker, years=5)` → `list[DataResult]`
- 测试：mock provider → 验证 fetch_historical 调用链和回退逻辑

**File 0b**: `finagent/engine/data/providers/fmp_provider.py`（修改）
- fetch 支持 `years` kwarg → 调用 `?limit=N` 多年查询
- 测试：mock FMP 5 年响应 → 验证 list[DataResult] 长度和年份排序

**File 0c**: `finagent/engine/data/providers/finnhub_provider.py`（修改）
- fetch 支持 `years` kwarg → 多年数据
- 测试：同上

**File 0d**: `finagent/engine/data/providers/yfinance_provider.py`（修改）
- fetch 支持 `years` kwarg → 拆 DataFrame 多列为 list[DataResult]
- 测试：mock yfinance DataFrame → 验证拆分正确

**File 1**: `finagent/engine/compute/clean.py`（新建）
- `clean_financial_number()`
- `FIELD_ALIASES` 映射表
- `normalize_field_names()`
- 测试：覆盖 commas、parentheses、currency、N/A、None

**File 2**: `finagent/engine/models/financial.py`（修改）
- 新增 `HistoricalMetrics`, `MarginAssumptions`, `ForecastAssumptions`, `ForecastResult`
- 新增 `CatalystEvent`, `CatalystAnalysis`
- 新增 `ValuationMethod`, `ValuationSynthesis`
- 注意：`ChartDataPoint` 和 `StepChartData` 不放 financial.py，定义在 `charts/base.py`（图表专属类型）
- `RawNewsItem` 和 `NewsItem` 定义在 `news.py`（模块内部类型，不跨模块传递，不加入 financial.py）
- **不更新 `StructuredOutput` Union**：`HistoricalMetrics`/`ForecastResult`/`ValuationSynthesis` 是确定性计算输出，不是 LLM `output_type`，不应混入 LLM output union。`CatalystAnalysis` 是 LLM 结构化输出，加入 Union。

**File 3**: `finagent/engine/compute/data_processor.py`（新建）
- `extract_historical_metrics()` — 从多年 FMP 数据提取结构化历史指标
- `forecast_financials()` — 3 年确定性 forecast
- `calculate_cagr()` — 复合年增长率
- 测试：手算验证，引用公式来源

**File 4**: `finagent/engine/compute/catalyst.py`（新建）
- `CatalystAnalyzer` — 接收新闻列表，用 LLM 提取结构化催化事件
- 排序、过滤、Top-N 选择（代码逻辑，不依赖 LLM）
- 测试：mock LLM 输出 + 排序/过滤逻辑验证

**File 5**: `finagent/engine/compute/valuation_synthesis.py`（新建）
- `synthesize_valuations()` — 多方法加权，football field 数据从 `methods` 字段直接派生
- 测试：3 种方法输入 → 加权平均验证

**File 6**: `finagent/engine/data/providers/fmp_provider.py`（修改）
- capabilities 加 `"news"`
- fetch 加 `data_type == "news"` 分支（调用 FMP News API）
- 返回 `DataResult(data={"news_items": [...]})`
- 测试：mock FMP news response → 验证 DataResult 结构

**File 7**: `finagent/engine/data/providers/finnhub_provider.py`（修改）
- 同上：capabilities 加 `"news"`，fetch 加 news 分支
- 测试：mock Finnhub news response

**File 8**: `finagent/engine/compute/news.py`（新建）
- `RawNewsItem` + `NewsItem`（模块内部类型，不放 financial.py）
- `fetch_news()` — 调用 DataLayer.fetch → 从 DataResult.data["news_items"] 转换为 list[RawNewsItem]
- `classify_news()` — LLM 分类 + 情感分析（PydanticAI output_type=NewsItem）
- 测试：mock DataLayer + mock LLM → 验证端到端流程

### Phase B：图表 + 报告

**File 9**: `finagent/engine/charts/base.py`（新建）
- `ChartConfig` — 统一配色（#1a365d / #d4a843 / #6b7280）、字体、尺寸
- `render_to_base64()` — matplotlib → PNG → base64 string
- `validate_png(data: bytes)` — 检查 magic bytes + 最小尺寸（供测试用）

**File 10a-10e**: `finagent/engine/charts/` 核心图表批次 1（5 个文件，逐个实现）

**在批次内严格遵守 Rule 1**：写 `revenue_ebitda.py` → 写 `test_revenue_ebitda.py` → 测试通过 → 再写 `margin_trend.py` → ...

- 10a: `revenue_ebitda.py` — 柱状图（历史实线 + 预测虚线）
- 10b: `margin_trend.py` — 多线折线图
- 10c: `peer_comparison.py` — 分组柱图（target 高亮）
- 10d: `sensitivity.py` — 热力图（seaborn-style）
- 10e: `football_field.py` — 横向范围柱图

每个图表的测试必须验证：
1. 输出是合法 PNG（`data[:4] == b'\x89PNG'`）
2. 图片尺寸符合 ChartConfig（decode 后检查 width/height）
3. matplotlib Figure 的 title 和 axis labels 正确（渲染前检查 `fig.axes[0].get_title()`）

**File 10f-10i**: `finagent/engine/charts/` 核心图表批次 2（4 个文件，逐个实现）
- 10f: `price_chart.py` — 折线 + volume
- 10g: `eps_pe.py` — 双轴图
- 10h: `waterfall.py` — 瀑布图
- 10i: `radar.py` — 多维度财务雷达图
- 同样的测试标准 + 同样的 one-at-a-time 流程
- 注意：`irr_sensitivity.py` 留给 P2d，本阶段不实现

**File 11**: `finagent/engine/reports/html_renderer.py`（新建）
- Jinja2 模板渲染
- 嵌入 base64 图表
- 5 页结构

**File 12**: `finagent/engine/reports/templates/`（新建 3 个模板）
- `equity_research.html` — 5 页 Jinja2 模板（对标 FinRobot 的完整报告）
- `comps.html` — Comps 单页模板（peer 表格 + 对比图）
- `dcf.html` — DCF 单页模板（敏感性表 + waterfall）

**File 13**: `finagent/engine/reports/pdf_renderer.py`（新建）
- HTML → PDF（weasyprint）
- 可选，如果 weasyprint 依赖太重用 reportlab 替代

**File 14**: `finagent/server.py`（修改）
- 新增 `/api/report/html?ticker=AAPL` — 返回完整 HTML 报告
- 新增 `/api/report/pdf?ticker=AAPL` — 返回 PDF 文件
- 修改现有 SSE 端点：`PipelineEvent` 新增 `chart_data: StepChartData | None = None` 字段
- `ChartDataPoint` 和 `StepChartData` 定义在模块 2（`engine/charts/base.py`），server.py 只 import 使用
- 每种 chart_type 的 data 契约见模块 2 的表格

### Phase C：Desktop UI 补完

**File 15**: 技术栈升级
- `desktop/package.json` 添加 tailwindcss@4, recharts, zustand, electron-store
- Tailwind CSS v4 使用 CSS-first 配置（不再需要 `tailwind.config.ts` 和 `postcss.config.ts`）：
  ```css
  /* desktop/src/index.css */
  @import "tailwindcss";
  ```
- `desktop/src/stores/appStore.ts` — Zustand 全局状态

**File 16**: 多面板 Workspace
- `desktop/src/components/Layout.tsx` — 左右分栏 + 底部进度条
- `desktop/src/components/DataPanel.tsx` — 右侧数据面板

**File 17a-17i**: 图表组件（recharts，9 种，逐个实现，与 matplotlib 一一对应）

**同样遵守 Rule 1**：写一个组件 → 写对应测试 → 通过 → 下一个。

- 17a: `RevenueEbitdaChart.tsx`
- 17b: `MarginTrendChart.tsx`
- 17c: `PeerComparisonChart.tsx`
- 17d: `SensitivityHeatmap.tsx`
- 17e: `FootballField.tsx`
- 17f: `PriceChart.tsx`
- 17g: `EpsPeChart.tsx`
- 17h: `WaterfallChart.tsx`
- 17i: `RadarChart.tsx`

**前端测试策略**（使用 vitest + @testing-library/react）：
- 每个组件写 `*.test.tsx`
- 测试内容：给定 mock `ChartDataPoint` → render 不崩溃 → 关键 DOM 元素存在（如 `<svg>`, recharts 的 `<Bar>` / `<Line>` 等）
- 不测像素内容（与后端 matplotlib 一致性靠人工对比 + ChartConfig 共享配色）
- **File 15 技术栈升级时**同步安装 vitest + @testing-library/react，CI 中 `npm run test`

**File 18**: Settings 页面
- `desktop/src/components/SettingsView.tsx`
- electron-store + `safeStorage` 加密 API keys（通过 preload.ts contextBridge 暴露加密/解密方法）

**File 19**: 报告预览 + 下载
- "View Full Report" 按钮 → 新窗口打开 HTML
- "Download PDF" 按钮 → 调用 API

**File 20**: 更新现有 View
- `ResearchView.tsx` — 加入图表渲染区域（从 structured 数据提取 chart_data）
- `DCFView.tsx` — 加敏感性热力图 + waterfall
- `CompsView.tsx` — 加 peer 对比柱图

**File 21**: 更新 App.tsx
- 接入 Zustand store
- 新增 Settings tab
- 使用 Layout 组件包裹所有页面

---

## 对标验收：FinRobot 基线检查

| FinRobot 能力 | FinAgent P2c 对应 | 验收方法 |
|---|---|---|
| Revenue/EBITDA 柱状图 | `charts/revenue_ebitda.py` + `RevenueEbitdaChart.tsx` | 运行 `finagent research AAPL`，检查报告中有 Revenue/EBITDA 图 |
| Margin 趋势图 | `charts/margin_trend.py` + `MarginTrendChart.tsx` | 同上 |
| Peer 对比图 | `charts/peer_comparison.py` + `PeerComparisonChart.tsx` | 运行 comps，检查有对比图 |
| Sensitivity 热力图 | `charts/sensitivity.py` + `SensitivityHeatmap.tsx` | 运行 DCF，检查有热力图 |
| Football field | `charts/football_field.py` + `FootballField.tsx` | 运行 research，检查估值综合有 football field |
| 多页 HTML 报告 | `reports/html_renderer.py` + 模板 | `GET /api/report/html?ticker=AAPL` 返回可浏览的 HTML |
| PDF 输出 | `reports/pdf_renderer.py` | `GET /api/report/pdf?ticker=AAPL` 返回可打印的 PDF |
| 3 年 forecast | `compute/data_processor.py` | forecast 数据出现在报告 Page 2 |
| 催化剂分析 | `compute/catalyst.py` | 报告 Page 4 有催化事件列表 |
| 数据清洗 | `compute/clean.py` | `clean_financial_number("(1,234)")` 返回 `-1234.0` |
| 估值综合 | `compute/valuation_synthesis.py` | 报告有 weighted target price + football field |

## 超越验收：FinAgent 比 FinRobot 更好的地方

| 领域 | FinRobot 水平 | FinAgent P2c 目标 |
|---|---|---|
| DCF 计算 | `net_debt = EV * 10%` 硬编码 | 使用实际 balance sheet 数据 + WACC CAPM ✅（P1.5 已实现） |
| 数据验证 | 从不检查 | 范围验证 + 异常值警告 ✅（P1.5 已实现） |
| 多模型 | 绑定 OpenAI | 任意 provider ✅（P0 已实现） |
| 测试 | 只检查 import | 每个计算函数有手算验证 + 公式引用 |
| 敏感性分析 | 固定 15% std_ratio | 真实的 WACC × TG 二维矩阵 ✅（P1.5 已实现） |
| 图表交互 | 静态 PNG | Desktop 用 recharts（hover 显示数值、缩放） |

---

## 验收标准

### 后端（10 条）
1. `clean_financial_number("$(1,234.56)")` 返回 `-1234.56`
2. `extract_historical_metrics()` 从 5 年 FMP 数据提取完整指标，所有 margin 有确定性计算
3. `forecast_financials()` 生成 3 年 forecast，手算验证（引用公式来源）
4. `CatalystAnalyzer` 从 10 条新闻中提取结构化 `CatalystAnalysis`（mock LLM 测试）
5. `synthesize_valuations()` 对 3 种估值方法做加权平均，结果有手算验证
6. 9 种核心图表都能生成合法 PNG（magic bytes `\x89PNG`）+ 尺寸符合 ChartConfig
7. HTML 报告渲染完整 5 页，图表内嵌
8. PDF 生成可打开、可打印
9. `/api/report/html?ticker=AAPL` 返回 200 + HTML content
10. 所有现有测试继续通过（不破坏 P1.5/P1c/P2a）

### 前端（6 条）
11. Desktop 打开后看到多面板 Workspace 布局
12. Research 结果页有 Revenue/EBITDA 图 + Margin 趋势图 + 敏感性热力图
13. DCF 结果页有交互式热力图（hover 显示数值）
14. Comps 结果页有 peer 对比柱图
15. Settings 页面可配置 API key 和 model，重启后保持
16. "View Full Report" 打开 HTML 报告，"Download PDF" 下载 PDF 文件

---

## 依赖管理

| 新增依赖 | 用途 | 是否必须 | 替代方案 |
|---|---|---|---|
| `matplotlib>=3.8` | 图表生成（HTML/PDF 报告用） | 是 | — |
| `jinja2>=3.1` | HTML 报告模板 | 是 | — |
| `weasyprint>=61` | HTML→PDF | 否 | reportlab（更轻但 API 更底层） |
| `recharts` (npm) | Desktop 图表 | 是 | lightweight-charts（功能少但体积小） |
| `tailwindcss` (npm) | Desktop 样式 | 是 | — |
| `zustand` (npm) | Desktop 状态管理 | 是 | — |
| `electron-store` (npm) | Settings 持久化 | 是 | — |
| `vitest` + `@testing-library/react` (npm) | 前端组件测试 | 是（devDependencies） | jest（更重但生态更大） |

Python 依赖加入 `pyproject.toml` main deps。npm 依赖加入 `desktop/package.json`。

---

## 已知风险

| 风险 | 影响 | 缓解方案 |
|------|------|----------|
| weasyprint 系统依赖（需要 pango/cairo） | macOS 需 brew install，Linux 需 apt | 提供安装指南；或用 reportlab 替代 |
| matplotlib 在无 display 环境报错 | CI 环境无 $DISPLAY | 使用 `Agg` backend（非交互） |
| recharts bundle size ~300KB | Desktop 体积增加 | 可接受 |
| Tailwind 迁移工作量 | 现有 CSS 需逐步替换 | 渐进迁移：新组件用 Tailwind，旧组件逐步 |
| 5 页 HTML 模板设计 | 需要前端设计能力 | 参考 FinRobot 的 `html_template_professional.py` 布局 |

---

## 不可替代性检查

- `data_processor.py`：确定性计算（margins, growth, CAGR, forecast），LLM 做不到可重复的数值 ✓
- `clean.py`：规则明确的数据清洗，不依赖 LLM 判断 ✓
- `charts/*`：代码生成的 PNG/SVG，不是 LLM 描述 ✓
- `reports/*`：结构化 HTML/PDF，内嵌图表，不是纯文本 ✓
- `catalyst.py`：LLM 提取结构化数据 + 代码排序/过滤/格式化（混合模式）✓
- `valuation_synthesis.py`：加权平均是确定性数学 ✓
- `news.py`：provider 获取原始数据（确定性）+ LLM 分类（结构化输出），两步分离 ✓

---

## Self-Review

### Wrapper Audit
- `clean.py`：规则清洗，LLM 做不到 → **不是包装器** ✓
- `data_processor.py`：margins/growth/CAGR/forecast 全部确定性算术 → **不是包装器** ✓
- `catalyst.py`：LLM 做结构化提取，代码做排序/过滤 → **混合模式，LLM 部分不可去除，代码部分不可替代** ✓
- `news.py`：provider fetch 是确定性 I/O；classify 用 LLM 但输出是 Pydantic model → **可接受** ✓
- `charts/*`：matplotlib 渲染 → **不是包装器** ✓
- `reports/*`：Jinja2 模板 + base64 图表嵌入 → **不是包装器** ✓
- `valuation_synthesis.py`：加权平均 → **不是包装器** ✓

### Data Typing Audit
- 所有跨边界数据传递使用 Pydantic model（`HistoricalMetrics`, `ForecastResult`, `CatalystAnalysis`, `ValuationSynthesis`, `NewsItem`）
- `ValuationSynthesis.football_field` 已删除 `dict` 字段，改为从 `methods: list[ValuationMethod]` 派生
- `ForecastResult.years` 是 `list[int]`（纯整数），"E" 标记由展示层添加
- `HistoricalMetrics.pe_ratio` 标注为需要 `price_data` 输入，无价格数据时为 `None`

### Test Honesty Audit
- `clean_financial_number` 测试用字面量期望值，不用公式推导
- `forecast_financials` 测试必须手算并引用公式来源
- `synthesize_valuations` 测试必须手算加权平均
- 图表测试必须验证：(1) 合法 PNG magic bytes，(2) 尺寸符合 ChartConfig，(3) Figure 的 title/axis labels 正确。"生成非空 bytes"不够。
- `classify_news` 测试用 mock LLM，验证输出结构而非 LLM 判断质量

### README Audit
- P2c 完成后需更新 README：
  - 当前功能列表加入：HTML/PDF 报告、图表生成、催化剂分析、估值综合
  - Known Limitations 更新：新闻分析依赖 LLM 分类准确性
  - Quick Start 更新：Desktop app 截图替换（不再是骨架）

### ARCHITECTURE.md 同步
- P2c 完成后（不是实现前）同步更新 ARCHITECTURE.md：
  - 目录结构加入 `charts/`, `reports/`, `compute/news.py`, `compute/catalyst.py`, `compute/data_processor.py`, `compute/clean.py`, `compute/valuation_synthesis.py`
  - Layer 2 Data Layer section 加入 `fetch_historical()` 说明
  - Provider 表格加入 news capability
  - Desktop App section 更新为完整 UI 状态
- **不在实现前更新**——避免再次出现"文档先于代码"导致的声明失实

### 额外检查
- `/health` endpoint 的 `"phase"` 字段已更新为 P2c（N3 修复时改了）
- 图表双套实现（matplotlib + recharts）的视觉一致性需要人工对比验证，不能只靠自动测试
