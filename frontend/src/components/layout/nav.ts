import {
  Activity,
  Bell,
  Cable,
  Database,
  FileText,
  FolderTree,
  HeartPulse,
  Info,
  LayoutDashboard,
  type LucideIcon,
  Radar,
  ScanSearch,
  Server,
  Settings,
  Settings2,
  Shield,
  Timer,
  Tv,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  description?: string;
}

export interface NavSection {
  to: string;
  label: string;
  icon: LucideIcon;
  children?: NavItem[];
}

export const settingsNav: NavItem[] = [
  { to: "/settings/general", label: "General", icon: Settings2, description: "Paths, permissions and link behaviour" },
  { to: "/settings/scanning", label: "Scanning", icon: Timer, description: "Schedule, debounce and the removal guard" },
  { to: "/settings/probers", label: "Probers", icon: ScanSearch, description: "How audio languages are detected" },
  { to: "/settings/media-servers", label: "Media servers", icon: Tv, description: "Refresh Plex, Jellyfin and Emby" },
  { to: "/settings/notifications", label: "Notifications", icon: Bell, description: "Apprise notification targets" },
  { to: "/settings/security", label: "Security", icon: Shield, description: "Login, single sign-on and API key" },
  { to: "/settings/server", label: "Web server", icon: Server, description: "Port, URL base and reverse proxies" },
  { to: "/settings/logging", label: "Logging & data", icon: Database, description: "Log files and the probe cache" },
];

export const systemNav: NavItem[] = [
  { to: "/system/status", label: "Status", icon: Info },
  { to: "/system/health", label: "Health", icon: HeartPulse },
  { to: "/system/logs", label: "Logs", icon: FileText },
  { to: "/system/backup", label: "Backup", icon: Cable },
];

export const mainNav: NavSection[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/libraries", label: "Libraries", icon: FolderTree },
  { to: "/activity", label: "Activity", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings, children: settingsNav },
  { to: "/system", label: "System", icon: Radar, children: systemNav },
];
