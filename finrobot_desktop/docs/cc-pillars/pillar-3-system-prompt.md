# Pillar 3: System Prompt 装配 — 研究与 FinRobot 设计决策

| | |
|---|---|
| **版本** | 0.2 草案 |
| **日期** | 2026-05-12 |
| **作者** | Architect AI (Opus 4.7) |
| **状态** | v0.2 加 `extra_static_prefix` kwarg 支持 Pillar 7 F-P7-4 |
| **前置** | Pillar 1 v0.7、Pillar 2 v0.3 |
| **原始报告** | `raw/cc-pillar-3-raw.md`、`raw/homepilot-pillar-3-raw.md` |

---

## Changelog

### v0.2(2026-05-12)

修评审 I8(版本号悬空)+ 配合 Pillar 7 v0.2 F-P7-4:
- `build_system_prompt` 加 `extra_static_prefix: str | None = None` kwarg(§4.2):若非 None,作为 0 层嵌入静态部分最前(在 identity / data_discipline / analyst_style / market_context 之前),与它们共同参与 prompt cache prefix
- 使用场景:Pillar 7 v0.2 spawn_subagent 把 `agent_def.system_prompt` 嵌入子 agent 的静态部分,**不破坏 STATIC_BOUNDARY_MARKER** 位置;父子 agent 共用同一 cache 前缀(尾部 6 层共享部分)
- 5 个 analyst style 名单确认:`value / growth / quant / education / ic_memo`(§4.3,与 Pillar 1 v0.7 `AgentProfile.analyst_style` literal 一致)
- 自审 F-P3-X 6 处 v0.2 仍未实施,留 v0.3

### v0.1(2026-05-12)

- 初版 7 层装配 + 5 analyst style + STATIC_BOUNDARY_MARKER + memory injection point + 6 处自审

---

## 0. TL;DR

- **CC**：12+ 层 static/dynamic 边界分隔的精密装配，outputStyles 文件式分发（.md），完整 prompt caching 整合
- **homepilot**：4 层简单字符串拼接，decision_styles 单 YAML 配置，无 caching
- **FinRobot v1**：**7 层** static/dynamic boundary 装配 + **5 个 analyst 风格** + AgentProfile 驱动 + Pillar 5 memory 预留挂载点 + prompt caching 友好

---

## 1. Pillar 3 的位置

System Prompt 装配决定**模型每次调用看到的人格、纪律、上下文**。这是 FinRobot "代码兜底的 LLM 金融分析" thesis 的核心承载——数据纪律约束（"数字必须来自工具"）就写在 system prompt 里强制 LLM。

Pillar 3 与其他 pillar 的关系：
- **Pillar 1** 已经定义 `QueryConfig.system_prompt: str`（最终拼好的字符串）和 `AgentProfile`（驱动 builder 的画像）。本 pillar 完成 builder 的实现规格
- **Pillar 2** 的工具描述（`tool.to_api_schema()`）由 query_loop 单独传给 API，**不进 system prompt 文本**
- **Pillar 5** 决定 memory 怎么存 / 怎么 invalidate；本 pillar 只定义 memory 注入的 hook point
- **Pillar 8** hooks 不在装配阶段干预 prompt——装配是确定性纯函数

---

## 2. 调研结论摘要

### 2.1 CC（详见 `raw/cc-pillar-3-raw.md`）

- **入口**：`getSystemPrompt(tools, model, ...)` 返回 `string[]`
- **结构**：STATIC（6 块）+ `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` + DYNAMIC（12+ 块）
- **OutputStyles**：.md 文件多源（项目 / 用户 / 插件 / 内置），数据结构含 `keepCodingInstructions` 标志，运行时切换
- **Memory**：`~/.claude/memory/` 目录，KAIROS / Team / 标准三种模式
- **Skills**：仅在 prompt 中列出名称，内容由 SkillTool 动态加载
- **Caching**：boundary 标记前的内容打 `cacheScope: 'global'`，TTL ~5 min

### 2.2 homepilot（详见 `raw/homepilot-pillar-3-raw.md`）

