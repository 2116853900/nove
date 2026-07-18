import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, FileText } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiRequest, useApiQuery, useNovel, type Chapter, type CharacterSummary } from "@/lib/api";

/**
 * Post-import review (PRD §7.2): check chapter split + bible entities before writing.
 */
export function ImportReviewPage() {
  const { id } = useParams();
  const { data: novel } = useNovel(id);
  const { data: chapters, refetch: refetchChapters } = useApiQuery<Chapter[]>(
    id ? `/novels/${id}/chapters` : null,
    [],
  );
  const { data: characters, refetch: refetchChars } = useApiQuery<CharacterSummary[]>(
    id ? `/novels/${id}/characters` : null,
    [],
  );
  const { data: memory } = useApiQuery<{
    confirmedChapters: number;
    chunkCount: number;
    status: string;
  }>(id ? `/novels/${id}/memory/status` : null, {
    confirmedChapters: 0,
    chunkCount: 0,
    status: "EMPTY",
  });
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMessage(null);
  }, [id]);

  const confirmChapter = async (chapterId: string) => {
    setBusy(true);
    try {
      await apiRequest(`/chapters/${chapterId}/confirm`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await Promise.all([refetchChapters(), refetchChars()]);
      setMessage("章节已确认并进入记忆索引流程。");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "确认失败");
    } finally {
      setBusy(false);
    }
  };

  const renameEntity = async (entityId: string, current: string) => {
    const name = window.prompt("修正人物姓名（合并请手动删除多余实体）", current)?.trim();
    if (!name || name === current) return;
    await apiRequest(`/story-entities/${entityId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    await refetchChars();
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-8 py-8">
        <div>
          <p className="text-[12px] text-text-secondary">导入审阅</p>
          <h1 className="mt-1 text-page-title font-semibold text-text-primary">
            {novel?.title ?? "导入项目"}
          </h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-text-secondary">
            检查章节切分与人物列表。确认章节后才会写入长期记忆。可先修正名称，再进入写作工作台。
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="章节数" value={String(chapters.length)} />
          <Stat label="人物实体" value={String(characters.length)} />
          <Stat label="记忆状态" value={`${memory.status} · ${memory.chunkCount} chunks`} />
        </div>

        {message && (
          <p className="rounded-control border border-border bg-surface px-3 py-2 text-[13px] text-text-secondary" role="status">
            {message}
          </p>
        )}

        <section className="rounded-card border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-[14px] font-semibold">章节列表</h2>
            <Link
              to={`/novel/${id}/write`}
              className="text-[13px] font-medium text-primary hover:underline"
            >
              进入写作 →
            </Link>
          </div>
          <ul className="divide-y divide-border">
            {chapters.map((c) => (
              <li key={c.id} className="flex items-center gap-3 px-4 py-3">
                <FileText size={16} className="shrink-0 text-text-secondary" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-medium text-text-primary">
                    第 {c.index} 章 · {c.title}
                  </p>
                  <p className="text-[12px] text-text-secondary">
                    {c.words?.toLocaleString?.() ?? c.words ?? "—"} 字 · {c.status}
                  </p>
                </div>
                {c.status !== "confirmed" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    icon={<Check size={14} />}
                    onClick={() => void confirmChapter(c.id)}
                  >
                    确认入记忆
                  </Button>
                ) : (
                  <span className="text-[12px] text-success">已确认</span>
                )}
              </li>
            ))}
            {!chapters.length && (
              <li className="px-4 py-8 text-[13px] text-text-secondary">暂无章节</li>
            )}
          </ul>
        </section>

        <section className="rounded-card border border-border bg-surface">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-[14px] font-semibold">人物实体（可改名）</h2>
            <p className="mt-0.5 text-[12px] text-text-secondary">
              同名冲突请手动改名后在故事圣经删除重复项。
            </p>
          </div>
          <ul className="divide-y divide-border">
            {characters.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <div>
                  <p className="text-[14px] text-text-primary">{c.name}</p>
                  <p className="text-[12px] text-text-secondary">{c.role || "—"}</p>
                </div>
                <Button size="sm" onClick={() => void renameEntity(c.id, c.name)}>
                  改名
                </Button>
              </li>
            ))}
            {!characters.length && (
              <li className="px-4 py-6 text-[13px] text-text-secondary">
                导入占位人物可在故事圣经中替换。
              </li>
            )}
          </ul>
        </section>
      </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <p className="text-[12px] text-text-secondary">{label}</p>
      <p className="mt-1 text-[16px] font-semibold text-text-primary">{value}</p>
    </div>
  );
}
