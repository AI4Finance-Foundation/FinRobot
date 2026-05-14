# CLAUDE.md

FinAgent 是开源金融分析平台，把确定性金融计算和 LLM 叙事能力配在一起。后端 PydanticAI + FastAPI；桌面端 Tauri + React 19；上层有 CLI 和 Python SDK。Apache-2.0。

## 核心赌注

金融 AI 市场正在收敛成 ChatGPT 包装器。FinAgent 押的是反向：**数字由代码算出，判断由 LLM 给出。** WACC、DCF、可比公司、LBO、敏感性全部以纯 Python 执行；LLM 永远不应该产出一个无法追溯到函数调用的数字。本仓库的每一行存在都为守住这条线。**让一个数字更难审计的改动 = 错的改动，哪怕它发版更快。**

## 命令

```bash
pytest tests/ -x -v --tb=short          # 测试
ruff check finagent/                    # lint
ruff format finagent/                   # format
mypy finagent/                          # 类型检查
pre-commit run --all-files              # 完整闸门（每次 commit 前必跑）
uv sync                                 # 依赖（永远不要用 pip）
```

`pre-commit` 是健康基线的事实源。不要在代码或文档里写死测试数 / 错误数 —— 会陈旧，`pre-commit run --all-files` 一条命令就能拿到当下真实状态。

## 仓库地图

| 路径 | 职责 | 叶子层？ |
|---|---|---|
| `finagent/engine/compute/` | 纯函数金融逻辑：DCF / WACC / LBO / multiples / extractor。确定性，相同输入 → 相同输出。 | **是 —— 禁止向上 import** |
| `finagent/engine/models/` | 金融数据 Pydantic 类型。Schema 即契约。 | **是 —— 禁止向上 import** |
| `finagent/engine/data/providers/` | yfinance / FMP / Finnhub / SEC EDGAR 适配器，统一在一个 ABC 之后。 | 是 |
| `finagent/engine/data/cache.py` | providers 前面的 aiosqlite 缓存层。 | — |
| `finagent/engine/pipelines/` | 代码强制的步骤顺序。每步有 validator；LLM 不能跳步或乱序。 | — |
| `finagent/engine/agents/` | PydanticAI 子 agent（data / analysis / modeling / synthesis / report）。 | — |
| `finagent/engine/orchestrator.py` | Lead agent + tool 注册。**唯一**一处 agent 接触 tool description 的地方。 | — |
| `finagent/engine/{charts,reports,analysis,backtest,rag,skills}/` | 专项能力（图表渲染、报告模板、BM25 RAG 等）。 | — |
| `finagent/routes/` | FastAPI HTTP 端点。 | — |
| `finagent/web/` | Jinja2 服务端渲染 web UI。 | — |
| `ui/` | React 19 + Tauri 桌面 UI 源码。 | — |
| `tests/` | unit / integration / artifact / audit / routes。integration 测试真打 yfinance + LLM。 | — |
| `docs/cc-pillars/` | 对话内核（P6）的 8 个 pillar spec。Pillars 1-3 + ADRs 已 accepted。 | — |
| `specs/` | 阶段 spec P0-P8、`BACKLOG.md`、`DESIGN-SYSTEM.md`、`PRODUCT-INSIGHTS.md`。 | — |
| `ARCHITECTURE.md` | 完整愿景文档。和 CLAUDE.md 冲突时 CLAUDE.md 胜。 | — |

**P6 对话内核当前状态**：pillar spec 已 accepted，ADR 1-3 已 accepted；`finagent/conversation/` **作为代码尚不存在**。任何说它已存在的说法都是错的。

## 架构红线

不可破。破必须有 ADR + 明确批准。

1. **`compute/` 和 `models/` 是叶子层。** 不允许 import `agents/`、`pipelines/`、`orchestrator` 或任何 PydanticAI / openai / LLM 符号。验证：
   ```bash
   grep -rn "from finagent.engine.\(pipelines\|agents\|orchestrator\)" finagent/engine/{compute,models}/
   grep -rn "pydantic_ai\|from openai\|import openai" finagent/engine/{compute,models}/
   ```
   两条都必须为空。