- **入口**：`_build_system_prompt(engine, user_id, decision_style) -> str`
- **结构**：4 层简单拼接：date + decision_style + 数据纪律 + memory
- **Decision styles**：4 种（professional / detailed / beginner_friendly / investor），单 `decision_styles.yaml` 配置
- **Memory**：MemoryStore Protocol，4 类型（USER / FEEDBACK / PROJECT / REFERENCE），20 条 / 25K 字符上限，XML 包裹
- **Skills**：有但**不进 system prompt**，query loop 动态调用
- **Caching**：无

---

## 3. CC vs homepilot vs FinRobot 决策对照

| 维度 | CC | homepilot | **FinRobot 决策** | 理由 |
|---|---|---|---|---|
| 入口签名 | `getSystemPrompt(tools, model, ...)` 返回 `string[]` | `_build_system_prompt(engine, user_id, decision_style)` 返回 `str` | **`build_system_prompt(profile, runtime_ctx) -> AssembledSystemPrompt`** | 强类型对象（含 caching boundary 元信息）|
| 层数 | 18+ | 4 | **7（含 boundary）** | 中庸：覆盖核心 + 不过度复杂 |
| Static/Dynamic 边界 | ✅ | ❌ | **✅ 沿用 CC 设计** | Prompt caching 命中率关键 |
| Output style 数据源 | 多源 .md | 单 YAML | **v1 Python hardcoded + v2 YAML 外置** | v1 工具集小，硬编码够用 |
| 风格切换语义 | 替换 identity + append style + 可跳过 coding section | append 一段 | **append 一段（不替换核心）** | 数据纪律约束等核心层不能被风格关掉 |
| Style 配置形态 | OutputStyleConfig dataclass | YAML dict | **AnalystStyleConfig dataclass + 5 个内置** | 类型安全 |
| Memory 接入 | 直接读 `~/.claude/memory/` | MemoryStore Protocol | **MemoryStore Protocol（Pillar 5 实现）** | 多租户 / DB 后端友好 |
| Skill 在 prompt 中 | 列名称 | 不列 | **不列（v1）+ v2 evaluate** | v1 工具数有限，列名增加 token 无收益 |
| Tool 描述位置 | 在 prompt 中（`getUsingYourToolsSection`）| API 单独 tools 参数 | **API 单独 tools 参数（不进 prompt）** | 与 PydanticAI 接口一致 |
| 时间注入 | env_info 中（语言中性）| 中文格式 | **按 config.language 双语** | 与 Pillar 1 双语 recovery msg 一致 |
| 数据纪律层 | ❌ | ✅ 硬编码英文 | **✅ 双语 + FinRobot 特有强化** | 核心差异化承载 |
| Caching 策略 | global scope + boundary | 无 | **boundary 标记 + Pillar 1 Claude 模型时启用** | 与 Pillar 1 §4.9 一致 |

---

## 4. FinRobot 实现规格

### 4.1 模块结构

```
finrobot/conversation/prompt/        # 全部新增
├─ __init__.py
├─ builder.py                        # build_system_prompt() 顶层装配
├─ types.py                          # AssembledSystemPrompt + AnalystStyleConfig
├─ layers/
│   ├─ identity.py                   # base persona "Alex"
│   ├─ data_discipline.py            # 数据纪律（核心差异化）
│   ├─ time_context.py               # 当前日期 / 财报季感知
│   ├─ analyst_style.py              # 5 个风格
│   ├─ fund_profile.py               # fund_id / fund_style / covered_tickers
│   ├─ market_context.py             # US / CN / HK 会计准则差异
│   └─ memory.py                     # memory 注入挂载点（Pillar 5 提供）
└─ styles.py                         # 5 个 AnalystStyleConfig 内置
```

### 4.2 顶层装配函数

