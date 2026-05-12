#!/bin/bash
# FinAgent 产品精品化循环 v3
# 阶段已变：功能基本齐了，现在要做精品。
# 70% 视觉打磨 + 交互精品化，30% 功能补全。
#
# 用法:
#   ./autofix.sh [轮数，默认10]
#   nohup ./autofix.sh 30 &

set -uo pipefail

ROUNDS=${1:-10}
PROJECT="$(cd "$(dirname "$0")" && pwd)"
LOG="$PROJECT/autofix.log"

echo "═══════════════════════════════════════════" | tee -a "$LOG"
echo "FinAgent Polish v3 — $ROUNDS rounds"        | tee -a "$LOG"
echo "Started: $(date)"                            | tee -a "$LOG"
echo "═══════════════════════════════════════════" | tee -a "$LOG"

for i in $(seq 1 "$ROUNDS"); do
  echo "" | tee -a "$LOG"
  echo "═══ Round $i / $ROUNDS — $(date) ═══" | tee -a "$LOG"

  if (( i % 5 == 1 )); then
    PHASE="research"
  else
    PHASE="execute"
  fi

  echo "Phase: $PHASE" | tee -a "$LOG"

  claude -p "
你是 FinAgent 的技术合伙人，负责把这个产品做到拿得出手。

━━━ 项目背景 ━━━

FinAgent 是 FinRobot（AI4Finance-Foundation 开源项目）的桌面应用重构版。
使命：100% 复刻 FinRobot 所有功能 → 在 UI/UX/产品体验上全面超越。

FinRobot 原版: /Users/zhunihaoyun/Desktop/code/Fin/FinRobot
FinAgent 项目: $PROJECT
QuantDinger（参考）: /Users/zhunihaoyun/Desktop/code/Fin/QuantDinger

目标用户：买方研究员、独立分析师、小基金 PM。
产品定位：数字有保证、流程有纪律的 AI 投资研究工作站。

━━━ 当前阶段：精品化 ━━━

功能已基本齐全（5 条 pipeline、History、Command Palette、图表）。
现在的问题不是"缺功能"，是"不够好看、不够专业、体验粗糙"。

你的工作重心：
  70% — 视觉品质 + 交互打磨（让它看起来值钱）
  30% — 功能补全（FinRobot 还没覆盖的）

━━━ 每轮开始：读真实状态 ━━━

不要凭记忆。执行以下命令：
  1. git -C $PROJECT log --oneline -10
  2. cat $PROJECT/BACKLOG.md | head -100
  3. ls $PROJECT/desktop/src/views/ $PROJECT/desktop/src/components/
  4. cat $PROJECT/specs/PRODUCT-INSIGHTS.md 2>/dev/null | tail -60
  5. cat $PROJECT/desktop/src/App.css | head -50  （看当前设计 token）

━━━ 设计标准 ━━━

对标产品（搜截图对比）：
  - Bloomberg Terminal — 数据密度、专业感、深色主题
  - Koyfin — 现代感、图表美感、交互流畅
  - Linear — 极致精简、键盘优先、微妙动画
  - Raycast — 命令面板交互品质

当前设计系统（$PROJECT/specs/DESIGN-SYSTEM.md）只是起点。
如果丑，直接改。配色、字体、布局、组件、动画都可以动。
改完同步更新 DESIGN-SYSTEM.md。

最终标准：截图发到 Twitter/Hacker News，第一反应是「这个工具看起来很专业」而不是「又一个 side project」。

当前轮次: $i / $ROUNDS
本轮模式: $PHASE

