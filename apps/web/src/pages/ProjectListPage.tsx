import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Archive, Download, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { BrandBar } from "@/components/layout/BrandBar";
import { SegControl } from "@/components/ui/Tabs";
import { apiRequest, updateNewNovelDraft, useApiQuery, type Novel } from "@/lib/api";
import { cn } from "@/lib/cn";

const filters = [
  { key: "all", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "archived", label: "已归档" },
];

// Column widths mirror the exported table header (.design-export/project-list.html).
const cols =
  "grid grid-cols-[minmax(220px,1fr)_120px_140px_120px_100px_160px_40px] items-center";

function updatedLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const minutes = Math.round((now.getTime() - date.getTime()) / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  if (date.toDateString() === now.toDateString()) {
    return `今天 ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return `昨天 ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
  }
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

function matchesSearch(novel: Novel, query: string) {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  const haystack = [novel.title, novel.genre, novel.coreIdea ?? ""]
    .join(" ")
    .toLocaleLowerCase();
  return q.split(/\s+/).every((token) => haystack.includes(token));
}

export function ProjectListPage() {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const navigate = useNavigate();
  const { data: novels, loading, error, refetch } = useApiQuery<Novel[]>("/novels", []);

  useEffect(() => {
    if (!menu) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("[data-novel-menu]")) return;
      setMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenu(null);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const updateNovel = async (novel: Novel, values: Record<string, unknown>) => {
    setActionError(null);
    await apiRequest(`/novels/${novel.id}`, { method: "PATCH", body: JSON.stringify(values) });
    setMenu(null);
    await refetch();
  };
  const renameNovel = async (novel: Novel) => {
    const title = window.prompt("输入新的项目名称", novel.title)?.trim();
    if (title && title !== novel.title) await updateNovel(novel, { title });
  };
  const deleteNovel = async (novel: Novel) => {
    let needConfirm = true;
    try {
      const prefs = JSON.parse(localStorage.getItem("nove:global-prefs") || "{}");
      if (prefs.confirmBeforeDelete === false) needConfirm = false;
    } catch {
      /* default confirm */
    }
    if (
      needConfirm &&
      !window.confirm(`确定永久删除《${novel.title}》及其所有章节、版本和设定吗？`)
    ) {
      return;
    }
    setActionError(null);
    await apiRequest(`/novels/${novel.id}`, { method: "DELETE" });
    setMenu(null);
    await refetch();
  };
  const exportNovel = async (novel: Novel, format: "markdown" | "txt") => {
    setActionError(null);
    try {
      const key =
        (import.meta.env.VITE_API_KEY as string | undefined) ||
        localStorage.getItem("nove:api-key") ||
        "";
      const res = await fetch(`/api/novels/${novel.id}/export?format=${format}`, {
        headers: {
          Accept: format === "txt" ? "text/plain" : "text/markdown",
          ...(key ? { "X-API-Key": key } : {}),
        },
      });
      if (!res.ok) throw new Error("导出失败");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${novel.title}.${format === "txt" ? "txt" : "md"}`;
      a.click();
      URL.revokeObjectURL(url);
      setMenu(null);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "导出失败");
    }
  };

  const visibleNovels = useMemo(() => {
    return novels.filter((novel) => {
      if (filter === "archived" && !novel.archived) return false;
      if (filter === "active" && novel.archived) return false;
      return matchesSearch(novel, search);
    });
  }, [novels, filter, search]);

  const emptyMessage = (() => {
    if (search.trim()) return `没有匹配「${search.trim()}」的项目`;
    if (filter === "archived") return "还没有已归档项目";
    if (filter === "active") return "还没有进行中的项目";
    return "还没有项目";
  })();

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <BrandBar search={search} onSearchChange={setSearch} />
      <div className="flex w-full flex-1 flex-col overflow-y-auto px-8 py-7">
        <div className="flex items-center justify-between pb-4">
          <h1 className="text-[20px] text-text-primary">
            最近项目
            {!loading && (
              <span className="ml-2 text-[13px] font-normal text-text-secondary">
                {visibleNovels.length}
                {search.trim() || filter !== "all" ? ` / ${novels.length}` : ""}
              </span>
            )}
          </h1>
          <SegControl items={filters} value={filter} onChange={setFilter} />
        </div>

        <div className={cn(cols, "h-9 border-b border-border px-4")}>
          <span className="text-assist font-medium text-text-secondary">标题</span>
          <span className="text-assist font-medium text-text-secondary">类型</span>
          <span className="text-assist font-medium text-text-secondary">章节进度</span>
          <span className="text-assist font-medium text-text-secondary">字数</span>
          <span className="text-assist font-medium text-text-secondary">待检查</span>
          <span className="text-assist font-medium text-text-secondary">更新时间</span>
          <span />
        </div>

        {loading && (
          <p className="px-4 py-8 text-[13px] text-text-secondary animate-nove-pulse">
            正在加载项目…
          </p>
        )}
        {error && <p className="px-4 py-8 text-[13px] text-danger">无法连接后端：{error}</p>}
        {actionError && (
          <p className="px-4 py-2 text-[13px] text-danger" role="alert">
            {actionError}
          </p>
        )}
        {!loading && !error && visibleNovels.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 px-4 py-16 animate-nove-fade-in">
            <p className="text-[14px] text-text-secondary">{emptyMessage}</p>
            {search.trim() ? (
              <button
                type="button"
                onClick={() => setSearch("")}
                className="rounded-control border border-border bg-surface px-4 py-2 text-[13px] text-text-primary hover:bg-surface-subtle"
              >
                清除搜索
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  updateNewNovelDraft({ creation_mode: "scratch" });
                  navigate("/new/1");
                }}
                className="rounded-control bg-primary px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-primary-hover"
              >
                新建小说
              </button>
            )}
          </div>
        )}
        {visibleNovels.map((n, i) => (
          <div
            key={n.id}
            onClick={() => navigate(`/novel/${n.id}/write`)}
            onKeyDown={(event) => {
              if (event.key === "Enter") navigate(`/novel/${n.id}/write`);
            }}
            role="link"
            tabIndex={0}
            className={cn(
              cols,
              "h-[52px] border-b border-border px-4 text-left transition-colors duration-150 hover:bg-surface-subtle animate-nove-fade-up",
            )}
            style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
          >
            <span className="truncate pr-3 text-[14px] font-semibold text-text-primary">
              {n.title}
              {n.archived && (
                <span className="ml-2 rounded bg-surface-subtle px-1.5 py-0.5 text-[11px] font-medium text-text-secondary">
                  已归档
                </span>
              )}
            </span>
            <span className="text-[13px] text-text-secondary">{n.genre}</span>
            <span className="text-[13px] text-text-primary">
              {n.progress.done} / {n.progress.total}
            </span>
            <span className="text-[13px] text-text-primary">{n.words.toLocaleString()}</span>
            <span>
              {n.pendingAudits > 0 ? (
                <span className="inline-flex items-center rounded px-2 py-0.5 text-[12px] font-semibold text-warning bg-[#FEF3C7]">
                  {n.pendingAudits}
                </span>
              ) : (
                <span className="text-[13px] text-text-secondary">—</span>
              )}
            </span>
            <span className="whitespace-nowrap text-[13px] text-text-secondary">
              {updatedLabel(n.updatedLabel)}
            </span>
            <span className="relative" data-novel-menu>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setMenu(menu === n.id ? null : n.id);
                }}
                className="flex h-8 w-8 items-center justify-center rounded-control text-text-secondary hover:bg-border/50"
                aria-label={`${n.title} 更多操作`}
                aria-expanded={menu === n.id}
              >
                <MoreHorizontal size={16} />
              </button>
              {menu === n.id && (
                <span className="absolute right-0 top-9 z-20 flex w-36 flex-col border border-border bg-surface py-1 shadow-lg animate-nove-pop">
                  <MenuAction
                    icon={<Pencil size={14} />}
                    label="重命名"
                    onClick={() => void renameNovel(n)}
                  />
                  <MenuAction
                    icon={<Download size={14} />}
                    label="导出 Markdown"
                    onClick={() => void exportNovel(n, "markdown")}
                  />
                  <MenuAction
                    icon={<Download size={14} />}
                    label="导出 TXT"
                    onClick={() => void exportNovel(n, "txt")}
                  />
                  <MenuAction
                    icon={<Archive size={14} />}
                    label={n.archived ? "取消归档" : "归档"}
                    onClick={() => void updateNovel(n, { archived: !n.archived })}
                  />
                  <MenuAction
                    danger
                    icon={<Trash2 size={14} />}
                    label="永久删除"
                    onClick={() => void deleteNovel(n)}
                  />
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MenuAction({
  icon,
  label,
  onClick,
  danger = false,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      className={cn(
        "flex items-center gap-2 px-3 py-2 text-left text-[13px] hover:bg-surface-subtle",
        danger ? "text-danger" : "text-text-primary",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