```python
# finrobot/conversation/prompt/builder.py

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Literal

from .styles import get_style, STATIC_BOUNDARY_MARKER
from .layers import (
    build_identity, build_data_discipline,
    build_time_context, build_analyst_style,
    build_fund_profile, build_market_context,
    build_memory,
)


@dataclass(frozen=True)
class AssembledSystemPrompt:
    """装配产物。包含完整字符串 + caching boundary 元信息。"""

    text: str
    """供 PydanticAIAdapter 直接传给 API 的完整 system prompt。"""

    static_prefix_length: int
    """静态部分的字符长度。
    >0: PydanticAIAdapter 把前 static_prefix_length 字符标记为
        cache_control=ephemeral；剩余部分不缓存。
    =0: 不启用 caching（如非 Claude 模型）。
    """

    style_name: str
    """已应用的 analyst style 名称（用于 audit log）。"""


def build_system_prompt(
    profile: "AgentProfile",
    *,
    language: Literal["zh", "en"] = "zh",
    enable_caching: bool = True,
    memory_store: "MemoryStore | None" = None,
    user_id: str | None = None,
    extra_static_prefix: str | None = None,  # v0.2: Pillar 7 v0.2 F-P7-4
) -> AssembledSystemPrompt:
    """
    装配顺序(v0.2:7 层 + 可选 sub-agent 静态前缀):

    [STATIC 部分,可 cache]
      0. extra_static_prefix  — 仅 sub-agent 用:agent_def.system_prompt 嵌入静态部分(F-P7-4)
      1. identity            — 人格 "Alex"
      2. data_discipline     — 数据纪律(FinRobot 核心)
      3. analyst_style       — 5 种之一(v0.2: value / growth / quant / education / ic_memo)
      4. market_context      — US/CN/HK 会计准则

    --- STATIC_BOUNDARY_MARKER ---

    [DYNAMIC 部分,不 cache]
      5. time_context        — 当前日期 + 财报季
      6. fund_profile        — fund_id / 风格 / watchlist
      7. memory              — 用户记忆(Pillar 5 提供)
    """
    static_parts: list[str] = []
    dynamic_parts: list[str] = []

    style = get_style(profile.analyst_style)

    # v0.2: sub-agent 额外静态前缀(F-P7-4):agent_def.system_prompt 嵌入静态部分,
    # 不破坏 STATIC_BOUNDARY_MARKER 位置;此前缀也参与 prompt cache。
    if extra_static_prefix:
        static_parts.append(extra_static_prefix)

    static_parts.append(build_identity(language))
    static_parts.append(build_data_discipline(language))
    static_parts.append(build_analyst_style(style, language))
    static_parts.append(build_market_context(profile.market, language))

    dynamic_parts.append(build_time_context(language))
    dynamic_parts.append(build_fund_profile(profile, language))
    if memory_store and user_id:
        memory_text = build_memory(memory_store, user_id, language)
        if memory_text:
            dynamic_parts.append(memory_text)

    static_text = "\n\n".join(static_parts)
    dynamic_text = "\n\n".join(dynamic_parts)

    if enable_caching:
        full_text = f"{static_text}\n\n{STATIC_BOUNDARY_MARKER}\n\n{dynamic_text}"
        # PydanticAIAdapter 用 marker 切分，前段加 cache_control
        static_prefix_length = len(static_text) + 2  # 含 "\n\n"
    else:
        full_text = f"{static_text}\n\n{dynamic_text}"
        static_prefix_length = 0

    return AssembledSystemPrompt(
        text=full_text,
        static_prefix_length=static_prefix_length,
        style_name=profile.analyst_style,
    )


STATIC_BOUNDARY_MARKER = "<!-- FINROBOT_STATIC_BOUNDARY -->"
"""不可见 HTML 注释。PydanticAIAdapter 切分依据。LLM 看到忽略即可。"""
```

### 4.3 5 个 Analyst Style（v1 内置）

