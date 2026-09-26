import { Lock, Plus, X } from "lucide-react";
import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { useConfig } from "@/lib/config-editor";
import type { Path } from "@/lib/path";
import { cn } from "@/lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input, Select } from "./ui/input";
import { Tooltip } from "./ui/misc";
import { Switch } from "./ui/switch";
import { PathPicker } from "./path-picker";

const SECRET_PREFIX = "__secret__:";

interface FieldProps {
  label: ReactNode;
  description?: ReactNode;
  error?: string;
  locked?: boolean;
  htmlFor?: string;
  children: ReactNode;
  inline?: boolean;
  className?: string;
}

/** Label + description on the left, control on the right (stacked on mobile). */
export function Field({ label, description, error, locked, htmlFor, children, inline, className }: FieldProps) {
  return (
    <div
      className={cn(
        "grid gap-x-8 gap-y-2 py-4 first:pt-0 last:pb-0",
        inline ? "grid-cols-[1fr_auto] items-center" : "grid-cols-1 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]",
        className,
      )}
    >
      <div className="min-w-0">
        <label htmlFor={htmlFor} className="flex items-center gap-2 text-[13px] font-medium">
          {label}
          {locked && (
            <Tooltip content="Set by an environment variable or command line option; change it there.">
              <Badge tone="info">
                <Lock className="size-3" /> env
              </Badge>
            </Tooltip>
          )}
        </label>
        {description && <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{description}</p>}
      </div>
      <div className="min-w-0">
        {children}
        {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
      </div>
    </div>
  );
}

export function FieldGroup({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("divide-y divide-border", className)}>{children}</div>;
}

interface BoundProps {
  path: Path;
  label: ReactNode;
  description?: ReactNode;
}

function useBound(path: Path) {
  const cfg = useConfig();
  const id = useId();
  const locked = cfg.envLocked(path);
  return {
    id,
    value: cfg.get(path),
    set: (value: unknown) => cfg.set(path, value),
    error: cfg.error(path),
    locked,
    disabled: cfg.readOnly || locked,
  };
}

export function TextField({
  path,
  label,
  description,
  placeholder,
  nullable,
  mono,
}: BoundProps & { placeholder?: string; nullable?: boolean; mono?: boolean }) {
  const f = useBound(path);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      <Input
        id={f.id}
        value={f.value ?? ""}
        placeholder={placeholder}
        disabled={f.disabled}
        aria-invalid={!!f.error}
        className={cn(mono && "font-mono text-[13px]")}
        onChange={(e) => f.set(nullable && e.target.value === "" ? null : e.target.value)}
      />
    </Field>
  );
}

export function NumberField({
  path,
  label,
  description,
  min,
  max,
  step,
  suffix,
  nullable,
  placeholder,
}: BoundProps & { min?: number; max?: number; step?: number; suffix?: string; nullable?: boolean; placeholder?: string }) {
  const f = useBound(path);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      <div className="flex max-w-56 items-center gap-2">
        <Input
          id={f.id}
          type="number"
          inputMode="decimal"
          value={f.value ?? ""}
          min={min}
          max={max}
          step={step}
          placeholder={placeholder}
          disabled={f.disabled}
          aria-invalid={!!f.error}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") f.set(nullable ? null : undefined);
            else f.set(Number(raw));
          }}
        />
        {suffix && <span className="shrink-0 text-xs text-muted">{suffix}</span>}
      </div>
    </Field>
  );
}

export function SwitchField({ path, label, description }: BoundProps) {
  const f = useBound(path);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id} inline>
      <Switch id={f.id} checked={!!f.value} onCheckedChange={f.set} disabled={f.disabled} />
    </Field>
  );
}

export function TriStateField({
  path,
  label,
  description,
  inheritLabel,
}: BoundProps & { inheritLabel: string }) {
  const f = useBound(path);
  const value = f.value === true ? "true" : f.value === false ? "false" : "";
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      <Select
        id={f.id}
        value={value}
        disabled={f.disabled}
        onChange={(e) => f.set(e.target.value === "" ? null : e.target.value === "true")}
      >
        <option value="">{inheritLabel}</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </Select>
    </Field>
  );
}

