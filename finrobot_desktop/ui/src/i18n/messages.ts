// FinAgent UI strings — single source of truth.
// Add a new key here, then translate in both en and zh blocks.
// Never inline user-facing strings in components.

export type Locale = 'en' | 'zh'

export const LOCALES: { code: Locale; label: string; native: string }[] = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'zh', label: 'Chinese',  native: '中文' },
]

type Dict = Record<string, string>

const en: Dict = {
  // ── Brand / shell ──
  'app.name':                'FinAgent',
  'app.tagline':             'AI-powered equity research workstation',

  // ── Top bar ──
  'topbar.search.placeholder': 'Search ticker or ask anything (⌘K)',
  'topbar.settings.tooltip':   'Settings',
  'topbar.account.tooltip':    'Account',
  'topbar.language.tooltip':   'Language',

  // ── Left nav ──
  'nav.stocks':                'Stocks',
  'nav.library':               'Library',
  'nav.settings':              'Settings',
  'nav.recent':                'Recent',
  'nav.recent.empty':          'Tickers you visit appear here',

  // ── Stocks empty state ──
  'stocks.empty.title':        'Type a ticker or pick one below',
  'stocks.empty.placeholder':  'AAPL',
  'stocks.empty.analyze':      'Analyze',
  'stocks.empty.recent':       'Recent',
  'stocks.empty.quick':        'Quick access',
  'stocks.empty.invalid':      'Letters, digits, . and - only (max 12 chars)',

  // ── Stock header ──
  'stock.watchlist.add':       '☆ Add to watchlist',
  'stock.watchlist.remove':    '★ Watching',
  'stock.marketcap':           'Mkt cap',
  'stock.loading':             'Loading market data…',
  'stock.error.title':         'Could not load price data',
  'stock.error.retry':         'Retry',

  // ── Verb toolbar ──
  'verb.dcf':                  'Run DCF',
  'verb.lbo':                  'Run LBO',
  'verb.comps':                'Compare peers',
  'verb.catalysts':            'Find catalysts',
  'verb.ic-memo':              'IC memo',
  'verb.ddm':                  'Run DDM',
  'verb.earnings':             'Earnings',
  'verb.ask-ai':               'Ask AI',
  'verb.more':                 'More',
  'verb.dcf.tooltip':          'Run discounted cash flow valuation with default assumptions + live financials',
  'verb.lbo.tooltip':          'Run leveraged buyout model: IRR, MOIC, debt schedule, sensitivity grid',
  'verb.comps.tooltip':        'Run comparable company analysis — fetch peer multiples',
  'verb.catalysts.tooltip':    'Extract upcoming catalysts from recent news and filings',
  'verb.ic-memo.tooltip':      'Generate an Investment Committee memo: situation, thesis, risks, recommendation',
  'verb.ddm.tooltip':          'Dividend discount model — best for banks and dividend-paying stocks',
  'verb.earnings.tooltip':     'Earnings analysis — beat/miss classification + trend across quarters',
  'verb.ask-ai.tooltip':       'Open the chat panel and ask anything about this stock',

  // ── Tabs ──
  'tab.overview':              'Overview',
  'tab.financials':            'Financials',
  'tab.performance':           'Performance',
  'tab.news':                  'News',
  'tab.valuation':             'Valuation',
  'tab.comps':                 'Comps',
  'tab.history':               'History',
  'tab.research':              '10-K Q&A',

  // ── Research (RAG Q&A) tab ──
  'research.heading':          '10-K Q&A',
  'research.placeholder':      "Ask about this company's 10-K filing…",
  'research.ask':              'Ask',
  'research.empty':            'Ask a question about the SEC 10-K filing to get started.',
  'research.source':           'Source: SEC 10-K Filing',
  'research.citations':        'Citations',
  'research.relevance':        'relevance',
  'research.error':            'Failed to get an answer. Check that the server is running.',

  // ── Valuation tab ──
  'valuation.dcf.title':       'DCF Workspace',
  'valuation.dcf.empty':       'No DCF run yet. Click "Run DCF" above to value this company.',
  'valuation.dcf.cta':         'Run DCF now',
  'valuation.comp.title':      'Comprehensive Valuation',
  'valuation.lbo.title':       'LBO Analysis',
  'valuation.source.research': 'Valuation from Research analysis. Run standalone DCF for fresh assumptions.',
  'valuation.source.standalone': 'Standalone DCF analysis.',

  // ── Peers tab ──
  'peers.empty':               'No peer comparison yet. Click "Compare peers" to analyze.',
  'peers.cta':                 'Compare peers now',

  // ── Tool run results ──
  'tool.toast.success':        '{tool} complete — saved to Library',
  'tool.toast.failure':        '{tool} failed',
  'tool.error.unavailable':    'Backend unavailable — is the server running?',
  'tool.error.invalid':        'Invalid inputs for {tool}',
  'tool.error.unsupported':    '{tool} is not yet supported',
  'tool.error.generic':        '{tool} failed (HTTP {status})',
  'tool.error.cancelled':      'Request cancelled',
  'tool.error.unknown':        'Unknown error',

  // ── Right chat panel ──
  'chat.title.new':            'New chat',
  'chat.title.explore':        'Explore',
  'chat.empty.heading':        'Ask anything about finance',
  'chat.empty.body':           'I have access to live prices, financials, news and can run valuations.',
  'chat.empty.example.1':      'Why is {ticker} down today?',
  'chat.empty.example.2':      'Summarize {ticker}\'s last quarter',
  'chat.empty.example.3':      'Compare {ticker} to its peers',
  'chat.empty.example.generic.1': 'Explain DCF in 30 seconds',
  'chat.empty.example.generic.2': 'What\'s the difference between LBO and DCF?',
  'chat.empty.example.generic.3': 'How do you read a 10-K?',
  'chat.input.placeholder':    'Message FinAgent… (Enter to send, Shift+Enter for newline)',
  'chat.send':                 'Send',
  'chat.stop':                 'Stop',
  'chat.retry':                'Retry',
  'chat.newSession':           'New chat',
  'chat.collapse':             'Collapse',
  'chat.expand':               'Open chat',
  'chat.history':              'History',
  'chat.model.tooltip':        'Model',
  'chat.reasoning':            'Reasoning',
  'chat.error.context':        'Conversation too long. Start a new chat.',
  'chat.error.unavailable':    'Service unavailable. Try again in a moment.',
  'chat.error.generic':        'Request failed.',
  'chat.overlength':           '{count} / {max} characters',
  'chat.ticker.switched':      'Switched to {ticker} — previous chat saved to Library',
  'chat.thinking':             'Thinking…',
  'chat.tool.share':           'Share to chat',

  // ── Library ──
  'library.title':             'Library',
  'library.empty':             'No saved analyses yet. Run any tool to start filling your library.',
  'library.filter.all':        'All',
  'library.filter.dcf':        'DCF',
  'library.filter.lbo':        'LBO',
  'library.filter.comps':      'Comps',
  'library.filter.research':   'Research',
  'library.filter.icmemo':     'IC memo',
  'library.delete':            'Delete',
  'library.export':            'Export',
  'library.open':              'Open',

  // ── Settings ──
  'settings.title':            'Settings',
  'settings.section.appearance': 'Appearance',
  'settings.language':         'Language',
  'settings.section.models':   'Models & API keys',
  'settings.section.data':     'Data sources',
  'settings.section.about':    'About',
  'settings.model.default':    'Default model',
  'settings.apikey.deepseek':  'DeepSeek API key',
  'settings.apikey.anthropic': 'Anthropic API key',
  'settings.apikey.openai':    'OpenAI API key',
  'settings.apikey.placeholder': 'sk-…',
  'settings.apikey.set':       '✓ Set',
  'settings.apikey.notset':    'Not configured',
  'settings.save':             'Save',
  'settings.saved':            'Saved.',
  'settings.saveFailed':       'Save failed: {error}',

  // ── Warnings / common ──
  'common.loading':            'Loading…',
  'common.error':              'Error',
  'common.retry':              'Retry',
  'common.cancel':              'Cancel',
  'common.close':              'Close',
  'common.open':                'Open',
  'common.delete':              'Delete',
  'common.notAvailable':        'N/A',

  // ── Command palette (⌘K) ──
  'cmdk.placeholder':          'Ticker, question or /command…',
  'cmdk.search.aria':          'Search',
  'cmdk.results.aria':         'Search results',
  'cmdk.results.searching':    'Searching…',
  'cmdk.results.timeout':      'Search timed out. Try again.',
  'cmdk.results.networkError': 'Search failed — check your network connection.',
  'cmdk.results.nothing':      'Nothing matched "{query}"',
  'cmdk.results.askHint':      'Press Enter to ask the AI / start a new chat',
  'cmdk.empty':                'Type a ticker (e.g. AAPL), a question, or a /command',
  'cmdk.section.recent':       'Recent searches',
  'cmdk.section.commands':     'Commands',
  'cmdk.section.artifacts':    'Past analyses',
  'cmdk.section.sessions':     'Chat history',
  'cmdk.foot.select':          'Select',
  'cmdk.foot.confirm':         'Confirm',
  'cmdk.foot.close':           'Close',
  'cmdk.foot.tipDcf':          'Type /dcf AAPL to run a tool directly',
  'cmdk.overlength':           'Query truncated (max {max} chars)',
  'cmdk.error.invalidAction':  'Invalid action',
  'cmdk.error.tickerRequired': 'A ticker is required to run that tool',
  'cmdk.error.unknownAction':  'Unknown action',
  'cmdk.error.actionFailed':   'Action failed',

  // ── Tool cards ──
  'toolcard.openArtifact':     '📁 Open artifact',
  'toolcard.failed':           'Tool call failed',
  'toolcard.retry':            'Retry',
}

