from __future__ import annotations

from typing import Final

from finrobot.engine.skills.spec import Skill


_PIPELINE_SAFE_METHODOLOGY: Final[dict[str, str]] = {
    "competitive-analysis": """
Pipeline-safe competitive landscape framework:
- Start with industry economics: cyclicality, commoditization vs differentiated
  IP, supply discipline, capital intensity, customer concentration, and pricing
  power.
- Segment peers before judging them: direct product peers, adjacent compute/IP
  peers, analog/industrial peers, and platform leaders are not interchangeable.
- Compare positioning by business model and moat: scale economies,
  technology/IP, switching costs, ecosystem lock-in, manufacturing intensity,
  distribution, and regulatory/geographic constraints.
- Translate the comparison into investment implications: what deserves a
  premium/discount, what is structurally durable, and what is merely cyclical.
- Do not ask the user follow-up questions, create decks, generate files, or
  pull external data from this methodology.
- Use qualitative labels if the numeric whitelist lacks a figure; do not invent
  market share, segment share, company margin, growth, valuation multiple, or
  current trading multiple data.
- Do not say the subject trades at a premium/discount to peers unless the
  subject company's own comparable multiple is explicitly supplied. Peer
  multiples alone support peer positioning, not the subject's relative multiple.
- Do not conclude peer-relative overvaluation or undervaluation from peer
  multiples alone. Use DCF/current-price/authorized target evidence for
  valuation conclusion when the subject multiple is absent.
""",
    "initiating-coverage": """
Pipeline-safe initiating-coverage framework for an automated equity research artifact:
- Organize the thesis like an initiation report: headline investment call,
  business/model overview, industry and competitive positioning, valuation
  bridge, catalysts, risks, and conclusion.
- Company overview should explain what the company sells, where it sits in the
  value chain, which end markets drive demand, and what cycle/structural forces
  matter.
- If those business-line, end-market, segment, or geography details are not in
  the prompt, keep the overview qualitative and say the exact split was not
  supplied. Do not fill the gap from model memory.
- Valuation overview should compare DCF, comps, and any available method as
  evidence, not as a fresh calculation. Discuss why methods diverge and what
  that says about confidence.
- Do not run the original workflow: no task selection, no prerequisite
  confirmation, no chart/file generation, no Word/PPT/Excel instructions.
- Never override authoritative target/recommendation or compute a new number.
""",
    "thesis-tracker": """
Pipeline-safe thesis tracking framework:
- Express key_takeaways as current thesis pillars, not a generic summary.
- Tie catalysts to proof points that would confirm or disprove the pillars.
- Frame risks as thesis-invalidating conditions, with mitigation/monitoring
  language where the prompt supports it.
- Use conviction vocabulary only from prompt evidence: strengthening, neutral,
  weakening, under review.
""",
    "ic-memo": """
Pipeline-safe IC memo framework:
- Use for decision discipline: executive recommendation, top risks and
  mitigants, investment merits, downside case, and debate-ready objections.
- Keep return, leverage, entry multiple, and scenario numbers out unless they
  are explicitly whitelisted in the prompt.
""",
    "earnings-analysis": """
Pipeline-safe earnings update framework:
- Use only when current earnings context is present. Emphasize what changed,
  beat/miss drivers, estimate/thesis impact, and whether catalysts or risks
  moved.
- Do not infer quarterly variances or consensus deltas unless those figures are
  explicitly in the prompt.
""",
    "comps-analysis": """
Pipeline-safe comps framework:
- Use as a narrative checklist for peer comparability, metric selection,
  premium/discount interpretation, and why the peer set is or is not clean.
- The peer set, multiples, medians, and statistics come from deterministic
  peer_analysis outputs. Do not calculate new multiples or spreadsheet formulas
  from the skill instructions.
""",
    "dcf-model": """
Pipeline-safe DCF framework:
- Use as a narrative checklist for revenue growth, margin path, reinvestment,
  WACC, terminal growth, sensitivity, and valuation bridge.
- All DCF inputs, WACC, terminal value, sensitivity, and implied price numbers
  must come from deterministic financial_modeling outputs. Do not build an
  Excel model, ask for checkpoints, or compute formulas in the LLM step.
""",
    "tear-sheet": """
Pipeline-safe tear sheet framework:
- Use as a compact-company-snapshot checklist: identity, business description,
  key metrics, recent developments, and concise investment implications.
- Do not use S&P/Kensho tools, create Word files, or introduce header metrics
  unless those values are present in the prompt whitelist.
""",
    "equity-research": """
Pipeline-safe research snapshot framework:
- Connect every table and metric to the investment thesis; do not dump numbers
  without explaining their implication.
- Include expectation, consensus, macro, or price-history framing only when
  those fields are supplied by upstream data.
- Close the report with evidence-backed bull case, bear case, catalysts, risks,
  and conviction language when the thesis data supports it.
- Do not call LSEG tools, browse, compute new valuation metrics, create files,
  or add source dates that were not supplied.
""",
    "strip-profile": """
Pipeline-safe company strip-profile framework:
- Organize the snapshot as four dense panels: company overview (identity, HQ,
  scale, leadership), business & positioning (revenue drivers, products, moat,
  end markets), key financials & valuation (revenue, EBITDA, margins, EPS, FCF,
  market cap, EV, multiples), and recent developments / ownership.
- Pack each panel with specific numbers and context — "$50B revenue (+6% YoY)",
  "EBITDA margin 25% (vs 18% peer avg)" — never vague qualifiers.
- All financial, valuation, ownership, and segment figures must come from the
  upstream deterministic payload. If a figure is absent, state it is not
  supplied; do not invent market share, multiples, or shareholder splits.
- This is a narrative methodology only: do not build PptxGenJS slides, render
  images, ask the user single-vs-multi-slide questions, request outline sign-off,
  produce slides incrementally, or pause for human sign-off between slides.
""",
    "process-letter": """
Pipeline-safe M&A process-letter framework:
- Use to structure how a sell-side process is communicated: letter type (initial
  process letter / IOI instructions / final-bid letter / management-meeting
  invitation), process timeline and rounds, and what each round requires.
- IOI requirements to frame: indicative enterprise-value range, consideration
  form (cash/stock/earnout/rollover), financing certainty, diligence needs,
  timeline to close, conditions, and strategic rationale.
- Final-bid additions to frame: SPA/APA markup, committed financing letters,
  confirmatory diligence scope, exclusivity terms, regulatory/antitrust timeline,
  key-personnel terms, and the evaluation criteria bidders are judged on.
- This is a narrative methodology only: do not draft or send actual letters,
  generate Word/.docx files, manage a recipient log, or route the letter for
  client sign-off prior to distribution.
""",
    "deal-sourcing": """
Pipeline-safe PE deal-sourcing framework:
- Frame sourcing as discover → relationship-check → outreach-rationale, but as
  analysis, not execution.
- Discovery: define the thesis filter (sector, revenue/EBITDA range, growth
  profile, geography, ownership type — founder-owned / PE-backed / carve-out) and
  describe the target shortlist by name, size, location, and thesis fit.
- Relationship context: note where prior firm contact would change the approach
  ("new" vs "existing relationship" vs "previously passed") as an analytical
  flag, framed from supplied evidence only.
- Outreach rationale: describe what makes a founder approach compelling
  (company-specific hook, partnership framing, concise low-pressure ask) as
  qualitative guidance.
- This is a narrative methodology only: do not search Gmail/Slack/CRM, draft or
  send founder emails, route shortlists for human sign-off, or pause for human
  confirmation before any step.
""",
    "client-report": """
Pipeline-safe client performance-report framework:
- Organize as: report parameters (client, period, accounts, benchmark),
  performance summary (portfolio vs benchmark across QTD/YTD/1Y/3Y/5Y/ITD),
  allocation overview, holdings detail, market commentary, activity summary, and
  planning notes against stated goals.
- Performance is net of fees unless gross is explicitly required; benchmark is
  the IPS benchmark, not whichever flatters the result.
- All returns, balances, allocation weights, and holdings come from the upstream
  deterministic payload. If a value is absent, state it is not supplied; do not
  fabricate returns, fees, or benchmark deltas.
- This is a narrative methodology only: do not generate PDF/Word/Excel files,
  apply firm branding, or route the template through a compliance sign-off gate
  prior to distribution.
""",
}


def render_pipeline_methodology(skill: Skill) -> str:
    """Render a skill body for unattended pipeline prompts.

    Interactive Claude-Code skills often contain workflow commands, user
    checkpoints, file-generation instructions, and spreadsheet formulas. Those
    are useful in chat, but unsafe inside FinRobot's automated report pipeline.
    Known financial skills therefore get a distilled, narrative-only excerpt.
    Unknown skills fall back to the original body so existing custom pipelines
    keep their current behavior.
    """
    safe_body = _PIPELINE_SAFE_METHODOLOGY.get(skill.id)
    body = safe_body if safe_body is not None else skill.full_content
    return f"### {skill.id}: {skill.name}\n{body.strip()}"
