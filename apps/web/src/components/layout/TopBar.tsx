import { Link } from "react-router-dom";
import { ArrowLeft, Search, Check, MoreHorizontal } from "lucide-react";
import type { ModelConfig, Novel } from "@/lib/api";
import { useApiQuery } from "@/lib/api";
import { cn } from "@/lib/cn";

type SaveState = "saving" | "saved" | "offline" | "error";

const saveMeta: Record<SaveState, { label: string; className: string }> = {
  saving: { label: "正在保存…", className: "text-text-secondary" },
  saved: { label: "已保存", className: "text-success" },
  offline: { label: "离线副本", className: "text-warning" },
  error: { label: "保存失败", className: "text-danger" },
};

function pickActiveModel(models: ModelConfig[]): ModelConfig | null {
  if (!models.length) return null;
  const byRole = (role: string) =>
    models.find((m) => (m.roles || []).includes(role) && m.status === "connected") ||
    models.find((m) => (m.roles || []).includes(role));
  return (
    byRole("写作") ||
    byRole("大纲") ||
    models.find((m) => m.status === "connected") ||
    models.find((m) => m.isDefault) ||
    models[0]
  );
}

/**
 * Workspace top bar (§8.1). Left: back + title/chapter. Center: save state.
 * Right: search, model status, more, avatar. Fixed 52px height.
 */
export function TopBar({
  novel,
  chapterLabel,
  saveState = "saved",
}: {
  novel: Novel;
  chapterLabel?: string;
  saveState?: SaveState;
}) {
  const save = saveMeta[saveState];
  const { data: models } = useApiQuery<ModelConfig[]>(
    novel.id ? `/novels/${novel.id}/models` : null,
    [],
  );
  const active = pickActiveModel(models);
  const statusDot =
    active?.status === "connected"
      ? "bg-success"
      : active?.status === "error"
        ? "bg-danger"
        : "bg-text-secondary";
  // Show model id/name only — never provider (供应商) as the primary label.
  const modelLabel = active?.modelId || active?.name || "未配置模型";

  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-2 border-b border-border bg-surface px-2 sm:px-4">
      <div className="flex h-full min-w-0 flex-1 items-center gap-2 sm:gap-3">
        <Link
          to="/"
          className="flex items-center gap-1.5 text-text-secondary hover:text-text-primary"
        >
          <ArrowLeft size={18} />
          <span className="hidden text-[13px] sm:inline">项目列表</span>
        </Link>
        <div className="hidden h-5 w-px bg-border sm:block" />
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[14px] font-semibold text-text-primary">{novel.title}</span>
          {chapterLabel && (
            <span className="hidden truncate text-[13px] text-text-secondary md:inline">· {chapterLabel}</span>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5 text-[13px]">
        <Check size={14} className={save.className} />
        <span className={save.className}>{save.label}</span>
      </div>

      <div className="flex min-w-0 flex-1 items-center justify-end gap-2 sm:gap-3">
        <div className="hidden h-9 w-[220px] items-center gap-2 rounded-control border border-border bg-surface-subtle px-3 md:flex">
          <Search size={14} className="text-text-secondary" />
          <span className="text-[13px] text-text-secondary">搜索本书…</span>
        </div>
        <Link
          to={novel.id ? `/novel/${novel.id}/settings` : "/"}
          className="flex max-w-[180px] items-center gap-1.5 rounded-control px-1.5 py-1 hover:bg-surface-subtle"
          title={
            active
              ? [active.name, active.modelId].filter(Boolean).join(" · ")
              : "前往配置模型"
          }
        >
          <span className={cn("h-2 w-2 shrink-0 rounded-full", statusDot)} aria-hidden />
          <span className="hidden truncate text-[13px] text-text-secondary lg:inline">{modelLabel}</span>
        </Link>
        <button
          className="hidden h-9 w-9 items-center justify-center rounded-control text-text-secondary hover:bg-surface-subtle sm:flex"
          aria-label="更多菜单"
        >
          <MoreHorizontal size={18} />
        </button>
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-[12px] font-semibold text-white">
          作
        </div>
      </div>
    </header>
  );
}