const zh: Dict = {
  // ── Brand / shell ──
  'app.name':                'FinAgent',
  'app.tagline':             'AI 驱动的股票研究工作站',

  'topbar.search.placeholder': '搜索股票或提问 (⌘K)',
  'topbar.settings.tooltip':   '设置',
  'topbar.account.tooltip':    '账号',
  'topbar.language.tooltip':   '语言',

  'nav.stocks':                '股票',
  'nav.library':               '资料库',
  'nav.settings':              '设置',
  'nav.recent':                '最近',
  'nav.recent.empty':          '访问过的股票会显示在这里',

  'stocks.empty.title':        '输入股票代码或从下方选择',
  'stocks.empty.placeholder':  'AAPL',
  'stocks.empty.analyze':      '分析',
  'stocks.empty.recent':       '最近',
  'stocks.empty.quick':        '快捷',
  'stocks.empty.invalid':      '只能是字母、数字、点和短划线（最长 12 位）',

  'stock.watchlist.add':       '☆ 加入关注',
  'stock.watchlist.remove':    '★ 已关注',
  'stock.marketcap':           '市值',
  'stock.loading':             '加载行情中…',
  'stock.error.title':         '无法加载行情',
  'stock.error.retry':         '重试',

  'verb.dcf':                  '跑 DCF',
  'verb.lbo':                  '跑 LBO',
  'verb.comps':                '对比同业',
  'verb.catalysts':            '找催化剂',
  'verb.ic-memo':              'IC Memo',
  'verb.ddm':                  '跑 DDM',
  'verb.earnings':             'Earnings',
  'verb.ask-ai':               '问 AI',
  'verb.more':                 '更多',
  'verb.dcf.tooltip':          '使用默认假设和实时财务数据，计算 DCF 估值',
  'verb.lbo.tooltip':          '运行 LBO 模型：IRR、MOIC、债务摊销、敏感性',
  'verb.comps.tooltip':        '同业对比分析 — 抓取可比公司倍数',
  'verb.catalysts.tooltip':    '从近期新闻和公告中提取潜在催化剂',
  'verb.ic-memo.tooltip':      '生成投委会备忘录：情境、论点、风险、建议',
  'verb.ddm.tooltip':          '股息折现模型 — 适用于银行/分红股',
  'verb.earnings.tooltip':     '财报分析 — beat/miss 分类 + 趋势',
  'verb.ask-ai.tooltip':       '展开聊天面板，针对这只股票提问',

  'tab.overview':              '概览',
  'tab.financials':            '财务',
  'tab.performance':           '走势',
  'tab.news':                  '新闻',
  'tab.valuation':             '估值',
  'tab.comps':                 '可比公司',
  'tab.history':               '历史',
  'tab.research':              '10-K 问答',

  'research.heading':          '10-K 问答',
  'research.placeholder':      '针对这家公司的 10-K 年报提问…',
  'research.ask':              '提问',
  'research.empty':            '提一个关于 SEC 10-K 年报的问题来开始。',
  'research.source':           '来源：SEC 10-K 年报',
  'research.citations':        '引用段落',
  'research.relevance':        '相关度',
  'research.error':            '获取回答失败。请确认后端服务已启动。',

  'valuation.dcf.title':       'DCF 工作区',
  'valuation.dcf.empty':       '尚未运行 DCF。点击上方 "跑 DCF" 开始估值。',
  'valuation.dcf.cta':         '立即跑 DCF',
  'valuation.comp.title':      '综合估值',
  'valuation.lbo.title':       'LBO 分析',
  'valuation.source.research': '估值来自研究流程。如需重新假设，请运行独立 DCF。',
  'valuation.source.standalone': '独立 DCF 分析。',

  'peers.empty':               '尚未做同业对比。点击 "对比同业" 开始分析。',
  'peers.cta':                 '立即对比同业',

  'tool.toast.success':        '{tool} 完成 — 已保存到资料库',
  'tool.toast.failure':        '{tool} 失败',
  'tool.error.unavailable':    '后端不可用 — 服务有没有在跑？',
  'tool.error.invalid':        '{tool} 入参非法',
  'tool.error.unsupported':    '{tool} 尚未支持',
  'tool.error.generic':        '{tool} 失败（HTTP {status}）',
  'tool.error.cancelled':      '已取消',
  'tool.error.unknown':        '未知错误',

  'chat.title.new':            '新对话',
  'chat.title.explore':        '探索',
  'chat.empty.heading':        '问一个关于金融的问题',
  'chat.empty.body':           '我能查实时行情、财报、新闻，也能跑估值模型。',
  'chat.empty.example.1':      '{ticker} 今天为什么跌？',
  'chat.empty.example.2':      '总结 {ticker} 上季度业绩',
  'chat.empty.example.3':      '把 {ticker} 和同业对比一下',
  'chat.empty.example.generic.1': '30 秒解释 DCF',
  'chat.empty.example.generic.2': 'LBO 和 DCF 有什么区别？',
  'chat.empty.example.generic.3': '怎么读 10-K 年报？',
  'chat.input.placeholder':    '给 FinAgent 留言…（Enter 发送，Shift+Enter 换行）',
  'chat.send':                 '发送',
  'chat.stop':                 '停止',
  'chat.retry':                '重试',
  'chat.newSession':           '新对话',
  'chat.collapse':             '收起',
  'chat.expand':               '展开对话',
  'chat.history':              '历史',
  'chat.model.tooltip':        '选择模型',
  'chat.reasoning':            '思考过程',
  'chat.error.context':        '对话过长，请开启新对话。',
  'chat.error.unavailable':    '服务暂时不可用，稍后再试。',
  'chat.error.generic':        '请求失败。',
  'chat.overlength':           '{count} / {max} 字符',
  'chat.ticker.switched':      '已切到 {ticker} — 旧对话已保存到资料库',
  'chat.thinking':             '思考中…',
  'chat.tool.share':           '分享到对话',

  'library.title':             '资料库',
  'library.empty':             '还没有分析记录。跑任何工具就会出现在这里。',
  'library.filter.all':        '全部',
  'library.filter.dcf':        'DCF',
  'library.filter.lbo':        'LBO',
  'library.filter.comps':      '同业',
  'library.filter.research':   '研究',
  'library.filter.icmemo':     'IC Memo',
  'library.delete':            '删除',
  'library.export':            '导出',
  'library.open':              '打开',

  'settings.title':            '设置',
  'settings.section.appearance': '外观',
  'settings.language':         '语言',
  'settings.section.models':   '模型与 API Key',
  'settings.section.data':     '数据源',
  'settings.section.about':    '关于',
  'settings.model.default':    '默认模型',
  'settings.apikey.deepseek':  'DeepSeek API Key',
  'settings.apikey.anthropic': 'Anthropic API Key',
  'settings.apikey.openai':    'OpenAI API Key',
  'settings.apikey.placeholder': 'sk-…',
  'settings.apikey.set':       '✓ 已配置',
  'settings.apikey.notset':    '未配置',
  'settings.save':             '保存',
  'settings.saved':            '已保存',
  'settings.saveFailed':       '保存失败：{error}',

  'common.loading':            '加载中…',
  'common.error':              '错误',
  'common.retry':              '重试',
  'common.cancel':              '取消',
  'common.close':              '关闭',
  'common.open':                '打开',
  'common.delete':              '删除',
  'common.notAvailable':        '—',

  'cmdk.placeholder':          '股票代码、问题或 /命令…',
  'cmdk.search.aria':          '搜索',
  'cmdk.results.aria':         '搜索结果',
  'cmdk.results.searching':    '搜索中…',
  'cmdk.results.timeout':      '搜索超时，请重试',
  'cmdk.results.networkError': '搜索失败 — 请检查网络',
  'cmdk.results.nothing':      '没找到 "{query}"',
  'cmdk.results.askHint':      '按 Enter 直接问 AI / 开始新对话',
  'cmdk.empty':                '输入股票代码（如 AAPL）、问题或 /命令',
  'cmdk.section.recent':       '最近搜索',
  'cmdk.section.commands':     '命令',
  'cmdk.section.artifacts':    '历史分析',
  'cmdk.section.sessions':     '对话历史',
  'cmdk.foot.select':          '选择',
  'cmdk.foot.confirm':         '确认',
  'cmdk.foot.close':           '关闭',
  'cmdk.foot.tipDcf':          '输入 /dcf AAPL 直接跑工具',
  'cmdk.overlength':           '查询过长，已截断（最多 {max} 字符）',
  'cmdk.error.invalidAction':  '操作格式无效',
  'cmdk.error.tickerRequired': '运行工具需要指定股票代码',
  'cmdk.error.unknownAction':  '未知操作类型',
  'cmdk.error.actionFailed':   '操作执行失败',

  'toolcard.openArtifact':     '📁 打开 artifact',
  'toolcard.failed':           '工具调用失败',
  'toolcard.retry':            '重试',
}

export const MESSAGES: Record<Locale, Dict> = { en, zh }

export type MessageKey = keyof typeof en

/**
 * Translate a key with optional {param} substitutions.
 * Falls back to English when the key is missing in the active locale.
 * Falls back to the key string itself if nothing matches — never throws.
 */
export function translate(
  locale: Locale,
  key: string,
  params?: Record<string, string | number>,
): string {
  const dict = MESSAGES[locale] ?? MESSAGES.en
  let s = dict[key] ?? MESSAGES.en[key] ?? key
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
    }
  }
  return s
}
