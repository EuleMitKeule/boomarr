import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiUrl } from "@/lib/api";
import type { Dashboard, LogEntry, Progress, ScanRecord } from "@/lib/types";

type Listener = (type: string, data: unknown) => void;
const listeners = new Set<Listener>();

/** Subscribe to raw live events (e.g. log lines) while mounted. */
export function useLiveEvent(listener: Listener): void {
  useEffect(() => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, [listener]);
}

const EVENT_TYPES = [
  "hello",
  "scan.queued",
  "scan.started",
  "scan.progress",
  "scan.finished",
  "scan.skipped",
  "config.updated",
  "log",
];

/** Keeps one EventSource open and folds events into the query cache. */
export function useEventStream(enabled: boolean): boolean {
  const client = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource(apiUrl("events"), { withCredentials: true });
    const patch = (fn: (d: Dashboard) => Partial<Dashboard>) =>
      client.setQueryData<Dashboard>(["dashboard"], (old) => (old ? { ...old, ...fn(old) } : old));

    const handle = (type: string) => (message: MessageEvent<string>) => {
      let payload: { data: unknown };
      try {
        payload = JSON.parse(message.data);
      } catch {
        return;
      }
      const data = payload.data;
      switch (type) {
        case "hello":
          patch(() => data as Partial<Dashboard>);
          break;
        case "scan.queued":
          patch((d) => ({ queued: d.queued + 1 }));
          break;
        case "scan.started":
          patch(() => ({
            scanning: true,
            queued: 0,
            scan_started_at: Date.now() / 1000,
            current_scan: data as Dashboard["current_scan"],
            progress: null,
          }));
          break;
        case "scan.progress":
          patch(() => ({ progress: data as Progress }));
          break;
        case "scan.finished": {
          const report = data as ScanRecord | null;
          patch(() => ({ scanning: false, current_scan: null, progress: null, scan_started_at: null }));
          void client.invalidateQueries({ queryKey: ["dashboard"] });
          void client.invalidateQueries({ queryKey: ["scans"] });
          void client.invalidateQueries({ queryKey: ["health"] });
          if (report?.error) toast.error(`Scan failed: ${report.error}`);
          else if (report?.cancelled) toast.info("Scan cancelled");
          else if (report?.result?.blocked) toast.warning("The removal guard blocked a scan");
          break;
        }
        case "scan.skipped":
          patch((d) => ({ queued: Math.max(0, d.queued - 1) }));
          toast.warning(`Scan skipped: ${(data as { reason: string }).reason}`);
          break;
        case "config.updated":
          void client.invalidateQueries({ queryKey: ["config"] });
          void client.invalidateQueries({ queryKey: ["dashboard"] });
          break;
        case "log":
          client.setQueryData<LogEntry[]>(["logs"], (old) => (old ? [...old.slice(-1999), data as LogEntry] : old));
          break;
      }
      listeners.forEach((listener) => listener(type, data));
    };

    for (const type of EVENT_TYPES) source.addEventListener(type, handle(type) as EventListener);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled, client]);

  return connected;
}
