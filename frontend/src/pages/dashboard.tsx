import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CircleAlert,
  Clock,
  FolderInput,
  FolderTree,
  HardDrive,
  Languages,
  Link2,
  Plus,
  RotateCcw,
  Square,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { ChangeCounts, OutcomeBadge } from "@/components/scan-summary";
import { Badge, Dot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Alert, EmptyState, PageLoader, ProgressBar } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { Dashboard, HealthCheck, ScanRecord } from "@/lib/types";
import { basename, duration, number, plural, relativeTime, sourceLabel } from "@/lib/utils";

function Stat({ icon, label, value, hint }: { icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-[12.5px] text-muted">
        <span className="text-subtle">{icon}</span>
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {hint && <div className="mt-1 truncate text-xs text-subtle">{hint}</div>}
    </Card>
  );
}

const PHASES: Record<string, string> = {
  discovering: "Discovering files",
  probing: "Probing audio tracks",
  linking: "Updating symlinks",
};

function ScanCard({ data }: { data: Dashboard }) {
  const cancel = useMutation({
    mutationFn: () => api.post("scans/cancel"),
    onSuccess: () => toast.info("Cancelling the scan…"),
  });
  const last = data.last_scan;

  if (data.scanning) {
    const p = data.progress;
    const fraction = p && p.total > 0 ? p.done / p.total : null;
    return (
      <Card className="overflow-hidden border-accent/40">
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Dot tone="accent" pulse />
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {data.current_scan?.dry_run ? "Dry run in progress" : "Scan in progress"}
                {p && <span className="text-muted"> · {p.library}</span>}
              </div>
              <div className="text-xs text-muted">
                {p ? PHASES[p.phase] ?? p.phase : "Starting"}
                {p && p.total > 0 && ` · ${number(p.done)} / ${number(p.total)}`}
                {data.current_scan && ` · ${sourceLabel(data.current_scan.source)}`}
                {data.scan_started_at && ` · started ${relativeTime(data.scan_started_at)}`}
              </div>
            </div>
            <Button variant="danger" size="sm" icon={<Square className="size-3" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
              Cancel
            </Button>
          </div>
          <ProgressBar value={fraction} active />
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardBody className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs text-muted">Last scan</div>
          {last ? (
            <div className="mt-1 flex flex-wrap items-center gap-2.5">
              <span className="font-medium">{relativeTime(last.finished_at)}</span>
              <OutcomeBadge scan={last} />
              <ChangeCounts scan={last} />
              <span className="text-xs text-subtle">
                {duration(last.duration_seconds)} · {sourceLabel(last.source)}
              </span>
            </div>
          ) : (
            <div className="mt-1 font-medium text-muted">No scan yet</div>
          )}
          {last?.error && <p className="mt-1.5 text-xs text-danger">{last.error}</p>}
        </div>
        <div>
          <div className="text-xs text-muted">Next scheduled scan</div>
          <div className="mt-1 flex items-center gap-1.5 font-medium">
            <Clock className="size-3.5 text-subtle" />
            {data.next_scheduled_scan ? relativeTime(data.next_scheduled_scan) : "Not scheduled"}
          </div>
        </div>
        {data.queued > 0 && <Badge tone="accent">{plural(data.queued, "request")} queued</Badge>}
      </CardBody>
    </Card>
  );
}

function LanguageBars({ languages }: { languages: Record<string, number> }) {
  const entries = Object.entries(languages).slice(0, 8);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <p className="text-[13px] text-muted">No files probed yet.</p>;
  return (
    <div className="space-y-2.5">
      {entries.map(([code, count]) => (
        <div key={code} className="grid grid-cols-[3rem_1fr_auto] items-center gap-3 text-[13px]">
          <span className="font-mono text-xs text-muted uppercase">{code}</span>
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full rounded-full bg-accent/80" style={{ width: `${(count / max) * 100}%` }} />
          </div>
          <span className="text-right font-mono text-xs text-muted tabular-nums">{number(count)}</span>
        </div>
      ))}
    </div>
  );
}

function RecentScans() {
  const query = useQuery({
    queryKey: ["scans", "recent"],
    queryFn: () => api.get<{ items: ScanRecord[]; total: number }>("scans?limit=6"),
  });
  const items = query.data?.items ?? [];
  return (
    <Card>
      <CardHeader
        title="Recent activity"
        actions={
          <Link to="/activity" className="flex items-center gap-1 text-xs text-muted hover:text-fg">
            View all <ArrowRight className="size-3" />
          </Link>
        }
      />
      {items.length === 0 ? (
        <p className="px-5 py-6 text-[13px] text-muted">Nothing happened yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((scan) => (
            <li key={scan.id}>
              <Link
                to={`/activity?scan=${scan.id}`}
                className="flex items-center gap-3 px-5 py-2.5 text-[13px] hover:bg-surface-2"
              >
                <OutcomeBadge scan={scan} />
                <span className="min-w-0 flex-1 truncate text-muted">{sourceLabel(scan.source)}</span>
                <ChangeCounts scan={scan} />
                <span className="w-24 text-right text-xs text-subtle">{relativeTime(scan.finished_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function HealthBanner() {
  const query = useQuery({ queryKey: ["health"], queryFn: () => api.get<HealthCheck[]>("system/health") });
  const problems = (query.data ?? []).filter((c) => c.level !== "ok");
  if (!problems.length) return null;
  const errors = problems.filter((c) => c.level === "error");
  return (
    <Alert
      tone={errors.length ? "danger" : "warning"}
      title={errors.length ? plural(errors.length, "problem") + " need attention" : plural(problems.length, "warning")}
      action={
        <Link to="/system/health" className="text-xs font-medium text-fg hover:underline">
          Details
        </Link>
      }
    >
      {problems[0].message}
      {problems.length > 1 && ` (+${problems.length - 1} more)`}
    </Alert>
  );
}

export function DashboardPage() {
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("dashboard"),
    refetchInterval: 60_000,
  });
  const data = query.data;
  if (!data) return <PageLoader />;

  const outputs = data.libraries.flatMap((l) => l.outputs);
  const links = outputs.reduce((sum, o) => sum + o.links, 0);
  const languageCount = Object.keys(data.cache.languages ?? {}).length;

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" description="What Boomarr is doing and how your libraries look." />
      <HealthBanner />
      {data.restart_required && (
        <Alert tone="warning" title="Restart required" action={<RotateCcw className="size-4 text-muted" />}>
          Web server settings changed. Restart the container to apply them.
        </Alert>
      )}
      <ScanCard data={data} />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat icon={<Link2 className="size-4" />} label="Symlinks" value={number(links)} hint={`in ${outputs.length} output ${outputs.length === 1 ? "library" : "libraries"}`} />
        <Stat icon={<FolderTree className="size-4" />} label="Libraries" value={data.libraries.length} hint={(() => {
            const missing = data.libraries.filter((l) => !l.input_available).length;
            return missing ? `${missing} source folder(s) missing` : "All source folders available";
          })()} />
        <Stat
          icon={<HardDrive className="size-4" />}
          label="Probed files"
          value={number(data.cache.total_cached)}
          hint={data.cache.without_audio ? `${number(data.cache.without_audio)} without audio` : `last probe ${relativeTime(data.cache.last_probe_time)}`}
        />
        <Stat icon={<Languages className="size-4" />} label="Audio languages" value={languageCount} hint={Object.keys(data.cache.languages ?? {}).slice(0, 4).join(", ").toUpperCase() || "—"} />
      </div>

      {data.libraries.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FolderInput className="size-5" />}
            title="No libraries yet"
            description="Point Boomarr at a movie or TV folder and choose which audio languages each filtered library should contain."
            action={
              <Link to="/libraries/new">
                <Button variant="primary" icon={<Plus className="size-4" />}>
                  Add library
                </Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Card>
            <CardHeader
              title="Libraries"
              actions={
                <Link to="/libraries" className="flex items-center gap-1 text-xs text-muted hover:text-fg">
                  Manage <ArrowRight className="size-3" />
                </Link>
              }
            />
            <div className="divide-y divide-border">
              {data.libraries.map((library, index) => (
                <div key={library.name} className="px-5 py-4">
                  <div className="flex items-center gap-2">
                    <Link to={`/libraries/${index}`} className="font-medium hover:text-accent">
                      {library.name}
                    </Link>
                    {!library.input_available && (
                      <Badge tone="danger">
                        <CircleAlert className="size-3" /> source missing
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 truncate font-mono text-xs text-subtle">{library.input_path}</div>
                  <div className="mt-3 space-y-1.5">
                    {library.outputs.map((out) => (
                      <div key={out.path} className="flex items-center gap-3 rounded-lg bg-surface-2 px-3 py-2">
                        <Link2 className="size-3.5 shrink-0 text-subtle" />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs" title={out.path}>
                          {basename(out.path)}
                        </span>
                        <span className="hidden truncate text-xs text-muted sm:inline" title={out.filters.join(" AND ")}>
                          {out.filters.join(" · ")}
                        </span>
                        <span className="w-16 text-right font-mono text-xs tabular-nums">
                          {out.exists ? number(out.links) : <span className="text-subtle">—</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <div className="space-y-6">
            <Card>
              <CardHeader title="Audio languages" description="Across all probed files" />
              <CardBody>
                <LanguageBars languages={data.cache.languages ?? {}} />
              </CardBody>
            </Card>
            <RecentScans />
          </div>
        </div>
      )}
    </div>
  );
}
