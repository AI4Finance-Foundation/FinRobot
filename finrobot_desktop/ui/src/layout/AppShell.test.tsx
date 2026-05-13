import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./AppShell";

function renderWithProviders(initialPath = "/stocks") {
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

describe("AppShell — routing skeleton smoke test", () => {
  it("renders all three nav links", () => {
    renderWithProviders();
    expect(screen.getByText("Stocks")).toBeInTheDocument();
    expect(screen.getByText("Library")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders recent-tickers-slot placeholder", () => {
    renderWithProviders();
    expect(screen.getByTestId("recent-tickers-slot")).toBeInTheDocument();
  });

  it("renders cmd+K trigger button", () => {
    renderWithProviders();
    expect(screen.getByTitle("Command Palette (⌘K)")).toBeInTheDocument();
  });
});
