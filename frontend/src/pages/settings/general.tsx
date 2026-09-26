import { ListField, NumberField, PathField, SwitchField, TextField } from "@/components/form";
import { Section, SettingsPage } from "./common";

export function GeneralSettings() {
  return (
    <SettingsPage>
      <Section title="Output" description="Where filtered libraries are created and how links look.">
        <PathField
          path={["output_path"]}
          label="Output folder"
          description="Default base folder for all filtered libraries. Libraries can override it."
          placeholder="/media/boomarr"
          nullable
        />
        <SwitchField
          path={["relative_symlinks"]}
          label="Relative symlinks"
          description="Use relative link targets, e.g. when the media server mounts the folders at a different path."
        />
        <ListField path={["sidecar_extensions"]} label="Sidecar files" description="Files next to a video that are linked with it (subtitles, NFO…)." mono />
        <ListField path={["ignore_patterns"]} label="Ignore patterns" description="Glob patterns of files and folders to skip." mono />
      </Section>
      <Section title="Performance">
        <NumberField path={["probe_workers"]} label="Parallel probes" description="How many files are probed at the same time." min={1} max={64} />
      </Section>
      <Section title="System" description="Applied by the container entrypoint on start.">
        <TextField path={["general", "tz"]} label="Time zone" placeholder="Europe/Berlin" description="IANA time zone used for log timestamps." />
        <NumberField path={["general", "puid"]} label="User ID (PUID)" min={0} />
        <NumberField path={["general", "pgid"]} label="Group ID (PGID)" min={0} />
        <TextField path={["general", "umask"]} label="Umask" mono placeholder="022" />
      </Section>
    </SettingsPage>
  );
}
