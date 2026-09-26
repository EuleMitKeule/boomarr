import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, History, Link2, Unlink } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { PageHeader } from "@/components/page-header";
import { ChangeCounts, OutcomeBadge } from "@/components/scan-summary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Alert, EmptyState, PageLoader, Spinner } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { ScanChange, ScanRecord } from "@/lib/types";
import { dateTime, duration, number, relativeTime, sourceLabel } from "@/lib/utils";

const PAGE_SIZE = 25;

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
      <div className="text-[11px] tracking-wide text-subtle uppercase">{label}</div>
      <div className={`mt-0.5 font-mono text-lg tabular-nums ${value ? tone ?? "" : "text-muted"}`}>{number(value)}</div>
    </div>
  );
}

function relative(path: string, roots: string[]): string {
  const root = roots.find((r) => path.startsWith(`${r}/`));
  return root ? `${root.split("/").pop()}/${path.slice(root.length + 1)}` : path;
}

function ChangeList({ changes, roots }: { changes: ScanChange[]; roots: string[] }) {
  const [filter, setFilter] = useState("");
  const shown = changes.filter((c) => c.path.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="space-y-2">
      <Input placeholder="Filter changes…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-border">
        {shown.map((change, i) => (
          <div key={`${change.path}-${i}`} className="flex items-start gap-2.5 border-b border-border/60 px-3 py-2 last:border-0">
            {change.action === "created" ? (
              <Link2 className="mt-0.5 size-3.5 shrink-0 text-success" aria-label="created" />
            ) : (
              <Unlink className="mt-0.5 size-3.5 shrink-0 text-danger" aria-label="removed" />
            )}
            <div className="min-w-0">
              <div className="font-mono text-xs break-all" title={change.path}>
                {relative(change.path, roots)}
              </div>
              {change.target && <div className="mt-0.5 font-mono text-[11px] break-all text-subtle">→ {change.target}</div>}
            </div>
          </div>
        ))}
        {shown.length === 0 && <p className="p-4 text-center text-[13px] text-muted">No matching changes</p>}
      </div>
    </div>
  );
}

function ScanDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const query = useQuery({ queryKey: ["scans", id], queryFn: () => api.get<ScanRecord>(`scans/${id}`) });
  const scan = query.data;
  const r = scan?.result;
  const changes = r?.changes ?? [];
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()} title={`Scan #${id}`} description={scan ? dateTime(scan.finished_at) : undefined} side>
      {!scan ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <OutcomeBadge scan={scan} />
            {scan.force && <Badge tone="warning">forced</Badge>}
            <span className="text-[13px] text-muted">
              {sourceLabel(scan.source)} · {duration(scan.duration_seconds)}
            </span>
          </div>
          {scan.error && <Alert tone="danger" title="Error">{scan.error}</Alert>}
          {r?.blocked ? (
            <Alert tone="warning" title="Removal guard">
              The guard refused to remove an unusually large number of links. Check the source mounts, then run a forced scan from the
              Dashboard if the removal is intended.
            </Alert>
          ) : null}
          {r && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric label="Created" value={r.created} tone="text-success" />
              <Metric label="Removed" value={r.removed} tone="text-danger" />
              <Metric label="Probed" value={r.probed} />
              <Metric label="Errors" value={r.errors} tone="text-warning" />
              <Metric label="Unchanged" value={r.unchanged} />
              <Metric label="Cached" value={r.skipped} />
              <Metric label="Non-media" value={r.filtered} />
              <Metric label="Blocked" value={r.blocked} tone="text-warning" />
            </div>
          )}
          {r && Object.keys(r.links).length > 0 && (
            <div>
              <h3 className="mb-2 text-[13px] font-medium">Links per output</h3>
              <div className="space-y-1">
                {Object.entries(r.links).map(([path, count]) => (
                  <div key={path} className="flex items-center justify-between gap-4 rounded-md bg-surface-2 px-3 py-1.5">
                    <span className="truncate font-mono text-xs">{path}</span>
                    <span className="font-mono text-xs tabular-nums">{number(count)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div>
            <h3 className="mb-2 text-[13px] font-medium">
              Changes {changes.length > 0 && <span className="text-muted">({number(changes.length)})</span>}
            </h3>
            {changes.length ? (
              <ChangeList changes={changes} roots={Object.keys(r?.links ?? {})} />
            ) : (
              <p className="text-[13px] text-muted">No links were created or removed.</p>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

export function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(0);
  const query = useQuery({
    queryKey: ["scans", "page", page],
    queryFn: () => api.get<{ items: ScanRecord[]; total: number }>(`scans?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`),
    placeholderData: (previous) => previous,
  });
  const selected = params.get("scan");
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <PageHeader title="Activity" description="Every scan with what it changed. Dry runs show what would change." />
      {!query.data ? (
        <PageLoader />
      ) : total === 0 ? (
        <Card>
          <EmptyState icon={<History className="size-5" />} title="No scans yet" description="Scans started by the schedule, webhooks or you will show up here." />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="border-b border-border bg-surface-2 text-xs text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Finished</th>
                  <th className="px-4 py-2.5 font-medium">Trigger</th>
                  <th className="px-4 py-2.5 font-medium">Changes</th>
                  <th className="px-4 py-2.5 font-medium">Probed</th>
                  <th className="px-4 py-2.5 text-right font-medium">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {query.data.items.map((scan) => (
                  <tr
                    key={scan.id}
                    tabIndex={0}
                    className="cursor-pointer hover:bg-surface-2 focus:bg-surface-2 focus:outline-none"
                    onClick={() => setParams({ scan: String(scan.id) })}
                    onKeyDown={(e) => e.key === "Enter" && setParams({ scan: String(scan.id) })}
                  >
                    <td className="px-4 py-2.5">
                      <OutcomeBadge scan={scan} />
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap" title={dateTime(scan.finished_at)}>
                      {relativeTime(scan.finished_at)}
                    </td>
                    <td className="px-4 py-2.5 text-muted">{sourceLabel(scan.source)}</td>
                    <td className="px-4 py-2.5">
                      <ChangeCounts scan={scan} />
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-muted tabular-nums">{number(scan.result?.probed)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-muted">{duration(scan.duration_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-xs text-muted">
            <span>
              {number(total)} scans · page {page + 1} of {pages}
            </span>
            <div className="flex gap-1">
              <Button variant="ghost" size="icon" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft className="size-4" />
              </Button>
              <Button variant="ghost" size="icon" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </Card>
      )}
      {selected && <ScanDetail id={Number(selected)} onClose={() => setParams({})} />}
    </div>
  );
}