2. **Pipeline 步骤顺序由代码强制，不由 LLM 决定。** 每个 `PipelineStep` 之间跑一次 validator。对话/agent 工具包**整个 pipeline**，绝不暴露单个步骤。一旦一个步骤变成独立工具，LLM 就接管了编排 —— 审计性当场死亡。

3. **数据 provider 只能走一个抽象。** 新数据源实现 `finagent/engine/data/interface.py` 里的 `DataProvider`，在 `finagent/engine/compute/extractor.py` 里完成归一化。Pipelines 永不直接调 provider SDK。

4. **依赖黑名单。** 不允许 LangChain / LangGraph / AutoGen / LiteLLM。PydanticAI 是唯一的 agent 框架。引入需要在 `docs/cc-pillars/adrs/` 里写一份 ADR，写出具体什么痛点是别的方案解决不了的。

## 每个改动必过的两个测试

两个都跑。任一失败就不写。

**架构师测试。** *用一条好 prompt 调原始 LLM API 能否得到同样结果？* 能 → 这是包装器，别写。代码值得存在只在三种情况下：(a) 确定性算出一个数字，(b) 强制一个步骤顺序或 schema，(c) 让组件之间走 typed 数据流。对 LLM 输出做漂亮编排不算。

**PM 测试。** *谁在用？他们现在怎么做？为什么换 FinAgent —— 答案是不是 10× 而不是 30%？* 目标用户是用 ChatGPT 做分析但不信任数字的买方研究员或基金 PM。每个功能必须满足三条之一：(a) 让一个数字更可信，(b) 实质性缩短到答时间，(c) 覆盖 ChatGPT 做不到的工作流。一条都不满足 → 进 `specs/BACKLOG.md`，不要做。

两者冲突时 **PM 胜**。被错数字坑过的用户根本不在乎代码漂不漂亮。

## 编码纪律

1. **先想再写。** 显式说出假设。如果有两种解读，两种都摆出来 —— 别静默选一种。不清楚 → 停下问。
2. **简单优先。** 没问的功能不加。一次性代码不抽象。可信边界内不写防御性校验。200 行能压成 50 行就重写。
3. **手术刀式改动。** 只动任务要求改的。别顺手 reformat 周围代码、别 refactor 没坏的东西、别把你的风格强加到不需要改的行上。每一行改动都能追溯回原始请求。
4. **类型端到端安全。** public 签名里不能出现 `Any`。不要 `cast`。`# type: ignore` 必须同行加一句话理由。
5. **异步正确性。** 异步函数里的同步阻塞 I/O 必须走 `asyncio.to_thread`。缓存、网络、文件 I/O 不是可选场景 —— 会把 event loop 卡死。
6. **异常处理。**
   - 用 `logger.exception("xxx 失败")`，不用 `logger.error(f"xxx 失败: {e}")`。stack trace 才是关键。
   - 捕具体异常：`(httpx.HTTPError, asyncio.TimeoutError)`，不捕 `Exception`。
   - **FORBIDDEN**：裸 `except Exception:`、`except: pass`、`except: continue`。失败要么传递，要么按名字处理。
7. **配置通过依赖注入。** 代码里永不写 `os.environ`。设置走 `finagent/config.py` + 依赖注入。
8. **logging，不 print。** `finagent/` 下任何 `print(` = bug。

## 测试与验证纪律

