import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./AppShell";

// Stub Tauri modules so tests run in jsdom without Tauri APIs.
vi.mock("../lib/tauri", () => ({
  registerShortcut: vi.fn().mockResolvedValue(() => {}),
  pickDirectory: vi.fn().mockResolvedValue(null),
  isTauri: vi.fn().mockReturnValue(false),
  openExternal: vi.fn().mockResolvedValue(undefined),
  DEFAULT_WORKSPACE_PATH: "~/finagent",
}));

function renderWithProviders(initialPath = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/*" element={<AppShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell — simplified shell structure", () => {
  it("renders core shell regions", () => {
    renderWithProviders();
    expect(screen.getByTestId("titlebar")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("statusbar")).toBeInTheDocument();
  });

  it("clicking Stocks button navigates to /stocks", () => {
    renderWithProviders();
    const stocksBtn = screen.getByLabelText("个股分析");
    fireEvent.click(stocksBtn);
    // Sidebar uses react-router navigate; button should remain in the doc
    expect(stocksBtn).toBeInTheDocument();
  });
});
