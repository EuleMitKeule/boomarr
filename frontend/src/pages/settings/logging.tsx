import { Field, NumberField, PathField, SelectField, SwitchField, TextField } from "@/components/form";
import { Select } from "@/components/ui/input";
import { useConfig } from "@/lib/config-editor";
import { Section, SettingsPage } from "./common";

export function LoggingSettings() {
  const cfg = useConfig();
  const database = cfg.get(["database", "type"]);
  return (
    <SettingsPage>
      <Section title="Logging">
        <SelectField
          path={["logging", "level"]}
          label="Level"
          options={["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((l) => ({ value: l, label: l.charAt(0) + l.slice(1).toLowerCase() }))}
        />
        <TextField path={["logging", "file_name"]} label="Log file" mono nullable description="Empty disables the log file. The folder is set with LOG_DIR." />
        <SwitchField path={["logging", "color"]} label="Colored console output" />
        <SwitchField path={["logging", "rotation", "enabled"]} label="Rotate log files" />
        <NumberField path={["logging", "rotation", "max_bytes"]} label="Rotate at" min={1024} suffix="bytes" />
        <NumberField path={["logging", "rotation", "backup_count"]} label="Keep old files" min={0} />
      </Section>
      <Section title="Probe cache" description="Remembers probe results so unchanged files are not probed again.">
        <Field label="Storage">
          <Select
            value={database}
            disabled={cfg.readOnly}
            onChange={(e) => cfg.set(["database"], { type: e.target.value })}
            aria-label="Storage"
          >
            <option value="sqlite">SQLite file (recommended)</option>
            <option value="memory">Memory (probes everything after a restart)</option>
          </Select>
        </Field>
        {database === "sqlite" && <PathField path={["database", "dir"]} label="Folder" />}
      </Section>
    </SettingsPage>
  );
}
