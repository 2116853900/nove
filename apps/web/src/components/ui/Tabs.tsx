import { cn } from "@/lib/cn";

export interface TabItem {
  key: string;
  label: string;
}

// Underline-style tabs used in the right panel (§8.5) and bible/plot pages.
export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn("flex items-stretch overflow-x-auto border-b border-border", className)}
    >
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.key)}
            className={cn(
              "relative h-11 shrink-0 whitespace-nowrap px-4 text-[14px] transition-colors duration-150",
              active
                ? "text-text-primary font-medium"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {item.label}
            {active && (
              <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-primary animate-nove-tab-indicator" />
            )}
          </button>
        );
      })}
    </div>
  );
}

// Pill-style segmented control used for list filters (§6) and timeline views.
export function SegControl({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            className={cn(
              "rounded-control border px-3 py-1.5 text-[12px] nove-interactive",
              active
                ? "border-border bg-surface-subtle font-medium text-text-primary"
                : "border-transparent text-text-secondary hover:bg-surface-subtle",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
