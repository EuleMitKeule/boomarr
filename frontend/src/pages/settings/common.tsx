import type { ReactNode } from "react";
import { useLocation } from "react-router";
import { settingsNav } from "@/components/layout/nav";
import { PageHeader } from "@/components/page-header";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Alert, PageLoader } from "@/components/ui/misc";
import { useConfig } from "@/lib/config-editor";
import { FieldGroup } from "@/components/form";

export function SettingsPage({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  const cfg = useConfig();
  const location = useLocation();
  const meta = settingsNav.find((n) => location.pathname.startsWith(n.to));
  if (cfg.loading) return <PageLoader />;
  return (
    <div className="space-y-6">
      <PageHeader title={meta?.label ?? "Settings"} description={meta?.description} actions={actions} />
      {cfg.readOnly && (
        <Alert tone="warning" title="Read-only configuration">
          {cfg.document?.path} cannot be written (for example a Kubernetes ConfigMap). Change the settings at their source.
        </Alert>
      )}
      {children}
    </div>
  );
}

export function Section({ title, description, children, actions }: { title: ReactNode; description?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <Card>
      <CardHeader title={title} description={description} actions={actions} />
      <CardBody>
        <FieldGroup>{children}</FieldGroup>
      </CardBody>
    </Card>
  );
}
