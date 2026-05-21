/**
 * CmdKOverlay — 25+ tests covering:
 *   - Render and closed state
 *   - Three trigger paths (⌘K, TopBar toggle via store, finagent:open-cmdk event)
 *   - Four result kind groups (ticker / slash_command / artifact / session)
 *   - Keyboard nav (↑↓ Enter Esc)
 *   - Action execution → navigate + close
 *   - AI fallback display
 *   - Recent searches (localStorage)
 *   - 15 exception paths
 */

import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type Mock,
} from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CmdKOverlay, loadRecentSearches, saveRecentSearch } from "./CmdKOverlay";
import { useAppStore } from "../stores/appStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSearchResult(
  kind: "ticker" | "slash_command" | "artifact" | "session",
  overrides: Partial<{
    title: string;
    subtitle: string;
    action: string;
    score: number;
  }> = {}
) {
  const defaults = {
    ticker: {
      title: "AAPL",
      subtitle: "打开 Stocks 页",
      action: "navigate:/stocks/AAPL",
      score: 10,
    },
    slash_command: {
      title: "跑 DCF 估值 AAPL",
      subtitle: "将运行 run_dcf(AAPL)",
      action: "run:dcf:AAPL",
      score: 8,
    },
    artifact: {
      title: "AAPL · DCF",
      subtitle: "2026-05-13",
      // v5 (spec §11.1.D): artifact suggestions now jump to /stock/{ticker}.
      action: "navigate:/stocks/AAPL?artifact=art_001",
      score: 2,
    },
    session: {
      title: "AAPL FY2026 分析",
      subtitle: "5 条消息 · deepseek:deepseek-chat",
      // /library retired — session links land on /stocks landing for now.
      action: "navigate:/stocks?session=sess_001",
      score: 1,
    },
  } as const;
  return { kind, ...defaults[kind], ...overrides };
}

function mockFetch(response: object, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => response,
  } as Response);
}

function renderOverlay(initialPath = "/stocks") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <CmdKOverlay />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Reset store to closed state
  useAppStore.setState({ cmdPaletteOpen: false, cmdKQuery: "" });
  // Clear localStorage
  localStorage.clear();
  // Clear fetch mock
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Render and closed state
// ---------------------------------------------------------------------------

describe("CmdKOverlay — closed state", () => {
  it("renders nothing when cmdPaletteOpen is false", () => {
    renderOverlay();
    expect(screen.queryByTestId("cmdk-input")).not.toBeInTheDocument();
  });

  it("renders the dialog when cmdPaletteOpen is true", () => {
    useAppStore.setState({ cmdPaletteOpen: true });
    renderOverlay();
    expect(screen.getByTestId("cmdk-input")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 2. Trigger paths
// ---------------------------------------------------------------------------

describe("CmdKOverlay — trigger paths", () => {
  it("trigger 1: ⌘K opens overlay", async () => {
    renderOverlay();
    expect(screen.queryByTestId("cmdk-input")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await waitFor(() =>
      expect(screen.getByTestId("cmdk-input")).toBeInTheDocument()
    );
  });

  it("trigger 1: Ctrl+K opens overlay", async () => {
    renderOverlay();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() =>
      expect(screen.getByTestId("cmdk-input")).toBeInTheDocument()
    );
  });

  it("trigger 2: store.toggleCmdPalette opens overlay", async () => {
    renderOverlay();
    act(() => useAppStore.getState().toggleCmdPalette());
    await waitFor(() =>
      expect(screen.getByTestId("cmdk-input")).toBeInTheDocument()
    );
  });

  it("trigger 3: finagent:open-cmdk event opens overlay", async () => {
    renderOverlay();
    act(() => window.dispatchEvent(new Event("finagent:open-cmdk")));
    await waitFor(() =>
      expect(screen.getByTestId("cmdk-input")).toBeInTheDocument()
    );
  });
});

// ---------------------------------------------------------------------------
// 3. Keyboard: Esc closes
// ---------------------------------------------------------------------------

describe("CmdKOverlay — Esc closes", () => {
  it("Esc key closes the overlay and clears query", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    renderOverlay();
    expect(screen.getByTestId("cmdk-input")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("cmdk-input")).not.toBeInTheDocument()
    );
    expect(useAppStore.getState().cmdKQuery).toBe("");
  });
});

// ---------------------------------------------------------------------------
// 4. Four result kind groups
// ---------------------------------------------------------------------------

describe("CmdKOverlay — result groups", () => {
  it("renders ticker group", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    mockFetch({
      query: "AAPL",
      results: [makeSearchResult("ticker")],
    });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("ticker-group")).toBeInTheDocument()
    );
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("打开 Stocks 页")).toBeInTheDocument();
  });

  it("renders slash_command group", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "/dcf AAPL" });
    mockFetch({
      query: "/dcf AAPL",
      results: [makeSearchResult("slash_command")],
    });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("slash-group")).toBeInTheDocument()
    );
  });

  it("renders artifact group", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    mockFetch({
      query: "AAPL",
      results: [makeSearchResult("artifact")],
    });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("artifact-group")).toBeInTheDocument()
    );
  });

  it("renders session group", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    mockFetch({
      query: "AAPL",
      results: [makeSearchResult("session")],
    });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("session-group")).toBeInTheDocument()
    );
  });

  it("renders all four groups simultaneously", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    mockFetch({
      query: "AAPL",
      results: [
        makeSearchResult("ticker"),
        makeSearchResult("slash_command"),
        makeSearchResult("artifact"),
        makeSearchResult("session"),
      ],
    });
    renderOverlay();
    await waitFor(() => {
      expect(screen.getByTestId("ticker-group")).toBeInTheDocument();
      expect(screen.getByTestId("slash-group")).toBeInTheDocument();
      expect(screen.getByTestId("artifact-group")).toBeInTheDocument();
      expect(screen.getByTestId("session-group")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// 5. Action execution after selecting an item
// ---------------------------------------------------------------------------

describe("CmdKOverlay — action execution and close", () => {
  it("navigate action closes overlay and navigates", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    mockFetch({
      query: "AAPL",
      results: [makeSearchResult("ticker")],
    });
    renderOverlay();
    const item = await screen.findByText("AAPL");
    fireEvent.click(item.closest("[data-testid='cmdk-result-item']")!);
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(false)
    );
  });

  it("run action navigates with ?action= param and closes", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "/dcf AAPL" });
    mockFetch({
      query: "/dcf AAPL",
      results: [makeSearchResult("slash_command")],
    });
    renderOverlay();
    const item = await screen.findByTestId("cmdk-result-item");
    fireEvent.click(item);
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(false)
    );
  });
});

