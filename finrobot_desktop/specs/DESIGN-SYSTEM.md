# FinAgent Design System v1.0

> **Status**: Locked — all desktop UI work must follow this spec
> **Visual reference**: `资料/finagent-design-demo.html`（在浏览器打开查看）
> **Aesthetic direction**: "Bloomberg meets Linear" — precision finance, not enterprise SaaS

---

## 1. Design Principles

| 原则 | 含义 | 违反示例 |
|------|------|----------|
| **精确** | 每个数字有出处，UI 传达"我不猜、我算" | 用 placeholder 数据不标注来源 |
| **克制** | 不花哨、不炫技。金融专业人士讨厌花里胡哨 | 渐变按钮、彩虹配色、大圆角 |
| **可信** | 看一眼就知道这是专业工具，不是玩具 | 用 Ant Design 默认蓝、消费品风格圆角 |

---

## 2. Color Tokens

所有颜色通过 CSS 变量引用，不允许硬编码 hex。

```css
:root {
  /* ── Background Layers ── */
  --base:          #0B0E14;   /* 页面底色，深墨蓝 */
  --surface:       #131720;   /* 卡片/面板 */
  --elevated:      #1A1F2E;   /* 悬浮/弹窗/hover 态 */
  --border:        #252A37;   /* 分隔线 */
  --border-subtle: #1C2030;   /* 卡片边框（比 border 更淡） */

  /* ── Text ── */
  --text-primary:   #E8ECF4;  /* 主文字 */
  --text-secondary: #7A8299;  /* 辅助说明 */
  --text-muted:     #4A5168;  /* 最弱层级（标签、占位符） */

  /* ── Brand ── */
  --gold:       #C9A84C;                  /* 品牌金色 */
  --gold-dim:   rgba(201, 168, 76, 0.15); /* 金色背景态 */
  --gold-glow:  rgba(201, 168, 76, 0.06); /* 微弱光晕 */

  /* ── Semantic ── */
  --positive:    #34D399;                   /* 涨/好 */
  --positive-bg: rgba(52, 211, 153, 0.10);
  --negative:    #F87171;                   /* 跌/差 */
  --negative-bg: rgba(248, 113, 113, 0.10);
  --warning:     #FBBF24;                   /* 警告 */
  --info:        #60A5FA;                   /* 信息 */

  /* ── Chart Palette（按顺序使用） ── */
  --chart-1: #60A5FA;  /* 蓝 — 主系列 */
  --chart-2: #C9A84C;  /* 金 — 对比系列 */
  --chart-3: #34D399;  /* 青绿 */
  --chart-4: #A78BFA;  /* 淡紫 */
  --chart-5: #FB923C;  /* 橙 */
  /* Forecast 系列：以上色值 40% opacity */
}
```

### 颜色使用规则

- 金色**只用于**：品牌标识、当前估值价格、active 态滑块、pipeline 运行中指示器、卡片 badge
- 涨绿跌红**不可覆盖**——全球金融惯例
- 图表背景**透明**，与卡片融合，不单独加底色
- 不使用渐变色（唯一例外：估值卡片顶部 2px 金色渐变线）

---

## 3. Typography

### 字体栈

```css
--font-ui:   'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
--font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
```

**安装**：Google Fonts CDN 或 npm 包 `@fontsource/dm-sans` + `@fontsource/jetbrains-mono`

### 使用规则

| 场景 | 字体 | 字重 | 字号 | 其他 |
|------|------|------|------|------|
| 估值大数字 | Mono | 700 | 2.8rem | letter-spacing: -0.03em |
| 数据表格值 | Mono | 500 | 0.82rem | — |
| Ticker 代码 | Mono | 700 | 1rem | letter-spacing: 0.03em, 金色 |
| 涨跌幅 | Mono | 600 | 0.8rem | 带语义色背景 pill |
| 卡片标题 | UI | 600 | 0.75rem | uppercase, letter-spacing: 0.06em |
| 正文/标签 | UI | 400 | 0.82rem | — |
| Metric 标签 | UI | 500 | 0.7rem | uppercase, letter-spacing: 0.05em, muted 色 |

**核心规则**：所有金融数字（价格、倍数、百分比、金额）**必须用等宽字体**。列对齐是金融界面的基本尊严。

---

## 4. Spacing & Layout

### 间距系统（4px 倍数）

```css
--sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px;  --sp-4: 16px;
--sp-5: 20px; --sp-6: 24px; --sp-8: 32px;  --sp-10: 40px;
```

### 圆角

```css
--r-sm: 4px;  /* 小元素：badge, pill */
--r-md: 6px;  /* 按钮、输入框 */
--r-lg: 8px;  /* 卡片 */
```

**规则**：圆角不超过 8px。大圆角是消费品 app 风格，不是专业工具。

### 主布局

