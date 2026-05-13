import { useState } from "react";
import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";
import { LeftNav } from "./LeftNav";
import { RightChatPanel } from "./RightChatPanel";
import { CmdKOverlay } from "./CmdKOverlay";

export function AppShell() {
  const [chatExpanded, setChatExpanded] = useState(false);

  return (
    <div
      className="flex h-screen flex-col"
      style={{ backgroundColor: "var(--base)", color: "var(--text-primary)" }}
    >
      {/* Top bar — fixed 60px row */}
      <TopBar />

      {/* Body — remaining height */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left nav — fixed 240px */}
        <LeftNav />

        {/* Main content — flex-1 */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>

        {/* Right chat panel — collapsible */}
        <RightChatPanel
          expanded={chatExpanded}
          onToggle={() => setChatExpanded((v) => !v)}
        />
      </div>

      {/* Global cmd+K overlay */}
      <CmdKOverlay />
    </div>
  );
}
