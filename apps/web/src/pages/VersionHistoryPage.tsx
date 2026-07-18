import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { RotateCcw, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/form";
import { VersionRow } from "./writing/VersionRow";
import { apiRequest, useApiQuery, type Chapter, type ChapterVersion } from "@/lib/api";
import { useWorkspaceStore } from "@/stores/workspace";
import { cn } from "@/lib/cn";

interface DiffRow {
  text: string;
  change: "equal" | "delete" | "insert";
}

interface DiffPayload {
  left: DiffRow[];
  right: DiffRow[];
  stats: {
    deleted: number;
    inserted: number;
    equal: number;
  };
}

/** Version history (§14): chapter picker + real paragraph diff. */
export function VersionHistoryPage() {
  const { id } = useParams();
  const { data: chapters } = useApiQuery<Chapter[]>(id ? `/novels/${id}/chapters` : null, []);
  const [chapterId, setChapterId] = useState("");
  const chapter = chapters.find((c) => c.id === chapterId) ?? chapters[0];
  const { data: versions, refetch } = useApiQuery<ChapterVersion[]>(
    chapter ? `/chapters/${chapter.id}/versions` : null,
    [],
  );
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [diff, setDiff] = useState<DiffPayload | null>(null);

  useEffect(() => {
    if (!chapterId && chapters.length) setChapterId(chapters[0].id);
  }, [chapters, chapterId]);

  useEffect(() => {
    setLeft("");
    setRight("");
    setDiff(null);
  }, [chapter?.id]);

  useEffect(() => {
    if (versions.length && !right) {
      setRight(versions[0].id);
      setLeft(versions[Math.min(1, versions.length - 1)].id);
    }
  }, [versions, left, right]);

  useEffect(() => {
    if (!chapter || !left || !right) {
      setDiff(null);
      return;
    }
    let cancelled = false;
    apiRequest<{ diff: DiffPayload }>(
      `/chapters/${chapter.id}/versions/diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    )
      .then((payload) => {
        if (!cancelled) setDiff(payload.diff);
      })
      .catch(() => {
        if (!cancelled) setDiff(null);
      });
    return () => {
      cancelled = true;
    };
  }, [chapter, left, right]);

  const leftVersion = versions.find((version) => version.id === left);
  const rightVersion = versions.find((version) => version.id === right);
  const setChapterLabel = useWorkspaceStore((s) => s.setChapterLabel);

  useEffect(() => {
    if (chapter) setChapterLabel(`第 ${chapter.index} 章 · ${chapter.title}`);
    else setChapterLabel(undefined);
  }, [chapter, setChapterLabel]);

  const restore = async () => {
    if (!chapter || !rightVersion) return;
    await apiRequest(`/chapters/${chapter.id}/versions/${rightVersion.id}/restore`, {
      method: "POST",
      body: JSON.stringify({
        current_content: versions.find((version) => version.current)?.content,
      }),
    });
    await refetch();
  };

  return (
    <div className="flex min-h-0 w-full flex-1">
        <aside className="flex w-[340px] shrink-0 flex-col border-r border-border bg-surface">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-panel-title font-semibold text-text-primary">版本历史</h2>
            <div className="mt-2">
              <Select
                value={chapter?.id ?? ""}
                onChange={(e) => setChapterId(e.target.value)}
                aria-label="选择章节"
              >
                {chapters.map((c) => (
                  <option key={c.id} value={c.id}>
                    第 {c.index} 章 · {c.title}
                  </option>
                ))}
              </Select>
            </div>
            <p className="mt-2 text-[12px] text-text-secondary">
              选择两个版本对比 · 共 {versions.length} 个
              {diff
                ? ` · 删 ${diff.stats.deleted} / 增 ${diff.stats.inserted}`
                : ""}
            </p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-border">
            {versions.map((v) => (
              <div key={v.id} className="flex items-center gap-2 px-2">
                <div className="flex flex-col gap-0.5 pl-1">
                  <button
                    onClick={() => setLeft(v.id)}
                    className={cn(
                      "rounded px-1.5 text-[10px] font-medium",
                      left === v.id
                        ? "bg-info/10 text-info"
                        : "text-text-secondary hover:bg-surface-subtle",
                    )}
                    aria-label="设为左侧对比版本"
                  >
                    左
                  </button>
                  <button
                    onClick={() => setRight(v.id)}
                    className={cn(
                      "rounded px-1.5 text-[10px] font-medium",
                      right === v.id
                        ? "bg-primary/10 text-primary"
                        : "text-text-secondary hover:bg-surface-subtle",
                    )}
                    aria-label="设为右侧对比版本"
                  >
                    右
                  </button>
                </div>
                <div className="min-w-0 flex-1">
                  <VersionRow version={v} />
                </div>
              </div>
            ))}
          </div>
        </aside>

        <section className="flex min-h-0 flex-1 flex-col bg-background">
          <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
            <div className="flex items-center gap-2 text-[13px]">
              <span className="rounded bg-info/10 px-2 py-0.5 font-medium text-info">
                {leftVersion?.label ?? left}
              </span>
              <ArrowRight size={14} className="text-text-secondary" />
              <span className="rounded bg-primary/10 px-2 py-0.5 font-medium text-primary">
                {rightVersion?.label ?? right}
              </span>
            </div>
            <Button
              variant="primary"
              size="sm"
              icon={<RotateCcw size={14} />}
              onClick={() => {
                void restore();
              }}
              disabled={!rightVersion}
            >
              恢复到 {rightVersion?.label ?? "—"}
            </Button>
          </div>

          <p className="border-b border-border bg-[#FEF3C7]/40 px-6 py-2 text-[12px] text-warning">
            恢复前，当前内容会先保存为新版本，不会丢稿。高亮为真实段落 diff。
          </p>

          <div className="grid min-h-0 flex-1 grid-cols-2 divide-x divide-border overflow-y-auto">
            <div className="px-6 py-5">
              <p className="mb-3 text-[12px] font-medium text-text-secondary">
                {leftVersion?.label ?? "左"} · 对照
              </p>
              <DiffColumn rows={diff?.left ?? []} side="left" />
            </div>
            <div className="px-6 py-5">
              <p className="mb-3 text-[12px] font-medium text-text-secondary">
                {rightVersion?.label ?? "右"} · 对照
              </p>
              <DiffColumn rows={diff?.right ?? []} side="right" />
            </div>
          </div>
        </section>
      </div>
  );
}

function DiffColumn({
  rows,
  side,
}: {
  rows: DiffRow[];
  side: "left" | "right";
}) {
  if (!rows.length) {
    return <p className="text-[13px] text-text-secondary">选择两个版本以查看差异。</p>;
  }
  return (
    <div className="flex flex-col gap-3 font-serif text-[16px] leading-[28px]">
      {rows.map((row, i) => (
        <p
          key={`${side}-${i}-${row.change}`}
          className={cn(
            "rounded px-2 py-0.5",
            row.change === "delete" && "bg-[#FEF2F2] text-danger",
            row.change === "insert" && "bg-[#F0FDF4] text-[#166534]",
            row.change === "equal" && "text-text-primary",
          )}
        >
          {row.text}
        </p>
      ))}
    </div>
  );
}
