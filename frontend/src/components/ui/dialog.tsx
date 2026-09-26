import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  side?: boolean;
}

const widths = { sm: "max-w-md", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };

export function Dialog({ open, onOpenChange, title, description, children, footer, size = "md", side }: DialogProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px] data-[state=open]:animate-in" />
        <DialogPrimitive.Content
          className={cn(
            "fixed z-50 flex flex-col border border-border bg-surface shadow-2xl focus:outline-none",
            side
              ? "inset-y-0 right-0 w-full max-w-2xl"
              : cn("top-1/2 left-1/2 max-h-[85vh] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl", widths[size]),
          )}
        >
          <div className="flex items-start gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="text-base font-semibold tracking-tight">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="mt-1 text-[13px] text-muted">{description}</DialogPrimitive.Description>
              ) : (
                <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close className="rounded-md p-1 text-muted hover:bg-surface-3 hover:text-fg" aria-label="Close">
              <X className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
