import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** "3 minutes ago" / "in 5 minutes" for a unix timestamp (seconds). */
export function relativeTime(timestamp: number | null | undefined, now = Date.now()): string {
  if (!timestamp) return "never";
  const diff = timestamp * 1000 - now;
  const abs = Math.abs(diff);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];
  for (const [unit, ms] of units) {
    if (abs >= ms) return rtf.format(Math.round(diff / ms), unit);
  }
  return abs < 10_000 ? "just now" : rtf.format(Math.round(diff / 1000), "second");
}

export function dateTime(timestamp: number | null | undefined): string {
  if (!timestamp) return "—";
  return new Date(timestamp * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${Math.round(seconds % 60)} s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

export function number(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString();
}

export function plural(count: number, word: string, suffix = "s"): string {
  return `${number(count)} ${word}${count === 1 ? "" : suffix}`;
}

/** Last path component (for compact display of long paths). */
export function basename(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** Human readable trigger source ("ui:admin" → "Manual (admin)"). */
export function sourceLabel(source: string): string {
  return source
    .split(", ")
    .map((part) => {
      const [kind, detail] = part.split(":", 2);
      switch (kind) {
        case "ui":
          return detail ? `Manual (${detail})` : "Manual";
        case "schedule":
          return "Schedule";
        case "webhook":
          return detail ? `Webhook (${detail})` : "Webhook";
        case "api":
          return "API";
        case "cli":
          return "Command line";
        default:
          return part;
      }
    })
    .join(", ");
}
