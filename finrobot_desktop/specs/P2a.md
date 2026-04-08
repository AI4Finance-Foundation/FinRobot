> **状态：✅ 已完成（2026-04-01）**
>
> 实现文件：
> - 新增：`providers/fmp_provider.py`、`providers/finnhub_provider.py`、`providers/sec_provider.py`
> - 修改：`models/financial.py`（D&A 字段）、`compute/dcf.py`（FCF 公式修复）、`data/layer.py`（链式回退）、`compute/extractor.py`（多 provider 提取）、`config.py`（新 API key 字段）
> - 测试：30 个新测试，288 测试全过，7/7 验收标准通过。

---

# P2a — 数据源扩展（FMP / Finnhub / SEC EDGAR）

**状态**：✅ 已完成
**前置条件**：P1.5 ✅，P1c ✅
**目标**：接入更多数据源，提升金融数据的覆盖面和质量

---

## 为什么 P2a 是现在最重要的

P1.5 的确定性计算 + P1c 的 Desktop App 已经建立了核心体验。
但 yfinance 数据有明显短板：
- 无 D&A（折旧摊销）数据 → DCF 的 FCF 公式不完整（已知 P1.5 限制）
- 财务数据覆盖有限（非美股、小市值公司数据缺失多）
- 无 SEC EDGAR 文件（10-K/10-Q）→ 无法做深度基本面分析
- 数据更新频率和准确性不如付费源

**P2a 解决的核心问题**：让金融计算从"yfinance 能给什么就算什么"变为"该有的数据都有"。

---

## 范围

### 包含
- **FMP（Financial Modeling Prep）Provider**：财务报表、企业估值数据、D&A 明细
- **Finnhub Provider**：实时行情、基本面数据、公司概况
- **SEC EDGAR Provider**：10-K/10-Q 文件摘要、管理层讨论（MD&A section）
- **DataLayer 回退链增强**：多数据源的链式回退（FMP → Finnhub → yfinance）
- **修复 FCF 公式**：有了 D&A 数据后，完善 `compute/dcf.py` 的 FCF 公式
- **Extractor 多 provider 支持**：每个 provider 返回 `DataResult`（`data: dict`），extractor 根据 `data_source` 字段选择对应的 key 映射策略，输出统一的 `FinancialData`

### 不包含
- 实时行情推送（WebSocket / streaming）— P3+
- 替代数据（卫星、社交媒体情绪）— 超出范围
- Bloomberg / FactSet / Capital IQ 接入 — 需要机构级许可证
- 数据存储优化（当前 SQLite cache 足够）

---

## 架构决策

### 数据源优先级与回退链

```
FMP (最优先，数据最全)
 ↓ 失败/无 API key
Finnhub (次优先)
 ↓ 失败/无 API key
yfinance (兜底，免费)
```

用户通过 `.env` 配置 API key。有 key 的 provider 自动启用。

### 现有接口保持不变

`DataProvider` ABC（`interface.py:31-43`）不改。实际签名：

```python
# interface.py — 这是现有代码，不要改
class DataProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def capabilities(self) -> list[str]: ...

    @abstractmethod
    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult: ...
```

每个新 provider 实现同一个接口。注意参数是 `data_type: str`（单数），不是 `data_types: list[str]`。

### DataResult 与 FinancialData 的关系（澄清）

这是两个不同层次的东西，不能混淆：

```
Provider 层：  DataResult（data: dict，原始 key-value，各 provider 格式不同）
                    ↓  extractor.py 负责转换
Compute 层：   FinancialData（Pydantic model，统一的类型化字段）
```

- Provider 仍然返回 `DataResult`（不变）
- `extractor.py` 根据 `DataResult.provider` 字段（如 `"fmp"` / `"finnhub"` / `"yfinance"`）选择对应的 key 映射策略
- 输出统一的 `FinancialData`

### Extractor 多 provider 策略

当前 `extractor.py` 硬编码 yfinance 的 dict key（如 `data.get("revenue")`）。不同 provider 的 key 不同：

| 字段 | yfinance key | FMP key | Finnhub key |
|------|-------------|---------|-------------|
| D&A | ❌ 无 | `depreciationAndAmortization` | `depreciation` |
| revenue | `revenue` | `revenue` | `revenue` |
| EBITDA | `ebitda` | `ebitda` | `ebitda` |

