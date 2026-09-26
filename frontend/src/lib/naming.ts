/** Mirrors Config.symlink_library_output() for the live output folder preview. */

const CODEC_ALIASES: Record<string, string> = {
  h265: "hevc",
  x265: "hevc",
  avc: "h264",
  x264: "h264",
  avc1: "h264",
  vp09: "vp9",
  "ac-3": "ac3",
  "e-ac-3": "eac3",
  ddp: "eac3",
  "dts-hd": "dts",
  dtshd: "dts",
  mlp: "truehd",
};

export function normalizeCodec(codec: string): string {
  const value = codec.trim().toLowerCase();
  return CODEC_ALIASES[value] ?? value;
}

type Filter = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function parseHeight(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = parseInt(String(value).toLowerCase().replace(/p$/, ""), 10);
  return Number.isFinite(n) ? n : null;
}

export function defaultSuffix(filter: Filter): string {
  switch (filter.type) {
    case "audio_language":
      return (filter.languages ?? [])
        .map((l: { code: string } | string) => (typeof l === "string" ? l : l.code).trim().toLowerCase())
        .sort()
        .join("-");
    case "resolution": {
      const min = parseHeight(filter.min_height);
      const max = parseHeight(filter.max_height);
      if (min !== null && max !== null) return `${min}p-${max}p`;
      if (min !== null) return `${min}p-plus`;
      return `max-${max}p`;
    }
    case "video_codec":
    case "audio_codec":
      return [...new Set((filter.codecs ?? []).map(normalizeCodec))].sort().join("-");
    case "audio_channels":
      return `${filter.min_channels}ch`;
    default:
      return String(filter.type);
  }
}

export function effectiveSuffix(filter: Filter): string {
  if (filter.suffix) return filter.suffix;
  const base = defaultSuffix(filter);
  return filter.invert ? `not-${base}` : base;
}

export function joinPath(base: string, name: string): string {
  return `${base.replace(/\/+$/, "")}/${name}`;
}

export function outputFolder(
  config: Record<string, any>, // eslint-disable-line @typescript-eslint/no-explicit-any
  library: Record<string, any>, // eslint-disable-line @typescript-eslint/no-explicit-any
  symlinkLibrary: Record<string, any>, // eslint-disable-line @typescript-eslint/no-explicit-any
): string | null {
  if (symlinkLibrary.output_path) return symlinkLibrary.output_path;
  const base: string | null = library.output_path ?? config.output_path ?? null;
  if (!base) return null;
  if (symlinkLibrary.name) return joinPath(base, symlinkLibrary.name);
  const slug = String(library.name ?? "").toLowerCase().replaceAll(" ", "-");
  const suffix = (symlinkLibrary.filters ?? []).map(effectiveSuffix).join("-");
  return joinPath(base, `${slug}-${suffix}`);
}
