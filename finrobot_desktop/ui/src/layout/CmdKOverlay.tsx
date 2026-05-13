import { useEffect, useState } from "react";
import { useAppStore } from "../stores/appStore";

export function CmdKOverlay() {
  const cmdOpen = useAppStore((s) => s.cmdPaletteOpen);
  const [localOpen, setLocalOpen] = useState(false);

  // Sync with appStore's cmdPaletteOpen
  useEffect(() => {
    setLocalOpen(cmdOpen);
  }, [cmdOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        useAppStore.getState().toggleCmdPalette();
      }
      if (e.key === "Escape" && localOpen) {
        useAppStore.getState().setCmdPaletteOpen(false);
      }
    };
    const onOpen = () => useAppStore.getState().setCmdPaletteOpen(true);

    window.addEventListener("keydown", onKey);
    window.addEventListener("finagent:open-cmdk", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("finagent:open-cmdk", onOpen);
    };
  }, [localOpen]);

  if (!localOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-start pt-32"
      style={{ backgroundColor: "rgba(0,0,0,0.6)" }}
      onClick={() => useAppStore.getState().setCmdPaletteOpen(false)}
    >
      <div
        className="mx-auto w-[600px] rounded-lg border shadow-2xl"
        style={{
          borderColor: "var(--border)",
          backgroundColor: "var(--elevated)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          placeholder="输入 ticker 或问题..."
          className="w-full bg-transparent px-4 py-3 text-sm outline-none"
          style={{
            color: "var(--text-primary)",
          }}
        />
        <div
          className="border-t p-3 text-xs"
          style={{
            borderColor: "var(--border)",
            color: "var(--text-muted)",
          }}
        >
          (搜索逻辑待 cmd+K agent 填充)
        </div>
      </div>
    </div>
  );
}
