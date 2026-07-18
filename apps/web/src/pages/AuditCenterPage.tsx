import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Wand2, RefreshCw, ShieldAlert, ChevronRight, List } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiRequest, useApiQuery, type AuditReport, type Chapter } from "@/lib/api";
import type { IssueSeverity } from "@/lib/types";
import { chapterStatusMeta, severityMeta } from "@/components/ui/status";
import { cn } from "@/lib/cn";

const severityBadge: Record<IssueSeverity, string> = {
  fatal: "bg-[#FEF2F2] text-danger",
  major: "bg-[#FEF3C7] text-warning",
  minor: "bg-[#EFF6FF] text-info",
};

/** Audit center (§17): chapter list on the left, full audit report on the right. */
export function AuditCenterPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: chapters } = useApiQuery<Chapter[]>(id ? `/novels/${id}/chapters` : null, []);
  const auditable = chapters.filter((c) => ["unaudited", "revise", "fatal", "pass", "confirmed"].includes(c.status));
  const auditedCount = auditable.filter((c) => c.status !== "unaudited").length;
  const [active, setActive] = useState("");
  const [mobileView, setMobileView] = useState<"chapters" | "report">("chapters");
  useEffect(() => {
    if (!active && auditable.length) setActive(auditable[0].id);
  }, [active, auditable]);
  const { data: audits, refetch } = useApiQuery<AuditReport[]>(active ? `/chapters/${active}/audits` : null, []);
  const report = audits[0];
  const activeChapter = chapters.find((chapter) => chapter.id === active);
  const auditDimensions = report?.dimensions ?? [];
  const auditIssues = report?.issues ?? [];
  const total = report?.totalScore ?? 0;
  const fatalCount = auditIssues.filter((i) => i.severity === "fatal").length;
  const openInWorkspace = () => {
    if (!id || !active) return;
    navigate(`/novel/${id}/write?chapter=${active}`);
  };
  const runAudit = async () => {
    await apiRequest(`/chapters/${active}/audit`, { method: "POST" });
    await refetch();
  };
  const [scan, setScan] = useState<{
    issueCount: number;
    fatalCount: number;
    issues: Array<{
      severity: string;
      type: string;
      evidence: string;
      reason: string;
      chapterIndex?: number | null;
      chapterTitle?: string | null;
    }>;
  } | null>(null);
  const [scanning, setScanning] = useState(false);
  const runNovelScan = async () => {
    if (!id) return;
    setScanning(true);
    try {
      const result = await apiRequest<NonNullable<typeof scan>>(`/novels/${id}/audit-scan`, {
        method: "POST",
      });
      setScan(result);
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <div className="grid shrink-0 grid-cols-2 gap-1 border-b border-border bg-surface p-1 md:hidden" aria-label="质量检查视图">
        <button
          type="button"
          aria-pressed={mobileView === "chapters"}
          onClick={() => setMobileView("chapters")}
          className={cn(
            "flex h-10 items-center justify-center gap-1.5 rounded-control text-[13px]",
            mobileView === "chapters" ? "bg-surface-subtle font-medium text-primary" : "text-text-secondary",
          )}
        >
          <List size={15} />
          章节
        </button>
        <button
          type="button"
          aria-pressed={mobileView === "report"}
          onClick={() => setMobileView("report")}
          className={cn(
            "flex h-10 items-center justify-center gap-1.5 rounded-control text-[13px]",
            mobileView === "report" ? "bg-surface-subtle font-medium text-primary" : "text-text-secondary",
          )}
        >
          <ShieldAlert size={15} />
          报告
        </button>
      </div>
      <div className="flex min-h-0 flex-1">
        {/* Chapter list */}
        <aside className={cn("w-full shrink-0 flex-col border-r border-border bg-surface md:w-[300px]", mobileView === "chapters" ? "flex" : "hidden md:flex")}>
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-panel-title font-semibold text-text-primary">待检查</h2>
              <Button size="sm" variant="secondary" disabled={scanning} onClick={() => void runNovelScan()}>
                {scanning ? "扫描中" : "全书扫描"}
              </Button>
            </div>
            <p className="mt-0.5 text-[12px] text-text-secondary">
              {auditedCount} / {auditable.length} 章已有检查结果
              {scan ? ` · 全书 ${scan.issueCount} 项` : ""}
            </p>
          </div>
          {scan && (
            <div className="max-h-40 overflow-y-auto border-b border-border px-3 py-2 text-[12px]">
              {scan.issues.slice(0, 8).map((issue, index) => (
                <p key={`${issue.type}-${index}`} className="mb-1 text-text-secondary">
                  <span className="font-medium text-text-primary">{issue.type}</span>
                  {issue.chapterIndex != null ? ` · 第${issue.chapterIndex}章` : ""}：{issue.evidence}
                </p>
              ))}
              {scan.issues.length > 8 && (
                <p className="text-text-secondary">…共 {scan.issueCount} 项</p>
              )}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {auditable.map((c) => {
              const meta = chapterStatusMeta[c.status];
              const Icon = meta.icon;
              const isActive = c.id === active;
              return (
                <button
                  key={c.id}
                  onClick={() => { setActive(c.id); setMobileView("report"); }}
                  className={cn(
                    "flex w-full items-center gap-2 border-l-2 px-3 py-2.5 text-left transition-colors",
                    isActive
                      ? "border-primary bg-[#F0FDFA]"
                      : "border-transparent hover:bg-surface-subtle",
                  )}
                >
                  <Icon size={15} className={cn("shrink-0", meta.className)} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-text-primary">
                      {c.index.toString().padStart(2, "0")} · {c.title}
                    </span>
                    <span className={cn("text-[12px]", meta.className)}>{meta.label}</span>
                  </span>
                  {c.score != null && (
                    <span className={cn("shrink-0 text-[13px] font-semibold", meta.className)}>
                      {c.score}
                    </span>
                  )}
                  <ChevronRight size={14} className="shrink-0 text-text-secondary" />
                </button>
              );
            })}
          </div>
        </aside>

        {/* Report */}
        <section className={cn("min-h-0 w-full flex-1 overflow-y-auto bg-background md:block", mobileView !== "report" && "hidden md:block")}>
          <div className="w-full px-4 py-5 sm:px-10 sm:py-8">
            {/* Overview */}
            <div className="flex flex-col items-start gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-[13px] text-text-secondary">第 {activeChapter?.index ?? "—"} 章 · {activeChapter?.title ?? "请选择章节"}</p>
                <h1 className="mt-0.5 text-page-title font-semibold text-warning">{report ? (report.decision === "PASS" ? "检查通过" : report.decision === "REVISE" ? "需要局部修改" : "需要整章重写") : "尚无检查结果"}</h1>
                <p className="mt-1 text-[13px] text-text-secondary">评分表与正文版本绑定保存</p>
              </div>
              <div className="text-left sm:text-right">
                <p className="text-[36px] font-semibold leading-none text-text-primary">
                  {total}
                  <span className="text-[18px] text-text-secondary"> / 100</span>
                </p>
              </div>
            </div>

            {/* Dimensions */}
            <div className="grid grid-cols-1 gap-x-8 gap-y-3 border-b border-border py-5 sm:grid-cols-2">
              {auditDimensions.map((d) => {
                const pct = (d.score / d.max) * 100;
                return (
                  <div key={d.name} className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-[13px] text-text-secondary">{d.name}</span>
                    <div className="h-1.5 flex-1 rounded-full bg-surface-subtle">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          pct >= 90 ? "bg-success" : pct >= 70 ? "bg-primary" : "bg-warning",
                        )}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="w-12 shrink-0 text-right text-[13px] tabular-nums text-text-primary">
                      {d.score}/{d.max}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Actions */}
            <div className="flex flex-col items-stretch gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
              <span className="flex flex-wrap items-center gap-2 text-[13px] text-text-secondary">
                <ShieldAlert size={15} className="text-danger" />
                严重问题 <span className="font-semibold text-danger">{fatalCount}</span> · 一般问题{" "}
                <span className="font-semibold text-text-primary">
                  {auditIssues.length - fatalCount}
                </span>
              </span>
              <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
                <Button variant="secondary" size="sm" icon={<Wand2 size={14} />} onClick={runAudit} disabled={!active}>
                  重新检查
                </Button>
                <Button variant="primary" size="sm" icon={<RefreshCw size={14} />} onClick={openInWorkspace} disabled={!active}>
                  整章重写
                </Button>
              </div>
            </div>

            {/* Issues — fatal pinned first, then a divider before minor ones */}
            <div className="flex flex-col gap-3 pb-8">
              {auditIssues.map((issue, i) => {
                const meta = severityMeta[issue.severity];
                const prevFatal = i > 0 && auditIssues[i - 1].severity === "fatal";
                const dividerBefore = issue.severity !== "fatal" && prevFatal;
                return (
                  <div key={issue.id}>
                    {dividerBefore && (
                      <p className="mb-3 mt-1 text-[12px] font-medium uppercase tracking-wide text-text-secondary">
                        一般建议
                      </p>
                    )}
                    <div className="rounded-card border border-border bg-surface p-4">
                      <div className="mb-2 flex items-center gap-2">
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[11px] font-semibold",
                            severityBadge[issue.severity],
                          )}
                        >
                          {meta.label}
                        </span>
                        <span className="text-[14px] font-medium text-text-primary">
                          {issue.type}
                        </span>
                      </div>
                      <p className="text-[14px] italic text-text-secondary">“{issue.evidence}”</p>
                      <p className="mt-1.5 text-[13px] text-text-secondary">
                        冲突：{issue.conflictsWith}
                      </p>
                      <p className="mt-1 text-[14px] text-text-primary">建议：{issue.suggestion}</p>
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
                        <button onClick={openInWorkspace} className="rounded-control border border-border px-2.5 py-1 text-primary hover:bg-surface-subtle">
                          打开正文处理
                        </button>
                        <button onClick={() => void runAudit()} className="rounded-control border border-border px-2.5 py-1 text-text-secondary hover:bg-surface-subtle">
                          重新检查
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      </div>
      </div>
  );
}
