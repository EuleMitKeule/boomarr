import { Field, ListField, NumberField } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useConfig } from "@/lib/config-editor";
import { Section, SettingsPage } from "./common";

type Trigger = { type: string; interval?: number; run_on_start?: boolean };

function ScheduleFields() {
  const cfg = useConfig();
  const triggers: Trigger[] = cfg.get(["triggers"]) ?? [];
  const index = triggers.findIndex((t) => t.type === "schedule");
  const schedule = index >= 0 ? triggers[index] : null;
  const disabled = cfg.readOnly;
  const setSchedule = (value: Trigger | null) => {
    const others = triggers.filter((t) => t.type !== "schedule");
    cfg.set(["triggers"], value ? [value, ...others] : others);
  };
  const minutes = schedule ? Math.round(((schedule.interval ?? 600) / 60) * 100) / 100 : 10;
  return (
    <>
      <Field
        label="Scheduled scans"
        description="Scan all libraries periodically. Webhooks from Sonarr/Radarr trigger scans in addition."
        inline
        error={cfg.error(["triggers"])}
      >
        <Switch
          checked={!!schedule}
          disabled={disabled}
          aria-label="Scheduled scans"
          onCheckedChange={(on) => setSchedule(on ? { type: "schedule", interval: 600, run_on_start: true } : null)}
        />
      </Field>
      {schedule && (
        <>
          <Field label="Interval" error={cfg.error(["triggers", index, "interval"])}>
            <div className="flex max-w-56 items-center gap-2">
              <Input
                type="number"
                min={1}
                step={1}
                value={minutes}
                disabled={disabled}
                onChange={(e) => setSchedule({ ...schedule, interval: Math.round(Number(e.target.value) * 60) })}
              />
              <span className="shrink-0 text-xs text-muted">minutes</span>
            </div>
          </Field>
          <Field label="Scan on start" description="Run a scan right after Boomarr starts." inline>
            <Switch
              checked={schedule.run_on_start ?? true}
              disabled={disabled}
              aria-label="Scan on start"
              onCheckedChange={(v) => setSchedule({ ...schedule, run_on_start: v })}
            />
          </Field>
        </>
      )}
    </>
  );
}

export function ScanningSettings() {
  return (
    <SettingsPage>
      <Section title="Triggers">
        <ScheduleFields />
        <NumberField
          path={["watch", "debounce"]}
          label="Debounce"
          description="Requests arriving within this time are merged into one scan (e.g. many webhooks after an import)."
          min={0}
          step={0.5}
          suffix="seconds"
        />
      </Section>
      <Section
        title="Removal guard"
        description="Protects your media server from an empty library when a mount disappears: a scan refuses to remove more links than allowed."
      >
        <NumberField
          path={["removal_guard", "max_percent"]}
          label="Maximum removal"
          description="Share of an output's links a single scan may remove. 100 disables the guard."
          min={1}
          max={100}
          suffix="%"
        />
        <NumberField
          path={["removal_guard", "min_count"]}
          label="Always allow up to"
          description="Removing this many links is always fine, regardless of the percentage."
          min={0}
          suffix="links"
        />
      </Section>
      <Section title="File selection">
        <ListField
          path={["pre_probe_filters", 0, "extensions"]}
          label="Video extensions"
          description="Only files with these extensions are probed. Empty uses the built-in list of video formats."
          placeholder=".mkv, .mp4"
          mono
        />
      </Section>
    </SettingsPage>
  );
}
