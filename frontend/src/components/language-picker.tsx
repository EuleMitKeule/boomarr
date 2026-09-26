import * as Popover from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { Check, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Language } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Input } from "./ui/input";

export interface LanguageEntry {
  code: string;
  aliases?: string[];
}

export function useLanguages() {
  return useQuery({
    queryKey: ["languages"],
    queryFn: () => api.get<Language[]>("languages"),
    staleTime: Infinity,
  });
}

export function LanguagePicker({
  value,
  onChange,
  disabled,
  invalid,
}: {
  value: LanguageEntry[];
  onChange: (value: LanguageEntry[]) => void;
  disabled?: boolean;
  invalid?: boolean;
}) {
  const languages = useLanguages().data ?? [];
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const names = useMemo(() => new Map(languages.map((l) => [l.code, l.name])), [languages]);
  const selected = new Set(value.map((v) => v.code));
  const term = search.trim().toLowerCase();
  const matches = languages
    .filter((l) => !term || l.name.toLowerCase().includes(term) || l.code === term || l.code1 === term)
    .slice(0, 60);
  const custom = term.length >= 2 && term.length <= 3 && /^[a-z]+$/.test(term) && !languages.some((l) => l.code === term);

  const toggle = (code: string) => {
    onChange(selected.has(code) ? value.filter((v) => v.code !== code) : [...value, { code, aliases: [] }]);
  };

  return (
    <div
      className={cn(
        "flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-border-strong bg-surface-2 px-2 py-1.5",
        invalid && "border-danger",
        disabled && "opacity-60",
      )}
    >
      {value.map((entry) => (
        <span key={entry.code} className="inline-flex items-center gap-1.5 rounded bg-accent-soft py-0.5 pr-1 pl-2 text-xs text-fg">
          <span className="font-mono text-[11px] text-accent uppercase">{entry.code}</span>
          {names.get(entry.code) ?? ""}
          {entry.aliases && entry.aliases.length > 0 && <span className="text-subtle">+{entry.aliases.join("/")}</span>}
          {!disabled && (
            <button
              type="button"
              className="rounded p-0.5 text-subtle hover:bg-border-strong hover:text-fg"
              aria-label={`Remove ${entry.code}`}
              onClick={() => toggle(entry.code)}
            >
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild disabled={disabled}>
          <button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted hover:bg-surface-3 hover:text-fg">
            <Plus className="size-3" /> Add language
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content align="start" sideOffset={6} className="z-50 w-72 rounded-lg border border-border bg-surface p-2 shadow-xl">
            <Input autoFocus placeholder="Search e.g. German, ja, eng…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="mt-2 max-h-64 overflow-y-auto">
              {custom && (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-surface-3"
                  onClick={() => toggle(term)}
                >
                  <Plus className="size-3.5 text-muted" /> Use code <span className="font-mono">{term}</span>
                </button>
              )}
              {matches.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-surface-3"
                  onClick={() => toggle(l.code)}
                >
                  <span className="w-9 font-mono text-[11px] text-muted uppercase">{l.code}</span>
                  <span className="flex-1 truncate">{l.name}</span>
                  {selected.has(l.code) && <Check className="size-3.5 text-accent" />}
                </button>
              ))}
              {!matches.length && !custom && <p className="px-2 py-3 text-center text-xs text-muted">No match</p>}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
