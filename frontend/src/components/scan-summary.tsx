import { Ban, CircleAlert, CircleCheck, CircleX, FlaskConical, ShieldAlert } from "lucide-react";
import type { ScanRecord } from "@/lib/types";
import { Badge } from "./ui/badge";

export function scanOutcome(scan: ScanRecord): { label: string; tone: "success" | "warning" | "danger" | "neutral" | "info"; icon: React.ReactNode } {
  if (scan.error) return { label: "Failed", tone: "danger", icon: <CircleX className="size-3" /> };
  if (scan.cancelled) return { label: "Cancelled", tone: "neutral", icon: <Ban className="size-3" /> };
  if (scan.result?.blocked) return { label: "Blocked", tone: "warning", icon: <ShieldAlert className="size-3" /> };
  if (scan.result?.errors) return { label: "Errors", tone: "warning", icon: <CircleAlert className="size-3" /> };
  if (scan.dry_run) return { label: "Dry run", tone: "info", icon: <FlaskConical className="size-3" /> };
  return { label: "Success", tone: "success", icon: <CircleCheck className="size-3" /> };
}

export function OutcomeBadge({ scan }: { scan: ScanRecord }) {
  const outcome = scanOutcome(scan);
  return (
    <Badge tone={outcome.tone}>
      {outcome.icon}
      {outcome.label}
    </Badge>
  );
}

export function ChangeCounts({ scan }: { scan: ScanRecord }) {
  const r = scan.result;
  if (!r) return <span className="text-subtle">—</span>;
  return (
    <span className="inline-flex items-center gap-3 font-mono text-xs tabular-nums">
      <span className={r.created ? "text-success" : "text-subtle"}>+{r.created}</span>
      <span className={r.removed ? "text-danger" : "text-subtle"}>−{r.removed}</span>
      {r.errors > 0 && <span className="text-warning">!{r.errors}</span>}
    </span>
  );
}
