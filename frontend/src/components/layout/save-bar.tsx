import { Undo2 } from "lucide-react";
import { useConfig } from "@/lib/config-editor";
import { Button } from "../ui/button";

export function SaveBar() {
  const cfg = useConfig();
  if (!cfg.dirty) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-30 flex justify-center px-4 lg:pl-64">
      <div className="pointer-events-auto flex w-full max-w-xl items-center gap-3 rounded-xl border border-border-strong bg-surface/95 px-4 py-2.5 shadow-2xl backdrop-blur">
        <span className="size-2 shrink-0 rounded-full bg-accent" />
        <p className="flex-1 text-[13px]">
          You have unsaved changes
          {cfg.errors.length > 0 && <span className="text-danger"> · {cfg.errors.length} problem(s)</span>}
        </p>
        <Button variant="ghost" size="sm" icon={<Undo2 className="size-3.5" />} onClick={cfg.reset} disabled={cfg.saving}>
          Discard
        </Button>
        <Button variant="primary" size="sm" loading={cfg.saving} onClick={() => void cfg.save()}>
          Save changes
        </Button>
      </div>
    </div>
  );
}