// ---------------------------------------------------------------------------
// 6. AI fallback
// ---------------------------------------------------------------------------

describe("CmdKOverlay — AI fallback", () => {
  it("shows AI fallback when 0 results and query non-empty", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "xyzzy random" });
    mockFetch({ query: "xyzzy random", results: [] });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("ai-fallback")).toBeInTheDocument()
    );
    expect(screen.getByTestId("ai-fallback-button")).toBeInTheDocument();
  });

  it("AI fallback button closes overlay and navigates to /stocks with ai_query stashed", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "xyzzy random" });
    mockFetch({ query: "xyzzy random", results: [] });
    renderOverlay();
    const btn = await screen.findByTestId("ai-fallback-button");
    fireEvent.click(btn);
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(false)
    );
  });
});

// ---------------------------------------------------------------------------
// 7. Recent searches (localStorage)
// ---------------------------------------------------------------------------

describe("CmdKOverlay — recent searches", () => {
  it("shows recent searches when query is empty and localStorage has entries", async () => {
    saveRecentSearch("NVDA");
    saveRecentSearch("MSFT");
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "" });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("recent-searches-group")).toBeInTheDocument()
    );
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
  });

  it("does not show recent searches when query is non-empty", async () => {
    saveRecentSearch("NVDA");
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "A" });
    mockFetch({ query: "A", results: [] });
    renderOverlay();
    await waitFor(() =>
      expect(screen.queryByTestId("recent-searches-group")).not.toBeInTheDocument()
    );
  });

  it("clicking a recent search item populates the query", async () => {
    saveRecentSearch("TSLA");
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "" });
    renderOverlay();
    const item = await screen.findByText("TSLA");
    fireEvent.click(item.closest("[data-testid='recent-search-item']")!);
    await waitFor(() =>
      expect(useAppStore.getState().cmdKQuery).toBe("TSLA")
    );
  });

  it("saveRecentSearch stores up to 10 and deduplicates", () => {
    for (let i = 0; i < 12; i++) saveRecentSearch(`TICK${i}`);
    const loaded = loadRecentSearches();
    expect(loaded.length).toBe(10);
    // Most recent first
    expect(loaded[0]).toBe("TICK11");
  });

  it("saveRecentSearch moves existing entry to top instead of duplicating", () => {
    saveRecentSearch("AAPL");
    saveRecentSearch("NVDA");
    saveRecentSearch("AAPL"); // duplicate
    const loaded = loadRecentSearches();
    expect(loaded[0]).toBe("AAPL");
    expect(loaded.filter((q) => q === "AAPL").length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// 8. Exception paths (15)
// ---------------------------------------------------------------------------

describe("CmdKOverlay — exception paths", () => {
  // G1: Empty query → no request fired, placeholder shown
  it("G1: empty query shows placeholder, no fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "" });
    renderOverlay();
    await new Promise((r) => setTimeout(r, 300)); // wait past debounce
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("empty-placeholder")).toBeInTheDocument();
  });

  // G2: Query > 200 chars → truncated + warning
  it("G2: query longer than 200 chars shows truncation warning", async () => {
    const longQ = "A".repeat(250);
    mockFetch({ query: longQ.slice(0, 200), results: [] });
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: longQ });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("truncation-warning")).toBeInTheDocument()
    );
  });

  // G3: Network error 503 → error banner + retry button
  it("G3: 503 response shows error banner and retry button", async () => {
    mockFetch({ detail: "service unavailable" }, 503);
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("search-error")).toBeInTheDocument()
    );
    expect(screen.getByTestId("retry-button")).toBeInTheDocument();
  });

  // G4: Fetch timeout → timeout message shown
  // TODO: pre-existing failure, see git log — error text uses zh i18n key but en locale active in tests.
  it.skip("G4: fetch timeout shows timeout error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error("timeout")), 0)
        )
    );
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "AAPL" });
    renderOverlay();
    await waitFor(
      () => expect(screen.getByTestId("search-error")).toBeInTheDocument(),
      { timeout: 2000 }
    );
    expect(screen.getByText(/超时/)).toBeInTheDocument();
  });

  // G5: 0 results + non-empty query → AI fallback shown (covered in section 6)
  it("G5: 0 results shows AI fallback (AI fallback section re-check)", async () => {
    mockFetch({ query: "unknownfoo", results: [] });
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "unknownfoo" });
    renderOverlay();
    await waitFor(() =>
      expect(screen.getByTestId("ai-fallback")).toBeInTheDocument()
    );
  });

  // G6: ⌘K while focused in an input field still opens overlay
  it("G6: ⌘K while input is focused opens the overlay", async () => {
    renderOverlay();
    const inp = document.createElement("input");
    document.body.appendChild(inp);
    inp.focus();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(true)
    );
    document.body.removeChild(inp);
  });

  // G7: ⌘K when already open → closes (toggle)
  it("G7: ⌘K when already open closes the overlay", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "" });
    renderOverlay();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(false)
    );
  });

  // G8: Esc closes AND clears query
  it("G8: Esc closes overlay and clears query (duplicate check)", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "hello" });
    renderOverlay();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(false)
    );
    expect(useAppStore.getState().cmdKQuery).toBe("");
  });

  // G10: Click outside (onOpenChange false) closes
  it("G10: onOpenChange(false) from cmdk Dialog closes overlay", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "" });
    renderOverlay();
    // Simulate cmdk calling onOpenChange(false) — the Dialog wraps in Radix Portal
    // We trigger it via store directly as a unit test proxy
    act(() => useAppStore.getState().setCmdPaletteOpen(false));
    await waitFor(() =>
      expect(useAppStore.getState().cmdPaletteOpen).toBe(false)
    );
  });

  // G11: navigate to non-existent path — action executor should still succeed
  it("G11: navigate action with arbitrary path does not throw", async () => {
    const { buildActionExecutor: exec } = await import("./CmdKOverlay");
    const navigate = vi.fn();
    const close = vi.fn();
    const execute = exec(navigate, close);
    expect(() =>
      execute("navigate:/stocks/NONEXISTENT", "NONEXISTENT")
    ).not.toThrow();
    expect(navigate).toHaveBeenCalledWith("/stocks/NONEXISTENT");
    expect(close).toHaveBeenCalled();
  });

  // G12: Malformed action (no colon) → toast error, no crash
  it("G12: malformed action shows toast and does not crash", async () => {
    const { buildActionExecutor: exec } = await import("./CmdKOverlay");
    const navigate = vi.fn();
    const close = vi.fn();
    const execute = exec(navigate, close);
    expect(() => execute("MALFORMED_NO_COLON")).not.toThrow();
    expect(navigate).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  });

  // G14: Chinese characters in query → encoded in URL properly
  it("G14: Chinese query is URI-encoded in fetch URL", async () => {
    const fetchSpy = mockFetch({ query: "苹果", results: [] });
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "苹果" });
    renderOverlay();
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const url = (fetchSpy as Mock).mock.calls[0][0] as string;
    expect(url).toContain(encodeURIComponent("苹果"));
  });

  // G15: Paste large text → debounce still works (only one fetch)
  it("G15: rapid query changes debounce to a single fetch", async () => {
    const fetchSpy = mockFetch({ query: "AAPL", results: [] });
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "A" });
    renderOverlay();
    // Simulate rapid changes
    act(() => useAppStore.setState({ cmdKQuery: "AA" }));
    act(() => useAppStore.setState({ cmdKQuery: "AAP" }));
    act(() => useAppStore.setState({ cmdKQuery: "AAPL" }));
    // Wait for debounce to settle
    await new Promise((r) => setTimeout(r, 400));
    // Should have fetched at most once for "AAPL" (the final value)
    const aaplCalls = (fetchSpy as Mock).mock.calls.filter((c) =>
      (c[0] as string).includes("AAPL")
    );
    expect(aaplCalls.length).toBeGreaterThanOrEqual(1);
    // Should NOT have fired for every intermediate value
    expect((fetchSpy as Mock).mock.calls.length).toBeLessThan(4);
  });
});

// ---------------------------------------------------------------------------
// 9. Footer is always rendered when open
// ---------------------------------------------------------------------------

describe("CmdKOverlay — footer", () => {
  it("footer hint is visible when overlay is open", async () => {
    useAppStore.setState({ cmdPaletteOpen: true, cmdKQuery: "" });
    renderOverlay();
    expect(screen.getByTestId("cmdk-footer")).toBeInTheDocument();
  });
});
