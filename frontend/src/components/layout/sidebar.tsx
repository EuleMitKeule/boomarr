import { NavLink, useLocation } from "react-router";
import { BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "../logo";
import { mainNav } from "./nav";

export function Sidebar({ version, onNavigate }: { version?: string; onNavigate?: () => void }) {
  const location = useLocation();
  return (
    <nav className="flex h-full flex-col" aria-label="Main">
      <div className="flex h-14 items-center gap-2.5 px-4">
        <Logo className="size-7" />
        <span className="text-[15px] font-semibold tracking-tight">Boomarr</span>
      </div>
      <div className="flex-1 space-y-0.5 overflow-y-auto px-2.5 py-2">
        {mainNav.map((item) => {
          const active = item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to);
          const Icon = item.icon;
          return (
            <div key={item.to}>
              <NavLink
                to={item.children ? item.children[0].to : item.to}
                onClick={onNavigate}
                className={cn(
                  "group flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13.5px] font-medium transition-colors",
                  active ? "bg-surface-3 text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
                )}
              >
                <Icon className={cn("size-4", active ? "text-accent" : "text-subtle group-hover:text-muted")} />
                {item.label}
              </NavLink>
              {item.children && active && (
                <div className="mt-0.5 mb-1.5 ml-[18px] space-y-0.5 border-l border-border pl-3">
                  {item.children.map((child) => (
                    <NavLink
                      key={child.to}
                      to={child.to}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        cn(
                          "block rounded-md px-2 py-1 text-[13px] transition-colors",
                          isActive ? "font-medium text-accent" : "text-muted hover:text-fg",
                        )
                      }
                    >
                      {child.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-subtle">
        <span className="font-mono">{version ? `v${version}` : ""}</span>
        <a
          href="https://eulemitkeule.github.io/boomarr/"
          target="_blank"
          rel="noreferrer"
          className="rounded p-1 hover:bg-surface-3 hover:text-fg"
          aria-label="Documentation"
        >
          <BookOpen className="size-4" />
        </a>
      </div>
    </nav>
  );
}
