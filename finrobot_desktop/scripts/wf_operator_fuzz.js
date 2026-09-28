export const meta = {
  name: 'operator-invariant-fuzz',
  description: 'B路: adversarial property-fuzz of pure operators/primitives for missing invariant guards',
  phases: [
    { title: 'Fuzz', detail: 'one agent per operator group: enumerate must-hold invariants + fuzz + report violations' },
    { title: 'Verify', detail: 'adversarial skeptic per candidate — default: system is right, refute me' },
  ],
}

const REPO = '/Users/zhunihaoyun/Desktop/code/FinAgent'

const DISCIPLINE = `
你是 FinAgent(可溯源的确定性估值驾驶舱,闭源桌面金融分析平台)的算子不变量 fuzzer。
目标用户=分析师/量化研究员,数字错一个=砸招牌。

工作目录: ${REPO}。算子在 finrobot/engine/compute/operators/,primitives 在 finrobot/engine/primitives/。
它们是纯函数(operators 不依赖 data I/O,ADR-0005),可直接 import 调用。
跑 python 用: cd ${REPO} && .venv/bin/python。写一次性 fuzz 脚本到 /tmp/fuzz_<name>.py 再跑。
导入形如: from finrobot.engine.compute.operators.signal import compute_signal。
已有 property 测试: tests/unit/test_property_metamorphic.py(读它,别重复它已覆盖的)。

【铁律 — 什么算合法 bug】
- 算子是纯函数 → 逻辑/符号/退化/量纲类断言是确定性的: 给定输入 → 错误/自相矛盾输出 = 合法 bug。这类你可以判。
- 但"某个数值大小对不对"(倍数高低/价位合理)需要外部真值,你拿不到 → 标 confidence=needs-human,别硬判。
- 报 bug 必须给"具体输入 → 实际输出 → 为什么错(违反哪条不变量)",或代码里的确定性矛盾(如一分支守了对称分支没守)。

【最强信号 = 不对称守卫(asymmetric guard)】
反复出现的根因模式: 一个分支/规则/字段守了某不变量,对称的那个没守。实例(已确认):
- signal.py Rule 2 有方向守卫 / Rule 1 没有(已修);
- sniper LONG 分支防退化 / SHORT 不防;
- IncomeStatement.operating_margin 允许负(ge=-5)/ gross_margin 不允许(ge=0)→ 亏损股 500。
看到"LONG 守了 SHORT 没守""上界有下界没有""一个 metric 归一了另一个没有"——就地撞它。

【要撞的不变量族】
1. 符号/方向一致: signal hit 必须朝目标方向; sniper entry≠stop, SHORT 与 LONG 对称(不退化成开仓即止损); 催化剂排序尊重 sentiment 符号; DDM 要求 g<r。
2. 退化态: debt>EV / 负 equity / 零或负 FCF / 零除分母 → 不许吐反向数字(LBO 负入场权益应 N/A,不是 moic=0/irr=-1),要么 None+warning 要么明确未定义。
3. 量纲/边界: 倍数在合理 band 内或 None; 绝不 NaN/Inf/负 EV/负 WACC。
4. 度量关系(metamorphic): DCF 增长↑→隐含价↑; WACC↓→价↑; 把所有 reporting 口径项同乘 k(换汇)→ 比率(ev_ebitda/pe/margin)不变。
5. None≠0: 缺数据必须 None/withheld,绝不从零数据捏确定信号。

【对抗输入清单】(每个算子都试)
极端杠杆 / 负 equity / 零或负 FCF / 零或负 EBITDA / 零除分母 / NaN / Inf / 极小(1e-9)极大(1e15)值 / 剧烈 TTM 摆动 / g≈r 与 g>r / 负增长 / 单期 vs 多期 / 空列表 / 全 None。
`

const SCHEMA = {
  type: 'object',
  properties: {
    operator_group: { type: 'string' },
    invariants_checked: { type: 'array', items: { type: 'string' } },
    ran_fuzz: { type: 'boolean', description: 'true if you actually executed python fuzz, false if static-only (e.g. subprocess blocked)' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          operator: { type: 'string' },
          location: { type: 'string', description: 'file:line' },
          invariant: { type: 'string', description: 'which invariant family is violated' },
          trigger_input: { type: 'string', description: 'concrete input that triggers it' },
          actual_output: { type: 'string' },
          expected: { type: 'string' },
          why_wrong: { type: 'string' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          confidence: { type: 'string', enum: ['confirmed-ran', 'static-only', 'needs-human'] },
        },
        required: ['operator', 'location', 'invariant', 'why_wrong', 'severity', 'confidence'],
      },
    },
  },
  required: ['operator_group', 'findings', 'ran_fuzz'],
}

