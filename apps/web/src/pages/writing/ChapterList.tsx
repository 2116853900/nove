import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  BookMarked,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  GitBranch,
  ListTree,
  Lock,
  Loader2,
  PanelLeftClose,
  PenLine,
  Plus,
  ShieldCheck,
} from "lucide-react";
import type { Chapter, OutlineNode } from "@/lib/api";
import { useApiQuery } from "@/lib/api";
import { chapterStatusMeta } from "@/components/ui/status";
import { cn } from "@/lib/cn";

const tabs = [
  { key: "chapters", label: "章节", icon: PenLine },
  { key: "outline", label: "大纲", icon: ListTree },
] as const;

const kindIcon = {
  volume: BookMarked,
  arc: GitBranch,
  chapter: FileText,
  scene: FileText,
} as const;

const kindLabel = {
  volume: "卷",
  arc: "弧",
  chapter: "章",
  scene: "场",
} as const;

/**
 * Left column of the workspace (§8.2):
 * - 章节：扁平写作列表（进度/字数/分数）
 * - 大纲：层级树（目标/亮点摘要），与章节列表视觉与信息不同
 */
export function ChapterList({
  activeId,
  chapters,
  onSelect,
  onCreate,
  onAuditPending,
  bulkAudit,
  onCollapse,
}: {
  activeId: string;
  chapters: Chapter[];
  onSelect: (id: string) => void;
  onCreate: () => void;
  onAuditPending: () => void;
  bulkAudit: {
    busy: boolean;
    completed: number;
    total: number;
    failed: number;
    error: string | null;
  };
  onCollapse?: () => void;
}) {
  const { id: novelId } = useParams();
  const [tab, setTab] = useState<"chapters" | "outline">("chapters");
  const { data: outlineTree } = useApiQuery<OutlineNode[]>(
    novelId && tab === "outline" ? `/novels/${novelId}/outline` : null,
    [],
  );
  const totalWords = chapters.reduce((s, c) => s + c.words, 0);
  const auditableCount = chapters.filter((c) => c.needsCheck && c.words > 0).length;
  const outlineCheckCount = chapters.filter((c) => c.needsCheck && c.words === 0).length;

  const chapterByOutlineNode = useMemo(() => {
    const map = new Map<string, Chapter>();
    for (const c of chapters) {
      if (c.outlineNodeId) map.set(c.outlineNodeId, c);
    }
    return map;
  }, [chapters]);

  return (
    <aside className="flex w-full shrink-0 flex-col border-r border-border bg-surface md:w-sidebar">
      <div className="flex items-center gap-1 border-b border-border p-2">
        {tabs.map((t) => {
          const Icon = t.icon;
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 rounded-control py-1.5 text-[13px] transition-colors",
                active
                  ? "bg-surface-subtle font-medium text-text-primary"
                  : "text-text-secondary hover:bg-surface-subtle",
              )}
            >
              <Icon size={15} />
              {t.label}
            </button>
          );
        })}
        {tab === "chapters" ? (
          <button
            type="button"
            onClick={onCreate}
            className="flex h-8 w-8 shrink-0 items-center justify-center text-text-secondary hover:bg-surface-subtle"
            aria-label="新建章节"
            title="新建章节"
          >
            <Plus size={15} />
          </button>
        ) : novelId ? (
          <Link
            to={`/novel/${novelId}/outline`}
            className="flex h-8 w-8 shrink-0 items-center justify-center text-text-secondary hover:bg-surface-subtle"
            aria-label="打开大纲编辑"
            title="打开大纲编辑"
          >
            <ExternalLink size={15} />
          </Link>
        ) : null}
      </div>

      {tab === "chapters" && (auditableCount > 0 || outlineCheckCount > 0 || bulkAudit.error) && (
        <div className="border-b border-border px-3 py-2">
          {auditableCount > 0 && (
            <button
              type="button"
              onClick={onAuditPending}
              disabled={bulkAudit.busy}
              className="flex h-8 w-full items-center justify-center gap-2 rounded-control border border-border bg-surface text-[12px] font-medium text-primary hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-60"
            >
              {bulkAudit.busy ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
              {bulkAudit.busy
                ? `检查中 ${bulkAudit.completed}/${bulkAudit.total || auditableCount}`
                : `检查待处理 ${auditableCount}`}
            </button>
          )}
          {outlineCheckCount > 0 && (
            <p className={cn("text-[11px] text-text-secondary", auditableCount > 0 && "mt-1.5")}>
              {outlineCheckCount} 个未写章节的安排待核对
            </p>
          )}
          {bulkAudit.error && <p className="mt-1.5 text-[11px] text-danger">{bulkAudit.error}</p>}
        </div>
      )}

      {tab === "outline" && (
        <div className="border-b border-border px-3 py-2">
          <p className="text-[11px] leading-relaxed text-text-secondary">
            故事规划 · 查看全书阶段与章节安排。点击章节即可开始写作。
          </p>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {tab === "chapters" ? (
          chapters.length === 0 ? (
            <p className="px-3 py-8 text-center text-[12px] text-text-secondary">
              暂无章节。可在故事规划页自动生成，或点 + 新建。
            </p>
          ) : (
            chapters.map((c) => {
              const meta = chapterStatusMeta[c.status];
              const Icon = meta.icon;
              const active = c.id === activeId;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => onSelect(c.id)}
                  className={cn(
                    "flex w-full flex-col gap-1 border-l-2 px-3 py-2.5 text-left transition-colors duration-150",
                    active
                      ? "border-primary bg-[#F0FDFA]"
                      : "border-transparent hover:bg-surface-subtle",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] font-medium text-text-primary">
                      {c.index.toString().padStart(2, "0")} · {c.title}
                    </span>
                    {c.score != null ? (
                      <span className={cn("shrink-0 text-[12px] font-semibold", meta.className)}>
                        {c.score}
                      </span>
                    ) : (
                      <Icon size={14} className={cn("shrink-0", meta.className)} />
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-[12px] text-text-secondary">
                    <Icon size={12} className={meta.className} />
                    <span className={meta.className}>{meta.label}</span>
                    <span>·</span>
                    <span>{c.words.toLocaleString()} 字</span>
                    {c.needsCheck && (
                      <span className="ml-auto rounded bg-[#FEF3C7] px-1.5 py-0.5 text-[11px] font-medium text-warning">
                        {c.words > 0 ? "待检查" : "安排待核对"}
                      </span>
                    )}
                  </div>
                </button>
              );
            })
          )
        ) : outlineTree.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <p className="text-[12px] text-text-secondary">暂无故事规划</p>
            {novelId && (
              <Link
                to={`/novel/${novelId}/outline?wizard=1`}
                className="mt-3 inline-flex text-[12px] font-medium text-primary hover:underline"
              >
                自动生成故事规划 →
              </Link>
            )}
          </div>
        ) : (
          outlineTree.map((node) => (
            <OutlineTreeNode
              key={node.id}
              node={node}
              depth={0}
              activeChapterId={activeId}
              chapterByOutlineNode={chapterByOutlineNode}
              onSelectChapter={onSelect}
            />
          ))
        )}
      </div>

      <div className="flex items-center justify-between border-t border-border px-3 py-2">
        <span className="text-[12px] text-text-secondary">
          {tab === "chapters"
            ? `${chapters.length} 章 · ${totalWords.toLocaleString()} 字`
            : `${countOutlineNodes(outlineTree)} 项规划 · ${countOutlineByKind(outlineTree, "chapter")} 章安排`}
        </span>
        <button
          type="button"
          onClick={onCollapse}
          className="flex h-7 w-7 items-center justify-center rounded-control text-text-secondary hover:bg-surface-subtle"
          aria-label="折叠左栏"
          title="折叠左栏"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>
    </aside>
  );
}

function countOutlineNodes(nodes: OutlineNode[]): number {
  let n = 0;
  for (const node of nodes) {
    n += 1 + countOutlineNodes(node.children ?? []);
  }
  return n;
}

function countOutlineByKind(nodes: OutlineNode[], kind: OutlineNode["kind"]): number {
  let n = 0;
  for (const node of nodes) {
    if (node.kind === kind) n += 1;
    n += countOutlineByKind(node.children ?? [], kind);
  }
  return n;
}

function OutlineTreeNode({
  node,
  depth,
  activeChapterId,
  chapterByOutlineNode,
  onSelectChapter,
}: {
  node: OutlineNode;
  depth: number;
  activeChapterId: string;
  chapterByOutlineNode: Map<string, Chapter>;
  onSelectChapter: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasChildren = !!node.children?.length;
  const Icon = kindIcon[node.kind];
  const linked = chapterByOutlineNode.get(node.id);
  const active = Boolean(linked && linked.id === activeChapterId);
  const goal = String(node.details?.goal ?? "").trim();
  const highlight = String(node.details?.highlight ?? "").trim();
  const isStructural = node.kind === "volume" || node.kind === "arc";

  return (
    <div>
      <div
        className={cn(
          "flex items-start gap-1 border-l-2 py-1.5 pr-2 text-left transition-colors",
          active
            ? "border-primary bg-[#F0FDFA]"
            : "border-transparent hover:bg-surface-subtle",
        )}
        style={{ paddingLeft: 6 + depth * 12 }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center text-text-secondary"
            aria-label={open ? "折叠" : "展开"}
          >
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : (
          <span className="mt-0.5 w-5 shrink-0" />
        )}

        {linked ? (
          <button
            type="button"
            onClick={() => onSelectChapter(linked.id)}
            className="min-w-0 flex-1 text-left"
          >
            <NodeTitle
              kind={node.kind}
              title={node.title}
              locked={node.locked}
              Icon={Icon}
              isStructural={isStructural}
              linkedIndex={linked.index}
            />
            {(goal || highlight) && (
              <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-text-secondary">
                {goal || highlight}
              </p>
            )}
            <p className="mt-0.5 text-[10px] text-text-secondary">
              写作 {linked.words.toLocaleString()} 字
              {linked.score != null ? ` · 分 ${linked.score}` : ""}
            </p>
          </button>
        ) : (
          <div className="min-w-0 flex-1">
            <NodeTitle
              kind={node.kind}
              title={node.title}
              locked={node.locked}
              Icon={Icon}
              isStructural={isStructural}
            />
            {(goal || highlight) && (
              <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-text-secondary">
                {goal || highlight}
              </p>
            )}
            {node.kind === "chapter" && (
              <p className="mt-0.5 text-[10px] text-text-secondary">尚未关联写作章节</p>
            )}
          </div>
        )}
      </div>

      {hasChildren && open && (
        <div>
          {node.children!.map((child) => (
            <OutlineTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              activeChapterId={activeChapterId}
              chapterByOutlineNode={chapterByOutlineNode}
              onSelectChapter={onSelectChapter}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function NodeTitle({
  kind,
  title,
  locked,
  Icon,
  isStructural,
  linkedIndex,
}: {
  kind: OutlineNode["kind"];
  title: string;
  locked?: boolean;
  Icon: typeof FileText;
  isStructural: boolean;
  linkedIndex?: number;
}) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Icon size={13} className="shrink-0 text-text-secondary" />
      <span
        className={cn(
          "rounded px-1 py-px text-[10px] font-medium",
          kind === "volume" && "bg-primary/10 text-primary",
          kind === "arc" && "bg-[#EEF2FF] text-[#4338CA]",
          kind === "chapter" && "bg-surface-subtle text-text-secondary",
          kind === "scene" && "bg-[#FFF7ED] text-[#C2410C]",
        )}
      >
        {kindLabel[kind]}
      </span>
      <span
        className={cn(
          "truncate text-[12px] text-text-primary",
          isStructural ? "font-semibold" : "font-medium",
        )}
      >
        {linkedIndex != null ? `${String(linkedIndex).padStart(2, "0")} · ` : ""}
        {title}
      </span>
      {locked && <Lock size={11} className="shrink-0 text-text-secondary" />}
    </div>
  );
}
