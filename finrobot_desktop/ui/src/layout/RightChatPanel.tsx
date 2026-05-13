interface RightChatPanelProps {
  expanded: boolean;
  onToggle: () => void;
}

export function RightChatPanel({ expanded, onToggle }: RightChatPanelProps) {
  return (
    <aside
      className="flex flex-col border-l"
      style={{
        borderColor: "var(--border)",
        backgroundColor: "var(--surface)",
        width: expanded ? "320px" : "56px",
        transition: "width 0.2s ease",
        overflow: "hidden",
      }}
    >
      <button
        onClick={onToggle}
        className="border-b p-3 text-center text-xs transition-colors"
        style={{
          borderColor: "var(--border)",
          color: "var(--text-secondary)",
          minHeight: "48px",
        }}
        title={expanded ? "收起对话" : "展开对话"}
      >
        💬
      </button>
      {expanded && (
        <div className="flex-1 p-3 text-xs" style={{ color: "var(--text-muted)" }}>
          {/* 后续 right-panel-chat agent 填充 */}
          (对话面板待实现)
        </div>
      )}
    </aside>
  );
}