const GROUPS = [
  { key: 'dcf', files: 'dcf.py, dcf_seed.py', focus: '度量关系(增长↑→价↑, WACC↓→价↑, 换汇比率不变); 负/零 FCF; 终值 g≥WACC 爆炸; 高低增长单调性' },
  { key: 'wacc', files: 'wacc.py', focus: 'WACC>0 且在合理 band; beta 极端值; cost_of_equity≥cost_of_debt? 负利率; 零权重/全债' },
  { key: 'multiples', files: 'multiples.py, xbrl_aligned_comps.py', focus: '混币 → None; 负 earnings 的 PE(应 None 非负 PE 当便宜); EV<0; 倍数量级 band' },
  { key: 'ddm', files: 'ddm.py, ddm_seed.py', focus: 'g<r 守卫(g≥r 应 N/A 非负价/爆炸); 零股息; 负增长' },
  { key: 'lbo', files: 'lbo.py, lbo_seed.py', focus: '债务>企业价值→负入场权益: 现报 moic=0/irr=-1(方向相反)应改 N/A; LONG/exit 对称; 零除' },
  { key: 'monte_carlo', files: 'monte_carlo.py', focus: '分布 sanity; NaN/Inf 渗入; 分位数单调(p10≤p50≤p90); 零方差退化; 负价采样' },
  { key: 'sniper', files: 'sniper.py', focus: 'entry≠stop; SHORT 与 LONG 对称(secondary_buy==stop_loss=开仓即止损是已知嫌疑); 退化降级门; 不变式校验对称' },
  { key: 'signal', files: 'signal.py', focus: 'hit 必须朝目标方向(Rule1/Rule2 对称); 逆向亏损不算 hit; 现价/目标/入场符号一致; 零除' },
  { key: 'forward', files: 'forward_estimates.py, earnings.py', focus: 'FY 选年正确; 负增长; 缺估计 → None 非 0; 量纲' },
  { key: 'aggregator', files: 'valuation_aggregator.py, valuation_synthesis.py', focus: '加权和=1; 离群值; 全 None 输入; 方法缺失降级; 负价中位数' },
  { key: 'catalyst', files: 'catalyst.py, peer_screen.py', focus: '催化剂排序尊重 expected-impact 符号(不被无符号 rank 覆盖); peer 选择混币/空; 排序稳定' },
  { key: 'primitives', files: 'primitives/ebitda.py, primitives/sentiment.py, primitives/market_cap.py, primitives/industry.py', focus: 'ebitda 口径(operating vs reported); sentiment 零活跃→None 非"100%看空"; market_cap live 价重算; 零除' },
]

phase('Fuzz')
const fuzzResults = await parallel(
  GROUPS.map((g) => () =>
    agent(
      `${DISCIPLINE}

【你的算子组: ${g.key}】文件: ${g.files}
重点不变量: ${g.focus}

步骤:
1. 读这些文件的源码,列出每个公共函数"必须恒成立"的不变量(显式写下每条 + 为什么)。
2. 特别找"不对称守卫"——一个分支/字段/规则守了,对称的没守。
3. 写 /tmp/fuzz_${g.key}.py 用对抗输入实际调用算子,断言不变量。cd ${REPO} && .venv/bin/python /tmp/fuzz_${g.key}.py。
   若 import 报错或 subprocess 被 TCC 挡(写不进/跑不了)→ 退化为纯静态代码审查,ran_fuzz=false,findings 标 confidence=static-only。
4. 每个真实违反 = 一条 finding,带 file:line + 触发输入 + 实际输出 + 为什么错。
   只报你实际触发的或代码里确定性的不对称/矛盾。数值大小类标 needs-human。不报风格/口味问题。
返回结构化结果。findings 可为空(该组很干净就空着,在 invariants_checked 里列你验过的)。`,
      { label: `fuzz:${g.key}`, phase: 'Fuzz', schema: SCHEMA },
    ),
  ),
)

const candidates = []
for (const r of fuzzResults.filter(Boolean)) {
  for (const f of r.findings || []) candidates.push({ ...f, group: r.operator_group })
}
log(`Fuzz 完成: ${candidates.length} 个 candidate 来自 ${fuzzResults.filter(Boolean).length} 组`)

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['real-bug', 'false-positive', 'needs-human'] },
    reasoning: { type: 'string' },
    refutation_attempt: { type: 'string', description: 'how you tried to prove the system is actually correct' },
    suggested_fix: { type: 'string' },
  },
  required: ['verdict', 'reasoning'],
}

phase('Verify')
const verified = await parallel(
  candidates.map((c) => () =>
    agent(
      `${DISCIPLINE}

【对抗式复核 — 默认立场: 系统大概率是对的,你的任务是努力反驳这个指控】
被指控的 candidate:
  算子: ${c.operator}  位置: ${c.location}
  违反不变量: ${c.invariant}
  触发输入: ${c.trigger_input || 'n/a'}
  实际输出: ${c.actual_output || 'n/a'}
  期望: ${c.expected || 'n/a'}
  指控理由: ${c.why_wrong}

步骤:
1. 读 ${c.location} 附近真实源码。
2. 努力证明系统其实是对的(也许有上游守卫/调用约定/这输入根本不可达/这输出其实正确)。
3. 能复现就 cd ${REPO} && .venv/bin/python 实跑确认。
4. 只有反驳失败、且能给"具体输入→确定性错误输出"或明确代码矛盾,才判 real-bug。
   数值大小类拿不到外部真值 → needs-human。给 suggested_fix(结构性,非 band-aid)。`,
      { label: `verify:${c.operator}:${c.location}`, phase: 'Verify', schema: VERIFY_SCHEMA },
    ).then((v) => ({ candidate: c, verdict: v })),
  ),
)

const real = verified.filter(Boolean).filter((v) => v.verdict?.verdict === 'real-bug')
const needsHuman = verified.filter(Boolean).filter((v) => v.verdict?.verdict === 'needs-human')
log(`Verify 完成: ${real.length} real-bug, ${needsHuman.length} needs-human, ${verified.filter(Boolean).length - real.length - needsHuman.length} false-positive`)

return {
  summary: { candidates: candidates.length, real: real.length, needsHuman: needsHuman.length },
  real_bugs: real.map((v) => ({ ...v.candidate, verdict: v.verdict })),
  needs_human: needsHuman.map((v) => ({ ...v.candidate, verdict: v.verdict })),
  groups_ran: fuzzResults.filter(Boolean).map((r) => ({ group: r.operator_group, ran_fuzz: r.ran_fuzz, n: (r.findings || []).length })),
}