```python
# finrobot/conversation/prompt/styles.py

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AnalystStyleConfig:
    name: str
    display_name_zh: str
    display_name_en: str
    description_zh: str
    description_en: str
    prompt_zh: str
    prompt_en: str
    default_wacc_bias: Literal["conservative", "neutral", "aggressive"] = "neutral"
    """与 Pillar 5 联动：refinement 工具的 WACC 默认值偏向。"""


VALUE_STYLE = AnalystStyleConfig(
    name="value",
    display_name_zh="价值投资型",
    display_name_en="Value Investor",
    description_zh="偏向 P/E、P/B、DCF；保守 WACC；强调安全边际",
    description_en="P/E, P/B, DCF focused; conservative WACC; margin of safety",
    prompt_zh="""你是价值投资型分析师 Alex。

行为准则：
- 优先使用 P/E、P/B、EV/EBITDA、DCF 多估值方法交叉验证
- WACC 默认偏保守（行业基准 + 0.5%~1%）
- 强调安全边际：fair value 计算后必须给出 30% 折扣下的进场价
- 警惕周期性 / 一次性收益，强调可持续 ROE
- 对成长股保持怀疑——除非估值已含足够保守的增长假设

输出语气：直接、数据驱动、不卖弄成长叙事
""",
    prompt_en="""You are Alex, a value-focused analyst.

Behavioral guidelines:
- Cross-validate using P/E, P/B, EV/EBITDA, and DCF
- Default WACC biased conservative (industry baseline +0.5%~1%)
- Margin of safety emphasis: always provide entry price at 30% discount to fair value
- Be wary of cyclical/one-time earnings; emphasize sustainable ROE
- Skeptical of growth stocks unless valuation embeds conservative growth assumptions

Tone: direct, data-driven, no growth narrative theatrics
""",
    default_wacc_bias="conservative",
)


GROWTH_STYLE = AnalystStyleConfig(
    name="growth",
    display_name_zh="成长投资型",
    display_name_en="Growth Investor",
    # ... 类似结构，prompts 突出 TAM / S-curve / revenue growth durability
    description_zh="偏向 P/S、收入增速、TAM；容忍较高 terminal growth",
    description_en="P/S, revenue growth, TAM focused; higher terminal growth tolerance",
    prompt_zh="""你是成长投资型分析师 Alex。

行为准则：
- 优先使用 P/S、EV/Sales、收入复合增速、TAM 估算
- DCF terminal growth 容忍度较高（3-5%）但必须明确市场天花板
- 关注单位经济（unit economics）、客户获取成本、留存率
- 评估管理层执行力 - 历史 guidance 命中率 / 战略一致性
- 对短期亏损宽容前提：unit economics 已正、增长 > 30%

输出语气：前瞻、关注趋势、但要标注"高增长假设"风险
""",
    prompt_en="...",
    default_wacc_bias="aggressive",
)


QUANT_STYLE = AnalystStyleConfig(
    name="quant",
    display_name_zh="量化型",
    display_name_en="Quantitative",
    description_zh="因子暴露、统计套利、事件驱动；不读叙述",
    description_en="Factor exposure, stat arb, event-driven; no narrative",
    prompt_zh="""你是量化型分析师 Alex。

行为准则：
- 输出以**数字 + 因子暴露**为主，叙述限制在 30 字以内
- 提供：Beta、波动率、Sharpe、F-Score、Z-Score、动量分位
- 同行业百分位排名（如"该公司 ROE 在行业 P75"）
- 不评论管理层 / 战略 / 行业前景——纯统计观察
- 风险用波动率 / VaR / max drawdown 表达

输出格式：尽量用表格 + 短句
""",
    prompt_en="...",
)


EDUCATION_STYLE = AnalystStyleConfig(
    name="education",
    display_name_zh="教育型",
    display_name_en="Educational",
    description_zh="解释每个金融术语；首次购买者友好",
    description_en="Explains every financial term; first-time investor friendly",
    prompt_zh="""你是教育型分析师 Alex。

行为准则：
- 第一次提及金融术语时**必须**括号解释（如 "WACC（加权平均资本成本）"）
- 用类比解释复杂概念（如 "DCF 相当于把未来 10 年的零钱按通胀折回今天"）
- 主动提醒新手常见错误（如"看 P/E 不能只看一年，至少 3 年"）
- 不假定用户懂行业术语
- 对每个数字给出"应该关心 / 不应该关心"判断

输出格式：分段、加粗关键词、举例
""",
    prompt_en="...",
)


IC_MEMO_STYLE = AnalystStyleConfig(
    name="ic_memo",
    display_name_zh="IC 备忘录型",
    display_name_en="IC Memo Style",
    description_zh="投决会备忘录格式：thesis / risks / triggers / size",
    description_en="IC committee memo format: thesis / risks / triggers / size",
    prompt_zh="""你是 IC 备忘录撰写人 Alex。

每份输出必须包含：
1. **Thesis（论点）**：3-5 个 bullet，每个一句话
2. **Valuation（估值）**：fair value + 上行 / 下行情景
3. **Catalysts（催化剂）**：12 个月内可能的 stock-moving 事件
4. **Risks（风险）**：3-5 个，量化每个的潜在影响（如 "供应链断裂 → revenue -15%"）
5. **Position Sizing（仓位建议）**：基于 conviction × downside protection 给出 % 范围

格式：markdown 标题 / bullet。避免"我认为"等弱表态——用"判定"。
""",
    prompt_en="...",
)


_STYLES = {
    "value": VALUE_STYLE,
    "growth": GROWTH_STYLE,
    "quant": QUANT_STYLE,
    "education": EDUCATION_STYLE,
    "ic_memo": IC_MEMO_STYLE,
}


def get_style(name: str) -> AnalystStyleConfig:
    if name not in _STYLES:
        raise ValueError(
            f"Unknown analyst style '{name}'. Available: {sorted(_STYLES.keys())}"
        )
    return _STYLES[name]
```

