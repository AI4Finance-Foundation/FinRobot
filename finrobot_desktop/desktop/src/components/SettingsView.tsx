import { useAppStore } from '../stores/appStore'

export default function SettingsView() {
  const { settings, updateSettings } = useAppStore()

  return (
    <div className="view-container p-6 max-w-2xl mx-auto">
      <h2 className="text-xl font-semibold mb-6">Settings</h2>

      <section className="mb-8">
        <h3 className="text-lg font-medium text-gray-300 mb-4">API Keys</h3>
        <div className="space-y-4">
          {([
            ['fmpApiKey', 'FMP (Financial Modeling Prep)'],
            ['finnhubApiKey', 'Finnhub'],
            ['anthropicApiKey', 'Anthropic (Claude)'],
            ['deepseekApiKey', 'DeepSeek'],
            ['openaiApiKey', 'OpenAI'],
          ] as const).map(([key, label]) => (
            <div key={key}>
              <label className="block text-sm text-gray-400 mb-1">{label}</label>
              <input
                type="password"
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-gray-200"
                value={settings[key]}
                onChange={(e) => updateSettings({ [key]: e.target.value })}
                placeholder={`Enter ${label} API key`}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h3 className="text-lg font-medium text-gray-300 mb-4">Model</h3>
        <select
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-gray-200"
          value={settings.modelName}
          onChange={(e) => updateSettings({ modelName: e.target.value })}
        >
          <option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
          <option value="claude-opus-4-20250514">Claude Opus 4</option>
          <option value="deepseek-chat">DeepSeek Chat</option>
          <option value="gpt-4o">GPT-4o</option>
        </select>
      </section>

      <section className="mb-8">
        <h3 className="text-lg font-medium text-gray-300 mb-4">SEC EDGAR</h3>
        <label className="block text-sm text-gray-400 mb-1">User-Agent</label>
        <input
          type="text"
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-gray-200"
          value={settings.secUserAgent}
          onChange={(e) => updateSettings({ secUserAgent: e.target.value })}
          placeholder="Company Name admin@example.com"
        />
      </section>
    </div>
  )
}
