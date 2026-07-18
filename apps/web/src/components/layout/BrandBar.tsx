import { Link } from "react-router-dom";
import { Search, Upload, Plus, Settings, X } from "lucide-react";
import { updateNewNovelDraft } from "@/lib/api";

/**
 * Global brand bar for the project list and wizard (§6). Brand on the left,
 * search + import + new + settings on the right. 52px, matches workspace top bar height.
 */
export function BrandBar({
  showActions = true,
  search = "",
  onSearchChange,
}: {
  showActions?: boolean;
  search?: string;
  onSearchChange?: (value: string) => void;
}) {
  const searchable = typeof onSearchChange === "function";

  return (
    <header className="flex h-topbar shrink-0 items-center justify-between border-b border-border bg-surface px-8">
      <Link to="/" className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-control bg-primary text-[14px] font-bold text-white">
          N
        </span>
        <span className="text-[16px] text-text-primary">Nove</span>
      </Link>

      {showActions && (
        <div className="flex items-center gap-3">
          <label className="flex h-9 w-[240px] items-center gap-2 rounded-control border border-border bg-surface-subtle px-3 focus-within:border-primary">
            <Search size={14} className="shrink-0 text-text-secondary" />
            {searchable ? (
              <>
                <input
                  value={search}
                  onChange={(event) => onSearchChange(event.target.value)}
                  placeholder="搜索项目…"
                  aria-label="搜索项目"
                  className="min-w-0 flex-1 bg-transparent text-[13px] text-text-primary outline-none placeholder:text-text-secondary"
                />
                {search && (
                  <button
                    type="button"
                    aria-label="清除搜索"
                    onClick={() => onSearchChange("")}
                    className="text-text-secondary hover:text-text-primary"
                  >
                    <X size={14} />
                  </button>
                )}
              </>
            ) : (
              <span className="text-[13px] text-text-secondary">搜索项目…</span>
            )}
          </label>
          <Link
            to="/import"
            className="flex h-9 items-center gap-1.5 rounded-control border border-border bg-surface px-3 text-[13px] text-text-primary hover:bg-surface-subtle"
          >
            <Upload size={14} />
            导入小说
          </Link>
          <Link
            to="/new/1"
            onClick={() => updateNewNovelDraft({ creation_mode: "scratch" })}
            className="flex h-9 items-center gap-1.5 rounded-control bg-primary px-3.5 text-[13px] font-semibold text-white hover:bg-primary-hover"
          >
            <Plus size={16} />
            新建小说
          </Link>
          <Link
            to="/settings"
            className="flex h-9 w-9 items-center justify-center rounded-control text-text-secondary hover:bg-surface-subtle"
            aria-label="全局设置"
            title="全局设置"
          >
            <Settings size={18} />
          </Link>
        </div>
      )}
    </header>
  );
}
