import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { StocksPage } from "./pages/StocksPage";
import { LibraryPage } from "./pages/LibraryPage";
import { SettingsPage } from "./pages/SettingsPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/stocks" replace /> },
      { path: "stocks", element: <StocksPage /> },
      { path: "stocks/:ticker", element: <StocksPage /> },
      { path: "library", element: <LibraryPage /> },
      { path: "library/:ticker", element: <LibraryPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