```
┌─ Top Bar (48px, fixed) ──────────────────────────────────┐
│  Logo    Ticker · Name · Price · Change        [Settings]│
├─────────────────────────┬────────────────────────────────┤
│  Left Panel (340px)     │  Right Canvas (flex: 1)        │
│  - Fundamentals 表格    │  - Warning Banner              │
│  - Pipeline 进度        │  - Valuation Hero Card         │
│  - Assumptions 滑块     │  - 2-col grid:                 │
│                         │    Sensitivity | Waterfall      │
│                         │    Revenue     | Margins        │
│                         │  - Export Bar                   │
└─────────────────────────┴────────────────────────────────┘
```

- Top Bar: 毛玻璃效果 `backdrop-filter: blur(12px)`
- 左栏: 输入/控制（固定 340px, 可滚动）
- 右栏: 输出/结果（flex: 1, 可滚动, 2 列 grid）
- 逻辑: **左边操作，右边反馈**

---

## 5. Component Specs

### Card

```css
.card {
  background: var(--surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-lg);
}
.card-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  /* 标题用 card-title 样式, 右侧可放 card-badge */
}
.card-body { padding: 16px; }
```

阴影最多一层：`0 1px 3px rgba(0,0,0,0.3)`。通常不用阴影，靠边框区分层级。

### Valuation Hero Card

最重要的组件——用户眼睛第一个看到的地方。

- 顶部 2px 金色渐变线: `linear-gradient(90deg, var(--gold), rgba(201,168,76,0.1))`
- 右上角微弱金色光晕: `radial-gradient(circle at top right, var(--gold-glow), transparent 70%)`
- 大数字: $214.50, Mono 700, 2.8rem
- Upside pill: 绿色背景 + 绿色文字 + 箭头 icon
- 下方 6 格 metrics grid (3 列)

### Sensitivity Heatmap

- 等宽字体，居中对齐
- 颜色梯度: 红 → 黄 → 绿（基于相对于当前价格的 upside/downside）
- 当前值单元格: `outline: 2px solid var(--gold)`
- hover 时微放大: `transform: scale(1.05)`

### Pipeline Progress

- 完成: 绿色圆圈 + checkmark
- 进行中: 金色圆圈 + 脉冲动画 + 进度条
- 待定: 灰色圆圈
- 每步右侧显示耗时（等宽字体）

### Assumptions Slider

- 轨道: 3px, `var(--border)` 色
- 滑块: 14px 圆形, 金色, 2px base 色边框
- hover 时微放大 `scale(1.2)`
- 右侧数值: 等宽字体, 右对齐, 固定 52px 宽

### Button

```
默认:  background: var(--elevated), border: var(--border), 文字 secondary
Hover: background: var(--border), 文字 primary
主要:  background: var(--gold), 文字 var(--base), font-weight 600
```

### Warning Banner

- 背景: `rgba(251,191,36,0.06)`
- 边框: `rgba(251,191,36,0.15)`
- 文字: `var(--warning)` 色
- 左侧三角警告 icon

---

## 6. Chart Styling (Recharts)

```typescript
// 统一 Recharts 配置
const CHART_THEME = {
  xAxis: { tick: { fill: '#7A8299' }, axisLine: { stroke: '#252A37' } },
  yAxis: { tick: { fill: '#7A8299' }, axisLine: { stroke: '#252A37' } },
  tooltip: {
    contentStyle: {
      background: '#1A1F2E',
      border: '1px solid #252A37',
      borderRadius: 6,
      color: '#E8ECF4',
      fontFamily: 'JetBrains Mono',
      fontSize: '0.78rem',
    },
  },
  grid: { stroke: '#1C2030' },
};
```

- 图表容器: 无独立背景色，与卡片融合
- Forecast 数据: 实线同色但 opacity 0.4-0.45
- Forecast 分割线: 虚线 `strokeDasharray="4,4"`, muted 色

---

## 7. Animation

- 页面加载: `fadeUp` 动画，stagger 每个卡片延迟 50ms
- 交互: `transition: all 0.15s` (按钮/hover 态)
- Pipeline pulse: `box-shadow 0 0 0 4px rgba(gold, 0.3)` 呼吸动画
- 进度条: 从左到右滑动动画
- 不使用弹跳、不使用 3D 变换、不使用 parallax

---

## 8. Hard Rules（红线）

| 规则 | 原因 |
|------|------|
| 永远暗色主题，不做浅色切换 | 金融工具标配，做两套是浪费时间 |
| 数字用等宽字体 | 金融数据必须列对齐 |
| 圆角不超过 8px | 大圆角是消费品 app 风格 |
| 不用渐变色（估值卡片顶线除外） | 克制 |
| 不用阴影层叠 | 阴影最多一层 |
| 间距用 4px 倍数 | 视觉节奏一致 |
| 金色只用于品牌标识和关键数据高亮 | 滥用变土豪金 |
| 图表背景透明 | 与卡片融合 |
| 不用 Ant Design / Material UI 组件库 | 风格不匹配，自己写 |
| 所有颜色通过 CSS 变量引用 | 可维护性 |
