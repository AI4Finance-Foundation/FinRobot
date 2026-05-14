import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./AppShell";
import { useUiStore } from "../stores/uiStore";

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

describe("AppShell — Phase 1+ shell structure", () => {
  it("renders all 6 shell regions", () => {
    renderWithProviders();
    expect(screen.getByTestId("titlebar")).toBeInTheDocument();
    expect(screen.getByTestId("activitybar")).toBeInTheDocument();
    expect(screen.getByTestId("explorer")).toBeInTheDocument();
    expect(screen.getByTestId("editor-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("breadcrumb")).toBeInTheDocument();
    expect(screen.getByTestId("statusbar")).toBeInTheDocument();
  });

  it("clicking an activity bar button updates activityBarSelection in uiStore", () => {
    renderWithProviders();
    // Initial state is "dashboard". Click "Pipeline 库" button.
    const pipelineBtn = screen.getByTitle("Pipeline 库");
    fireEvent.click(pipelineBtn);
    expect(useUiStore.getState().activityBarSelection).toBe("pipelines");
  });
});
