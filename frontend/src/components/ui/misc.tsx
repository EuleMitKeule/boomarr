import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-muted", className)} aria-label="Loading" />;
}

export function PageLoader() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner className="size-6" />
    </div>
  );
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={250}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-border bg-surface-3 px-2 py-1 text-xs text-fg shadow-lg"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

type AlertTone = "info" | "warning" | "danger" | "success";

const alertStyles: Record<AlertTone, { box: string; icon: ReactNode }> = {
  info: { box: "border-info/30 bg-info/8 text-info", icon: <Info className="size-4" /> },
  warning: { box: "border-warning/30 bg-warning/8 text-warning", icon: <AlertTriangle className="size-4" /> },
  danger: { box: "border-danger/30 bg-danger/8 text-danger", icon: <XCircle className="size-4" /> },
  success: { box: "border-success/30 bg-success/8 text-success", icon: <CheckCircle2 className="size-4" /> },
};

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const style = alertStyles[tone];
  return (
    <div role="alert" className={cn("flex items-start gap-3 rounded-lg border px-3.5 py-3", style.box, className)}>
      <div className="mt-px shrink-0">{style.icon}</div>
      <div className="min-w-0 flex-1 text-[13px] text-fg">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className={cn(title && "mt-0.5", "text-muted")}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-xl border border-border bg-surface-2 text-muted">
        {icon}
      </div>
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
      {children}
    </kbd>
  );
}

export function ProgressBar({ value, active, className }: { value: number | null; active?: boolean; className?: string }) {
  const pct = value === null ? 100 : Math.max(2, Math.min(100, value * 100));
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}>
      <div
        className={cn("h-full rounded-full bg-accent transition-[width] duration-500", active && "progress-active")}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