- **测试紧挨被测代码**：`tests/unit/test_dcf.py` 对应 `finagent/engine/compute/dcf.py`。
- **integration 测试打真 provider + 真 LLM**，标 `@pytest.mark.integration`。integration 测试里不 mock yfinance 或模型 —— P3 就是这样被审计出问题的。
- **unit 测试的期望值必须来自外部。** 用被测公式自己推出的期望值是同义反复，不是测试。用 Apple 10-K、Damodaran 教学案例、CFA 公开例题。
- **每个金融公式必测的边界**：负收益、零或负净债、亏损公司、零分母、负 FCF。五种全覆盖才算测过。
- **简化必须双标注。** 简化版 DCF 在代码注释里**和**用户可见输出里**都要**标"简化版"。把教学简化静默呈现为"估值" —— 在我们这个体量等于诈骗。
- **不确定性必须传递。** "数据不可用，用缓存" 和 "数据不可用，跳过" 是两种不同状态，到用户那里也得是两种。不能合并。

**改动前必扫**（重要改动前都跑一遍）：

```bash
grep -rn "except Exception" finagent/                              # 1. 异常粒度
grep -rn "retry\|for attempt in range\|max_retries" finagent/engine/  # 2. 重复 retry
grep -rn "data\.get(" finagent/engine/compute/extractor.py         # 3. 隐式 key 依赖
grep -rn "rate\|throttle\|sleep" finagent/engine/data/providers/   # 4. provider 限速
grep -rn "connect\|cursor\|execute" finagent/engine/data/cache.py  # 5. 缓存并发安全
# 6. 读 specs/BACKLOG.md：分清"真要做"和"已弃但没清理"
# 7. spec 承诺 vs 实现：每条 spec 功能 → grep 代码 → 标"已实现"或"spec 失实"
```

子 agent 报告改动**必须**附上这 7 条扫描结果，哪怕都是 "no findings"。没跑 = 任务未完成。

## 改动流程

1. **先读对应 spec / ADR / pillar 文档。** 写 `finagent/conversation/` 前必读 `docs/cc-pillars/pillar-*.md`。改 `compute/` 前必读 `tests/unit/` 里对应那个 pin 住期望值的测试。
2. **改动前先写或找一个能捕捉当前行为的测试。** 找不到 → 说明设计太纠缠，先重构到可测，或者干脆停手。
3. **为新行为写一个会失败的测试，确认它真的失败。**
4. **实现，一次一个文件。** 每写完一个文件，`pytest -x -v --tb=short` 跑对应目录。
5. **`pre-commit run --all-files` 通过才算完成。** 任何让 ruff / mypy / tests 退化的改动都是阻塞项，不允许"先合后修"。
6. **相关文档和测试同步更新。** ADR、pillar spec、`BACKLOG.md`、`DESIGN-SYSTEM.md` 都是代码的一部分。

**Greenfield 例外**：pillar spec 里已批准的模块（如 P6 `conversation/`）允许批量创建紧耦合骨架，但模块完成时必须 ≥30 unit tests + ≥5 integration tests 才能合。

## 会咬人的坑

- **`finagent/conversation/` 不存在。** 8 个 pillar spec + 3 个 ADR 是已 accepted 的设计稿，代码还没动。别假装它已存在。
- **ticker 不总是美股。** P5 松绑了 ticker validator，但货币转换、交易所路由、非美数据源都没做。A 股 / 港股 ticker 是最大开口项。
- **`DataLayer.fetch` 里 `StrEnum` 有隐式字符串转换。** 在 `specs/BACKLOG.md` "P3 audit todo" 里以 I7 记录。改数据层时要么修，要么文档化绕开。
- **`pydantic_ai` API 从 0.x → 1.7x 有大量破坏性变更。** 写 agent 代码前必到 https://ai.pydantic.dev/ 核对当前版本 API，不要依赖训练数据。
- **桌面 UI 只暴露了 3/7 pipelines。** 后端有 research / DCF / comps / LBO / IC memo / earnings / backtest；Tauri UI 只渲染前三个。差距是"暴露已有的"，不是"再造新的"。
- **姐妹工作站在 `/Users/zhunihaoyun/Desktop/code/Fin/`**，用对抗视角审本仓库。两边对同一改动有不同结论时，**默认信外部** —— 它没有被本地叙事捕获。

## Opus 4.7 Prompt 卫生（你对自己说的话）

