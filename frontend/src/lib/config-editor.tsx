import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { api, ApiError, type FieldError } from "./api";
import { getIn, pathKey, samePath, setIn, startsWith, type Path } from "./path";
import type { ConfigData, ConfigDocument } from "./types";

interface ConfigEditor {
  loading: boolean;
  document: ConfigDocument | undefined;
  draft: ConfigData;
  dirty: boolean;
  saving: boolean;
  readOnly: boolean;
  errors: FieldError[];
  get: (path: Path) => any; // eslint-disable-line @typescript-eslint/no-explicit-any
  set: (path: Path, value: unknown) => void;
  update: (path: Path, fn: (value: any) => unknown) => void; // eslint-disable-line @typescript-eslint/no-explicit-any
  error: (path: Path) => string | undefined;
  errorsBelow: (path: Path) => FieldError[];
  envLocked: (path: Path) => boolean;
  save: () => Promise<boolean>;
  reset: () => void;
}

const Context = createContext<ConfigEditor | null>(null);

export const CONFIG_QUERY = ["config"] as const;

export function ConfigEditorProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: CONFIG_QUERY,
    queryFn: () => api.get<ConfigDocument>("config"),
  });
  const [draft, setDraft] = useState<ConfigData | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const saved = query.data?.config;
  const current = draft ?? saved ?? {};
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(saved);

  useEffect(() => {
    if (draft !== null && !dirty) setDraft(null);
  }, [draft, dirty]);

  const mutation = useMutation({
    mutationFn: (config: ConfigData) =>
      api.put<ConfigDocument>("config", { config }, { "If-Match": `"${query.data?.etag ?? ""}"` }),
    onSuccess: (doc) => {
      client.setQueryData(CONFIG_QUERY, doc);
      setDraft(null);
      setErrors([]);
      void client.invalidateQueries({ queryKey: ["dashboard"] });
      void client.invalidateQueries({ queryKey: ["health"] });
      if (doc.restart_required) {
        toast.warning("Saved. Restart Boomarr to apply the web server settings.");
      } else {
        toast.success("Settings saved and applied");
      }
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setErrors(err.errors);
        if (err.status === 409) {
          toast.error(err.message, {
            action: { label: "Reload", onClick: () => void client.invalidateQueries({ queryKey: CONFIG_QUERY }) },
          });
          return;
        }
        toast.error(err.errors.length ? "Please fix the highlighted fields" : err.message);
      } else {
        toast.error("Saving failed");
      }
    },
  });

  const set = useCallback(
    (path: Path, value: unknown) => {
      setDraft((prev) => setIn(prev ?? saved ?? {}, path, value));
      setErrors((prev) => prev.filter((e) => !samePath(e.loc, path)));
    },
    [saved],
  );

  const value = useMemo<ConfigEditor>(() => {
    const envOverrides = new Set(query.data?.env_overrides ?? []);
    return {
      loading: query.isLoading,
      document: query.data,
      draft: current,
      dirty,
      saving: mutation.isPending,
      readOnly: query.data ? !query.data.writable : true,
      errors,
      get: (path) => getIn(current, path),
      set,
      update: (path, fn) => set(path, fn(getIn(current, path))),
      error: (path) => errors.find((e) => samePath(e.loc, path))?.msg,
      errorsBelow: (path) => errors.filter((e) => startsWith(e.loc, path)),
      envLocked: (path) => envOverrides.has(pathKey(path)),
      save: async () => {
        try {
          await mutation.mutateAsync(current);
          return true;
        } catch {
          return false;
        }
      },
      reset: () => {
        setDraft(null);
        setErrors([]);
      },
    };
  }, [query.data, query.isLoading, current, dirty, mutation, errors, set]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useConfig(): ConfigEditor {
  const value = useContext(Context);
  if (!value) throw new Error("useConfig outside of ConfigEditorProvider");
  return value;
}
