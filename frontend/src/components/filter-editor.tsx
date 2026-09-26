import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { AudioLines, Film, Languages, MonitorPlay, Plus, Speaker, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { normalizeCodec } from "@/lib/naming";
import { TagInput } from "./form";
import { LanguagePicker, type LanguageEntry } from "./language-picker";
import { Button } from "./ui/button";
import { Input, Select } from "./ui/input";
import { Switch } from "./ui/switch";

type Filter = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const FILTER_TYPES: { type: string; label: string; icon: ReactNode; template: Filter; hint: string }[] = [
  {
    type: "audio_language",
    label: "Audio language",
    icon: <Languages className="size-4" />,
    template: { type: "audio_language", languages: [], mode: "any" },
    hint: "Files with (or without) audio tracks in these languages",
  },
  {
    type: "resolution",
    label: "Resolution",
    icon: <MonitorPlay className="size-4" />,
    template: { type: "resolution", min_height: 2160 },
    hint: "Video height, e.g. only 4K or only up to 1080p",
  },
  {
    type: "video_codec",
    label: "Video codec",
    icon: <Film className="size-4" />,
    template: { type: "video_codec", codecs: ["hevc"] },
    hint: "E.g. hevc, h264, av1",
  },
  {
    type: "audio_codec",
    label: "Audio codec",
    icon: <AudioLines className="size-4" />,
    template: { type: "audio_codec", codecs: ["truehd"] },
    hint: "E.g. truehd, eac3, dts",
  },
  {
    type: "audio_channels",
    label: "Audio channels",
    icon: <Speaker className="size-4" />,
    template: { type: "audio_channels", min_channels: 6 },
    hint: "At least N channels, e.g. 6 for 5.1",
  },
];

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid items-center gap-1.5 sm:grid-cols-[9rem_1fr] sm:gap-4">
      <span className="text-xs text-muted">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function heightValue(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function FilterFields({ filter, set, disabled }: { filter: Filter; set: (key: string, value: unknown) => void; disabled?: boolean }) {
  switch (filter.type) {
    case "audio_language":
      return (
        <>
          <Row label="Languages">
            <LanguagePicker
              value={(filter.languages ?? []).map((l: LanguageEntry | string) => (typeof l === "string" ? { code: l, aliases: [] } : l))}
              onChange={(v) => set("languages", v)}
              disabled={disabled}
            />
          </Row>
          <Row label="Match">
            <Select value={filter.mode ?? "any"} onChange={(e) => set("mode", e.target.value)} disabled={disabled}>
              <option value="any">At least one of these languages</option>
              <option value="all">All of these languages</option>
            </Select>
          </Row>
        </>
      );
    case "resolution":
      return (
        <Row label="Height">
          <div className="flex items-center gap-2">
            <Input
              placeholder="min, e.g. 2160"
              value={heightValue(filter.min_height)}
              disabled={disabled}
              onChange={(e) => set("min_height", e.target.value === "" ? null : Number(e.target.value.replace(/p$/i, "")) || e.target.value)}
            />
            <span className="text-muted">–</span>
            <Input
              placeholder="max, e.g. 1080"
              value={heightValue(filter.max_height)}
              disabled={disabled}
              onChange={(e) => set("max_height", e.target.value === "" ? null : Number(e.target.value.replace(/p$/i, "")) || e.target.value)}
            />
            <span className="text-xs text-muted">px</span>
          </div>
        </Row>
      );
    case "video_codec":
    case "audio_codec":
      return (
        <Row label="Codecs">
          <TagInput value={filter.codecs ?? []} onChange={(v) => set("codecs", v)} disabled={disabled} mono normalize={normalizeCodec} placeholder="Type a codec and press Enter" />
        </Row>
      );
    case "audio_channels":
      return (
        <Row label="Minimum channels">
          <Input
            type="number"
            min={1}
            className="max-w-28"
            value={filter.min_channels ?? ""}
            disabled={disabled}
            onChange={(e) => set("min_channels", e.target.value === "" ? null : Number(e.target.value))}
          />
        </Row>
      );
    default:
      return null;
  }
}

export function FilterCard({
  filter,
  onChange,
  onRemove,
  disabled,
  errors,
}: {
  filter: Filter;
  onChange: (filter: Filter) => void;
  onRemove?: () => void;
  disabled?: boolean;
  errors: string[];
}) {
  const meta = FILTER_TYPES.find((f) => f.type === filter.type);
  const set = (key: string, value: unknown) => onChange({ ...filter, [key]: value });
  return (
    <div className={cn("rounded-lg border bg-surface-2/60", errors.length ? "border-danger/60" : "border-border")}>
      <div className="flex items-center gap-2.5 border-b border-border px-3 py-2">
        <span className="text-accent">{meta?.icon}</span>
        <span className="flex-1 text-[13px] font-medium">{meta?.label ?? filter.type}</span>
        <label className="flex items-center gap-2 text-xs text-muted">
          Invert
          <Switch checked={!!filter.invert} onCheckedChange={(v) => set("invert", v)} disabled={disabled} aria-label="Invert filter" />
        </label>
        {onRemove && (
          <Button variant="ghost" size="icon" aria-label="Remove filter" onClick={onRemove} disabled={disabled}>
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </div>
      <div className="space-y-3 px-3 py-3">
        <FilterFields filter={filter} set={set} disabled={disabled} />
        <Row label="Folder suffix">
          <Input
            placeholder="automatic"
            className="max-w-60 font-mono text-[13px]"
            value={filter.suffix ?? ""}
            disabled={disabled}
            onChange={(e) => set("suffix", e.target.value === "" ? null : e.target.value)}
          />
        </Row>
        {errors.map((e) => (
          <p key={e} className="text-xs text-danger">
            {e}
          </p>
        ))}
      </div>
    </div>
  );
}

export function AddFilterMenu({ onAdd, disabled, label = "Add filter" }: { onAdd: (filter: Filter) => void; disabled?: boolean; label?: string }) {
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild disabled={disabled}>
        <Button variant="outline" size="sm" icon={<Plus className="size-3.5" />}>
          {label}
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="start" sideOffset={6} className="z-50 w-72 rounded-lg border border-border bg-surface p-1.5 shadow-xl">
          {FILTER_TYPES.map((f) => (
            <Dropdown.Item
              key={f.type}
              onSelect={() => onAdd(structuredClone(f.template))}
              className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-2 outline-none data-[highlighted]:bg-surface-3"
            >
              <span className="mt-0.5 text-accent">{f.icon}</span>
              <span>
                <span className="block text-[13px] font-medium">{f.label}</span>
                <span className="block text-xs text-muted">{f.hint}</span>
              </span>
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
