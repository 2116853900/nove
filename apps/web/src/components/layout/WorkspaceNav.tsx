import { NavLink, useParams, useLocation } from "react-router-dom";
import {
  PenLine,
  ListTree,
  BookMarked,
  GitBranch,
  ShieldCheck,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  // match this path prefix as active (for nested sections like bible/plot)
  matchPrefix?: string;
}

/**
 * Vertical module switcher for the novel workspace (§3.2). Sits between the top
 * bar and the three-column body. Icons + text, 44px click targets.
 */
export function WorkspaceNav() {
  const { id } = useParams();
  const routerLocation = useLocation();
  const base = `/novel/${id}`;

  const items: NavItem[] = [
    { to: `${base}/write`, label: "写作", icon: PenLine },
    { to: `${base}/outline`, label: "大纲", icon: ListTree },
    { to: `${base}/bible/characters`, label: "故事圣经", icon: BookMarked, matchPrefix: `${base}/bible` },
    { to: `${base}/plot`, label: "剧情", icon: GitBranch, matchPrefix: `${base}/plot` },
    { to: `${base}/audit`, label: "质量检查", icon: ShieldCheck },
    { to: `${base}/settings`, label: "项目设置", icon: Settings },
  ];

  return (
    <nav
      aria-label="工作区导航"
      className="order-2 flex h-14 w-full shrink-0 flex-row items-center justify-around border-t border-border bg-surface md:order-none md:h-auto md:w-14 md:flex-col md:justify-start md:gap-1 md:border-r md:border-t-0 md:py-3"
    >
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => {
              const active =
                isActive ||
                (item.matchPrefix ? routerLocation.pathname.startsWith(item.matchPrefix) : false);
              return cn(
                "group flex h-14 w-full max-w-16 flex-col items-center justify-center gap-1 rounded-control nove-interactive md:w-14",
                active
                  ? "text-primary"
                  : "text-text-secondary hover:bg-surface-subtle hover:text-text-primary",
              );
            }}
          >
            {({ isActive }) => {
              const active =
                isActive ||
                (item.matchPrefix ? routerLocation.pathname.startsWith(item.matchPrefix) : false);
              return (
                <>
                  <Icon size={18} className={active ? "text-primary" : ""} />
                  <span className="text-[11px] leading-none">{item.label}</span>
                </>
              );
            }}
          </NavLink>
        );
      })}
    </nav>
  );
}
