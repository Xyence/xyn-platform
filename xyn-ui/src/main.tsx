import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { NotificationsProvider } from "./app/state/notificationsStore";
import { OperationsProvider } from "./app/state/operationRegistry";
import { PreviewProvider } from "./app/state/previewStore";
import { XynConsoleProvider } from "./app/state/xynConsoleStore";
import { ThemeProvider } from "./theme/ThemeProvider";
import "./styles/base.css";

const stored = window.localStorage.getItem("xyn.theme");
const isValidTheme = stored === "light" || stored === "dim" || stored === "dark";
if (isValidTheme) {
  document.documentElement.setAttribute("data-theme", stored);
} else {
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
  document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "dim");
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <OperationsProvider>
        <PreviewProvider>
          <NotificationsProvider>
            <XynConsoleProvider>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </XynConsoleProvider>
          </NotificationsProvider>
        </PreviewProvider>
      </OperationsProvider>
    </ThemeProvider>
  </React.StrictMode>
);
