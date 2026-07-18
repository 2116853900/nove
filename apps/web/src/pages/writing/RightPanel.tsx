import { useState, useEffect } from "react";
import {
  ChevronRight,
  ChevronDown,
  Users,
  MapPin,
  BookText,
  Sparkles,
  Wand2,
  RefreshCw,
  Loader2,
  Check,
  PanelRightClose,
  Trash2,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";
import { Tabs } from "@/components/ui/Tabs";
import { Field, TextArea, Select, Slider } from "@/components/ui/form";
import { Button } from "@/components/ui/Button";
import type { AuditIssue, AuditReport, ChapterDetail, ChapterVersion, CharacterSummary, ContextSource, LocationSummary, WritingContract } from "@/lib/api";
import type { AuditTarget } from "@/lib/audit-target";
import { severityMeta } from "@/components/ui/status";
import { cn } from "@/lib/cn";
import { VersionRow } from "./VersionRow";

const tabs = [
  { key: "context", label: "上下文" },
  { key: "ai", label: "AI" },
  { key: "audit", label: "检查" },
  { key: "version", label: "版本" },
];

const stages = [
  "正在执行写前检查",
  "正在组装上下文",
  "正在设计场景节拍",
  "正在生成正文",
  "正在检查连续性",
  "正在检查质量",
];

export function RightPanel({
  tab,
  onTabChange,
  generating,
  generatingStage = 2,
  characters,
  locations,
  audit,
  auditTarget = null,
  versions,
  versionBusyId = null,
  chapter,
  contextSources,
  writingContract = null,
  onGenerate,
  onGenerationOptionsChange,
  onAudit,
  auditBusy = false,
  auditError = null,
  confirmBusy = false,
  confirmError = null,
  confirmSuccess = null,
  onRewrite,
  onConfirm,
  onAccept,
  onRestore,
  onDeleteVersion,
  onJumpToEvidence,
  onRewriteIssue,
  onCollapse,
}: {
  tab: string;
  onTabChange: (key: string) => void;
  generating: boolean;
  generatingStage?: number;
  characters: CharacterSummary[];
  locations: LocationSummary[];
  audit?: AuditReport;
  auditTarget?: AuditTarget | null;
  versions: ChapterVersion[];
  versionBusyId?: string | null;
  chapter: ChapterDetail | null;
  contextSources: ContextSource[];
  writingContract?: WritingContract | null;
  onGenerate: () => void;
  onGenerationOptionsChange: (options: GenerationOptions) => void;
  onAudit: () => void;
  auditBusy?: boolean;
  auditError?: string | null;
  confirmBusy?: boolean;
  confirmError?: string | null;
  confirmSuccess?: string | null;
  onRewrite: () => void;
  onConfirm: (fatalOverrideReason?: string) => Promise<void> | void;
  onAccept: (versionId: string) => void;
  onRestore: (versionId: string) => void;
  onDeleteVersion: (versionId: string) => void;
  onJumpToEvidence?: (evidence: string) => boolean;
  onRewriteIssue?: (issue: AuditIssue) => Promise<void>;
  onCollapse?: () => void;
}) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-l border-border bg-surface md:w-panel">
      <div className="flex items-center justify-between pr-2">
        <Tabs items={tabs} value={tab} onChange={onTabChange} className="flex-1" />
        <button
          onClick={onCollapse}
          className="flex h-8 w-8 items-center justify-center rounded-control text-text-secondary hover:bg-surface-subtle"
          aria-label="折叠右栏"
          title="折叠右栏"
        >
          <PanelRightClose size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {generating && <GeneratingBanner stage={generatingStage} />}
        {tab === "context" && <ContextTab characters={characters} locations={locations} sources={contextSources} contract={writingContract} />}
        {tab === "ai" && <AiTab chapter={chapter} generating={generating} onGenerate={onGenerate} onOptionsChange={onGenerationOptionsChange} onRewrite={onRewrite} />}
        {tab === "audit" && (
          <AuditTab
            audit={audit}
            auditTarget={auditTarget}
            onAudit={onAudit}
            auditBusy={auditBusy}
            auditError={auditError}
            hasContent={Boolean(auditTarget)}
            confirmBusy={confirmBusy}
            confirmError={confirmError}
            confirmSuccess={confirmSuccess}
            alreadyConfirmed={Boolean(
              chapter?.currentVersionId &&
                chapter.currentVersionId === chapter.confirmedVersionId &&
                !auditTarget?.isCandidate
            )}
            onConfirm={onConfirm}
            onRewrite={onRewrite}
            onAcceptCandidate={
              auditTarget?.isCandidate ? () => onAccept(auditTarget.versionId) : undefined
            }
            onJumpToEvidence={onJumpToEvidence}
            onRewriteIssue={onRewriteIssue}
            writingContract={writingContract}
          />
        )}
        {tab === "version" && <VersionTab versions={versions} versionBusyId={versionBusyId} onRestore={onRestore} onAccept={onAccept} onDelete={onDeleteVersion} />}
      </div>
    </aside>
  );
}