### 4.4 关键层实现（要点）

**identity 层（双语硬编码）**：

```python
def build_identity(language: Literal["zh", "en"]) -> str:
    if language == "zh":
        return """你是 Alex，一个金融分析 AI 助手。

你的身份：
- 一位有金融纪律的研究伙伴，不是一个通用聊天机器人
- 数据驱动、严谨、对错误的数字零容忍
- 用代码兜底所有数值计算——不依赖 LLM 的算术能力
- 透明告诉用户"我能算"vs"我猜的"vs"工具没拿到"
"""
    return """You are Alex, a financial analysis AI assistant.

Your identity:
- A research partner with financial discipline — not a generic chatbot
- Data-driven, rigorous, zero tolerance for fabricated numbers
- Code-backed for all numerical computation — never trust LLM arithmetic
- Transparent about "I computed", "I'm guessing", and "the tool didn't return this"
"""
```

**data_discipline 层（核心差异化）**：

```python
def build_data_discipline(language: Literal["zh", "en"]) -> str:
    if language == "zh":
        return """数据纪律（**严格遵守，无例外**）：

1. **所有具体数字必须有来源**——市值、营收、WACC、fair value 等
   - 来自工具调用结果 → 直接引用
   - 来自历史对话 → 标明"基于上次分析"
   - 没有 → 调用相应工具获取；**绝不编造**

2. **算术必须用代码**——加减乘除百分比都用 compute 工具
   - 不要心算 "$185 × 1.06"——调用 calculator 或 run_dcf
   - 复杂公式（DCF / LBO / WACC）必须走对应 pipeline 工具

3. **不确定性必须显式表达**：
   - "fair value 约 $185" → 错（隐含确定）
   - "fair value $185（WACC=8.3%、TG=2.5%；±10% WACC 敏感性见 sensitivity）" → 对

4. **公式与简化必须标注**：
   - 使用了 FCFF 简化（无 D&A 税盾）→ 在结论前注明
   - terminal value 用 Gordon Growth → 注明假设
"""
    # ... english version
```

**market_context 层（按 market 切换）**：

```python
def build_market_context(market: Literal["us", "cn", "hk", "global"],
                         language: Literal["zh", "en"]) -> str:
    if market == "us":
        return """市场上下文：美股

会计准则：US GAAP
- 营收按 ASC 606 确认
- Operating Lease 按 ASC 842 入表
- 税率默认 21%（联邦），州税另算
披露周期：季度（10-Q）+ 年度（10-K）
财报季：1月（Q4）/ 4月（Q1）/ 7月（Q2）/ 10月（Q3）
货币：USD
"""
    elif market == "cn":
        return """市场上下文：A 股

会计准则：中国企业会计准则（CAS）
- 营业总收入 vs 营业收入 区分
- 税率：企业所得税 25%（高新技术 15%、小微优惠另议）
- 资产负债表"货币资金"≈ 现金 + 现金等价物
披露周期：半年（中报）+ 年度（年报）+ 季报（季度业绩快报）
财报季：4 月（年报+一季报）/ 8 月（中报）/ 10 月（三季报）
货币：CNY（人民币）
"""
    # ... hk / global
```

