import { useAppStore } from "../stores/appStore";

export function TopBar() {
  return (
    <header
      className="flex items-center justify-between border-b px-4"
      style={{
        borderColor: "var(--border)",
        backgroundColor: "var(--base)",
        height: "60px",
      }}
    >
      <div className="flex items-center gap-3">
        <button
          className="rounded border px-3 py-1.5 text-sm transition-colors"
          style={{
            borderColor: "var(--border)",
            backgroundColor: "var(--surface)",
            color: "var(--text-secondary)",
          }}
          onClick={() => {
            useAppStore.getState().toggleCmdPalette();
          }}
          title="Command Palette (⌘K)"
        >
          🔍 ticker 或问题 (⌘K)
        </button>
      </div>

      <div className="flex items-center gap-3">
        {/* 模型选择器占位 */}
        <select
          className="rounded border px-2 py-1 text-xs"
          style={{
            borderColor: "var(--border)",
            backgroundColor: "var(--surface)",
            color: "var(--text-secondary)",
          }}
        >
          <option>DeepSeek</option>
          <option>Claude</option>
          <option>OpenAI</option>
        </select>

        <button
          className="text-sm transition-colors"
          style={{ color: "var(--text-secondary)" }}
          title="Settings"
        >
          ⚙️
        </button>

        <div
          className="h-7 w-7 rounded-full"
          style={{ backgroundColor: "var(--elevated)" }}
          title="账号"
        />
      </div>
    </header>
  );
}
