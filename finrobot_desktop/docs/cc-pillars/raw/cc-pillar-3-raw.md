# Raw Research: Claude Code System Prompt Assembly (Pillar 3)

**来源**: Explore 子 agent 深度通读 CC `src/constants/prompts.ts`、`src/outputStyles/`、`src/memdir/`、`src/QueryEngine.ts`
**日期**: 2026-05-12

---

## A. 装配流程

**入口**: `getSystemPrompt(tools, model, additionalDirs?, mcpClients?) -> Promise<string[]>`
- 位置: `src/constants/prompts.ts:444`
- 返回 `string[]` 数组（由 `asSystemPrompt()` 包装成 `SystemPrompt` 品牌类型）

**顶层装配** (`QueryEngine.ts:321-324`):
```typescript
const systemPrompt = asSystemPrompt([
  ...(customPrompt !== undefined ? [customPrompt] : defaultSystemPrompt),
  ...(memoryMechanicsPrompt ? [memoryMechanicsPrompt] : []),
  ...(appendSystemPrompt ? [appendSystemPrompt] : []),
])
```

## B. 装配层（按实际顺序）

**静态部分**（缓存友好，scope='global'）：
1. `getSimpleIntroSection()` — base identity + cyber risk
2. `getSimpleSystemSection()` — tool 执行 / permission / hooks 指导
3. `getSimpleDoingTasksSection()` — coding 指令（可被 outputStyle 跳过）
4. `getActionsSection()` — tool 调用规范
5. `getUsingYourToolsSection()` — 按 tools Set 定制
6. `getSimpleToneAndStyleSection()`

**`SYSTEM_PROMPT_DYNAMIC_BOUNDARY`** 分隔标记（位置：`prompts.ts:572`）

**动态部分**（用户 / 会话特定）：
7. session_guidance — skill commands + agent tool 指导
8. memory — `loadMemoryPrompt()` 注入
9. ant_model_override — Ant 员工定制
10. env_info_simple — git status / platform / model
11. language — 用户语言偏好
12. output_style — OutputStyle prompt
13. mcp_instructions — MCP servers
14. scratchpad — Scratchpad 访问
15. frc — Function Result Clearing
16. summarize_tool_results
17. numeric_length_anchors — Ant 长度限制
18. token_budget — 当启用 TOKEN_BUDGET
19. brief — KAIROS Brief

**运行时追加**：`appendSystemContext(systemPrompt, systemContext)` 在 `query.ts:450` 把 systemContext（git status、cache breaker）附加到末尾

## C. OutputStyles 机制

**目录**：
- 项目级 `.claude/output-styles/*.md`
- 用户级 `~/.claude/output-styles/*.md`
- 插件级 `loadPluginOutputStyles()`
- 内置常量 `OUTPUT_STYLE_CONFIG`

**内置风格**（`constants/outputStyles.ts:41-135`）：
- `default` — null（无额外 prompt）
- `Explanatory` — 教育模式，用 `✨ Insight` 标记
- `Learning` — 交互学习，暂停请用户实现 2-10 行代码片段

**数据结构**：
```typescript
type OutputStyleConfig = {
  name: string
  description: string
  prompt: string                       // 从 md 文件 frontmatter 后的 content
  source: SettingSource | 'built-in' | 'plugin'
  keepCodingInstructions?: boolean     // 若 false，跳过 doing-tasks section
  forceForPlugin?: boolean
}
```

**加载**：`getAllOutputStyles(cwd)` 合并 built-in + plugin + 自定义。优先级：plugin < user < project < managed。

**切换时机**：运行时，`settings.outputStyle` 控制。

**对 prompt 的 3 种影响**：
1. 替换 identity section（`getSimpleIntroSection(outputStyleConfig)`）
2. 追加 style prompt（`getOutputStyleSection(outputStyleConfig)`）
3. 条件性跳过 coding instructions（若 `keepCodingInstructions === false`）

**能改工具行为吗**：否，仅影响输出文本风格 + 人物设定 + 可选跳过 coding instructions。

## D. Memory 注入