**策略**：在每个 provider 内部做 key 归一化（返回 `DataResult` 前把 key 映射成统一格式），extractor 只处理一套 key。这比"extractor 里写 if provider == 'fmp'" 更干净。

```python
# 在 FMPProvider.fetch() 内部
raw = await self._call_fmp_api(ticker)
normalized = {
    "revenue": raw.get("revenue"),
    "ebitda": raw.get("ebitda"),
    "depreciation_amortization": raw.get("depreciationAndAmortization"),  # 归一化
    ...
}
return DataResult(data=normalized, provider="fmp", ...)
```

这样 extractor 只需要 `data.get("depreciation_amortization")`，不管数据来自哪个 provider。

### FinancialData 模型扩展

```python
# models/financial.py — 新增字段（P2a）
class FinancialData(BaseModel):
    # ... 现有字段 ...
    depreciation_amortization: float | None = None  # D&A，用于修复 FCF 公式
    rd_expense: float | None = None                 # R&D，用于调整型分析
    sga_expense: float | None = None                # SGA
    interest_expense: float | None = None           # 利息费用
```

新字段全部 `Optional`（`| None = None`），不破坏现有代码。yfinance provider 返回 None，FMP provider 返回实际值。

### DCFInputs 模型扩展

当前 `calculate_dcf()` 的输入是 `DCFInputs`，里面用的是比率（`ebitda_margin`），不是绝对值。
要让修复后的 FCF 公式使用 D&A，需要在 `DCFInputs` 中新增：

```python
# models/financial.py — DCFInputs 新增字段
class DCFInputs(BaseModel):
    # ... 现有字段 ...
    da_pct_revenue: float | None = Field(
        default=None,
        ge=0,
        le=0.5,
        description="D&A as % of revenue. None = use simplified FCF formula (P1.5)."
    )
```

为什么用 `da_pct_revenue`（比率）而不是绝对值：
- 与现有字段一致（`capex_pct_revenue`, `nwc_pct_revenue` 都是比率）
- DCF 投影是 per-year 的，比率可以直接乘以当年 projected_revenue
- 绝对值只代表历史一年，无法直接用于多年投影

### FCF 公式修复

```python
# compute/dcf.py — 修改 calculate_dcf() 内部的 FCF 计算循环
for g in inputs.revenue_growth_rates:
    rev = prev_revenue * (1 + g)
    ebitda = rev * inputs.ebitda_margin

    if inputs.da_pct_revenue is not None:
        # P2a 标准公式：EBIT(1-T) + D&A - CapEx - ΔNWC
        da = rev * inputs.da_pct_revenue
        ebit = ebitda - da
        fcf = ebit * (1 - inputs.tax_rate) + da - rev * inputs.capex_pct_revenue - rev * inputs.nwc_pct_revenue
    else:
        # P1.5 简化公式（回退）
        fcf = (
            ebitda * (1 - inputs.tax_rate)
            - rev * inputs.capex_pct_revenue
            - rev * inputs.nwc_pct_revenue
        )

    projected_revenue.append(rev)
    projected_ebitda.append(ebitda)
    projected_fcf.append(fcf)
    prev_revenue = rev
```

**注意**：`DCFResult` 需要新增一个字段标记使用了哪个公式：
```python
class DCFResult(BaseModel):
    # ... 现有字段 ...
    fcf_formula: str = "simplified"  # "simplified" | "standard_with_da"
```

### DataLayer 回退链（改为链式遍历）

当前 `layer.py` 的 `_select_fallback` 只找 primary 之后的**第一个**备选。三级回退链需要遍历整个 provider 列表：

```python
# layer.py — 修改 fetch() 方法（替代现有 primary + 单次 fallback）
async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
    # 1. Fresh cache hit
    cached = await self._cache.get(data_type, ticker)
    if cached is not None and not cached.is_stale:
        return cached.data

    # 2. 遍历所有支持该 data_type 的 provider（按优先级排序）
    last_error = None
    for provider in self._providers:
        if data_type not in provider.capabilities():
            continue
        try:
            result = await provider.fetch(ticker, data_type, **kwargs)
            await self._cache.set(data_type, ticker, result)
            return result
        except ProviderError as e:
            logger.warning(f"Provider '{provider.name}' failed for {ticker}/{data_type}: {e}")
            last_error = e
            continue  # 尝试下一个 provider

    # 3. All providers failed — return stale cache if available
    if cached is not None:
        stale = cached.data
        return stale.model_copy(
            update={"warnings": stale.warnings + ["stale data: all providers failed"]}
        )

    # 4. No data anywhere
    msg = f"Data unavailable for {ticker}/{data_type}: all providers failed and no cache exists."
    logger.error(msg)
    return DataResult(data={"error": msg}, provider="none", ticker=ticker,
                      data_type=data_type, timestamp=datetime.now(tz=timezone.utc), warnings=[msg])
```

