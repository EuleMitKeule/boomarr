import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, KeyRound, LogOut, Menu, Monitor, Moon, Play, Sun, User, Zap } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Outlet, useNavigate } from "react-router";
import { toast } from "sonner";
import { useEventStream } from "@/hooks/use-events";
import { AUTH_QUERY, useAuthState } from "@/hooks/use-auth";
import { useTheme, type Theme } from "@/hooks/use-theme";
import { api, ApiError } from "@/lib/api";
import { ConfigEditorProvider } from "@/lib/config-editor";
import type { Dashboard } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Dot } from "../ui/badge";
import { Button } from "../ui/button";
import { Tooltip } from "../ui/misc";
import { ChangePasswordDialog } from "../change-password";
import { SaveBar } from "./save-bar";
import { Sidebar } from "./sidebar";

function MenuItem({ icon, children, onSelect, danger }: { icon: ReactNode; children: ReactNode; onSelect: () => void; danger?: boolean }) {
  return (
    <Dropdown.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px] outline-none data-[highlighted]:bg-surface-3",
        danger && "text-danger",
      )}
    >
      {icon}
      {children}
    </Dropdown.Item>
  );
}

function ThemeSwitch({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  const options: { value: Theme; icon: ReactNode; label: string }[] = [
    { value: "light", icon: <Sun className="size-3.5" />, label: "Light" },
    { value: "dark", icon: <Moon className="size-3.5" />, label: "Dark" },
    { value: "system", icon: <Monitor className="size-3.5" />, label: "System" },
  ];
  return (
    <div className="flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Theme">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={theme === o.value}
          aria-label={o.label}
          onClick={(e) => {
            e.preventDefault();
            setTheme(o.value);
          }}
          className={cn(
            "flex flex-1 items-center justify-center rounded px-2 py-1 text-muted",
            theme === o.value && "bg-surface-3 text-fg",
          )}
        >
          {o.icon}
        </button>
      ))}
    </div>
  );
}

export function ScanButtons({ compact }: { compact?: boolean }) {
  const client = useQueryClient();
  const scan = useMutation({
    mutationFn: (body: { dry_run?: boolean; force?: boolean }) => api.post("scans", body),
    onSuccess: (_, body) => {
      toast.success(body.dry_run ? "Dry run queued" : "Scan queued");
      void client.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Could not queue the scan"),
  });
  return (
    <div className="flex items-center gap-2">
      <Tooltip content="Preview what a scan would change without touching anything">
        <Button
          variant="outline"
          size="sm"
          icon={<FlaskConical className="size-3.5" />}
          onClick={() => scan.mutate({ dry_run: true })}
          disabled={scan.isPending}
        >
          {!compact && "Dry run"}
        </Button>
      </Tooltip>
      <Button variant="primary" size="sm" icon={<Play className="size-3.5" />} onClick={() => scan.mutate({})} loading={scan.isPending}>
        Scan now
      </Button>
    </div>
  );
}

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const auth = useAuthState();
  const navigate = useNavigate();
  const client = useQueryClient();
  const connected = useEventStream(true);
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("dashboard") });
  const user = auth.data?.user;

  const logout = async () => {
    await api.post("auth/logout");
    client.clear();
    await client.invalidateQueries({ queryKey: AUTH_QUERY });
    navigate("/login");
  };

  const scanning = dashboard.data?.scanning;

  return (
    <ConfigEditorProvider>
      <div className="min-h-dvh">
        <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 border-r border-border bg-surface lg:block">
          <Sidebar version={dashboard.data?.version} />
        </aside>
        <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50 lg:hidden" />
            <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 w-64 border-r border-border bg-surface lg:hidden">
              <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">Main navigation</DialogPrimitive.Description>
              <Sidebar version={dashboard.data?.version} onNavigate={() => setMobileOpen(false)} />
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>

        <div className="lg:pl-60">
          <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur md:px-6">
            <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>
              <Menu className="size-4" />
            </Button>
            <div className="flex min-w-0 flex-1 items-center gap-2 text-[13px] text-muted">
              {scanning ? (
                <span className="flex items-center gap-2">
                  <Dot tone="accent" pulse /> Scanning
                  {dashboard.data?.progress && (
                    <span className="hidden text-subtle sm:inline">
                      · {dashboard.data.progress.library} · {dashboard.data.progress.phase}
                    </span>
                  )}
                </span>
              ) : (
                <Tooltip content={connected ? "Live updates connected" : "Live updates disconnected; retrying"}>
                  <span className="flex items-center gap-2">
                    <Dot tone={connected ? "success" : "warning"} />
                    <span className="hidden sm:inline">{connected ? "Idle" : "Reconnecting…"}</span>
                  </span>
                </Tooltip>
              )}
            </div>
            <ScanButtons compact />
            <Dropdown.Root>
              <Dropdown.Trigger asChild>
                <Button variant="ghost" size="icon" aria-label="Account menu">
                  <User className="size-4" />
                </Button>
              </Dropdown.Trigger>
              <Dropdown.Portal>
                <Dropdown.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 w-56 rounded-lg border border-border bg-surface p-1.5 shadow-xl"
                >
                  <div className="px-2 pt-1 pb-2">
                    <div className="truncate text-[13px] font-medium">{user?.name ?? "Guest"}</div>
                    <div className="text-xs text-subtle">
                      {{ session: "Password login", oidc: "Single sign-on", external: "Reverse proxy", local: "Local network", none: "No authentication", api_key: "API key" }[
                        user?.method ?? "none"
                      ] ?? user?.method}
                    </div>
                  </div>
                  <div className="px-1 pb-1.5">
                    <ThemeSwitch theme={theme} setTheme={setTheme} />
                  </div>
                  <Dropdown.Separator className="my-1 h-px bg-border" />
                  <MenuItem icon={<Zap className="size-3.5" />} onSelect={() => navigate("/settings/security")}>
                    API key &amp; security
                  </MenuItem>
                  {user?.method === "session" && (
                    <MenuItem icon={<KeyRound className="size-3.5" />} onSelect={() => setPasswordOpen(true)}>
                      Change password
                    </MenuItem>
                  )}
                  {(user?.method === "session" || user?.method === "oidc") && (
                    <MenuItem icon={<LogOut className="size-3.5" />} onSelect={() => void logout()} danger>
                      Sign out
                    </MenuItem>
                  )}
                </Dropdown.Content>
              </Dropdown.Portal>
            </Dropdown.Root>
          </header>
          <main className="mx-auto w-full max-w-6xl px-4 pt-6 pb-28 md:px-6">
            <Outlet />
          </main>
        </div>
        <SaveBar />
        <ChangePasswordDialog open={passwordOpen} onOpenChange={setPasswordOpen} />
      </div>
    </ConfigEditorProvider>
  );
}
