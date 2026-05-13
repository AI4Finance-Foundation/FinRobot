import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/stocks", icon: "📈", label: "Stocks" },
  { to: "/library", icon: "📚", label: "Library" },
  { to: "/settings", icon: "⚙️", label: "Settings" },
];

export function LeftNav() {
  return (
    <nav
      className="flex flex-col border-r p-3"
      style={{
        borderColor: "var(--border)",
        backgroundColor: "var(--surface)",
        width: "240px",
      }}
    >
      {/* Brand */}
      <div
        className="mb-4 flex items-center gap-2 px-1"
        style={{ color: "var(--text-primary)" }}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <rect x="1" y="4" width="4" height="12" rx="1" fill="#C9A84C" />
          <rect x="8" y="2" width="4" height="14" rx="1" fill="#C9A84C" opacity="0.6" />
          <rect x="15" y="6" width="4" height="10" rx="1" fill="#C9A84C" opacity="0.35" />
        </svg>
        <span className="text-base font-semibold">
          Fin<span style={{ color: "var(--gold)" }}>Agent</span>
        </span>
      </div>

      {/* Nav items */}
      <ul className="flex flex-col gap-1">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className="flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors"
              style={({ isActive }) =>
                isActive
                  ? {
                      backgroundColor: "rgba(201, 168, 76, 0.10)",
                      color: "var(--gold)",
                      borderLeft: "2px solid var(--gold)",
                      paddingLeft: "10px",
                    }
                  : {
                      color: "var(--text-secondary)",
                    }
              }
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      {/* Recent tickers slot */}
      <div
        className="mt-6 text-xs uppercase tracking-wider"
        style={{ color: "var(--text-muted)" }}
      >
        最近
      </div>
      <div
        data-testid="recent-tickers-slot"
        className="mt-2 text-xs"
        style={{ color: "var(--text-muted)" }}
      >
        (待填充)
      </div>
    </nav>
  );
}
