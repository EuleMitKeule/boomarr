import { useQueryClient } from "@tanstack/react-query";
import { ScanSearch, Tv } from "lucide-react";
import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { AppLayout } from "./components/layout/app-layout";
import { PageLoader } from "./components/ui/misc";
import { AUTH_QUERY, useAuthState } from "./hooks/use-auth";
import { setUnauthorizedHandler } from "./lib/api";
import { ActivityPage } from "./pages/activity";
import { LoginPage, SetupPage } from "./pages/auth";
import { DashboardPage } from "./pages/dashboard";
import { LibrariesPage, LibraryEditorPage } from "./pages/libraries";
import { GeneralSettings } from "./pages/settings/general";
import { MediaServerSettings, ProberSettings } from "./pages/settings/integrations";
import { LoggingSettings } from "./pages/settings/logging";
import { NotificationSettings } from "./pages/settings/notifications";
import { ScanningSettings } from "./pages/settings/scanning";
import { SecuritySettings } from "./pages/settings/security";
import { ServerSettings } from "./pages/settings/server";
import { BackupPage, HealthPage, LogsPage, StatusPage } from "./pages/system";

function RequireAuth() {
  const auth = useAuthState();
  const location = useLocation();
  if (auth.isLoading || !auth.data) return <PageLoader />;
  if (auth.data.setup_required) return <Navigate to="/setup" replace />;
  if (!auth.data.user) {
    const next = location.pathname + location.search;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <AppLayout />;
}

function NotFound() {
  return (
    <div className="py-24 text-center">
      <p className="font-mono text-sm text-accent">404</p>
      <h1 className="mt-2 text-xl font-semibold">Page not found</h1>
    </div>
  );
}

export function App() {
  const client = useQueryClient();
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      void client.invalidateQueries({ queryKey: AUTH_QUERY });
      navigate("/login", { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [client, navigate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<DashboardPage />} />
        <Route path="libraries" element={<LibrariesPage />} />
        <Route path="libraries/:index" element={<LibraryEditorPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="settings" element={<Navigate to="/settings/general" replace />} />
        <Route path="settings/general" element={<GeneralSettings />} />
        <Route path="settings/scanning" element={<ScanningSettings />} />
        <Route path="settings/probers" element={<ProberSettings icon={<ScanSearch className="size-5" />} />} />
        <Route path="settings/media-servers" element={<MediaServerSettings icon={<Tv className="size-5" />} />} />
        <Route path="settings/notifications" element={<NotificationSettings />} />
        <Route path="settings/security" element={<SecuritySettings />} />
        <Route path="settings/server" element={<ServerSettings />} />
        <Route path="settings/logging" element={<LoggingSettings />} />
        <Route path="system" element={<Navigate to="/system/status" replace />} />
        <Route path="system/status" element={<StatusPage />} />
        <Route path="system/health" element={<HealthPage />} />
        <Route path="system/logs" element={<LogsPage />} />
        <Route path="system/backup" element={<BackupPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