$(if [ "$PHASE" = "research" ]; then cat << RESEARCH
━━━ 研究轮 ━━━

不写代码，只研究和输出报告。

1. 视觉对标（最重要）：
   用 WebSearch 搜索这些，找截图和设计分析：
   - "Koyfin dashboard screenshot dark mode"
   - "Bloomberg terminal UI design analysis"
   - "best financial desktop app UI 2026"
   - "dark theme data dashboard design inspiration dribbble behance"
   用 WebFetch 打开 2-3 个最有价值的结果，提取具体的设计模式。

2. 读 FinAgent 当前的 App.css 和核心组件，对比搜索到的竞品截图，写出：
   - FinAgent 哪里看起来不专业？（具体到组件、配色、间距、字体）
   - 竞品哪里比我们好？（具体的设计手法，不是泛泛而谈）
   - 3 个最值得抄的视觉细节

3. 交互对标：
   - "best command palette UX patterns"
   - "financial app keyboard shortcuts design"
   找到 FinAgent 交互上的差距。

4. FinRobot 功能差距：
   读 /Users/zhunihaoyun/Desktop/code/Fin/FinRobot 源码，对比 FinAgent Desktop 还缺什么。

5. 写入 $PROJECT/specs/PRODUCT-INSIGHTS.md（追加，不覆盖）：
   ---
   ## 研究日期: [日期] — 精品化阶段

   ### 视觉差距（对比竞品截图）
   - [FinAgent 的具体问题]: [竞品怎么做的] → [具体怎么改]

   ### 交互差距
   - [缺失的交互模式]: [竞品怎么做的] → [具体怎么改]

   ### FinRobot 功能差距
   - [缺失功能]: [后端有没有？Desktop 差什么？]

   ### 行动建议（按视觉影响力排序）
   1. [改了之后视觉提升最大的事] — 具体方案: [...]
   2. ...
   ---

输出格式：
ROUND: $i
PHASE: RESEARCH
INSIGHTS: [发现了几条]
TOP_VISUAL_FIX: [视觉上最值得做的一件事]
STATUS: REPORT_WRITTEN
RESEARCH
else cat << EXECUTE
━━━ 执行轮 ━━━

1. 读 $PROJECT/specs/PRODUCT-INSIGHTS.md，按「行动建议」优先级选择做什么。

2. 选出本轮目标后，判断类型：

   类型 A — 视觉改造（可以一次改多个文件）：
   比如"整体调整卡片样式"需要同时改 App.css + 多个组件。
   这种情况允许一轮改 3-5 个文件，但必须保持视觉一致性。
   改完后截图级别地审视每个组件：这个组件放到 Koyfin 旁边丢人吗？

   类型 B — 交互改进（一轮一件事）：
   比如"加 loading 骨架屏"或"修空态设计"。
   一轮只做一个交互点，做到位。

   类型 C — 功能补全（一轮一件事）：
   只在研究报告的"FinRobot 功能差距"里有且评为高优先级的情况下做。
   不要自己发明功能。

3. 视觉检查清单（每轮必须过一遍改动的组件）：
   - 间距是否统一？（用 CSS 变量，不用魔法数字）
   - 颜色是否在 token 系统里？（不硬编码 hex）
   - 数字是否用等宽字体？
   - 空态有没有？（无数据时显示什么）
   - 动画有没有？（组件出现时的 animate-in、hover 态的 transition）
   - 这个组件放到 Bloomberg/Koyfin 旁边，丢不丢人？

4. 代码健壮性检查（改过的文件必须检查）：
   - React hooks 全部在条件 return 之前
   - 可选链防 undefined
   - 列表有唯一 key
   - 无 console.log

5. 验证：
   cd $PROJECT/desktop && npx electron-vite build
   确认无报错。

6. commit（格式按改动类型）：
   视觉：polish(desktop): 具体描述
   交互：ux(desktop): 具体描述
   功能：feat(desktop): 具体描述
   不要 add finagent_cache.db* / node_modules/ / specs/

7. 如果你觉得产品已经达到"截图发到 HN 不丢人"的水平，输出 ALL_CLEAR

输出格式：
ROUND: $i
PHASE: EXECUTE
TYPE: [A:视觉 / B:交互 / C:功能]
CHANGED: [改了哪些文件]
BEFORE_AFTER: [改之前是什么样 → 改之后是什么样]
STATUS: [COMMITTED / FAILED / ALL_CLEAR]
EXECUTE
fi)
" --dangerously-skip-permissions \
  --model opus \
  --allowedTools 'Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch' \
  --max-turns 50 \
  2>&1 | tee -a "$LOG"

  if tail -100 "$LOG" | grep -q "ALL_CLEAR"; then
    echo "" | tee -a "$LOG"
    echo "Product reached target quality. Stopping." | tee -a "$LOG"
    break
  fi

  echo "Cooling down 30s..." | tee -a "$LOG"
  sleep 30
done

echo "" | tee -a "$LOG"
echo "═══════════════════════════════════════════" | tee -a "$LOG"
echo "Done. $i rounds completed at $(date)"       | tee -a "$LOG"
echo "Review: cd $PROJECT && git log --oneline -$i" | tee -a "$LOG"
echo "Research: cat $PROJECT/specs/PRODUCT-INSIGHTS.md" | tee -a "$LOG"
echo "═══════════════════════════════════════════" | tee -a "$LOG"
