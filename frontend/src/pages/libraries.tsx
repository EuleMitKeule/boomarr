import { ArrowLeft, CircleAlert, FolderInput, FolderOutput, Link2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { AddFilterMenu, FilterCard } from "@/components/filter-editor";
import { Field, FieldGroup, ListField, PathField, TextField, TriStateField } from "@/components/form";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Alert, EmptyState, PageLoader } from "@/components/ui/misc";
import { useConfig } from "@/lib/config-editor";
import { outputFolder } from "@/lib/naming";
import type { Path } from "@/lib/path";

type Library = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const NEW_LIBRARY: Library = {
  name: "",
  input_path: "",
  symlink_libraries: [{ filters: [{ type: "audio_language", languages: [], mode: "any" }] }],
};

function ConfirmDelete({ name, onConfirm, onCancel }: { name: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onCancel()}
      title={`Remove library "${name}"?`}
      description="The library is removed from the configuration when you save. Existing symlinks stay on disk until you delete the output folders."
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm}>
            Remove
          </Button>
        </>
      }
    />
  );
}

export function LibrariesPage() {
  const cfg = useConfig();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState<number | null>(null);
  if (cfg.loading) return <PageLoader />;
  const libraries: Library[] = cfg.get(["libraries"]) ?? [];

  const add = () => {
    cfg.set(["libraries"], [...libraries, structuredClone(NEW_LIBRARY)]);
    navigate(`/libraries/${libraries.length}`);
  };

  return (
    <div>
      <PageHeader
        title="Libraries"
        description="Each source library can feed any number of filtered symlink libraries."
        actions={
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={add} disabled={cfg.readOnly}>
            Add library
          </Button>
        }
      />
      {libraries.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FolderInput className="size-5" />}
            title="No libraries configured"
            description="Add your movie or TV folder and choose which audio languages the filtered copies should contain."
            action={
              <Button variant="primary" icon={<Plus className="size-4" />} onClick={add} disabled={cfg.readOnly}>
                Add library
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {libraries.map((library, index) => {
            const problems = cfg.errorsBelow(["libraries", index]).length;
            return (
              <Card key={index} className="flex flex-col">
                <div className="flex items-start gap-3 px-5 pt-4">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                    <FolderInput className="size-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Link to={`/libraries/${index}`} className="truncate font-semibold hover:text-accent">
                        {library.name || "Unnamed library"}
                      </Link>
                      {problems > 0 && (
                        <Badge tone="danger">
                          <CircleAlert className="size-3" /> {problems}
                        </Badge>
                      )}
                    </div>
                    <div className="truncate font-mono text-xs text-subtle">{library.input_path || "no source folder"}</div>
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" aria-label="Edit" onClick={() => navigate(`/libraries/${index}`)}>
                      <Pencil className="size-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label="Remove" disabled={cfg.readOnly} onClick={() => setDeleting(index)}>
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
                <div className="mt-3 flex-1 space-y-1.5 px-5 pb-4">
                  {(library.symlink_libraries ?? []).map((sym: Library, i: number) => (
                    <div key={i} className="flex items-center gap-2 rounded-md bg-surface-2 px-2.5 py-1.5">
                      <Link2 className="size-3.5 shrink-0 text-subtle" />
                      <span className="truncate font-mono text-xs">{outputFolder(cfg.draft, library, sym) ?? "—"}</span>
                    </div>
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {deleting !== null && (
        <ConfirmDelete
          name={libraries[deleting]?.name || "Unnamed library"}
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            cfg.set(["libraries"], libraries.filter((_, i) => i !== deleting));
            setDeleting(null);
          }}
        />
      )}
    </div>
  );
}

function SymlinkLibraryCard({ base, index, library, remove }: { base: Path; index: number; library: Library; remove?: () => void }) {
  const cfg = useConfig();
  const path = [...base, "symlink_libraries", index];
  const sym: Library = cfg.get(path) ?? {};
  const filters: Library[] = sym.filters ?? [];
  const folder = outputFolder(cfg.draft, library, sym);
  const filterErrors = (i: number) =>
    cfg.errorsBelow([...path, "filters", i]).map((e) => `${e.loc.slice(path.length + 2).join(".") || "filter"}: ${e.msg}`);
  const ownErrors = cfg.errorsBelow(path).filter((e) => e.loc[path.length] !== "filters" || e.loc.length === path.length + 1);

  return (
    <Card>
      <CardHeader
        icon={<FolderOutput className="size-4" />}
        title={sym.name || folder?.split("/").pop() || `Output ${index + 1}`}
        description={
          <span className="font-mono text-xs">{folder ?? "Set an output folder for this library or in Settings → General"}</span>
        }
        actions={
          remove && (
            <Button variant="ghost" size="sm" icon={<Trash2 className="size-3.5" />} onClick={remove} disabled={cfg.readOnly}>
              Remove
            </Button>
          )
        }
      />
      <CardBody className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="space-y-1.5">
            <span className="text-xs text-muted">Folder name (optional)</span>
            <Input
              value={sym.name ?? ""}
              placeholder="automatic from the filters"
              disabled={cfg.readOnly}
              className="font-mono text-[13px]"
              onChange={(e) => cfg.set([...path, "name"], e.target.value === "" ? null : e.target.value)}
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs text-muted">Absolute output path (optional)</span>
            <Input
              value={sym.output_path ?? ""}
              placeholder="overrides the folder name"
              disabled={cfg.readOnly}
              className="font-mono text-[13px]"
              onChange={(e) => cfg.set([...path, "output_path"], e.target.value === "" ? null : e.target.value)}
            />
          </label>
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="text-[13px] font-medium">
              Filters <span className="font-normal text-muted">— a file must match all of them</span>
            </h4>
            <AddFilterMenu disabled={cfg.readOnly} onAdd={(f) => cfg.set([...path, "filters"], [...filters, f])} />
          </div>
          {filters.map((filter, i) => (
            <FilterCard
              key={i}
              filter={filter}
              errors={filterErrors(i)}
              disabled={cfg.readOnly}
              onChange={(f) => cfg.set([...path, "filters", i], f)}
              onRemove={filters.length > 1 ? () => cfg.set([...path, "filters"], filters.filter((_, j) => j !== i)) : undefined}
            />
          ))}
        </div>
        {ownErrors.map((e) => (
          <p key={e.loc.join(".")} className="text-xs text-danger">
            {e.msg}
          </p>
        ))}
      </CardBody>
    </Card>
  );
}

export function LibraryEditorPage() {
  const { index: raw } = useParams();
  const cfg = useConfig();
  const navigate = useNavigate();
  if (cfg.loading) return <PageLoader />;
  const index = Number(raw);
  const libraries: Library[] = cfg.get(["libraries"]) ?? [];
  const library = libraries[index];
  if (!library) return <Navigate to="/libraries" replace />;
  const base: Path = ["libraries", index];
  const symlinkLibraries: Library[] = library.symlink_libraries ?? [];
  const generalErrors = cfg.errorsBelow(base).filter((e) => e.loc.length === base.length);

  return (
    <div className="space-y-6">
      <div>
        <button type="button" onClick={() => navigate("/libraries")} className="mb-3 flex items-center gap-1 text-xs text-muted hover:text-fg">
          <ArrowLeft className="size-3.5" /> Libraries
        </button>
        <PageHeader title={library.name || "New library"} description="Changes are applied after you save. Use a dry run to preview them." />
      </div>
      {cfg.readOnly && <Alert tone="warning">The configuration file is read-only; changes cannot be saved.</Alert>}
      {generalErrors.map((e) => (
        <Alert key={e.msg} tone="danger">
          {e.msg}
        </Alert>
      ))}
      <Card>
        <CardHeader title="Source" description="The original media. It must be mounted read-only." />
        <CardBody>
          <FieldGroup>
            <TextField path={[...base, "name"]} label="Name" description="Also used for automatic folder names; renaming changes them." placeholder="Movies" />
            <PathField path={[...base, "input_path"]} label="Source folder" placeholder="/media/movies" />
            <PathField
              path={[...base, "output_path"]}
              label="Output base folder"
              description="Where the filtered libraries are created. Defaults to the global output folder."
              placeholder={cfg.get(["output_path"]) ?? "/media/boomarr"}
              nullable
            />
          </FieldGroup>
        </CardBody>
      </Card>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[15px] font-semibold">Filtered libraries</h2>
            <p className="text-[13px] text-muted">Point Plex or Jellyfin at these folders.</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            icon={<Plus className="size-3.5" />}
            disabled={cfg.readOnly}
            onClick={() =>
              cfg.set(
                [...base, "symlink_libraries"],
                [...symlinkLibraries, { filters: [{ type: "audio_language", languages: [], mode: "any" }] }],
              )
            }
          >
            Add filtered library
          </Button>
        </div>
        {symlinkLibraries.map((_, i) => (
          <SymlinkLibraryCard
            key={i}
            base={base}
            index={i}
            library={library}
            remove={symlinkLibraries.length > 1 ? () => cfg.set([...base, "symlink_libraries"], symlinkLibraries.filter((__, j) => j !== i)) : undefined}
          />
        ))}
      </div>

      <Card>
        <CardHeader title="Advanced" description="Leave empty to use the global settings." />
        <CardBody>
          <FieldGroup>
            <ListField
              path={[...base, "sidecar_extensions"]}
              label="Sidecar files"
              description="Linked next to each video, e.g. subtitles."
              placeholder=".srt, .ass"
              mono
              nullable
            />
            <ListField path={[...base, "ignore_patterns"]} label="Ignore patterns" description="Glob patterns of files to skip." placeholder="*sample*" mono nullable />
            <TriStateField path={[...base, "relative_symlinks"]} label="Relative symlinks" inheritLabel="Use global setting" />
            <Field label="Probers" description="Override the global prober chain for this library in the YAML file if needed.">
              <span className="text-[13px] text-muted">{library.probers ? `${library.probers.length} custom` : "Global"}</span>
            </Field>
          </FieldGroup>
        </CardBody>
      </Card>
    </div>
  );
}
