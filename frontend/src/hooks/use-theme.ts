import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light" | "system";
const KEY = "boomarr.theme";

function resolve(theme: Theme): "dark" | "light" {
  if (theme !== "system") return theme;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  const resolved = resolve(theme);
  document.documentElement.classList.toggle("dark", resolved === "dark");
  document.documentElement.style.colorScheme = resolved;
}

export function storedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "dark" || value === "light" || value === "system") return value;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(storedTheme);
  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    const listener = () => applyTheme("system");
    media?.addEventListener("change", listener);
    return () => media?.removeEventListener("change", listener);
  }, [theme]);
  const setTheme = useCallback((value: Theme) => {
    try {
      localStorage.setItem(KEY, value);
    } catch {
      /* storage unavailable */
    }
    setThemeState(value);
  }, []);
  return [theme, setTheme];
}
