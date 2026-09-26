import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Input } from "./ui/input";
import { Alert } from "./ui/misc";

export function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const mutation = useMutation({
    mutationFn: () => api.post("auth/password", { current, new: next }),
    onSuccess: () => {
      toast.success("Password changed; other sessions were signed out");
      onOpenChange(false);
      setCurrent("");
      setNext("");
      setConfirm("");
    },
  });
  const mismatch = confirm.length > 0 && confirm !== next;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) mutation.mutate();
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Change password" size="sm">
      <form className="space-y-3" onSubmit={submit}>
        {mutation.error && (
          <Alert tone="danger">{mutation.error instanceof ApiError ? mutation.error.message : "Failed"}</Alert>
        )}
        <label className="block space-y-1.5">
          <span className="text-[13px] font-medium">Current password</span>
          <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label className="block space-y-1.5">
          <span className="text-[13px] font-medium">New password</span>
          <Input type="password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />
        </label>
        <label className="block space-y-1.5">
          <span className="text-[13px] font-medium">Confirm new password</span>
          <Input
            type="password"
            autoComplete="new-password"
            value={confirm}
            aria-invalid={mismatch}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          {mismatch && <span className="text-xs text-danger">The passwords do not match</span>}
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={mutation.isPending} disabled={mismatch}>
            Change password
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
