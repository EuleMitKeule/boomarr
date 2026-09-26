import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { Toaster } from "sonner";
import { App } from "./App";
import { applyTheme, storedTheme } from "./hooks/use-theme";
import { ApiError } from "./lib/api";
import "./index.css";

applyTheme(storedTheme());

const client = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

/** The server injects <base href="{url_base}/">; the router needs the same prefix. */
export function basename(): string {
  return new URL(document.baseURI).pathname.replace(/\/$/, "");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <TooltipPrimitive.Provider>
        <BrowserRouter basename={basename()}>
          <App />
        </BrowserRouter>
        <Toaster
          position="top-right"
          offset={64}
          toastOptions={{
            classNames: {
              toast: "!bg-surface !border-border !text-fg !shadow-xl",
              description: "!text-muted",
            },
          }}
        />
      </TooltipPrimitive.Provider>
    </QueryClientProvider>
  </StrictMode>,
);