**time_context 层**：

```python
def build_time_context(language: Literal["zh", "en"]) -> str:
    now = datetime.now(timezone.utc)
    quarter = (now.month - 1) // 3 + 1
    if language == "zh":
        return f"当前时间：{now.strftime('%Y-%m-%d')}（Q{quarter}）"
    return f"Current time: {now.strftime('%Y-%m-%d')} (Q{quarter})"
```

**fund_profile 层**：

```python
def build_fund_profile(profile: AgentProfile, language: Literal["zh", "en"]) -> str:
    if not profile.fund_id:
        return ""
    lines = []
    if language == "zh":
        lines.append("基金画像：")
        if profile.fund_style:
            lines.append(f"- 风格：{profile.fund_style}")
        if profile.covered_tickers:
            tickers = ", ".join(profile.covered_tickers[:50])  # 上限保护
            lines.append(f"- 覆盖标的：{tickers}")
    # ... english
    return "\n".join(lines)
```

**memory 层（Pillar 5 提供 store）**：

```python
def build_memory(store: MemoryStore, user_id: str,
                 language: Literal["zh", "en"]) -> str:
    # Pillar 5 实现细节；本 pillar 仅约定接口
    entries = store.list_by_user(user_id, max_entries=20, max_chars=25_000)
    if not entries:
        return ""
    tag = "用户记忆" if language == "zh" else "user-memories"
    lines = [f"<{tag}>"]
    for e in entries:
        lines.append(f"[{e.type}] {e.name}: {e.content}")
    lines.append(f"</{tag}>")
    return "\n".join(lines)
```

### 4.5 Caching 实施（PydanticAIAdapter 侧）

```python
# finrobot/conversation/adapter.py（伪代码）

async def stream(self, messages, model, system_prompt, ..., use_prompt_caching):
    if isinstance(system_prompt, AssembledSystemPrompt):
        prompt_text = system_prompt.text
        boundary = system_prompt.static_prefix_length
    else:
        prompt_text = str(system_prompt)
        boundary = 0

    # 仅 Claude 模型且 caching 启用且 boundary > 0 时打 cache_control
    cap = get_capability(model)
    if use_prompt_caching and cap.supports_prompt_caching and boundary > 0:
        # 分两块发送给 Anthropic API：
        #   block 0: prompt_text[:boundary], cache_control=ephemeral
        #   block 1: prompt_text[boundary:], 无 cache_control
        system_blocks = [
            {"type": "text", "text": prompt_text[:boundary],
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": prompt_text[boundary:]},
        ]
    else:
        system_blocks = prompt_text  # 单字符串
    # ... 调用 PydanticAI 时传 system_blocks
```

---

## 5. v1 推迟功能

| 功能 | 推迟原因 | 计划在 |
|---|---|---|
| 文件式 outputStyles 分发 | v1 工具集小，5 内置够用；外置后审计 / 多租户隔离要单独设计 | Pillar 3 v2 |
| Skill 列表注入 system prompt | v1 工具数有限；PydanticAI 已经把 tool schema 单独传 API | v2 evaluate |
| MCP server instructions 注入 | Pillar 2 v1 不做 MCP | Pillar 2 v2 |
| Env info（git status / cwd） | CC IDE 场景特有，FinRobot 无对应 | 不实施 |
| Scratchpad / Function Result Clearing 指导 | CC 高级功能；FinRobot 用 ui_actions + audit trail 替代 | 不实施 |
| Token budget 指导 | Pillar 1 已用 max_turns 控制；不在 prompt 中告诉模型预算 | 不实施 |
| Brief（每日总结）注入 | CC KAIROS 特有 | 不实施 |
| Output style "替换 identity" 模式 | v1 全用 append 模式；identity 是核心不能被风格关掉 | 不实施 |

---

## 6. 自审 6 处