现有的 `_select_provider` 和 `_select_fallback` 两个方法可以删掉，用上面的 for 循环替代。

### SEC EDGAR User-Agent 要求

SEC EDGAR API **强制要求** `User-Agent` header（格式：`CompanyName AdminEmail`），不设会被 403 拒绝。

需要在 `FinAgentSettings` 中新增：

```python
# config.py
class FinAgentSettings(BaseSettings):
    # ... 现有字段 ...
    sec_user_agent: str = "FinAgent admin@example.com"  # SEC EDGAR 强制要求
```

用户应在 `.env` 中设置真实的公司名+邮箱。

---

## 实现顺序

### File 1：`finagent/engine/models/financial.py`（修改）

1. `FinancialData` 新增 Optional 字段：`depreciation_amortization`, `rd_expense`, `sga_expense`, `interest_expense`
2. `DCFInputs` 新增 `da_pct_revenue: float | None = None`
3. `DCFResult` 新增 `fcf_formula: str = "simplified"`

### File 2：`finagent/engine/compute/dcf.py`（修改）

修复 FCF 公式：
- `inputs.da_pct_revenue is not None` 时用标准公式 `EBIT(1-T) + D&A - CapEx - ΔNWC`
- 否则回退到 P1.5 简化公式
- 设置 `result.fcf_formula` 为 `"standard_with_da"` 或 `"simplified"`

### File 3：`finagent/config.py`（修改）

`FinAgentSettings` 新增：
- `fmp_api_key: str = ""`
- `finnhub_api_key: str = ""`
- `sec_user_agent: str = "FinAgent admin@example.com"`

### File 4：`finagent/engine/data/providers/fmp_provider.py`（新建）

FMP API 客户端。使用 `httpx.AsyncClient` 调用 FMP REST API。
- 实现 `DataProvider` 接口：`name` = `"fmp"`，`capabilities` = `["financials", "price"]`
- `fetch(ticker, data_type, **kwargs)` → 返回 `DataResult`
- 内部做 key 归一化（`depreciationAndAmortization` → `depreciation_amortization`）
- API key 通过 `FinAgentSettings.fmp_api_key` 注入（构造器参数），不读 `os.environ`

### File 5：`finagent/engine/data/providers/finnhub_provider.py`（新建）

Finnhub API 客户端。同样使用 `httpx.AsyncClient`。
- 实现 `DataProvider` 接口：`name` = `"finnhub"`，`capabilities` = `["financials", "profile"]`
- `fetch(ticker, data_type, **kwargs)` → 返回 `DataResult`
- 内部做 key 归一化

### File 6：`finagent/engine/data/providers/sec_provider.py`（新建）

SEC EDGAR API（免费，无需 key，但有 rate limit + 强制 User-Agent）。
- 实现 `DataProvider` 接口：`name` = `"sec_edgar"`，`capabilities` = `["filings"]`
- `fetch_10k_summary(ticker)` → 最近年度报告摘要
- `fetch_mdna(ticker)` → Management Discussion & Analysis section
- 使用 SEC EDGAR XBRL/full-text search API
- 构造器参数：`user_agent: str`（从 `FinAgentSettings.sec_user_agent` 注入）
- 所有 HTTP 请求带 `User-Agent: {user_agent}` header

### File 7：`finagent/engine/data/layer.py`（修改）

将 `fetch()` 改为链式遍历所有 provider（见上方"DataLayer 回退链"section），删除 `_select_provider` 和 `_select_fallback`。

### File 8：`finagent/engine/compute/extractor.py`（修改）

在 `extract_financial_data()` 中新增 D&A 字段提取：
```python
depreciation_amortization=data.get("depreciation_amortization"),  # FMP 提供，yfinance 返回 None
```

