import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  Check,
  Circle,
  ListTree,
  LoaderCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { apiRequest } from "@/lib/api";
import type { NovelBootstrapStatus } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

const STAGES = [
  { key: "blueprint", label: "故事方向" },
  { key: "bible", label: "人物与世界" },
  { key: "volumes", label: "全书规划" },
  { key: "arcs", label: "第一卷剧情" },
  { key: "chapters", label: "首批章节" },
] as const;

export function NovelSetupPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<NovelBootstrapStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [pollVersion, setPollVersion] = useState(0);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 });
  }, []);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await apiRequest<NovelBootstrapStatus>(`/novels/${id}/bootstrap`);
        if (cancelled) return;
        setData(next);
        setLoadError(null);
        if (next.status === "pending" || next.status === "running" || next.status === "not_started") {
          timer = window.setTimeout(poll, 1400);
        }
      } catch (reason) {
        if (cancelled) return;
        setLoadError(reason instanceof Error ? reason.message : "暂时无法读取搭建进度");
        timer = window.setTimeout(poll, 2500);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [id, pollVersion]);

  const retry = async () => {
    if (!id) return;
    setRetrying(true);
    setLoadError(null);
    try {
      const next = await apiRequest<NovelBootstrapStatus>(`/novels/${id}/bootstrap/retry`, {
        method: "POST",
      });
      setData(next);
      setPollVersion((value) => value + 1);
    } catch (reason) {
      setLoadError(reason instanceof Error ? reason.message : "重试失败");
    } finally {
      setRetrying(false);
    }
  };

  const stageIndex = data?.stage === "complete"
    ? STAGES.length
    : Math.max(0, STAGES.findIndex((stage) => stage.key === data?.stage));
  const complete = data?.status === "complete";
  const failed = data?.status === "failed";

  return (
    <div className="min-h-screen bg-background text-text-primary">
      <header className="flex h-topbar items-center justify-between border-b border-border bg-surface px-4 sm:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-control bg-primary text-[14px] font-bold text-white">N</span>
          <span className="text-[15px]">正在准备新故事</span>
        </div>
        <Link to="/" className="text-[13px] text-text-secondary hover:text-text-primary">返回书架</Link>
      </header>

      <main className="mx-auto w-full max-w-[880px] px-5 py-10 sm:px-8 sm:py-14">
        <div className="flex items-start gap-4">
          <span className={cn(
            "flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-white",
            failed ? "bg-danger" : complete ? "bg-success" : "bg-primary",
          )}>
            {complete ? <Check size={22} /> : failed ? <RefreshCw size={21} /> : <Sparkles size={21} />}
          </span>
          <div className="min-w-0">
            <h1 className="text-[24px] font-semibold sm:text-[28px]">
              {complete ? "故事已经准备好" : failed ? "搭建暂时停在这里" : "AI 正在搭建你的故事"}
            </h1>
            <p className="mt-2 text-[14px] text-text-secondary">
              {data?.message || "正在读取进度…"}
            </p>
          </div>
        </div>

        <div className="mt-9">
          <div className="h-2 overflow-hidden rounded-full bg-surface-subtle">
            <div
              className={cn("h-full rounded-full transition-all duration-500", failed ? "bg-danger" : "bg-primary")}
              style={{ width: `${data?.progress ?? 2}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[12px] text-text-secondary">
            <span>{data?.progress ?? 0}%</span>
            {!complete && !failed && <span>可以离开此页，后台会继续</span>}
          </div>
        </div>

        <ol className="mt-8 grid grid-cols-2 gap-x-5 gap-y-4 border-y border-border py-6 sm:grid-cols-5">
          {STAGES.map((stage, index) => {
            const done = complete || index < stageIndex;
            const active = !complete && !failed && index === stageIndex;
            return (
              <li key={stage.key} className="flex items-center gap-2.5">
                {done ? (
                  <Check size={17} className="shrink-0 text-success" />
                ) : active ? (
                  <LoaderCircle size={17} className="shrink-0 animate-spin text-primary" />
                ) : (
                  <Circle size={15} className="shrink-0 text-border-strong" />
                )}
                <span className={cn("text-[13px]", active || done ? "text-text-primary" : "text-text-secondary")}>
                  {stage.label}
                </span>
              </li>
            );
          })}
        </ol>

        {failed && (
          <div className="mt-7 border-l-2 border-danger pl-4">
            <p className="text-[14px] font-medium text-text-primary">已保留完成的部分</p>
            <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
              {data?.error || loadError || "连接恢复后可以从当前阶段继续。"}
            </p>
            <Button className="mt-4" variant="primary" icon={<RefreshCw size={15} />} disabled={retrying} onClick={() => void retry()}>
              {retrying ? "正在重试…" : "继续搭建"}
            </Button>
          </div>
        )}

        {loadError && !failed && <p className="mt-5 text-[13px] text-danger">{loadError}</p>}

        {complete && data && (
          <div className="mt-8 animate-nove-fade-up">
            <div className="border-b border-border pb-6">
              <p className="text-[12px] text-text-secondary">书名</p>
              <h2 className="mt-1 text-[22px] font-semibold">{data.blueprint.bookTitle}</h2>
              <p className="mt-3 max-w-[720px] text-[14px] leading-7 text-text-secondary">{data.blueprint.logline}</p>
            </div>
            <dl className="grid grid-cols-1 gap-x-10 gap-y-5 border-b border-border py-6 sm:grid-cols-2">
              <div>
                <dt className="text-[12px] text-text-secondary">主角与目标</dt>
                <dd className="mt-1 text-[14px] leading-6">{data.blueprint.protagonistName} · {data.blueprint.protagonistGoal}</dd>
              </div>
              <div>
                <dt className="text-[12px] text-text-secondary">故事世界</dt>
                <dd className="mt-1 text-[14px] leading-6">{data.blueprint.worldSetting}</dd>
              </div>
            </dl>
            <p className="mt-4 text-[12px] text-text-secondary">
              已准备 {data.counts.characters} 个人物、{data.counts.locations} 个地点、{data.counts.factions} 个势力、
              {data.counts.volumes} 卷规划、{data.counts.arcs} 个剧情阶段和 {data.counts.chapters} 章安排
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Button
                variant="primary"
                icon={<BookOpen size={16} />}
                disabled={!data.firstChapterId}
                onClick={() => navigate(`/novel/${id}/write?chapter=${data.firstChapterId}`)}
              >
                开始写第一章
              </Button>
              <Button icon={<ListTree size={16} />} onClick={() => navigate(`/novel/${id}/outline`)}>
                查看完整大纲
              </Button>
              <button
                type="button"
                onClick={() => navigate(`/novel/${id}/write`)}
                className="flex items-center gap-1 text-[13px] text-text-secondary hover:text-text-primary sm:ml-auto"
              >
                进入工作台 <ArrowRight size={14} />
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