export function SelectField({
  path,
  label,
  description,
  options,
}: BoundProps & { options: { value: string; label: string }[] }) {
  const f = useBound(path);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      <Select id={f.id} value={f.value ?? ""} disabled={f.disabled} onChange={(e) => f.set(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function SecretField({ path, label, description, placeholder }: BoundProps & { placeholder?: string }) {
  const f = useBound(path);
  const masked = typeof f.value === "string" && f.value.startsWith(SECRET_PREFIX);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      {masked ? (
        <div className="flex items-center gap-2">
          <Input id={f.id} value="••••••••••••" disabled className="font-mono tracking-widest" readOnly />
          <Button variant="outline" disabled={f.disabled} onClick={() => f.set("")}>
            Change
          </Button>
        </div>
      ) : (
        <Input
          id={f.id}
          type="password"
          autoComplete="new-password"
          value={f.value ?? ""}
          placeholder={placeholder}
          disabled={f.disabled}
          aria-invalid={!!f.error}
          onChange={(e) => f.set(e.target.value === "" ? null : e.target.value)}
        />
      )}
    </Field>
  );
}

export function PathField({
  path,
  label,
  description,
  placeholder,
  nullable,
}: BoundProps & { placeholder?: string; nullable?: boolean }) {
  const f = useBound(path);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      <PathPicker
        id={f.id}
        value={f.value ?? ""}
        placeholder={placeholder}
        disabled={f.disabled}
        invalid={!!f.error}
        onChange={(value) => f.set(nullable && value === "" ? null : value)}
      />
    </Field>
  );
}

/** Editable list of short strings shown as chips. */
export function TagInput({
  value,
  onChange,
  placeholder,
  disabled,
  mono,
  id,
  normalize,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  mono?: boolean;
  id?: string;
  normalize?: (value: string) => string;
}) {
  const [text, setText] = useState("");
  const add = () => {
    const items = text
      .split(",")
      .map((t) => (normalize ? normalize(t.trim()) : t.trim()))
      .filter(Boolean)
      .filter((t) => !value.includes(t));
    if (items.length) onChange([...value, ...items]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  };
  return (
    <div
      className={cn(
        "flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-border-strong bg-surface-2 px-2 py-1.5",
        "focus-within:border-accent focus-within:ring-2 focus-within:ring-ring/40",
        disabled && "opacity-60",
      )}
    >
      {value.map((item) => (
        <span
          key={item}
          className={cn(
            "inline-flex items-center gap-1 rounded bg-surface-3 py-0.5 pr-1 pl-2 text-xs",
            mono && "font-mono",
          )}
        >
          {item}
          {!disabled && (
            <button
              type="button"
              className="rounded p-0.5 text-subtle hover:bg-border-strong hover:text-fg"
              onClick={() => onChange(value.filter((v) => v !== item))}
              aria-label={`Remove ${item}`}
            >
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
      <input
        id={id}
        value={text}
        disabled={disabled}
        placeholder={value.length ? "" : placeholder}
        className="min-w-24 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-subtle"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
      />
    </div>
  );
}

export function ListField({
  path,
  label,
  description,
  placeholder,
  mono,
  nullable,
  normalize,
}: BoundProps & { placeholder?: string; mono?: boolean; nullable?: boolean; normalize?: (value: string) => string }) {
  const f = useBound(path);
  const inherited = nullable && (f.value === null || f.value === undefined);
  return (
    <Field label={label} description={description} error={f.error} locked={f.locked} htmlFor={f.id}>
      {inherited ? (
        <Button variant="outline" size="sm" icon={<Plus className="size-3.5" />} disabled={f.disabled} onClick={() => f.set([])}>
          Override global setting
        </Button>
      ) : (
        <div className="space-y-1.5">
          <TagInput
            id={f.id}
            value={(f.value as string[] | undefined) ?? []}
            onChange={f.set}
            placeholder={placeholder}
            disabled={f.disabled}
            mono={mono}
            normalize={normalize}
          />
          {nullable && (
            <button type="button" className="text-xs text-muted hover:text-fg" onClick={() => f.set(null)}>
              Use global setting
            </button>
          )}
        </div>
      )}
    </Field>
  );
}