/** Generation progress (§9): stages, no fake percentage, editor stays unlocked. */
function GeneratingBanner({ stage }: { stage: number }) {
  return (
    <div className="border-b border-border bg-[#F0FDFA] px-4 py-3 animate-nove-fade-down">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-medium text-primary">
        <Loader2 size={15} className="animate-spin" />
        正在生成本章
      </div>
      <ol className="flex flex-col gap-1.5">
        {stages.map((s, i) => {
          const done = i < stage;
          const active = i === stage;
          return (
            <li
              key={s}
              className={cn(
                "flex items-center gap-2 text-[13px] transition-opacity duration-200",
                active && "animate-nove-fade-in",
              )}
            >
              {done ? (
                <Check size={14} className="text-success" />
              ) : active ? (
                <Loader2 size={14} className="animate-spin text-primary" />
              ) : (
                <span className="h-3.5 w-3.5 rounded-full border border-border" />
              )}
              <span
                className={cn(
                  "transition-colors duration-150",
                  done && "text-text-secondary",
                  active && "font-medium text-text-primary",
                  !done && !active && "text-text-secondary/60",
                )}
              >
                {s}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-[12px] text-text-secondary">
        生成期间可继续编辑，完成稿会保存为候选版本，不覆盖正文。
      </p>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="px-4 pb-2 pt-4 text-[12px] font-semibold uppercase tracking-wide text-text-secondary">
      {children}
    </h3>
  );
}

function ContractSummary({ contract }: { contract: WritingContract | null }) {
  if (!contract) {
    return (
      <div className="border-b border-border px-4 py-4 text-[12px] text-text-secondary">
        正在读取本章安排…
      </div>
    );
  }
  const statusMeta = {
    pass: { label: "可开始写作", className: "text-success", icon: ShieldCheck },
    warning: { label: "生成时会自动核对", className: "text-warning", icon: AlertTriangle },
    blocked: { label: "生成前自动补齐", className: "text-warning", icon: AlertTriangle },
  } as const;
  const status = statusMeta[contract.gate.status];
  const StatusIcon = status.icon;
  const directive = contract.taskbook.chapter_directive;
  const nodes = contract.taskbook.story_nodes;
  const facts = [
    ["目标", directive.goal],
    ["阻力", directive.conflict],
    ["代价", directive.cost],
    ["时间", directive.time_anchor],
    ["跨度", directive.chapter_span],
    ["章末问题", directive.chapter_end_open_question],
  ].filter(([, value]) => String(value ?? "").trim());
  const issues = [...contract.gate.blockers, ...contract.gate.warnings];
  return (
    <div className="border-b border-border">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <span className={cn("flex items-center gap-2 text-[13px] font-semibold", status.className)}>
          <StatusIcon size={15} />
          {status.label}
        </span>
      </div>
      {issues.length > 0 && (
        <ul className="border-t border-border px-4 py-2 text-[12px] leading-relaxed">
          {issues.map((item) => (
            <li key={item.code} className={contract.gate.blockers.some((blocker) => blocker.code === item.code) ? "text-danger" : "text-warning"}>
              {item.message}
            </li>
          ))}
        </ul>
      )}
      <dl className="border-t border-border px-4 py-2 text-[12px]">
        {facts.map(([label, value]) => (
          <div key={String(label)} className="grid grid-cols-[56px_1fr] gap-2 py-1">
            <dt className="text-text-secondary">{String(label)}</dt>
            <dd className="text-text-primary">{String(value)}</dd>
          </div>
        ))}
      </dl>
      {(nodes.cbn || nodes.cpns.length > 0 || nodes.cen) && (
        <div className="border-t border-border px-4 py-3 text-[12px]">
          <p className="font-medium text-text-primary">章节推进</p>
          <ol className="mt-1.5 space-y-1 text-text-secondary">
            {nodes.cbn && <li>开场 · {nodes.cbn}</li>}
            {nodes.cpns.map((item, index) => <li key={`${index}-${item}`}>推进 {index + 1} · {item}</li>)}
            {nodes.cen && <li>收束 · {nodes.cen}</li>}
          </ol>
        </div>
      )}
    </div>
  );
}

function ContextTab({ characters, locations, sources, contract }: { characters: CharacterSummary[]; locations: LocationSummary[]; sources: ContextSource[]; contract: WritingContract | null }) {
  const memorySources = sources.filter((s) => s.type === "memory" || s.type === "chapter" || !s.type);
  const chapterSources = sources.filter((s) => s.type === "chapter");
  const otherSources = sources.filter((s) => s.type && s.type !== "memory" && s.type !== "chapter");
  return (
    <div className="pb-6">
      <ContractSummary contract={contract} />
      <SectionTitle>本章人物</SectionTitle>
      <ul className="px-2">
        {characters.slice(0, 5).map((c) => (
          <li key={c.id}>
            <button className="flex w-full items-center gap-2.5 rounded-control px-2 py-2 text-left hover:bg-surface-subtle">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-subtle text-[12px] font-semibold text-text-secondary">
                <Users size={15} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-[14px] text-text-primary">
                  {c.name}
                  <span className="text-[12px] text-text-secondary">{c.role}</span>
                </span>
                <span className="block truncate text-[12px] text-text-secondary">{c.status}</span>
              </span>
              <ChevronRight size={15} className="text-text-secondary" />
            </button>
          </li>
        ))}
        {!characters.length && (
          <li className="px-2 py-2 text-[13px] text-text-secondary">故事圣经中尚无人物</li>
        )}
      </ul>

      <SectionTitle>本章地点</SectionTitle>
      <ul className="px-2">
        {locations.slice(0, 5).map((l) => (
          <li key={l.id}>
            <button className="flex w-full items-center gap-2.5 rounded-control px-2 py-2 text-left hover:bg-surface-subtle">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-subtle text-text-secondary">
                <MapPin size={15} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] text-text-primary">{l.name}</span>
                <span className="block truncate text-[12px] text-text-secondary">
                  {l.region} · {l.state}
                </span>
              </span>
              <ChevronRight size={15} className="text-text-secondary" />
            </button>
          </li>
        ))}
        {!locations.length && (
          <li className="px-2 py-2 text-[13px] text-text-secondary">故事圣经中尚无地点</li>
        )}
      </ul>

      <SectionTitle>本次记忆来源</SectionTitle>
      <p className="px-4 pb-2 text-[12px] text-text-secondary">
        生成任务完成后展示实际进入上下文的最近章与检索片段（FR-007）。
      </p>
      <ul className="flex flex-col gap-1.5 px-4 text-[13px]">
        {!sources.length && (
          <li className="text-text-secondary">尚未生成，或上下文未写入 job.result.contextSources。</li>
        )}
        {chapterSources.map((source) => (
          <li key={`ch-${source.id}`} className="flex items-start gap-2 rounded-control border border-border bg-surface px-2 py-1.5">
            <BookText size={14} className="mt-0.5 shrink-0 text-info" />
            <span>
              <span className="text-[11px] font-medium uppercase text-info">最近章</span>
              <span className="mt-0.5 block text-text-primary">{source.label}</span>
            </span>
          </li>
        ))}
        {memorySources
          .filter((s) => s.type === "memory")
          .map((source) => (
            <li key={`mem-${source.id}`} className="flex items-start gap-2 rounded-control border border-border bg-surface px-2 py-1.5">
              <BookText size={14} className="mt-0.5 shrink-0 text-primary" />
              <span>
                <span className="text-[11px] font-medium uppercase text-primary">
                  记忆
                  {source.score ? ` · ${source.score}` : ""}
                </span>
                <span className="mt-0.5 block text-text-primary">{source.label}</span>
              </span>
            </li>
          ))}
        {otherSources.map((source) => (
          <li key={`o-${source.id}`} className="flex items-start gap-2 text-text-secondary">
            <BookText size={14} className="mt-0.5 shrink-0" />
            <span>{source.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface GenerationOptions {
  goal: string;
  target_words: number;
  pace: string;
  dialogue_ratio: number;
  style_instruction: string;
  must_preserve: string[];
  must_improve: string[];
  must_not_include: string[];
}

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function AiTab({ chapter, generating, onGenerate, onOptionsChange, onRewrite }: { chapter: ChapterDetail | null; generating: boolean; onGenerate: () => void; onOptionsChange: (options: GenerationOptions) => void; onRewrite: () => void }) {
  const [ratio, setRatio] = useState(35);
  const [moreOpen, setMoreOpen] = useState(false);
  const [goal, setGoal] = useState(String(chapter?.brief.goal ?? ""));
  const [targetWords, setTargetWords] = useState(chapter?.targetWords ?? 3500);
  const [pace, setPace] = useState("均衡");
  const [style, setStyle] = useState("");
  const [preserve, setPreserve] = useState("");
  const [improve, setImprove] = useState("");
  const [forbidden, setForbidden] = useState(((chapter?.brief.forbidden_events as string[] | undefined) ?? []).join("\n"));
  const emit = (overrides: Partial<GenerationOptions> = {}) => onOptionsChange({
    goal, target_words: targetWords, pace, dialogue_ratio: ratio, style_instruction: style,
    must_preserve: lines(preserve), must_improve: lines(improve), must_not_include: lines(forbidden),
    ...overrides,
  });

  useEffect(() => {
    const nextGoal = String(chapter?.brief.goal ?? "");
    const nextTargetWords = chapter?.targetWords ?? 3500;
    const nextForbidden = ((chapter?.brief.forbidden_events as string[] | undefined) ?? []).join("\n");
    setGoal(nextGoal);
    setTargetWords(nextTargetWords);
    setPace("均衡");
    setRatio(35);
    setStyle("");
    setPreserve("");
    setImprove("");
    setForbidden(nextForbidden);
    onOptionsChange({
      goal: nextGoal,
      target_words: nextTargetWords,
      pace: "均衡",
      dialogue_ratio: 35,
      style_instruction: "",
      must_preserve: [],
      must_improve: [],
      must_not_include: lines(nextForbidden),
    });
  }, [chapter?.id]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="border-y border-border py-4">
        <p className="text-[12px] font-medium text-text-secondary">本章安排</p>
        <p className="mt-1 text-[14px] leading-6 text-text-primary">
          {String(chapter?.brief?.goal ?? goal ?? "").trim() || "生成前由 AI 自动补齐本章目标与推进方式"}
        </p>
        {Array.isArray(chapter?.brief?.must_events) && chapter.brief.must_events.length > 0 && (
          <ul className="mt-2 space-y-1 text-[12px] leading-5 text-text-secondary">
            {(chapter.brief.must_events as string[]).slice(0, 3).map((item) => (
              <li key={item}>· {item}</li>
            ))}
          </ul>
        )}
      </div>

      <Button variant="primary" icon={<Sparkles size={15} />} disabled={generating} onClick={onGenerate}>
        {generating ? "生成中…" : "生成本章"}
      </Button>

      <button
        type="button"
        onClick={() => setMoreOpen((value) => !value)}
        className="flex items-center gap-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary"
      >
        {moreOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        更多设置
      </button>
      {moreOpen && (
        <div className="flex flex-col gap-3 border-t border-border pt-4">
          <Field label="本章想达到的结果">
            <TextArea
              rows={2}
              value={goal}
              onChange={(event) => { setGoal(event.target.value); emit({ goal: event.target.value }); }}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="篇幅">
              <Select value={String(targetWords)} onChange={(event) => { const value = Number(event.target.value); setTargetWords(value); emit({ target_words: value }); }}>
                <option value="2500">短</option>
                <option value="3500">标准</option>
                <option value="4500">长</option>
              </Select>
            </Field>
            <Field label="阅读节奏">
              <Select value={pace} onChange={(event) => { setPace(event.target.value); emit({ pace: event.target.value }); }}>
                <option value="舒缓">舒缓</option>
                <option value="均衡">均衡</option>
                <option value="紧凑">紧凑</option>
              </Select>
            </Field>
          </div>
          <Field label={`对话多少 · ${ratio}%`}>
            <Slider value={ratio} onChange={(value) => { setRatio(value); emit({ dialogue_ratio: value }); }} />
          </Field>
          <Field label="原样保留">
            <TextArea rows={2} value={preserve} onChange={(event) => { setPreserve(event.target.value); emit({ must_preserve: lines(event.target.value) }); }} placeholder="每行一项" />
          </Field>
          <Field label="希望改善">
            <TextArea rows={2} value={improve} onChange={(event) => { setImprove(event.target.value); emit({ must_improve: lines(event.target.value) }); }} placeholder="每行一项" />
          </Field>
          <Field label="不要写到">
            <TextArea rows={2} value={forbidden} onChange={(event) => { setForbidden(event.target.value); emit({ must_not_include: lines(event.target.value) }); }} placeholder="每行一项" />
          </Field>
          <Field label="其他写作偏好">
            <TextArea rows={2} value={style} onChange={(event) => { setStyle(event.target.value); emit({ style_instruction: event.target.value }); }} />
          </Field>
        </div>
      )}

      <p className="text-[12px] leading-5 text-text-secondary">
        人物状态、时间连续性和章节结构会在后台自动检查；缺失部分会在生成前补齐。
      </p>

      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" icon={<Wand2 size={14} />} onClick={() => { setMoreOpen(true); setImprove("请只处理检查指出的问题，保留其余内容"); emit({ must_improve: ["请只处理检查指出的问题，保留其余内容"] }); }}>局部修改</Button>
        <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} disabled={generating} onClick={onRewrite}>整章重写</Button>
      </div>
    </div>
  );
}

type AuditIssueAction = "ignored" | "intentional";

interface AuditIssueResolution {
  action: AuditIssueAction;
  note?: string;
}

interface AuditActionNotice {
  message: string;
  issueId?: string;
  canUndo?: boolean;
  error?: boolean;
}

function AuditTab({
  audit,
  auditTarget = null,
  onAudit,
  auditBusy,
  auditError,
  hasContent,
  confirmBusy,
  confirmError,
  confirmSuccess,
  alreadyConfirmed,
  onConfirm,
  onRewrite,
  onAcceptCandidate,
  onJumpToEvidence,
  onRewriteIssue,
  writingContract,
}: {
  audit?: AuditReport;
  auditTarget?: AuditTarget | null;
  onAudit: () => void;
  auditBusy?: boolean;
  auditError?: string | null;
  hasContent: boolean;
  confirmBusy?: boolean;
  confirmError?: string | null;
  confirmSuccess?: string | null;
  alreadyConfirmed: boolean;
  onConfirm: (fatalOverrideReason?: string) => Promise<void> | void;
  onRewrite: () => void;
  onAcceptCandidate?: () => void;
  onJumpToEvidence?: (evidence: string) => boolean;
  onRewriteIssue?: (issue: AuditIssue) => Promise<void>;
  writingContract?: WritingContract | null;
}) {
  const storageKey = audit?.id ? `nove:audit-actions:${audit.id}` : "";
  const [dismissed, setDismissed] = useState<Record<string, AuditIssueResolution>>({});
  const [notice, setNotice] = useState<AuditActionNotice | null>(null);
  const [intentionalIssueId, setIntentionalIssueId] = useState<string | null>(null);
  const [intentionalNote, setIntentionalNote] = useState("");
  const [rewriteBusyId, setRewriteBusyId] = useState<string | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");

  useEffect(() => {
    setNotice(null);
    setIntentionalIssueId(null);
    setIntentionalNote("");
    setOverrideOpen(false);
    setOverrideReason("");
    if (!storageKey) {
      setDismissed({});
      return;
    }
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "{}") as Record<
        string,
        AuditIssueAction | AuditIssueResolution
      >;
      const normalized = Object.fromEntries(
        Object.entries(stored).flatMap(([issueId, value]) => {
          if (value === "ignored" || value === "intentional") {
            return [[issueId, { action: value } satisfies AuditIssueResolution]];
          }
          if (value && (value.action === "ignored" || value.action === "intentional")) {
            return [[issueId, value]];
          }
          return [];
        }),
      );
      setDismissed(normalized);
    } catch {
      setDismissed({});
      setNotice({ message: "无法读取已处理的问题记录", error: true });
    }
  }, [storageKey]);

  useEffect(() => {
    if (!confirmSuccess) return;
    setOverrideOpen(false);
    setOverrideReason("");
  }, [confirmSuccess]);

  const auditDimensions = audit?.dimensions ?? [];
  const allAuditIssues = Array.from(
    new Map(
      [...(audit?.fatalIssues ?? []), ...(audit?.issues ?? [])].map((issue) => [issue.id, issue]),
    ).values(),
  );
  const auditIssues = allAuditIssues.filter((issue) => !dismissed[issue.id]);
  const total = audit?.totalScore ?? 0;
  const fatalCount = auditIssues.filter((issue) => issue.severity === "fatal").length;
  const otherCount = auditIssues.length - fatalCount;
  const hasFatalIssues = Boolean(audit?.fatalIssues?.length);
  const needsQualityOverride = Boolean(
    hasFatalIssues ||
      (audit && audit.decision !== "PASS") ||
      (writingContract?.strict && !writingContract.ready),
  );
  const strictAuditMissing = Boolean(writingContract?.strict && !audit);
  const validOverrideReason = overrideReason.trim().length >= 8;

  const persistDismissed = (next: Record<string, AuditIssueResolution>) => {
    setDismissed(next);
    if (!storageKey) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      setNotice({ message: "操作已生效，但无法保存到浏览器", error: true });
    }
  };

  const markIssue = (issue: AuditIssue, action: AuditIssueAction, note?: string) => {
    persistDismissed({
      ...dismissed,
      [issue.id]: { action, ...(note?.trim() ? { note: note.trim() } : {}) },
    });
    setIntentionalIssueId(null);
    setIntentionalNote("");
    setNotice({
      message: action === "ignored" ? `已忽略「${issue.type}」` : `已将「${issue.type}」标记为有意设定`,
      issueId: issue.id,
      canUndo: true,
    });
  };

  const undoIssue = (issueId: string) => {
    const next = { ...dismissed };
    delete next[issueId];
    persistDismissed(next);
    setNotice({ message: "已撤销，问题已恢复" });
  };

  const locateIssue = (issue: AuditIssue) => {
    if (issue.locatable === false) {
      setNotice({ message: "这条问题引用的是大纲或上下文依据，不是当前正文原句，无法直接定位" });
      return;
    }
    if (onJumpToEvidence?.(issue.evidenceQuote || issue.evidence)) {
      setNotice({ message: `已在正文中选中「${issue.type}」的证据` });
    } else {
      setNotice({ message: "这条检查证据是概述文本，不是可定位的正文原句；请重新检查以生成精确引用", error: true });
    }
  };

  const rewriteIssue = async (issue: AuditIssue) => {
    if (!onRewriteIssue || rewriteBusyId) return;
    setRewriteBusyId(issue.id);
    setNotice(null);
    try {
      await onRewriteIssue(issue);
      setNotice({ message: "改写候选已生成，请在正文下方确认" });
    } catch (reason) {
      setNotice({
        message: reason instanceof Error ? reason.message : "生成改写候选失败",
        error: true,
      });
    } finally {
      setRewriteBusyId(null);
    }
  };

  const auditButtonLabel = auditBusy
    ? "检查中…"
    : !hasContent
      ? "暂无可检查正文"
      : audit
        ? "重新检查"
        : auditTarget?.isCandidate
          ? "检查候选"
          : "开始检查";

  return (
    <div className="flex flex-col">
      {/* Overview */}
      <div className="border-b border-border p-4">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-[13px] text-text-secondary">AI 质量检查</p>
            <p className="text-[15px] font-medium text-warning">{audit ? (audit.decision === "PASS" ? "检查通过" : audit.decision === "REVISE" ? "需要局部修改" : "需要整章重写") : "尚无检查结果"}</p>
            {auditTarget && (
              <p className="mt-1 text-[12px] text-text-secondary">
                目标：{auditTarget.label}
                {auditTarget.isCandidate ? " · AI 候选（未接受）" : " · 当前正文"}
                {" · "}
                {auditTarget.words.toLocaleString()} 字
              </p>
            )}
          </div>
          <div className="text-right">
            <p className="text-[28px] font-semibold leading-none text-text-primary">
              {audit ? total : 0}
              <span className="text-[16px] text-text-secondary"> / 100</span>
            </p>
          </div>
        </div>
        {auditTarget?.isCandidate && (
          <p className="mt-3 rounded-control border border-primary/20 bg-primary/5 px-3 py-2 text-[12px] leading-relaxed text-text-secondary">
            当前显示的是 AI 候选版本的检查结果。接受候选后才会写入正式正文；也可直接重新检查。
          </p>
        )}
        {!hasContent && (
          <p className="mt-3 rounded-control border border-border bg-surface-subtle px-3 py-2 text-[12px] leading-relaxed text-text-secondary">
            还没有可检查的正文。请先生成 AI 草稿，或在编辑器中写入并保存当前版本。
          </p>
        )}
      </div>

      {/* Dimensions */}
      <div className="flex flex-col gap-2.5 border-b border-border p-4">
        {auditDimensions.map((d) => {
          const pct = (d.score / d.max) * 100;
          return (
            <div key={d.name} className="flex items-center gap-3">
              <span className="w-20 shrink-0 text-[13px] text-text-secondary">{d.name}</span>
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
                {d.score} / {d.max}
              </span>
            </div>
          );
        })}
        {!audit && hasContent && (
          <p className="text-[12px] text-text-secondary">该版本尚未检查，点击下方按钮开始。</p>
        )}
      </div>

      {/* Issue counts + actions */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 text-[13px]">
        <span className="text-text-secondary">
          严重问题 <span className="font-semibold text-danger">{fatalCount}</span> · 一般问题{" "}
          <span className="font-semibold text-text-primary">{otherCount}</span>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 border-b border-border p-4">
        <Button variant="secondary" size="sm" icon={auditBusy ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} disabled={auditBusy || !hasContent} onClick={onAudit}>
          {auditButtonLabel}
        </Button>
        <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />} onClick={onRewrite}>
          整章重写
        </Button>
      </div>
      {auditTarget?.isCandidate && onAcceptCandidate && (
        <div className="border-b border-border px-4 py-3">
          <Button variant="primary" size="sm" className="w-full" onClick={onAcceptCandidate}>
            接受此候选为正文
          </Button>
        </div>
      )}
      {auditError && (
        <div className="border-b border-[#FECACA] bg-[#FEF2F2] px-4 py-2 text-[12px] text-danger" role="alert">
          {auditError}
        </div>
      )}
      {notice && (
        <div
          className={cn(
            "flex items-center justify-between gap-3 border-b px-4 py-2 text-[12px]",
            notice.error
              ? "border-[#FECACA] bg-[#FEF2F2] text-danger"
              : "border-primary/20 bg-primary/5 text-text-primary",
          )}
          role={notice.error ? "alert" : "status"}
        >
          <span>{notice.message}</span>
          {notice.canUndo && notice.issueId && (
            <button
              type="button"
              className="shrink-0 font-medium text-primary hover:underline"
              onClick={() => undoIssue(notice.issueId!)}
            >
              撤销
            </button>
          )}
        </div>
      )}
      <div className="border-b border-border p-4">
        <Button
          variant="primary"
          size="sm"
          className="w-full"
          icon={confirmBusy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          disabled={confirmBusy || alreadyConfirmed || Boolean(auditTarget?.isCandidate) || !hasContent || strictAuditMissing}
          aria-busy={confirmBusy}
          onClick={() => {
            if (needsQualityOverride) {
              setOverrideOpen(true);
              return;
            }
            void onConfirm();
          }}
        >
          {confirmBusy
            ? "确认中…"
            : alreadyConfirmed
              ? "当前版本已确认"
              : auditTarget?.isCandidate
                ? "请先接受候选再确认"
                : "确认当前版本"}
        </Button>
        {strictAuditMissing && (
          <p className="mt-2 text-[12px] text-warning">质量保护要求当前版本先完成检查。</p>
        )}
        {overrideOpen && needsQualityOverride && (
          <div className="mt-3 rounded-control border border-[#FECACA] bg-[#FEF2F2] p-3">
            <p className="text-[12px] font-medium text-danger">
              {hasFatalIssues ? "当前检查仍有严重问题" : "当前版本未通过质量检查"}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-text-secondary">
              建议先处理阻断或非通过项。若仍需确认，请填写至少 8 个字符的理由，记录会随版本保存。
            </p>
            <label htmlFor="fatal-override-reason" className="mt-3 block text-[12px] font-medium text-text-primary">
              确认理由
            </label>
            <textarea
              id="fatal-override-reason"
              rows={3}
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
              placeholder="说明为何仍要确认这个版本"
              className="mt-1.5 w-full resize-y rounded-control border border-border bg-surface px-2.5 py-2 text-[13px] text-text-primary outline-none focus:border-primary"
              autoFocus
            />
            <div className="mt-2 flex items-center justify-between gap-3">
              <span className="text-[11px] text-text-secondary">{overrideReason.trim().length} / 8</span>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={confirmBusy}
                  onClick={() => {
                    setOverrideOpen(false);
                    setOverrideReason("");
                  }}
                >
                  取消
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={confirmBusy || !validOverrideReason}
                  onClick={() => void onConfirm(overrideReason.trim())}
                >
                  仍然确认
                </Button>
              </div>
            </div>
          </div>
        )}
        {confirmError && (
          <p className="mt-2 rounded-control border border-[#FECACA] bg-[#FEF2F2] px-3 py-2 text-[12px] text-danger" role="alert">
            {confirmError}
          </p>
        )}
        {confirmSuccess && (
          <p className="mt-2 rounded-control border border-success/30 bg-success/5 px-3 py-2 text-[12px] text-text-primary" role="status">
            {confirmSuccess}
          </p>
        )}
      </div>

      {/* Issues — fatal pinned first */}
      <ul className="flex flex-col divide-y divide-border">
        {auditIssues.map((issue) => {
          const meta = severityMeta[issue.severity];
          return (
            <li key={issue.id} className="p-4">
              <div className="mb-1.5 flex items-center gap-2">
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[11px] font-semibold",
                    issue.severity === "fatal" && "bg-[#FEF2F2] text-danger",
                    issue.severity === "major" && "bg-[#FEF3C7] text-warning",
                    issue.severity === "minor" && "bg-[#EFF6FF] text-info",
                  )}
                >
                  {meta.label}
                </span>
                <span className="text-[13px] font-medium text-text-primary">{issue.type}</span>
              </div>
              <p className="text-[13px] italic text-text-secondary">“{issue.evidence}”</p>
              {issue.evidenceSource && (
                <p className="mt-1 text-[11px] text-text-secondary">
                  证据来源：{issue.evidenceSource === "content" ? "当前正文" : issue.evidenceSource === "outline" ? "章节大纲" : "上下文记忆"}
                </p>
              )}
              <p className="mt-1 text-[12px] text-text-secondary">冲突：{issue.conflictsWith}</p>
              <p className="mt-1 text-[13px] text-text-primary">建议：{issue.suggestion}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
                {issue.locatable !== false && (
                  <>
                    <button
                      type="button"
                      onClick={() => locateIssue(issue)}
                      className="rounded-control border border-border px-2 py-1 text-text-secondary hover:bg-surface-subtle"
                    >
                      定位正文
                    </button>
                    <button
                      type="button"
                      className="rounded-control border border-border px-2 py-1 text-primary hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={rewriteBusyId !== null}
                      onClick={() => void rewriteIssue(issue)}
                    >
                      {rewriteBusyId === issue.id ? "改写中…" : "去改写"}
                    </button>
                  </>
                )}
                <button
                  type="button"
                  className="rounded-control border border-border px-2 py-1 text-text-secondary hover:bg-surface-subtle"
                  onClick={() => markIssue(issue, "ignored")}
                >
                  忽略一次
                </button>
                <button
                  type="button"
                  className="rounded-control border border-border px-2 py-1 text-text-secondary hover:bg-surface-subtle"
                  aria-expanded={intentionalIssueId === issue.id}
                  onClick={() => {
                    setIntentionalIssueId(issue.id);
                    setIntentionalNote("");
                    setNotice(null);
                  }}
                >
                  标记为有意设定
                </button>
              </div>
              {intentionalIssueId === issue.id && (
                <div className="mt-3 rounded-control border border-border bg-surface-subtle p-3">
                  <label htmlFor={`intentional-note-${issue.id}`} className="text-[12px] font-medium text-text-primary">
                    设定说明
                  </label>
                  <textarea
                    id={`intentional-note-${issue.id}`}
                    rows={3}
                    value={intentionalNote}
                    onChange={(event) => setIntentionalNote(event.target.value)}
                    placeholder="说明这是有意安排的原因，或需要更新的权威事实"
                    className="mt-1.5 w-full resize-y rounded-control border border-border bg-surface px-2.5 py-2 text-[13px] text-text-primary outline-none focus:border-primary"
                    autoFocus
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setIntentionalIssueId(null);
                        setIntentionalNote("");
                      }}
                    >
                      取消
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={!intentionalNote.trim()}
                      onClick={() => markIssue(issue, "intentional", intentionalNote)}
                    >
                      确认标记
                    </Button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function VersionTab({ versions, versionBusyId, onRestore, onAccept, onDelete }: { versions: ChapterVersion[]; versionBusyId: string | null; onRestore: (versionId: string) => void; onAccept: (versionId: string) => void; onDelete: (versionId: string) => void }) {
  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <h3 className="text-[13px] font-semibold text-text-primary">版本历史</h3>
        <span className="text-[12px] text-text-secondary">{versions.length} 个版本</span>
      </div>
      <ul className="flex flex-col divide-y divide-border">
        {versions.map((v) => (
          <li key={v.id} className="border-b border-border">
            <VersionRow version={v} compact />
            {!v.current && (
              <div className="flex gap-2 px-4 pb-3">
                {(v.source === "generate" || v.source === "revise" || v.source === "rewrite") && <Button size="sm" variant="primary" disabled={versionBusyId !== null} onClick={() => onAccept(v.id)}>{versionBusyId === `accept:${v.id}` ? "接受中…" : "接受候选"}</Button>}
                <Button size="sm" variant="secondary" disabled={versionBusyId !== null} onClick={() => onRestore(v.id)}>{versionBusyId === `restore:${v.id}` ? "恢复中…" : "恢复此版本"}</Button>
                <Button size="sm" variant="danger" icon={<Trash2 size={14} />} disabled={versionBusyId !== null} onClick={() => onDelete(v.id)}>{versionBusyId === `delete:${v.id}` ? "删除中…" : "删除"}</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