不需要 `if provider == "fmp"` 分支——因为 provider 内部已做 key 归一化，extractor 只读统一的 key。

### File 9：`tests/unit/test_fmp_provider.py`、`test_finnhub_provider.py`、`test_sec_provider.py`（新建）

每个 provider 的单元测试（mock HTTP responses）：
- 正常响应 → 返回正确的 DataResult
- API 错误 → 抛出 ProviderError
- 超时 → 抛出 ProviderError
- FMP 测试必须验证 key 归一化（`depreciationAndAmortization` → `depreciation_amortization`）

### File 10：`tests/unit/test_dcf_with_da.py`（新建）

修复后的 FCF 公式测试：
- 有 `da_pct_revenue` 时：标准公式结果，`fcf_formula == "standard_with_da"`
- 无 `da_pct_revenue` 时（`None`）：回退到简化公式，`fcf_formula == "simplified"`
- 手算验证，引用 Damodaran Chapter 12

### File 11：`tests/unit/test_data_layer_chain.py`（新建）

回退链测试：
- 3 个 mock provider（FMP/Finnhub/yfinance），第一个失败 → 自动尝试第二个
- 全部失败 → 返回 stale cache
- 无 cache → 返回 error DataResult

---

## 验收标准

1. `finagent research AAPL`（有 FMP key）→ 输出中 DCF 使用标准 FCF 公式（`fcf_formula == "standard_with_da"`），无"simplified formula"警告
2. `finagent research AAPL`（无 FMP key）→ 自动回退到 yfinance，DCF 使用简化公式（`fcf_formula == "simplified"`）
3. FMP provider 单元测试通过，mock 数据覆盖正常/异常/超时三种场景
4. D&A 字段出现在 FinancialData 中，`DCFInputs.da_pct_revenue` 传入 DCF 计算
5. SEC EDGAR provider 能获取最近 10-K 的 MD&A section，HTTP 请求带正确的 User-Agent header
6. DataLayer 回退链测试通过：FMP 失败 → Finnhub → yfinance，全部失败 → stale cache
7. 所有现有测试继续通过（不破坏 P1.5/P1c）

---

## 不可替代性检查

"如果删掉 P2a 的代码，给用户 yfinance + LLM，能得到一样的结果吗？"

- **FMP/Finnhub provider**：能提供 yfinance 没有的 D&A 数据 → DCF 更准确 ✓
- **FCF 公式修复**：确定性计算，LLM 做不到 ✓
- **Provider 回退链**：自动降级 + warning，用户可见的数据质量标注 → 超过手动操作 ✓
- **SEC EDGAR**：结构化获取 10-K 内容，不依赖 LLM 记忆或编造 ✓

---

## 已知风险

| 风险 | 影响 | 缓解方案 |
|------|------|----------|
| FMP API 免费 tier 限制（250次/天） | 开发/测试受限 | 本地 cache aggressive（24h TTL），测试用 mock |
| SEC EDGAR rate limit（10 req/s） | 批量分析时变慢 | 加 rate limiter，P2b 考虑批量优化 |
| SEC EDGAR 强制 User-Agent | 不设置会被 403 | config 中加 `sec_user_agent` 字段，`.env.example` 注明 |
| 不同 provider 数据口径不一致 | 同一公司不同源数据可能差异 5-10% | provider 内部 key 归一化 + 输出标注 `data_source` |

---

## 与现有代码的对齐清单

以下确认 spec 与现有代码一致，避免实现时发现不匹配：

| 项目 | 现有代码 | spec 已对齐 |
|------|----------|-------------|
| Provider 接口签名 | `fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult` (`interface.py:43`) | ✅ |
| Config 类名 | `FinAgentSettings` (`config.py:7`) | ✅ |
| 回退逻辑位置 | `layer.py` 的 `DataLayer` 类，不存在 `router.py` | ✅ |
| DCF 输入是比率 | `DCFInputs.ebitda_margin`/`capex_pct_revenue` 都是比率 | ✅ 新增 `da_pct_revenue` 保持一致 |
| DataResult vs FinancialData | `DataResult.data: dict`（provider 层） → `extractor.py` → `FinancialData`（compute 层） | ✅ |
| httpx 依赖 | 已在 main deps（`pyproject.toml:43`） | ✅ 不需要动 |
