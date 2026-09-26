import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

type Mapping = { local: string; remote: string };

export function PathMappings({
  value,
  onChange,
  disabled,
  remoteLabel,
}: {
  value: Mapping[];
  onChange: (value: Mapping[]) => void;
  disabled?: boolean;
  remoteLabel: string;
}) {
  const update = (i: number, key: keyof Mapping, v: string) => onChange(value.map((m, j) => (j === i ? { ...m, [key]: v } : m)));
  return (
    <div className="space-y-2">
      {value.map((mapping, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            aria-label="Path in Boomarr"
            placeholder="/media (Boomarr)"
            className="font-mono text-[13px]"
            value={mapping.local}
            disabled={disabled}
            onChange={(e) => update(i, "local", e.target.value)}
          />
          <ArrowRight className="size-4 shrink-0 text-subtle" />
          <Input
            aria-label={`Path in ${remoteLabel}`}
            placeholder={`/data (${remoteLabel})`}
            className="font-mono text-[13px]"
            value={mapping.remote}
            disabled={disabled}
            onChange={(e) => update(i, "remote", e.target.value)}
          />
          <Button variant="ghost" size="icon" aria-label="Remove mapping" disabled={disabled} onClick={() => onChange(value.filter((_, j) => j !== i))}>
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      ))}
      <Button variant="ghost" size="sm" icon={<Plus className="size-3.5" />} disabled={disabled} onClick={() => onChange([...value, { local: "", remote: "" }])}>
        Add path mapping
      </Button>
    </div>
  );
}
