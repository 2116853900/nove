import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Sparkles, AlertCircle } from "lucide-react";
import { SegControl } from "@/components/ui/Tabs";
import { StatusDot } from "@/components/ui/Badge";
import { useApiQuery, type PlotThread, type TimelineEvent } from "@/lib/api";
import type { ThreadStatus } from "@/lib/types";
import { cn } from "@/lib/cn";

const threadStatusMeta: Record<ThreadStatus, { label: string; className: string }> = {
  planted: { label: "已种下", className: "text-text-secondary" },
  developing: { label: "发展中", className: "text-info" },
  ready: { label: "待回收", className: "text-warning" },
  paid: { label: "已回收", className: "text-success" },
  abandoned: { label: "已放弃", className: "text-text-secondary" },
};

const tabs = [
  { key: "timeline", label: "时间线" },
  { key: "threads", label: "伏笔" },
];

const timelineViews = [
  { key: "story", label: "按故事时间" },
  { key: "chapter", label: "按章节顺序" },
];

/** Plot page (§13): timeline + foreshadowing. Highlights live on their own route. */
export function PlotPage() {
  const { id } = useParams();
  const [tab, setTab] = useState("timeline");
  const [view, setView] = useState("story");
  const { data: timeline } = useApiQuery<TimelineEvent[]>(id ? `/novels/${id}/timeline` : null, []);
  const { data: plotThreads } = useApiQuery<PlotThread[]>(id ? `/novels/${id}/plot-threads` : null, []);

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
        {/* Sub header */}
        <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
          <div className="flex items-center gap-1">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "relative px-3 py-2 text-[14px] transition-colors",
                  t.key === tab
                    ? "font-medium text-text-primary"
                    : "text-text-secondary hover:text-text-primary",
                )}
              >
                {t.label}
                {t.key === tab && (
                  <span className="absolute inset-x-2 -bottom-3 h-0.5 rounded-full bg-primary" />
                )}
              </button>
            ))}
            <Link
              to={`/novel/${id}/highlights`}
              className="px-3 py-2 text-[14px] text-text-secondary hover:text-text-primary"
            >
              亮点与转折
            </Link>
          </div>
          {tab === "timeline" && (
            <SegControl items={timelineViews} value={view} onChange={setView} />
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === "timeline" ? <TimelineView timeline={timeline} /> : <ThreadsView plotThreads={plotThreads} />}
        </div>
      </div>
  );
}

function TimelineView({ timeline }: { timeline: TimelineEvent[] }) {
  return (
    <div className="w-full px-8 py-6">
      <ul className="flex flex-col">
        {timeline.map((e, i) => (
          <li key={e.id} className="flex gap-4">
            {/* Rail */}
            <div className="flex flex-col items-center">
              <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full border-2 border-primary bg-surface" />
              {i < timeline.length - 1 && <span className="w-px flex-1 bg-border" />}
            </div>
            <div className="flex-1 pb-6">
              <div className="flex items-center gap-2 text-[12px] text-text-secondary">
                <span className="font-medium text-text-primary">{e.storyTime}</span>
                <span>·</span>
                <span>{e.chapter}</span>
              </div>
              <p className="mt-1 text-[14px] text-text-primary">
                <span className="font-medium">{e.subjects}</span> {e.action}
                <span className="text-text-secondary"> · {e.location}</span>
              </p>
              <p className="mt-0.5 text-[13px] text-text-secondary">结果：{e.consequence}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ThreadsView({ plotThreads }: { plotThreads: PlotThread[] }) {
  const cols =
    "grid grid-cols-[minmax(160px,1fr)_90px_110px_110px_110px_90px] items-center gap-3";
  return (
    <div className="w-full px-8 py-6">
      <div className="mb-3 flex items-center gap-2 rounded-card border border-border bg-[#FEF3C7]/40 px-4 py-2.5 text-[13px] text-warning">
        <AlertCircle size={15} />
        伏笔「信标的真实来源」重要度高，已 24 章未发展，建议尽快推进或回收。
      </div>

      <div className={cn(cols, "border-b border-border px-4 py-2")}>
        {["名称", "状态", "种下", "计划回收", "重要度", "类型"].map((h) => (
          <span key={h} className="text-assist font-medium text-text-secondary">
            {h}
          </span>
        ))}
      </div>
      {plotThreads.map((t) => {
        const meta = threadStatusMeta[t.status];
        return (
          <div
            key={t.id}
            className={cn(cols, "border-b border-border px-4 py-3 hover:bg-surface-subtle")}
          >
            <div className="min-w-0">
              <p className="truncate text-[14px] font-medium text-text-primary">{t.name}</p>
              <p className="truncate text-[12px] text-text-secondary">{t.latest}</p>
            </div>
            <span className={cn("flex items-center gap-1.5 text-[13px]", meta.className)}>
              <StatusDot className="bg-current" />
              {meta.label}
            </span>
            <span className="text-[13px] text-text-secondary">{t.planted}</span>
            <span className="text-[13px] text-text-secondary">{t.payoff}</span>
            <span className="text-[13px] text-text-primary">{t.importance}</span>
            <span className="text-[13px] text-text-secondary">{t.kind}</span>
          </div>
        );
      })}

      <button className="mt-4 flex items-center gap-1.5 text-[13px] text-primary hover:underline">
        <Sparkles size={14} /> 让 AI 检查未发展的伏笔
      </button>
    </div>
  );
}