当前模型字面化解读指令。它不会善意外推，也不会推断你没明说的请求。按此校准。

- **scope 显式说出来。** "对每一节都套用这个格式" —— 不是"套用这个格式"然后碰运气。
- **形容词换成动作。** "carefully review" / "thoroughly analyze" / "think step by step" 这种短语在 4.7 下不增加严谨度 —— 直接被忽略。用动词清单："执行 grep X / 读取文件 Y / 对比输出 Z / 报告发现 W"。
- **默认最小实现。** 一次性 helper 不写。没动过的代码不加 docstring。不存在的状态不写 fallback。用户没要的灵活性不加。
- **回答前先调查。** 没读过的代码不臆测。用户提到某个文件 → 先读再答。
- **并行工具调用。** 多个调用之间无依赖 → 一条消息里同时发。后一个依赖前一个输出 → 顺序执行。永远不要为缺参数瞎编占位符。
- **破坏性操作必须先确认。** 本地可逆操作（改文件、跑测试）放手做。`rm -rf`、`git push --force`、`git reset --hard`、删库、强推到 `main`、删分支 —— 每次都先问，无论下一步看起来多自然。hook 失败 → 修 hook 根因，不要加 `--no-verify`。

## Sub-agent 协议

调用子 agent 时：

1. **显式说身份**："架构师" / "PM" / "两者都是"。
2. **显式说 effort**：审计和复杂实现用 `xhigh`，普通任务用 `high`。
3. **递给它动作清单，不是请求。** "在 `path/` 执行 `grep X`，读 `file Y`，对比 `spec Z`，按这个格式报告发现。" 模糊 prompt 出模糊报告。
4. **指定输出格式**：`严重度 | 视角 | 路径:行号 | 证据 | 修复方向`。
5. **一次性全输出，按严重度排序。** 禁止挤牙膏。
6. **子 agent 必须报告"改动前必扫"的 7 条结果**，哪怕全部为 "no findings"。没跑 = 任务未完成。
7. **子 agent 必须先 `cd /Users/zhunihaoyun/Desktop/code/FinAgent`**，否则相对路径全错。

**Code-review 子 agent 是例外**：不要告诉它"只报高优先级 bug"。4.7 下它会忠实按你的门槛丢掉低优 finding。改成："报告每一个 finding，标 confidence + severity；下游另起一步过滤。" 找的时候要 coverage，排序的时候才过滤。

## 沟通风格

- "这是错的"，不说"可以考虑"。直接。
- 评审分三类：**缺陷**（必修） / **失实**（误导） / **改进**（锦上添花）。打标签。
- 文档和代码冲突 → 信代码，再修文档。
- 风险在它兑现之前说，不在之后说。
- 完成日常工作不自我表扬。不加废话。除非明确要求否则不用 emoji。

## 不要做

- 没必要不写新文件。
- 不主动创建 `*.md` 文档。
- 没要求不加 `Co-Authored-By: Claude` commit trailer。
- 不在代码/文档里写死测试数、文件数、错误数 —— 会陈旧。
- 不在本文件里写 `ruff` / `mypy` / `pre-commit` 能强制的风格规则。
- 不预写未来阶段的代码。非要打桩用 `# TODO(phase-N): ...`。
- 不静默偏离 spec。觉得 spec 错了 → 说出来，不要悄悄改对。
- 不引入 phase spec 白名单之外的依赖。

## 权威性

重要改动前先读以下文件。直接冲突时以 CLAUDE.md 为准。

- @docs/cc-pillars/README.md —— 对话内核的 8-pillar 框架
- @docs/cc-pillars/adrs/ —— 已 accepted 的架构决策
- @specs/BACKLOG.md —— 开口项，含严重度
- `ARCHITECTURE.md` —— 完整愿景文档（按需查阅；过大不预加载）
- `specs/PRODUCT-INSIGHTS.md` —— 用户研究、竞品论据、市场定位（按需查阅；过大不预加载）
