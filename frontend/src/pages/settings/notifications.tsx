import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Field, SwitchField } from "@/components/form";
import { TestButton } from "@/components/test-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfig } from "@/lib/config-editor";
import { Section, SettingsPage } from "./common";

const SECRET_PREFIX = "__secret__:";

function scheme(url: string): string {
  return url.split("://")[0] || "url";
}

function UrlList() {
  const cfg = useConfig();
  const path = ["notifications", "urls"];
  const urls: string[] = cfg.get(path) ?? [];
  const [text, setText] = useState("");
  const locked = cfg.envLocked(path);
  const disabled = cfg.readOnly || locked;
  const add = () => {
    if (!text.trim()) return;
    cfg.set(path, [...urls, text.trim()]);
    setText("");
  };
  return (
    <Field
      label="Targets"
      locked={locked}
      error={cfg.error(path)}
      description={
        <>
          Any{" "}
          <a className="text-accent hover:underline" href="https://github.com/caronc/apprise/wiki" target="_blank" rel="noreferrer">
            Apprise URL
          </a>
          , e.g. <code className="font-mono">tgram://token/chat</code>, <code className="font-mono">discord://id/token</code> or{" "}
          <code className="font-mono">ntfy://topic</code>. Stored like a password.
        </>
      }
    >
      <div className="space-y-2">
        {urls.map((url, i) => (
          <div key={`${url}-${i}`} className="flex items-center gap-2">
            <Input
              value={url.startsWith(SECRET_PREFIX) ? "•••••••••• (saved)" : url}
              readOnly
              disabled
              className="font-mono text-[13px]"
              aria-label={`Notification target ${i + 1}`}
            />
            {!url.startsWith(SECRET_PREFIX) && <span className="text-xs text-muted">{scheme(url)}</span>}
            <Button variant="ghost" size="icon" aria-label="Remove target" disabled={disabled} onClick={() => cfg.set(path, urls.filter((_, j) => j !== i))}>
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <Input
            value={text}
            placeholder="scheme://…"
            className="font-mono text-[13px]"
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            aria-label="New notification URL"
          />
          <Button variant="outline" size="icon" aria-label="Add target" disabled={disabled || !text.trim()} onClick={add}>
            <Plus className="size-4" />
          </Button>
        </div>
      </div>
    </Field>
  );
}

export function NotificationSettings() {
  const cfg = useConfig();
  return (
    <SettingsPage>
      <Section title="Targets" description="Boomarr uses Apprise, which supports 100+ services.">
        <UrlList />
        <Field label="Test">
          <TestButton kind="notifications" config={cfg.get(["notifications"]) ?? {}} />
        </Field>
      </Section>
      <Section title="When to notify">
        <SwitchField path={["notifications", "on_changes"]} label="Links changed" description="After every scan that created or removed links." />
        <SwitchField path={["notifications", "on_errors"]} label="Scan errors" description="When a scan fails or files cannot be probed." />
        <SwitchField path={["notifications", "on_blocked"]} label="Removal guard" description="When the removal guard blocks a scan." />
      </Section>
    </SettingsPage>
  );
}
