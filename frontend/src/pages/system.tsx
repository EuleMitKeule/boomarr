import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Download, HeartPulse, Pause, Play, RefreshCw, TriangleAlert, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { toast } from "sonner";
import { systemNav } from "@/components/layout/nav";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Alert, EmptyState, PageLoader } from "@/components/ui/misc";
import { useLiveEvent } from "@/hooks/use-events";
import { api, ApiError, apiUrl } from "@/lib/api";
import { CONFIG_QUERY } from "@/lib/config-editor";
import type { HealthCheck, LogEntry, SystemStatus } from "@/lib/types";
import { cn, dateTime, duration } from "@/lib/utils";

function SystemHeader({ actions }: { actions?: ReactNode }) {
  const location = useLocation();
  const meta = systemNav.find((n) => location.pathname.startsWith(n.to));
  return <PageHeader title={meta?.label ?? "System"} actions={actions} />;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 py-2.5 sm:grid-cols-[12rem_1fr]">
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="min-w-0 text-[13px] break-all">{children}</dd>
    </div>
  );
}

export function StatusPage() {
  const query = useQuery({ queryKey: ["system-status"], queryFn: () => api.get<SystemStatus>("system/status") });
  const s = query.data;
  if (!s) return <PageLoader />;
  return (
    <div className="space-y-6">
      <SystemHeader />
      <Card>
        <CardHeader title="About" />
        <CardBody>
          <dl className="divide-y divide-border">
            <Row label="Version">
              <span className="font-mono">{s.version}</span>
            </Row>
            <Row label="Python">{s.python}</Row>
            <Row label="Platform">
              {s.platform}
              {s.in_container && <Badge className="ml-2">container</Badge>}
            </Row>
            <Row label="Started">
              {dateTime(s.started_at)} · up {duration(s.uptime_seconds)}
            </Row>
            <Row label="Configuration">
              <span className="font-mono">{s.config_file}</span>
              {!s.config_writable && (
                <Badge tone="warning" className="ml-2">
                  read-only
                </Badge>
              )}
            </Row>
            <Row label="Probe cache">
              <span className="font-mono">{s.database}</span>
            </Row>
            <Row label="Log file">
              <span className="font-mono">{s.log_file ?? "disabled"}</span>
            </Row>
            <Row label="Authentication">{s.auth_method}</Row>
          </dl>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Resources" />
        <CardBody className="flex flex-wrap gap-2">
          {[
            ["Documentation", "https://eulemitkeule.github.io/boomarr/"],
            ["Source code", "https://github.com/EuleMitKeule/boomarr"],
            ["Report a bug", "https://github.com/EuleMitKeule/boomarr/issues/new/choose"],
            ["Releases", "https://github.com/EuleMitKeule/boomarr/releases"],
          ].map(([label, href]) => (
            <a key={href} href={href} target="_blank" rel="noreferrer">
              <Button variant="outline" size="sm">
                {label}
              </Button>
            </a>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

const levelIcon = {
  ok: <CircleCheck className="size-4 text-success" />,
  warning: <TriangleAlert className="size-4 text-warning" />,
  error: <CircleAlert className="size-4 text-danger" />,
};

export function HealthPage() {
  const query = useQuery({ queryKey: ["health"], queryFn: () => api.get<HealthCheck[]>("system/health") });
  return (
    <div className="space-y-6">
      <SystemHeader
        actions={
          <Button variant="outline" size="sm" icon={<RefreshCw className="size-3.5" />} loading={query.isFetching} onClick={() => void query.refetch()}>
            Check again
          </Button>
        }
      />
      {!query.data ? (
        <PageLoader />
      ) : query.data.length === 0 ? (
        <Card>
          <EmptyState icon={<HeartPulse className="size-5" />} title="Everything looks good" description="No problems were found." />
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-border">
            {query.data.map((check) => (
              <li key={check.id + check.message} className="flex items-start gap-3 px-5 py-3.5">
                <span className="mt-0.5">{levelIcon[check.level]}</span>
                <div className="min-w-0 flex-1 text-[13px]">{check.message}</div>
                {check.wiki && (
                  <a
                    href={`https://eulemitkeule.github.io/boomarr/troubleshooting/#${check.wiki}`}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 text-xs text-muted hover:text-fg"
                  >
                    More info
                  </a>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];
const levelStyle: Record<string, string> = {
  DEBUG: "text-subtle",
  INFO: "text-info",
  WARNING: "text-warning",
  ERROR: "text-danger",
  CRITICAL: "text-danger font-semibold",
};

function timeOf(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour12: false });
}

export function LogsPage() {
  const client = useQueryClient();
  const [level, setLevel] = useState("INFO");
  const [search, setSearch] = useState("");
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<LogEntry[] | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const query = useQuery({ queryKey: ["logs"], queryFn: () => api.get<LogEntry[]>("logs?limit=2000"), staleTime: Infinity });
  const onEvent = useCallback(
    (type: string) => {
      if (type === "log" && !paused) bottom.current?.scrollIntoView({ block: "end" });
    },
    [paused],
  );
  useLiveEvent(onEvent);
  useEffect(() => {
    if (query.data) bottom.current?.scrollIntoView({ block: "end" });
  }, [query.data === undefined]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => void client.removeQueries({ queryKey: ["logs"] }), [client]);

  const entries = paused ? frozen ?? [] : query.data ?? [];
  const threshold = LEVELS.indexOf(level);
  const shown = useMemo(
    () =>
      entries.filter(
        (e) =>
          LEVELS.indexOf(e.level) >= threshold &&
          (!search || e.message.toLowerCase().includes(search.toLowerCase()) || e.logger.includes(search)),
      ),
    [entries, threshold, search],
  );

  return (
    <div className="space-y-4">
      <SystemHeader
        actions={
          <a href={apiUrl("logs/download")} download>
            <Button variant="outline" size="sm" icon={<Download className="size-3.5" />}>
              Download
            </Button>
          </a>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-36">
          <Select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Minimum level">
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {l.charAt(0) + l.slice(1).toLowerCase()}
              </option>
            ))}
          </Select>
        </div>
        <Input className="max-w-xs" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Button
          variant="outline"
          size="sm"
          icon={paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
          onClick={() => {
            setFrozen(paused ? null : [...(query.data ?? [])]);
            setPaused((p) => !p);
          }}
        >
          {paused ? "Resume" : "Pause"}
        </Button>
        <span className="ml-auto text-xs text-subtle">{shown.length} lines</span>
      </div>
      <Card className="overflow-hidden">
        <div className="h-[calc(100dvh-16rem)] min-h-80 overflow-auto bg-surface-2/40 py-2 font-mono text-[12px] leading-5">
          {shown.map((e) => (
            <div key={e.id} className="flex gap-3 px-4 hover:bg-surface-3/60">
              <span className="shrink-0 text-subtle tabular-nums">{timeOf(e.time)}</span>
              <span className={cn("w-16 shrink-0", levelStyle[e.level])}>{e.level}</span>
              <span className="hidden w-44 shrink-0 truncate text-subtle md:inline" title={e.logger}>
                {e.logger.replace(/^boomarr\.?/, "") || "boomarr"}
              </span>
              <span className="min-w-0 whitespace-pre-wrap break-words">{e.message}</span>
            </div>
          ))}
          {shown.length === 0 && <p className="p-6 text-center text-muted">No log lines</p>}
          <div ref={bottom} />
        </div>
      </Card>
    </div>
  );
}

export function BackupPage() {
  const client = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const restore = useMutation({
    mutationFn: async (upload: File) => api.post("config/import", await upload.text(), { "Content-Type": "application/yaml" }),
    onSuccess: () => {
      toast.success("Configuration restored and applied");
      void client.invalidateQueries({ queryKey: CONFIG_QUERY });
      void client.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const error = restore.error instanceof ApiError ? restore.error : null;
  return (
    <div className="space-y-6">
      <SystemHeader />
      <Card>
        <CardHeader title="Download configuration" description="The YAML file with all settings, including secrets. Store it safely." />
        <CardBody>
          <a href={apiUrl("config/export")} download>
            <Button variant="primary" icon={<Download className="size-4" />}>
              Download boomarr.yml
            </Button>
          </a>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Restore configuration" description="Replaces the current configuration after validating the file. The previous file is kept as .bak." />
        <CardBody className="space-y-3">
          {error && (
            <Alert tone="danger" title={error.message}>
              {error.errors.slice(0, 5).map((e) => (
                <div key={e.loc.join(".")}>
                  <code className="font-mono">{e.loc.join(".")}</code>: {e.msg}
                </div>
              ))}
            </Alert>
          )}
          <input
            ref={file}
            type="file"
            accept=".yml,.yaml,application/yaml,text/yaml"
            className="hidden"
            onChange={(e) => {
              const upload = e.target.files?.[0];
              if (upload) restore.mutate(upload);
              e.target.value = "";
            }}
          />
          <Button variant="outline" icon={<Upload className="size-4" />} loading={restore.isPending} onClick={() => file.current?.click()}>
            Upload a backup
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
