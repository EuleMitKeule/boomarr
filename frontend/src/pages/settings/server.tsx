import { ListField, NumberField, TextField } from "@/components/form";
import { Alert } from "@/components/ui/misc";
import { Section, SettingsPage } from "./common";

export function ServerSettings() {
  return (
    <SettingsPage>
      <Alert tone="info">Changes on this page take effect after restarting Boomarr.</Alert>
      <Section title="Listener">
        <TextField path={["server", "host"]} label="Bind address" mono placeholder="0.0.0.0" />
        <NumberField path={["server", "port"]} label="Port" min={1} max={65535} />
        <TextField
          path={["server", "url_base"]}
          label="URL base"
          mono
          placeholder="/boomarr"
          description="Serve Boomarr below a path, e.g. https://example.com/boomarr."
        />
      </Section>
      <Section title="Reverse proxy">
        <ListField
          path={["server", "trusted_proxies"]}
          label="Trusted proxies"
          mono
          placeholder="172.16.0.0/12"
          description="Addresses or networks whose X-Forwarded-For and authentication headers are trusted."
        />
      </Section>
    </SettingsPage>
  );
}