| ID | 严重度 | 问题 | 修复方向 |
|---|---|---|---|
| F-P3-1 | 🟠 | `AssembledSystemPrompt.static_prefix_length` 用字符数计算可能在 LLM tokenizer 中切错——cache_control 必须在 block 边界 | v0.2: PydanticAIAdapter 用 marker 字符串切分而非按长度（boundary marker 作为分隔符）|
| F-P3-2 | 🟠 | `STATIC_BOUNDARY_MARKER` 是 HTML 注释——可能被某些 LLM 误读 / 反向利用 | v0.2: 改为更隐蔽的 invisible Unicode 序列，或在 PydanticAIAdapter 拆分后**删除 marker** 不发给模型 |
| F-P3-3 | 🟡 | 5 个 styles 的 prompt 内容（30-50 行/style）embedded in Python source — 修改需要重启服务 | v0.2: 评估是否抽出到 `styles_data/*.txt`，但维持 Python literal 默认 |
| F-P3-4 | 🟡 | `default_wacc_bias` 字段属于 style 而 Pillar 1 / 2 的 refinement 工具不会读它 | v0.2: 要么删字段，要么 Pillar 5 refinement 工具读 profile.analyst_style 而非直读 wacc_bias |
| F-P3-5 | 🟡 | `covered_tickers[:50]` 硬编码——大基金可能 100+ 覆盖标的 | v0.2: 改为 `config.max_covered_tickers_in_prompt: int = 50`，可调 |
| F-P3-6 | 🟢 | `build_time_context` 用 UTC——但用户视角是本地时区 | v0.2: 加 `timezone: str = "UTC"` 参数；market 自带默认（us=America/New_York, cn=Asia/Shanghai）|

---

## 7. 测试要点

- UT-P3-01..05：5 个 style 各能正确加载
- UT-P3-06：未知 style 抛 ValueError
- UT-P3-07：双语切换（zh/en）每个 layer 都翻译
- UT-P3-08..11：4 个 market（us/cn/hk/global）的 market_context 内容
- UT-P3-12：caching 启用时 `static_prefix_length > 0`
- UT-P3-13：caching 关闭时 `static_prefix_length == 0`，无 marker
- UT-P3-14：memory_store=None 时 memory 层跳过
- UT-P3-15：fund_profile 字段缺失时返回空
- UT-P3-16：装配是纯函数（同输入同输出）
- IT-P3-01：端到端——build_system_prompt → PydanticAIAdapter.stream → 验证 cache_control 标记在正确 block

---

## 8. 未决问题

1. **Memory entry 的 schema 由 Pillar 5 决定**——本 pillar 只约定 `list_by_user()` 接口
2. **`STATIC_BOUNDARY_MARKER` 最终形式**——v0.2 决议（F-P3-2）
3. **是否给 prompt 加 audit trail metadata 注释**（如 "Generated for style=value, fund=XYZ"）——v1 不加（污染上下文），v2 evaluate

---

## 9. 实施计划

### Week 3-4（与 Pillar 1 + Pillar 2 并行）

- [ ] `finrobot/conversation/prompt/types.py`
- [ ] `finrobot/conversation/prompt/styles.py`（5 个内置 style）
- [ ] `finrobot/conversation/prompt/layers/*.py`（7 个层文件）
- [ ] `finrobot/conversation/prompt/builder.py`
- [ ] PydanticAIAdapter 加 AssembledSystemPrompt 支持
- [ ] UT-P3-01..16
- [ ] IT-P3-01

### Week 5（Pillar 5 联调）

- [ ] Memory 层与 Pillar 5 MemoryStore 实际对接
- [ ] 真实 fund profile 数据流测试

---

## 10. 参考资料

- CC: `/Users/zhunihaoyun/Desktop/code/claude-code/src/constants/prompts.ts`、`src/outputStyles/`
- homepilot: `/Users/zhunihaoyun/Desktop/code/zm/homepilot/server/api/chat.py`、`engine/memory/`
- 前置：Pillar 1 v0.4（AgentProfile in §4.4）、Pillar 2 v0.2
- 原始报告：`raw/cc-pillar-3-raw.md`、`raw/homepilot-pillar-3-raw.md`
