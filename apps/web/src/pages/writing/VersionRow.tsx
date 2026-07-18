import type { ChapterVersion, VersionSource } from "@/lib/types";
import { cn } from "@/lib/cn";

const sourceMeta: Record<VersionSource, { label: string; className: string }> = {
  user: { label: "用户手改", className: "bg-surface-subtle text-text-secondary" },
  generate: { label: "AI 生成", className: "bg-[#EFF6FF] text-info" },
  revise: { label: "AI 修改", className: "bg-[#FEF3C7] text-warning" },
  rewrite: { label: "AI 重写", className: "bg-[#F3E8FF] text-twist" },
  restore: { label: "恢复", className: "bg-surface-subtle text-text-secondary" },
  confirm: { label: "已确认", className: "bg-[#F0FDF4] text-success" },
};

export function VersionRow({
  version,
  compact = false,
  selected = false,
  onSelect,
}: {
  version: ChapterVersion;
  compact?: boolean;
  selected?: boolean;
  onSelect?: () => void;
}) {
  const meta = sourceMeta[version.source];
  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-3",
        onSelect && "cursor-pointer hover:bg-surface-subtle",
        selected && "bg-[#F0FDFA]",
      )}
      onClick={onSelect}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-semibold text-text-primary">{version.label}</span>
          <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium", meta.className)}>
            {meta.label}
          </span>
          {version.current && (
            <span className="rounded border border-primary px-1.5 py-0.5 text-[11px] font-medium text-primary">
              当前
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[12px] text-text-secondary">
          <span>{version.time}</span>
          <span>·</span>
          <span>{version.words.toLocaleString()} 字</span>
          {version.model && (
            <>
              <span>·</span>
              <span className="truncate">{version.model}</span>
            </>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {version.score !== null && (
          <span className="text-[13px] font-semibold tabular-nums text-text-primary">
            {version.score}
            <span className="text-[11px] font-normal text-text-secondary"> 分</span>
          </span>
        )}
        {!compact && (
          <button
            className="rounded-control border border-border px-2 py-1 text-[12px] text-text-secondary hover:bg-surface"
            onClick={(e) => e.stopPropagation()}
          >
            恢复
          </button>
        )}
      </div>
    </div>
  );
}
