import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Field, FieldGroup, NumberField, SecretField, TextField } from "@/components/form";
import { PathMappings } from "@/components/path-mappings";
import { TestButton } from "@/components/test-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Alert, EmptyState } from "@/components/ui/misc";
import { useConfig } from "@/lib/config-editor";
import type { Path } from "@/lib/path";
import { SettingsPage } from "./common";

type Item = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

interface Kind {
  type: string;
  label: string;
  description: string;
  template: Item;
  fields: (path: Path) => ReactNode;
}

function IntegrationList({
  listPath,
  kinds,
  testKind,
  emptyIcon,
  emptyTitle,
  emptyText,
  ordered,
  intro,
}: {
  listPath: Path;
  kinds: Kind[];
  testKind: string;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyText: string;
  ordered?: boolean;
  intro?: ReactNode;
}) {
  const cfg = useConfig();
  const items: Item[] = cfg.get(listPath) ?? [];
  const disabled = cfg.readOnly;
  const move = (from: number, to: number) => {
    const next = [...items];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    cfg.set(listPath, next);
  };
  const addMenu = (
    <Dropdown.Root>
      <Dropdown.Trigger asChild disabled={disabled}>
        <Button variant="primary" icon={<Plus className="size-4" />}>
          Add
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 w-64 rounded-lg border border-border bg-surface p-1.5 shadow-xl">
          {kinds.map((k) => (
            <Dropdown.Item
              key={k.type}
              onSelect={() => cfg.set(listPath, [...items, structuredClone(k.template)])}
              className="cursor-pointer rounded-md px-2 py-2 outline-none data-[highlighted]:bg-surface-3"
            >
              <span className="block text-[13px] font-medium">{k.label}</span>
              <span className="block text-xs text-muted">{k.description}</span>
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );

  return (
    <SettingsPage actions={addMenu}>
      {intro}
      {items.length === 0 ? (
        <Card>
          <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyText} />
        </Card>
      ) : (
        items.map((item, i) => {
          const kind = kinds.find((k) => k.type === item.type);
          const path = [...listPath, i];
          const errors = cfg.errorsBelow(path).filter((e) => e.loc.length === path.length);
          return (
            <Card key={i}>
              <div className="flex items-center gap-3 border-b border-border px-5 py-3">
                {ordered && <Badge tone="neutral">{i + 1}</Badge>}
                <span className="flex-1 text-[15px] font-semibold">{kind?.label ?? item.type}</span>
                {ordered && (
                  <>
                    <Button variant="ghost" size="icon" aria-label="Move up" disabled={disabled || i === 0} onClick={() => move(i, i - 1)}>
                      <ArrowUp className="size-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label="Move down" disabled={disabled || i === items.length - 1} onClick={() => move(i, i + 1)}>
                      <ArrowDown className="size-3.5" />
                    </Button>
                  </>
                )}
                <Button variant="ghost" size="icon" aria-label="Remove" disabled={disabled} onClick={() => cfg.set(listPath, items.filter((_, j) => j !== i))}>
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
              <CardBody>
                {errors.map((e) => (
                  <Alert key={e.msg} tone="danger" className="mb-3">
                    {e.msg}
                  </Alert>
                ))}
                <FieldGroup>
                  {kind?.fields(path)}
                  <Field label="Connection">
                    <TestButton kind={testKind} config={item} />
                  </Field>
                </FieldGroup>
              </CardBody>
            </Card>
          );
        })
      )}
    </SettingsPage>
  );
}

function MappingField({ path, remoteLabel }: { path: Path; remoteLabel: string }) {
  const cfg = useConfig();
  return (
    <Field
      label="Path mappings"
      description={`Needed when ${remoteLabel} sees the media under a different path than Boomarr.`}
      error={cfg.error([...path, "path_mappings"])}
    >
      <PathMappings
        value={cfg.get([...path, "path_mappings"]) ?? []}
        onChange={(v) => cfg.set([...path, "path_mappings"], v)}
        disabled={cfg.readOnly}
        remoteLabel={remoteLabel}
      />
    </Field>
  );
}

const arrFields = (name: string) => (path: Path) => (
  <>
    <TextField path={[...path, "url"]} label="URL" placeholder={name === "Sonarr" ? "http://sonarr:8989" : "http://radarr:7878"} mono />
    <SecretField path={[...path, "api_key"]} label="API key" description={`${name} → Settings → General → Security`} />
    <MappingField path={path} remoteLabel={name} />
    <NumberField path={[...path, "cache_ttl"]} label="Cache duration" description="How long the library index is reused." min={0} suffix="seconds" />
    <NumberField path={[...path, "timeout"]} label="Timeout" min={1} suffix="seconds" />
  </>
);

const proberKinds: Kind[] = [
  {
    type: "ffprobe",
    label: "FFprobe",
    description: "Reads the audio tracks of each file (always correct)",
    template: { type: "ffprobe", path: "ffprobe", timeout: 30 },
    fields: (path) => (
      <>
        <TextField path={[...path, "path"]} label="Executable" mono placeholder="ffprobe" />
        <NumberField path={[...path, "timeout"]} label="Timeout per file" min={1} suffix="seconds" />
      </>
    ),
  },
  {
    type: "sonarr",
    label: "Sonarr",
    description: "Uses the languages Sonarr already knows (fast)",
    template: { type: "sonarr", url: "http://sonarr:8989", api_key: "", path_mappings: [] },
    fields: arrFields("Sonarr"),
  },
  {
    type: "radarr",
    label: "Radarr",
    description: "Uses the languages Radarr already knows (fast)",
    template: { type: "radarr", url: "http://radarr:7878", api_key: "", path_mappings: [] },
    fields: arrFields("Radarr"),
  },
];

const serverFields = (name: string, tokenLabel: string, tokenPath: string, hint: string) => (path: Path) => (
  <>
    <TextField path={[...path, "url"]} label="URL" mono placeholder={name === "Plex" ? "http://plex:32400" : "http://jellyfin:8096"} />
    <SecretField path={[...path, tokenPath]} label={tokenLabel} description={hint} />
    <MappingField path={path} remoteLabel={name} />
    <NumberField path={[...path, "timeout"]} label="Timeout" min={1} suffix="seconds" />
  </>
);

const mediaServerKinds: Kind[] = [
  {
    type: "plex",
    label: "Plex",
    description: "Partial scan of the changed folders",
    template: { type: "plex", url: "http://plex:32400", token: "", path_mappings: [] },
    fields: serverFields("Plex", "Token", "token", "Your X-Plex-Token"),
  },
  {
    type: "jellyfin",
    label: "Jellyfin",
    description: "Notifies Jellyfin about changed folders",
    template: { type: "jellyfin", url: "http://jellyfin:8096", api_key: "", path_mappings: [] },
    fields: serverFields("Jellyfin", "API key", "api_key", "Dashboard → API keys"),
  },
  {
    type: "emby",
    label: "Emby",
    description: "Notifies Emby about changed folders",
    template: { type: "emby", url: "http://emby:8096", api_key: "", path_mappings: [] },
    fields: serverFields("Emby", "API key", "api_key", "Settings → API keys"),
  },
];

export function ProberSettings({ icon }: { icon: ReactNode }) {
  return (
    <IntegrationList
      listPath={["probers"]}
      kinds={proberKinds}
      testKind="prober"
      ordered
      emptyIcon={icon}
      emptyTitle="No probers"
      emptyText="Add FFprobe to detect audio languages."
      intro={
        <Alert tone="info">
          Probers are asked in this order. Sonarr/Radarr answer from their database; files they do not know fall through to the next
          prober, usually FFprobe.
        </Alert>
      }
    />
  );
}

export function MediaServerSettings({ icon }: { icon: ReactNode }) {
  return (
    <IntegrationList
      listPath={["media_servers"]}
      kinds={mediaServerKinds}
      testKind="media_server"
      emptyIcon={icon}
      emptyTitle="No media servers"
      emptyText="Boomarr can ask Plex, Jellyfin or Emby to rescan exactly the folders that changed after each scan."
    />
  );
}
