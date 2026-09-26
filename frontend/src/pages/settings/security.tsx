import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Eye, EyeOff, KeyRound, LogOut, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ChangePasswordDialog } from "@/components/change-password";
import { Field, ListField, NumberField, SecretField, SelectField, SwitchField, TextField } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { useAuthState } from "@/hooks/use-auth";
import { api, ApiError } from "@/lib/api";
import { useConfig } from "@/lib/config-editor";
import { Section, SettingsPage } from "./common";

function ApiKeyField() {
  const client = useQueryClient();
  const [visible, setVisible] = useState(false);
  const query = useQuery({ queryKey: ["apikey"], queryFn: () => api.get<{ api_key: string; source: string }>("auth/apikey") });
  const regenerate = useMutation({
    mutationFn: () => api.post<{ api_key: string; source: string }>("auth/apikey/regenerate"),
    onSuccess: (data) => {
      client.setQueryData(["apikey"], data);
      toast.success("New API key generated; update Sonarr/Radarr webhooks");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed"),
  });
  const key = query.data?.api_key ?? "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(key);
      toast.success("Copied");
    } catch {
      toast.error("Copying is not allowed here; select the key manually");
    }
  };
  return (
    <Field
      label={
        <>
          API key {query.data && query.data.source !== "generated" && <Badge tone="info">from {query.data.source}</Badge>}
        </>
      }
      description={
        <>
          For webhooks (<code className="font-mono">/api/v1/webhook/sonarr</code>) and scripts: send it as{" "}
          <code className="font-mono">X-Api-Key</code> header, <code className="font-mono">?apikey=</code> or basic auth password.
        </>
      }
    >
      <div className="flex items-center gap-2">
        <Input readOnly value={visible ? key : "•".repeat(Math.max(8, key.length))} className="font-mono text-[13px]" aria-label="API key" />
        <Button variant="outline" size="icon" aria-label={visible ? "Hide" : "Show"} onClick={() => setVisible((v) => !v)}>
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </Button>
        <Button variant="outline" size="icon" aria-label="Copy" onClick={() => void copy()}>
          <Copy className="size-4" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Regenerate"
          loading={regenerate.isPending}
          disabled={query.data?.source !== "generated"}
          onClick={() => regenerate.mutate()}
        >
          {!regenerate.isPending && <RefreshCw className="size-4" />}
        </Button>
      </div>
    </Field>
  );
}

function AccountSection() {
  const auth = useAuthState();
  const [open, setOpen] = useState(false);
  const revoke = useMutation({
    mutationFn: () => api.post("auth/sessions/revoke"),
    onSuccess: () => window.location.reload(),
  });
  const user = auth.data?.user;
  return (
    <Section title="Account">
      <Field label="Signed in as" description={user?.method === "session" ? "Local account" : user?.method}>
        <span className="text-[13px] font-medium">{user?.name}</span>
      </Field>
      {user?.method === "session" && (
        <Field label="Password">
          <Button variant="outline" icon={<KeyRound className="size-4" />} onClick={() => setOpen(true)}>
            Change password
          </Button>
        </Field>
      )}
      <Field label="Sessions" description="Sign out everywhere, including this browser.">
        <Button variant="danger" icon={<LogOut className="size-4" />} loading={revoke.isPending} onClick={() => revoke.mutate()}>
          Sign out all sessions
        </Button>
      </Field>
      <ChangePasswordDialog open={open} onOpenChange={setOpen} />
    </Section>
  );
}

export function SecuritySettings() {
  const cfg = useConfig();
  const method = cfg.get(["auth", "method"]);
  const oidc = cfg.get(["auth", "oidc", "enabled"]);
  const redirect = new URL("api/v1/auth/oidc/callback", document.baseURI).toString();
  return (
    <SettingsPage>
      <Section title="Authentication">
        <SelectField
          path={["auth", "method"]}
          label="Method"
          options={[
            { value: "forms", label: "Login page (password and/or single sign-on)" },
            { value: "external", label: "Reverse proxy (Authelia, Authentik forward auth…)" },
            { value: "none", label: "None (not recommended)" },
          ]}
        />
        {method === "none" && (
          <Alert tone="danger">Anyone who can reach Boomarr can change its configuration. Only use this behind another authentication layer.</Alert>
        )}
        {method === "external" && (
          <>
            <TextField path={["auth", "external_header"]} label="User header" mono description="Header your proxy sets with the authenticated user." />
            <Alert tone="info">
              The header is only trusted from the addresses in <b>Web server → Trusted proxies</b>.
            </Alert>
          </>
        )}
        <SwitchField
          path={["auth", "local_bypass"]}
          label="No login on local networks"
          description="Skip authentication for requests from private addresses (192.168.x.x, 10.x.x.x…)."
        />
        <NumberField path={["auth", "session_days"]} label="Stay signed in for" min={1} max={365} suffix="days" />
      </Section>
      {method === "forms" && (
        <Section title="Single sign-on (OpenID Connect)" description="Authentik, Authelia, Keycloak, Pocket ID, Zitadel, Google…">
          <SwitchField path={["auth", "oidc", "enabled"]} label="Enable single sign-on" />
          {oidc && (
            <>
              <Field label="Redirect URI" description="Register this URL at your identity provider.">
                <Input readOnly value={redirect} className="font-mono text-[13px]" onFocus={(e) => e.currentTarget.select()} />
              </Field>
              <TextField path={["auth", "oidc", "name"]} label="Button label" placeholder="SSO" />
              <TextField path={["auth", "oidc", "issuer"]} label="Issuer URL" mono placeholder="https://auth.example.com/application/o/boomarr/" />
              <TextField path={["auth", "oidc", "client_id"]} label="Client ID" mono />
              <SecretField path={["auth", "oidc", "client_secret"]} label="Client secret" description="Leave empty for public clients (PKCE only)." />
              <ListField path={["auth", "oidc", "scopes"]} label="Scopes" mono />
              <TextField path={["auth", "oidc", "username_claim"]} label="Username claim" mono />
              <TextField path={["auth", "oidc", "groups_claim"]} label="Groups claim" mono />
              <ListField path={["auth", "oidc", "allowed_users"]} label="Allowed users" description="Usernames or e-mail addresses. Empty allows everyone the provider lets in." />
              <ListField path={["auth", "oidc", "allowed_groups"]} label="Allowed groups" />
              <SwitchField path={["auth", "oidc", "auto_login"]} label="Redirect automatically" description="Skip the login page and go straight to the provider." />
              <SwitchField path={["auth", "oidc", "disable_password_login"]} label="Disable password login" description="Only allow single sign-on." />
            </>
          )}
        </Section>
      )}
      <Section title="API">
        <ApiKeyField />
        <SecretField
          path={["server", "api_key"]}
          label="Fixed API key"
          description="Optional. Set a key in the configuration instead of the generated one above."
        />
        <SwitchField path={["server", "metrics_auth"]} label="Protect /metrics" description="Require the API key for Prometheus scrapes." />
      </Section>
      <AccountSection />
    </SettingsPage>
  );
}
