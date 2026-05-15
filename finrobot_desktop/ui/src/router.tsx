import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { StocksPage } from "./pages/StocksPage";
import { LibraryPage } from "./pages/LibraryPage";
import { SettingsPage } from "./pages/SettingsPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { JournalPage } from "./pages/JournalPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "stocks", element: <StocksPage /> },
      { path: "stocks/:ticker", element: <StocksPage /> },
      { path: "playground", element: <PlaygroundPage /> },
      { path: "playground/:ticker", element: <PlaygroundPage /> },
      { path: "journal", element: <JournalPage /> },
      { path: "library", element: <LibraryPage /> },
      { path: "library/:ticker", element: <LibraryPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
