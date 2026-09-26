import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Folder, FolderOpen, HardDrive } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Input } from "./ui/input";
import { Alert, Spinner } from "./ui/misc";

interface Listing {
  path: string;
  parent: string | null;
  writable: boolean;
  entries: { name: string; path: string }[];
}

function Browser({ start, onPick, onCancel }: { start: string; onPick: (path: string) => void; onCancel: () => void }) {
  const [path, setPath] = useState(start || "/");
  const query = useQuery({
    queryKey: ["filesystem", path],
    queryFn: () => api.get<Listing>(`filesystem?path=${encodeURIComponent(path)}`),
    retry: false,
  });
  const listing = query.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          aria-label="Parent directory"
          disabled={!listing?.parent}
          onClick={() => listing?.parent && setPath(listing.parent)}
        >
          <ArrowUp className="size-4" />
        </Button>
        <Input
          value={path}
          className="font-mono text-[13px]"
          onChange={(e) => setPath(e.target.value || "/")}
          aria-label="Current directory"
        />
      </div>
      <div className="h-72 overflow-y-auto rounded-lg border border-border bg-surface-2">
        {query.isLoading && (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        )}
        {query.error && (
          <div className="p-3">
            <Alert tone="danger">{query.error instanceof ApiError ? query.error.message : "Cannot read directory"}</Alert>
          </div>
        )}
        {listing && listing.entries.length === 0 && (
          <p className="p-4 text-center text-[13px] text-muted">No sub directories</p>
        )}
        {listing?.entries.map((entry) => (
          <button
            key={entry.path}
            type="button"
            className="flex w-full items-center gap-2.5 border-b border-border/60 px-3 py-2 text-left text-[13px] last:border-0 hover:bg-surface-3"
            onClick={() => setPath(entry.path)}
          >
            <Folder className="size-4 shrink-0 text-accent" />
            <span className="truncate">{entry.name}</span>
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs text-muted">
          <HardDrive className="size-3.5" />
          {listing ? (listing.writable ? "Writable" : "Read-only") : "…"}
        </span>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!listing} onClick={() => listing && onPick(listing.path)}>
            Select this folder
          </Button>
        </div>
      </div>
    </div>
  );
}

export function PathPicker({
  id,
  value,
  onChange,
  placeholder,
  disabled,
  invalid,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={invalid}
        className="font-mono text-[13px]"
        onChange={(e) => onChange(e.target.value)}
      />
      <Button variant="outline" size="icon" aria-label="Browse" disabled={disabled} onClick={() => setOpen(true)}>
        <FolderOpen className="size-4" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title="Choose a folder" description="Paths as seen by Boomarr (inside the container).">
        {open && (
          <Browser
            start={value}
            onCancel={() => setOpen(false)}
            onPick={(path) => {
              onChange(path);
              setOpen(false);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}
