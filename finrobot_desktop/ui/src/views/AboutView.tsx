// AboutView — Phase 5 T5.5
// 关于页：产品介绍 + 三种接入方式 + 底部链接。
// 不拉取 GitHub Star 数（REFACTOR §10，留 P2+）。

import { useState } from 'react'
import { openExternal } from '../lib/tauri'

interface CodeBlockProps {
  code: string
}

function CodeBlock({ code }: CodeBlockProps): React.ReactElement {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }

  return (
    <div className="about-code-block">
      <pre className="about-code-pre">{code}</pre>
      <button
        className="about-copy-btn"
        onClick={handleCopy}
        title="复制到剪贴板"
      >
        {copied ? '已复制' : '复制'}
      </button>
    </div>
  )
}

const CLI_CODE = `pip install finagent
finagent run pl-001 --symbol NVDA`

const SDK_CODE = `from finagent import Agent
agent = Agent(model="deepseek-chat")
result = agent.run("分析英伟达最新财报")`

export default function AboutView(): React.ReactElement {
  function link(url: string) {
    return () => void openExternal(url)
  }

  return (
    <div className="about-root">
      {/* Hero */}
      <div className="about-hero">
        <div className="about-logo">FinAgent</div>
        <p className="about-tagline">
          确定性金融计算 × LLM 叙事能力
        </p>
        <p className="about-desc">
          开源金融分析平台（Apache-2.0），把确定性金融计算和 LLM
          叙事能力配在一起。后端 PydanticAI + FastAPI；桌面端 Tauri + React 19。
        </p>
      </div>

      {/* 三种接入方式 */}
      <div className="about-methods">
        {/* CLI */}
        <div className="about-method-card">
          <div className="about-method-header">
            <span className="about-method-badge mode-b">CLI</span>
            <span className="about-method-title">命令行</span>
          </div>
          <CodeBlock code={CLI_CODE} />
        </div>

        {/* Python SDK */}
        <div className="about-method-card">
          <div className="about-method-header">
            <span className="about-method-badge mode-b">SDK</span>
            <span className="about-method-title">Python SDK</span>
          </div>
          <CodeBlock code={SDK_CODE} />
        </div>

        {/* Desktop — current */}
        <div className="about-method-card about-method-card--active">
          <div className="about-method-header">
            <span className="about-method-badge mode-a">Desktop</span>
            <span className="about-method-title">桌面端</span>
          </div>
          <div className="about-desktop-badge">
            你已经在桌面端 ✓
          </div>
          <p className="about-desktop-note">
            Tauri + React 19 · 本地优先 · Apache-2.0
          </p>
        </div>
      </div>

      {/* 底部链接 */}
      <div className="about-links">
        <button
          className="about-link-btn about-link-primary"
          onClick={link('https://github.com/finagent/finagent')}
        >
          Star on GitHub
        </button>
        <button
          className="about-link-btn"
          onClick={link('https://github.com/finagent/finagent#readme')}
        >
          查看文档
        </button>
        <button
          className="about-link-btn"
          onClick={link('https://github.com/finagent/finagent/issues')}
        >
          报告 Issue
        </button>
      </div>
    </div>
  )
}
