import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogIn } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, PageLoader } from "@/components/ui/misc";
import { AUTH_QUERY, useAuthState } from "@/hooks/use-auth";
import { api, ApiError } from "@/lib/api";

function AuthShell({ title, subtitle, children }: { title: string; subtitle: ReactNode; children: ReactNode }) {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-12">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[40rem] -translate-x-1/2 rounded-full bg-accent/15 blur-3xl"
      />
      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo className="mb-4 size-12" />
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-[13px] text-muted">{subtitle}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-6 shadow-card">{children}</div>
      </div>
    </div>
  );
}

function LabeledInput({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[13px] font-medium">{label}</span>
      <Input {...props} />
    </label>
  );
}

function errorText(error: unknown): string | null {
  if (!error) return null;
  return error instanceof ApiError ? error.message : "Something went wrong";
}

export function LoginPage() {
  const auth = useAuthState();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const next = params.get("next") ?? "/";
  const oidcError = params.get("error");

  const login = useMutation({
    mutationFn: () => api.post("auth/login", { username, password, remember }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: AUTH_QUERY });
      navigate(next.startsWith("/") ? next : "/", { replace: true });
    },
  });

  const state = auth.data;
  const ssoUrl = `api/v1/auth/oidc/login?next=${encodeURIComponent(new URL(next, document.baseURI).pathname)}`;

  useEffect(() => {
    if (state?.oidc.enabled && state.oidc.auto_login && !oidcError && !state.user) {
      window.location.assign(ssoUrl);
    }
  }, [state, oidcError, ssoUrl]);

  if (auth.isLoading || !state) return <PageLoader />;
  if (state.setup_required) return <Navigate to="/setup" replace />;
  if (state.user) return <Navigate to={next} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <AuthShell title="Sign in to Boomarr" subtitle="Audio language filtered libraries for Plex & Jellyfin">
      <div className="space-y-4">
        {(oidcError || login.error) && <Alert tone="danger">{oidcError ?? errorText(login.error)}</Alert>}
        {state.method === "external" && (
          <Alert tone="warning" title="Reverse proxy login">
            Boomarr expects your reverse proxy to authenticate you. Sign in through the proxy and reload this page.
          </Alert>
        )}
        {state.oidc.enabled && (
          <Button variant="primary" className="w-full justify-center" icon={<KeyRound className="size-4" />} onClick={() => window.location.assign(ssoUrl)}>
            Continue with {state.oidc.name}
          </Button>
        )}
        {state.oidc.enabled && state.password_login && (
          <div className="flex items-center gap-3 text-xs text-subtle">
            <div className="h-px flex-1 bg-border" /> or <div className="h-px flex-1 bg-border" />
          </div>
        )}
        {state.password_login && (
          <form className="space-y-3.5" onSubmit={submit}>
            <LabeledInput label="Username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            <LabeledInput label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <label className="flex items-center gap-2 text-[13px] text-muted">
              <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Keep me signed in
            </label>
            <Button
              type="submit"
              variant={state.oidc.enabled ? "outline" : "primary"}
              className="w-full justify-center"
              loading={login.isPending}
              icon={<LogIn className="size-4" />}
            >
              Sign in
            </Button>
          </form>
        )}
      </div>
    </AuthShell>
  );
}

export function SetupPage() {
  const auth = useAuthState();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [token, setToken] = useState("");

  const setup = useMutation({
    mutationFn: () => api.post("auth/setup", { username, password, token }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: AUTH_QUERY });
      navigate("/", { replace: true });
    },
  });

  if (auth.isLoading || !auth.data) return <PageLoader />;
  if (!auth.data.setup_required) return <Navigate to="/" replace />;

  const mismatch = confirm.length > 0 && confirm !== password;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) setup.mutate();
  };

  return (
    <AuthShell title="Welcome to Boomarr" subtitle="Create the admin account to secure the web interface.">
      <form className="space-y-3.5" onSubmit={submit}>
        {setup.error && <Alert tone="danger">{errorText(setup.error)}</Alert>}
        <LabeledInput label="Username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        <LabeledInput label="Password" type="password" autoComplete="new-password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required />
        <LabeledInput
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          aria-invalid={mismatch}
          onChange={(e) => setConfirm(e.target.value)}
          required
        />
        {mismatch && <p className="text-xs text-danger">The passwords do not match</p>}
        {auth.data.setup_token_required && (
          <div className="space-y-1.5">
            <LabeledInput label="Setup token" className="font-mono" value={token} onChange={(e) => setToken(e.target.value)} required />
            <p className="text-xs text-muted">
              You are not connecting from a local network. The token is printed in the Boomarr log
              (<code className="font-mono">docker logs boomarr</code>).
            </p>
          </div>
        )}
        <Button type="submit" variant="primary" className="w-full justify-center" loading={setup.isPending} disabled={mismatch}>
          Create account
        </Button>
        <p className="text-center text-xs text-subtle">
          Prefer single sign-on or a reverse proxy? You can switch in Settings → Security later.
        </p>
      </form>
    </AuthShell>
  );
}