**目录约定**：
- `~/.claude/memory/` 或 `.claude/memory/`（由 `isAutoMemoryEnabled()` 控制）
- Teamwork: `~/.claude/memory/team/`
- KAIROS daily log: `~/.claude/memory/daily-logs/`

**加载** (`memdir/memdir.ts:loadMemoryPrompt()`)：
- KAIROS + auto enabled → `buildAssistantDailyLogPrompt(skipIndex)`
- TEAMMEM → `buildCombinedMemoryPrompt(...)`
- 标准 → `buildMemoryPrompt(autoDir, undefined)`
- 目录走查：`getMemoryFiles()` 加载所有 .md / .mdx

**注入位置**：
- 两处：系统 prompt 动态层 `memory` section + 用户 context（`getUserContext()`）

**冲突处理**：KAIROS > TEAMMEM > 标准；同名时 team 覆盖 auto。

## E. Skills 注入

**注册流程**：
- `getSkillToolCommands(cwd)` 扫描 `~/.claude/skills/` + 项目 `.claude/skills/`
- 在 `getSessionSpecificGuidanceSection()` 中检查 `skillToolCommands.length > 0`
- 满足条件追加："/<skill-name> 是用户快捷调用，用 SkillTool 执行"

**Prefetch vs 懒加载**：
- 标准：runtime 按需加载（Skill Tool 执行时读取）
- Feature gate `EXPERIMENTAL_SKILL_SEARCH` 启用时 prefetch

**System prompt 中不直接嵌入 skill 内容**——只列可用 skill 名称。

**优先级**：项目 skill 覆盖用户 skill（同名）

## F. Prompt Caching 协同

**全局 scope**（`scope='global'`）：
- 前提：`shouldUseGlobalCacheScope()` true（1P Anthropic API 专属）
- `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 标记之前的所有块
- 内容：static identity + system + tools 指导
- TTL：~5 分钟

**Org scope**（`scope='org'`）：
- 备选：MCP 存在或 3P provider
- 内容：attribution header 外所有内容
- TTL：同上

**Ephemeral / 不缓存**：
- Attribution header
- Dynamic boundary 之后的所有内容

**装配顺序对 cache 的影响**：
- boundary 越靠后 → 越多静态内容可缓存
- 当前设计：boundary 在所有会话特定内容之前 → 最大化静态缓存

## G. 关键代码片段

```typescript
// QueryEngine.ts:321-324 — 顶层装配
const systemPrompt = asSystemPrompt([
  ...(customPrompt !== undefined ? [customPrompt] : defaultSystemPrompt),
  ...(memoryMechanicsPrompt ? [memoryMechanicsPrompt] : []),
  ...(appendSystemPrompt ? [appendSystemPrompt] : []),
])

// constants/outputStyles.ts:181-211 — OutputStyle 加载
export async function getOutputStyleConfig(): Promise<OutputStyleConfig | null> {
  const allStyles = await getAllOutputStyles(getCwd())
  const forcedStyles = Object.values(allStyles).filter(
    (s): s is OutputStyleConfig => s !== null && s.source === 'plugin' && s.forceForPlugin === true,
  )
  if (forcedStyles[0]) return forcedStyles[0]
  const settings = getSettings_DEPRECATED()
  const outputStyle = (settings?.outputStyle || DEFAULT_OUTPUT_STYLE_NAME) as string
  return allStyles[outputStyle] ?? null
}

// utils/api.ts:388-395 — Cache control 标记
if (useGlobalCacheFeature) {
  const boundaryIndex = systemPrompt.findIndex(s => s === SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
  if (boundaryIndex !== -1) {
    const staticJoined = staticBlocks.join('\n\n')
    if (staticJoined) result.push({ text: staticJoined, cacheScope: 'global' })
  }
}
```

## H. 未理解的部分

1. Reactive Compact 是否动态修改 system prompt？
2. Context Collapse 是否影响 prompt 装配？
3. Skill Search Prefetch 与运行时 skill prompt 展开的关系
4. OutputStyle `keepCodingInstructions: false` 是整段跳过还是部分？
5. `appendSystemPrompt` 的位置（memory 后）是设计还是偶然？
