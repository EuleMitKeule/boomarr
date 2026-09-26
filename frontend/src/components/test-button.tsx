import { useMutation } from "@tanstack/react-query";
import { CircleCheck, CircleX, PlugZap } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";

export function TestButton({ kind, config, disabled }: { kind: string; config: unknown; disabled?: boolean }) {
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; message: string }>("test", { kind, config: config as Record<string, unknown> }),
  });
  const result = test.data;
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <Button variant="outline" size="sm" icon={<PlugZap className="size-3.5" />} loading={test.isPending} disabled={disabled} onClick={() => test.mutate()}>
        Test
      </Button>
      {result && (
        <span className={`flex min-w-0 items-center gap-1.5 text-xs ${result.ok ? "text-success" : "text-danger"}`} role="status">
          {result.ok ? <CircleCheck className="size-3.5 shrink-0" /> : <CircleX className="size-3.5 shrink-0" />}
          <span className="truncate">{result.message}</span>
        </span>
      )}
      {test.error && <span className="text-xs text-danger">Test failed</span>}
    </div>
  );
}
