import { NavLink, useParams } from "react-router-dom";
import { Users, MapPin, Flag, Package, Scale } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

interface BibleSection {
  slug: string;
  label: string;
  icon: LucideIcon;
}

const sections: BibleSection[] = [
  { slug: "characters", label: "人物", icon: Users },
  { slug: "locations", label: "地点", icon: MapPin },
  { slug: "factions", label: "势力", icon: Flag },
  { slug: "items", label: "物品", icon: Package },
  { slug: "world-rules", label: "世界规则", icon: Scale },
];

/** Secondary nav for the story-bible sections (§12). */
export function BibleSubNav() {
  const { id } = useParams();
  return (
    <div className="flex items-center gap-1 overflow-x-auto border-b border-border bg-surface px-3 sm:px-4">
      <span className="mr-2 shrink-0 whitespace-nowrap py-3 text-[13px] font-semibold text-text-primary sm:mr-3">故事圣经</span>
      {sections.map((s) => {
        const Icon = s.icon;
        return (
          <NavLink
            key={s.slug}
            to={`/novel/${id}/bible/${s.slug}`}
            className={({ isActive }) =>
              cn(
                "relative flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 py-3 text-[13px] transition-colors",
                isActive
                  ? "font-medium text-text-primary"
                  : "text-text-secondary hover:text-text-primary",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon size={15} />
                {s.label}
                {isActive && (
                  <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
                )}
              </>
            )}
          </NavLink>
        );
      })}
    </div>
  );
}
