import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { FileText, List, PanelRightClose, ShieldCheck, X } from "lucide-react";
import {
  apiRequest,
  jobEventsUrl,
  useApiQuery,
  type AuditIssue,
  type AuditConfig,
  type AuditReport,
  type Chapter,
  type ChapterDetail,
  type ChapterVersion,
  type CharacterSummary,
  type GenerationJob,
  type LocationSummary,
  type ModelConfig,
  type WritingContract,
} from "@/lib/api";
import { findAuditForVersion, resolveAuditTarget } from "@/lib/audit-target";
import { ChapterList } from "./writing/ChapterList";
import { EditorPane } from "./writing/EditorPane";
import type { EvidenceSelectionRequest, SelectionCandidate, SelectionOp } from "./writing/EditorPane";
import { RightPanel } from "./writing/RightPanel";
import type { GenerationOptions } from "./writing/RightPanel";
import { useWorkspaceStore } from "@/stores/workspace";
import { findEvidenceOffset } from "@/lib/text-marks";
import { cn } from "@/lib/cn";
import {
  chapterGenerationPath,
  type ChapterGenerationOperation,
} from "@/lib/chapter-generation";

/**
 * The writing workspace (§8) — the product's centerpiece. Three columns:
 * chapter list, editor, and a tabbed right panel. `?generating=1` starts in the
 * AI generating state (§9) without locking the editor.
 */
export function WritingWorkspacePage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const { data: chapters, refetch: refetchChapters } = useApiQuery<Chapter[]>(id ? `/novels/${id}/chapters` : null, []);
  const [activeChapter, setActiveChapter] = useState("");
  const [mobilePane, setMobilePane] = useState<"chapters" | "editor" | "contract">("editor");
  const chapterQuery = useApiQuery<ChapterDetail>(activeChapter ? `/chapters/${activeChapter}` : null, null as unknown as ChapterDetail);
  const { data: versions, refetch: refetchVersions } = useApiQuery<ChapterVersion[]>(activeChapter ? `/chapters/${activeChapter}/versions` : null, []);
  const {
    data: audits,
    refetch: refetchAudits,
    setData: setAudits,
  } = useApiQuery<AuditReport[]>(activeChapter ? `/chapters/${activeChapter}/audits` : null, []);
  const writingContractQuery = useApiQuery<WritingContract>(
    activeChapter ? `/chapters/${activeChapter}/writing-contract` : null,
    null as unknown as WritingContract,
  );
  const { data: characters } = useApiQuery<CharacterSummary[]>(id ? `/novels/${id}/characters` : null, []);
  const { data: locations } = useApiQuery<LocationSummary[]>(id ? `/novels/${id}/locations` : null, []);
  const { data: novelModels } = useApiQuery<ModelConfig[]>(id ? `/novels/${id}/models` : null, []);
  const { data: auditConfig } = useApiQuery<AuditConfig>(
    id ? `/novels/${id}/audit-config` : null,
    { passScore: 85, reviseScore: 70, maxRewriteAttempts: 1, autoAudit: true, autoRevise: true, autoRewrite: true, fatalIssueForceRewrite: true, dimensions: [] },
  );
  const { data: memoryStatus } = useApiQuery<{
    hasNeuralEmbedding?: boolean;
    embeddingMode?: string;
    embeddingModelId?: string;
  }>(id ? `/novels/${id}/memory/status` : null, {});
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [dirty, setDirty] = useState(false);
  const [savingVersion, setSavingVersion] = useState(false);
  const [embedBannerDismissed, setEmbedBannerDismissed] = useState(false);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [generatingStage, setGeneratingStage] = useState(0);
  const [generationPreview, setGenerationPreview] = useState<string | null>(null);
  const [generationTyping, setGenerationTyping] = useState(false);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [selectionGuidance, setSelectionGuidance] = useState<string | null>(null);
  const [auditBusy, setAuditBusy] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [bulkAudit, setBulkAudit] = useState({
    busy: false,
    completed: 0,
    total: 0,
    failed: 0,
    error: null as string | null,
  });
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmSuccess, setConfirmSuccess] = useState<string | null>(null);
  const [versionBusyId, setVersionBusyId] = useState<string | null>(null);
  const [selectionCandidate, setSelectionCandidate] = useState<SelectionCandidate | null>(null);
  const [evidenceSelection, setEvidenceSelection] = useState<EvidenceSelectionRequest | null>(null);
  const [generationOptions, setGenerationOptions] = useState<GenerationOptions>({
    goal: "", target_words: 3500, pace: "均衡", dialogue_ratio: 35, style_instruction: "",
    must_preserve: [], must_improve: [], must_not_include: [],
  });
  const editRevision = useRef(0);
  const dirtyRef = useRef(false);
  const chapterRef = useRef<ChapterDetail | null>(null);
  const contentRef = useRef("");
  const titleRef = useRef("");
  const saveInFlight = useRef<Promise<ChapterDetail | null> | null>(null);
  const generationCharsRef = useRef<string[]>([]);
  const generationCharIndexRef = useRef(0);
  const generationPreviewRef = useRef("");
  const generationFrameRef = useRef<number | null>(null);
  const evidenceSelectionRequestId = useRef(0);
  const {
    leftOpen, rightOpen, rightTab, focusMode,
    setLeftOpen, setRightOpen, setRightTab, setChapterLabel, setSaveState,
  } = useWorkspaceStore();

  const generating = job?.state === "PENDING" || job?.state === "RUNNING";

  const resetGenerationPreview = useCallback((next: string | null = null) => {
    if (generationFrameRef.current != null) {
      window.cancelAnimationFrame(generationFrameRef.current);
      generationFrameRef.current = null;
    }
    generationCharsRef.current = [];
    generationCharIndexRef.current = 0;
    generationPreviewRef.current = next ?? "";
    setGenerationPreview(next);
    setGenerationTyping(false);
  }, []);

  const enqueueGenerationDelta = useCallback((delta: string) => {
    if (!delta) return;
    generationCharsRef.current.push(...Array.from(delta));
    setGenerationTyping(true);
    if (generationFrameRef.current != null) return;

    const typeNextCharacter = () => {
      const index = generationCharIndexRef.current;
      const character = generationCharsRef.current[index];
      if (character === undefined) {
        generationFrameRef.current = null;
        generationCharsRef.current = [];
        generationCharIndexRef.current = 0;
        setGenerationTyping(false);
        return;
      }
      generationCharIndexRef.current = index + 1;
      generationPreviewRef.current += character;
      setGenerationPreview(generationPreviewRef.current);
      generationFrameRef.current = window.requestAnimationFrame(typeNextCharacter);
    };

    generationFrameRef.current = window.requestAnimationFrame(typeNextCharacter);
  }, []);

  useEffect(() => () => {
    if (generationFrameRef.current != null) {
      window.cancelAnimationFrame(generationFrameRef.current);
    }
  }, []);

  const hasEmbeddingRole = novelModels.some(
    (m) =>
      m.status === "connected" &&
      (m.roles || []).some((r) => r === "Embedding" || r.toLowerCase() === "embedding") &&
      Boolean(m.baseUrl?.trim()),
  );
  const hasNeuralEmbedding =
    memoryStatus.hasNeuralEmbedding === true || hasEmbeddingRole;
  const showEmbedBanner =
    Boolean(id) && !hasNeuralEmbedding && !embedBannerDismissed && !focusMode;

  useEffect(() => {
    if (!id) return;
    setEmbedBannerDismissed(
      sessionStorage.getItem(`nove:embed-banner-dismissed:${id}`) === "1",
    );
  }, [id]);

  useEffect(() => {
    const requested = params.get("chapter");
    if (requested && chapters.some((chapter) => chapter.id === requested)) {
      if (activeChapter !== requested) setActiveChapter(requested);
      return;
    }
    if (!activeChapter && chapters.length) setActiveChapter(chapters[0].id);
  }, [activeChapter, chapters, params]);

  useEffect(() => {
    setConfirmBusy(false);
    setConfirmError(null);
    setConfirmSuccess(null);
  }, [activeChapter]);

  useEffect(() => {
    const chapter = chapterQuery.data;
    if (chapter?.id) {
      setChapterLabel(`第 ${chapter.index} 章 · ${chapter.title}`);
    } else {
      setChapterLabel(undefined);
    }
  }, [chapterQuery.data, setChapterLabel]);

  useEffect(() => {
    const chapter = chapterQuery.data;
    if (chapter?.id !== activeChapter) return;
    chapterRef.current = chapter;
    if (dirtyRef.current) return;
    const local = localStorage.getItem(`nove:draft:${chapter.id}`);
    let recovered: { content: string; title: string; baseVersionId: string | null } | null = null;
    try { recovered = local ? JSON.parse(local) : null; } catch { recovered = null; }
    const useRecovery = recovered?.baseVersionId === chapter.currentVersionId && recovered.content !== chapter.content;
    const nextContent = useRecovery ? recovered!.content : (chapter.content ?? "");
    const nextTitle = useRecovery ? recovered!.title : (chapter.title ?? "");
    contentRef.current = nextContent;
    titleRef.current = nextTitle;
    setContent(nextContent);
    setTitle(nextTitle);
    dirtyRef.current = Boolean(useRecovery);
    setDirty(Boolean(useRecovery));
    editRevision.current += 1;
    setSaveState(useRecovery ? "offline" : "saved");
  }, [activeChapter, chapterQuery.data, setSaveState]);

  const saveNow = useCallback(async () => {
    if (saveInFlight.current) await saveInFlight.current;
    const chapter = chapterRef.current;
    if (!chapter?.id || !dirtyRef.current) return chapter;
    const savingRevision = editRevision.current;
    const savingContent = contentRef.current;
    const savingTitle = titleRef.current;
    const savingLockedRanges = chapter.lockedRanges ?? [];
    // Avoid creating empty user versions when editor only re-serialized the same text.
    if (
      savingContent === (chapter.content ?? "") &&
      savingTitle === (chapter.title ?? "") &&
      JSON.stringify(savingLockedRanges) === JSON.stringify(chapter.lockedRanges ?? [])
    ) {
      dirtyRef.current = false;
      setDirty(false);
      setSaveState("saved");
      localStorage.removeItem(`nove:draft:${chapter.id}`);
      return chapter;
    }
    setSaveState("saving");
    const request = (async () => {
      const result = await apiRequest<{ chapter: ChapterDetail }>(`/chapters/${chapter.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: savingTitle,
          content: savingContent,
          base_version_id: chapter.currentVersionId,
          source: "user",
          locked_ranges: savingLockedRanges,
        }),
      });
      const unchanged = editRevision.current === savingRevision;
      const nextChapter = unchanged ? result.chapter : {
        ...result.chapter,
        title: titleRef.current,
        content: contentRef.current,
      };
      chapterRef.current = nextChapter;
      if (editRevision.current === savingRevision) {
        dirtyRef.current = false;
        setDirty(false);
        setSaveState("saved");
        localStorage.removeItem(`nove:draft:${chapter.id}`);
      }
      chapterQuery.setData(nextChapter);
      await Promise.all([refetchChapters(), refetchVersions()]);
      return nextChapter;
    })();
    saveInFlight.current = request;
    try {
      return await request;
    } catch (reason) {
      setSaveState("error");
      throw reason;
    } finally {
      if (saveInFlight.current === request) saveInFlight.current = null;
    }
  }, [chapterQuery]);

  useEffect(() => {
    const chapter = chapterRef.current;
    if (!dirty || !chapter?.id) return;
    localStorage.setItem(`nove:draft:${chapter.id}`, JSON.stringify({
      content,
      title,
      baseVersionId: chapter.currentVersionId,
      savedAt: new Date().toISOString(),
    }));
  }, [content, dirty, title]);

  const selectChapter = async (chapterId: string) => {
    if (chapterId === activeChapter) return;
    if (
      dirtyRef.current &&
      !window.confirm("当前修改尚未保存为版本。切换后会保留本机草稿，确定继续吗？")
    ) {
      return;
    }
    resetGenerationPreview();
    dirtyRef.current = false;
    setDirty(false);
    chapterRef.current = null;
    setActiveChapter(chapterId);
  };

  const createChapter = async () => {
    if (!id) return;
    try {
      if (
        dirtyRef.current &&
        !window.confirm("当前修改尚未保存为版本。新建章节后草稿仍会保留，确定继续吗？")
      ) {
        return;
      }
      resetGenerationPreview();
      const title = window.prompt("章节标题", "未命名")?.trim();
      if (!title) return;
      const chapter = await apiRequest<ChapterDetail>(`/novels/${id}/chapters`, { method: "POST", body: JSON.stringify({ title, target_words: 3500, brief: { goal: "", must_events: [], forbidden_events: [] } }) });
      await refetchChapters();
      dirtyRef.current = false;
      chapterRef.current = null;
      setActiveChapter(chapter.id);
    } catch { setSaveState("error"); }
  };

  const watchJob = (nextJob: GenerationJob) => {
    setJob(nextJob);
    const source = new EventSource(jobEventsUrl(nextJob.id));
    source.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      setGeneratingStage(payload.index ?? 0);
      setJob((current) => current ? { ...current, state: "RUNNING", stage: payload.stage } : current);
    });
    source.addEventListener("content_delta", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      enqueueGenerationDelta(String(payload.delta ?? ""));
    });
    source.addEventListener("content_reset", () => {
      resetGenerationPreview("");
    });
    const finish = async (event: Event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      source.close();
      const completed = payload.type === "completed";
      setJob((current) => current ? {
        ...current,
        state: completed ? "COMPLETED" : payload.type === "cancelled" ? "CANCELLED" : "FAILED",
        result: payload.result ?? current.result,
        error: payload.error ?? current.error,
      } : current);
      const next = new URLSearchParams(params);
      next.delete("generating");
      setParams(next, { replace: true });
      await Promise.all([refetchChapters(), refetchVersions(), refetchAudits()]);
      // Prefer audit tab when auto-audit produced a result for the candidate.
      const hasAudit = Boolean(payload.result?.auditId || payload.result?.versionId);
      setRightTab(completed && hasAudit ? "audit" : "version");
    };
    source.addEventListener("completed", finish);
    source.addEventListener("failed", finish);
    source.addEventListener("cancelled", finish);
  };

  const startGeneration = async (operation: ChapterGenerationOperation = "generate") => {
    if (dirtyRef.current) {
      window.alert("正文有未保存修改，请先点击“保存版本”再生成。");
      return;
    }
    const chapter = chapterRef.current;
    if (!chapter?.id) return;
    const nextJob = await apiRequest<GenerationJob>(chapterGenerationPath(chapter.id, operation), {
      method: "POST",
      body: JSON.stringify({
        base_version_id: chapter.currentVersionId,
        ...generationOptions,
        goal: generationOptions.goal || String(chapter.brief.goal ?? ""),
        target_words: generationOptions.target_words || chapter.targetWords,
        auto_audit: auditConfig.autoAudit,
      }),
    });
    const next = new URLSearchParams(params);
    next.set("generating", "1");
    setParams(next, { replace: true });
    setGeneratingStage(0);
    resetGenerationPreview("");
    setRightTab("ai");
    setRightOpen(true);
    watchJob(nextJob);
  };

  const toggleGenerate = () => {
    if (generating && job) {
      apiRequest(`/jobs/${job.id}/cancel`, { method: "POST" }).catch(() => undefined);
    } else {
      startGeneration("generate").catch(() => setSaveState("error"));
    }
  };

  const auditTarget = useMemo(
    () =>
      resolveAuditTarget({
        chapter: chapterQuery.data?.id ? chapterQuery.data : null,
        versions,
        job,
      }),
    [chapterQuery.data, versions, job],
  );

  const activeAudit = useMemo(
    () => findAuditForVersion(audits, auditTarget?.versionId),
    [audits, auditTarget?.versionId],
  );

  const runAudit = async () => {
    if (auditBusy) return;
    setAuditBusy(true);
    setAuditError(null);
    try {
      if (dirtyRef.current && !auditTarget?.isCandidate) {
        setAuditError("正文有未保存修改，请先保存版本再检查");
        return;
      }
      const chapter = chapterRef.current;
      if (!chapter?.id) return;
      const target = resolveAuditTarget({ chapter, versions, job });
      if (!target) {
        setAuditError("没有可检查的正文。请先生成 AI 候选，或写入并保存当前版本。");
        return;
      }
      const result = await apiRequest<AuditReport>(
        `/chapters/${chapter.id}/versions/${target.versionId}/audit`,
        { method: "POST" },
      );
      setAudits((current) => [result, ...current.filter((item) => item.id !== result.id)]);
      await Promise.all([refetchAudits(), refetchChapters(), refetchVersions()]);
      setRightTab("audit");
    } catch (reason) {
      setAuditError(reason instanceof Error ? reason.message : "重新检查失败");
      throw reason;
    } finally {
      setAuditBusy(false);
    }
  };

  const auditPendingChapters = async () => {
    if (bulkAudit.busy) return;
    setBulkAudit({ busy: true, completed: 0, total: 0, failed: 0, error: null });
    try {
      if (dirtyRef.current) {
        setBulkAudit({
          busy: false,
          completed: 0,
          total: 0,
          failed: 0,
          error: "当前章节有未保存修改，请先保存版本再批量检查",
        });
        return;
      }
      const latestChapters = await refetchChapters();
      const targets = latestChapters.filter((chapter) => chapter.needsCheck && chapter.words > 0);
      setBulkAudit({ busy: true, completed: 0, total: targets.length, failed: 0, error: null });
      let failed = 0;
      for (let index = 0; index < targets.length; index += 1) {
        try {
          await apiRequest<AuditReport>(`/chapters/${targets[index].id}/audit`, { method: "POST" });
        } catch {
          failed += 1;
        }
        setBulkAudit({
          busy: true,
          completed: index + 1,
          total: targets.length,
          failed,
          error: null,
        });
      }
      await Promise.all([refetchChapters(), refetchAudits(), refetchVersions()]);
      setBulkAudit({
        busy: false,
        completed: targets.length,
        total: targets.length,
        failed,
        error: failed ? `${failed} 章检查失败，可再次执行重试` : null,
      });
    } catch (reason) {
      setBulkAudit((current) => ({
        ...current,
        busy: false,
        error: reason instanceof Error ? reason.message : "批量检查失败",
      }));
    }
  };

  const confirm = async (fatalOverrideReason?: string) => {
    if (confirmBusy) return;
    setConfirmBusy(true);
    setConfirmError(null);
    setConfirmSuccess(null);
    try {
      if (dirtyRef.current) {
        setConfirmError("正文有未保存修改，请先保存版本再确认");
        return;
      }
      const current = chapterRef.current;
      if (!current?.id) throw new Error("当前没有可确认的章节版本");
      const chapter = await apiRequest<ChapterDetail>(`/chapters/${current.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({
          fatal_override_reason: fatalOverrideReason?.trim() || null,
          gate_override_reason: fatalOverrideReason?.trim() || null,
        }),
      });
      chapterRef.current = chapter;
      chapterQuery.setData(chapter);
      await Promise.all([refetchChapters(), refetchVersions(), refetchAudits()]);
      setConfirmSuccess("当前版本已确认，并已写入章节记忆");
      setSaveState("saved");
    } catch (reason) {
      setConfirmError(reason instanceof Error ? reason.message : "确认当前版本失败");
      setSaveState("error");
    } finally {
      setConfirmBusy(false);
    }
  };

  const accept = async (versionId: string) => {
    if (versionBusyId) return;
    if (dirtyRef.current && !window.confirm("当前未保存修改将被放弃，确定接受这个候选版本吗？")) return;
    setVersionBusyId(`accept:${versionId}`);
    const hadDirtyDraft = dirtyRef.current;
    dirtyRef.current = false;
    setDirty(false);
    try {
      if (saveInFlight.current) await saveInFlight.current;
      const current = chapterRef.current;
      if (!current?.id) return;
      const chapter = await apiRequest<ChapterDetail>(`/chapters/${current.id}/versions/${versionId}/accept`, {
        method: "POST",
      });
      chapterRef.current = chapter;
      contentRef.current = chapter.content;
      titleRef.current = chapter.title;
      chapterQuery.setData(chapter);
      setContent(chapter.content);
      setTitle(chapter.title);
      editRevision.current += 1;
      resetGenerationPreview();
      localStorage.removeItem(`nove:draft:${current.id}`);
      await Promise.all([refetchChapters(), refetchVersions(), refetchAudits()]);
      setRightTab("audit");
    } catch (reason) {
      if (hadDirtyDraft) {
        dirtyRef.current = true;
        setDirty(true);
      }
      throw reason;
    } finally {
      setVersionBusyId(null);
    }
  };

  const restore = async (versionId: string) => {
    if (!activeChapter || versionBusyId) return;
    if (dirtyRef.current && !window.confirm("当前未保存修改将被放弃，确定恢复这个历史版本吗？")) return;
    setVersionBusyId(`restore:${versionId}`);
    const hadDirtyDraft = dirtyRef.current;
    dirtyRef.current = false;
    setDirty(false);
    try {
      if (saveInFlight.current) await saveInFlight.current;
      const result = await apiRequest<{ chapter: ChapterDetail }>(`/chapters/${activeChapter}/versions/${versionId}/restore`, {
        method: "POST",
        body: JSON.stringify({ current_content: null }),
      });
      chapterRef.current = result.chapter;
      contentRef.current = result.chapter.content;
      titleRef.current = result.chapter.title;
      chapterQuery.setData(result.chapter);
      setContent(result.chapter.content);
      setTitle(result.chapter.title);
      resetGenerationPreview();
      localStorage.removeItem(`nove:draft:${activeChapter}`);
      await Promise.all([refetchChapters(), refetchVersions(), refetchAudits()]);
    } catch (reason) {
      if (hadDirtyDraft) {
        dirtyRef.current = true;
        setDirty(true);
      }
      throw reason;
    } finally {
      setVersionBusyId(null);
    }
  };

  const deleteVersion = async (versionId: string) => {
    if (!activeChapter || versionBusyId) return;
    if (!window.confirm("确定删除这个版本吗？删除后无法恢复。")) return;
    setVersionBusyId(`delete:${versionId}`);
    try {
      await apiRequest(`/chapters/${activeChapter}/versions/${versionId}`, { method: "DELETE" });
      await Promise.all([refetchChapters(), refetchVersions(), refetchAudits()]);
    } finally {
      setVersionBusyId(null);
    }
  };

  const runSelectionEdit = async (payload: {
    operation: SelectionOp;
    start: number;
    end: number;
    selectedText: string;
    content: string;
    instruction?: string;
    guidance?: string;
  }) => {
    const chapter = chapterRef.current;
    if (!chapter?.id) return;
    setSelectionBusy(true);
    setSelectionError(null);
    setSelectionCandidate(null);
    setSelectionGuidance(payload.guidance ?? null);
    try {
      const result = await apiRequest<{
        operation: SelectionOp;
        start: number;
        end: number;
        originalText: string;
        candidateText: string;
        mergedContent: string;
        modelName?: string;
      }>(`/chapters/${chapter.id}/selection-edit`, {
        method: "POST",
        body: JSON.stringify({
          operation: payload.operation,
          start: payload.start,
          end: payload.end,
          selected_text: payload.selectedText,
          content: payload.content,
          instruction: payload.instruction ?? "",
          base_version_id: chapter.currentVersionId,
        }),
      });
      setSelectionCandidate({
        operation: result.operation,
        start: result.start,
        end: result.end,
        originalText: result.originalText,
        candidateText: result.candidateText,
        mergedContent: result.mergedContent,
        modelName: result.modelName,
      });
    } catch (reason) {
      setSelectionError(reason instanceof Error ? reason.message : "选区 AI 请求失败");
      throw reason;
    } finally {
      setSelectionBusy(false);
    }
  };

  const acceptSelection = () => {
    if (!selectionCandidate) return;
    contentRef.current = selectionCandidate.mergedContent;
    setContent(selectionCandidate.mergedContent);
    dirtyRef.current = true;
    setDirty(true);
    editRevision.current += 1;
    setSelectionCandidate(null);
    setSelectionError(null);
    setSelectionGuidance(null);
  };

  const rejectSelection = () => {
    setSelectionCandidate(null);
    setSelectionError(null);
    setSelectionGuidance(null);
  };

  const selectEvidence = (evidence: string) => {
    const range = findEvidenceOffset(contentRef.current, evidence);
    if (!range) return null;
    evidenceSelectionRequestId.current += 1;
    setEvidenceSelection({ ...range, requestId: evidenceSelectionRequestId.current });
    return range;
  };

  const jumpToEvidence = (evidence: string) => Boolean(selectEvidence(evidence));

  const rewriteAuditIssue = async (issue: AuditIssue) => {
    const range = selectEvidence(issue.evidenceQuote || issue.evidence);
    if (!range) throw new Error("这条检查证据不是可定位的正文原句，请重新检查后再局部改写");
    const currentContent = contentRef.current;
    await runSelectionEdit({
      operation: "rewrite",
      start: range.start,
      end: range.end,
      selectedText: currentContent.slice(range.start, range.end),
      content: currentContent,
      guidance: issue.suggestion,
      instruction: `严格参考以下质量建议改写选中内容，只修改问题相关部分并保留其余信息：${issue.suggestion}`,
    });
  };

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {showEmbedBanner && (
        <div
          className="flex shrink-0 items-start gap-3 border-b border-[#FDE68A] bg-[#FFFBEB] px-4 py-2.5 text-[13px] text-text-primary"
          role="status"
        >
          <div className="min-w-0 flex-1 leading-relaxed">
            <span className="font-medium">智能记忆正在使用基础模式</span>
            <span className="text-text-secondary">
              {" "}
              — 不影响写作与保存；连接专用模型后，较早章节的细节检索会更准确。
            </span>
            <Link
              to={id ? `/novel/${id}/settings` : "/settings"}
              className="ml-2 shrink-0 font-medium text-primary underline-offset-2 hover:underline"
            >
              提升记忆效果 →
            </Link>
          </div>
          <button
            type="button"
            className="shrink-0 rounded p-1 text-text-secondary hover:bg-black/5 hover:text-text-primary"
            aria-label="关闭提示"
            onClick={() => {
              if (id) sessionStorage.setItem(`nove:embed-banner-dismissed:${id}`, "1");
              setEmbedBannerDismissed(true);
            }}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {!focusMode && (
        <div className="grid shrink-0 grid-cols-3 gap-1 border-b border-border bg-surface p-1 md:hidden" aria-label="写作视图">
          {[
            { key: "chapters", label: "章节", icon: List },
            { key: "editor", label: "正文", icon: FileText },
            { key: "contract", label: "章节安排", icon: ShieldCheck },
          ].map((item) => {
            const Icon = item.icon;
            const active = mobilePane === item.key;
            return (
              <button
                key={item.key}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  const pane = item.key as "chapters" | "editor" | "contract";
                  setMobilePane(pane);
                  if (pane === "contract") setRightTab("context");
                }}
                className={cn(
                  "flex h-10 items-center justify-center gap-1.5 rounded-control text-[13px]",
                  active ? "bg-surface-subtle font-medium text-primary" : "text-text-secondary",
                )}
              >
                <Icon size={15} />
                {item.label}
              </button>
            );
          })}
        </div>
      )}
      <div className="flex min-h-0 min-w-0 flex-1">
      {!focusMode && (leftOpen || mobilePane === "chapters" ? (
        <div className={cn("flex min-h-0 min-w-0 flex-1 overflow-hidden md:contents", mobilePane !== "chapters" && "hidden md:contents")}>
          <ChapterList
          activeId={activeChapter}
          chapters={chapters}
          onSelect={(chapterId) => { void selectChapter(chapterId); setMobilePane("editor"); }}
          onCreate={() => { void createChapter(); }}
          onAuditPending={() => { void auditPendingChapters(); }}
          bulkAudit={bulkAudit}
          onCollapse={() => { setLeftOpen(false); setMobilePane("editor"); }}
          />
        </div>
      ) : (
        <button
          onClick={() => setLeftOpen(true)}
          className="hidden w-8 shrink-0 items-center justify-center border-r border-border bg-surface text-text-secondary hover:bg-surface-subtle md:flex"
          aria-label="展开左栏"
          title="展开章节列表"
        >
          <PanelRightClose size={16} />
        </button>
      ))}

      <div className={cn("flex min-h-0 min-w-0 flex-1 overflow-hidden md:contents", !focusMode && mobilePane !== "editor" && "hidden md:contents")}>
        <EditorPane
        generating={generating}
        generationPreview={generationPreview}
        generationPreviewActive={generating || generationTyping}
        chapter={chapterQuery.data?.id ? chapterQuery.data : null}
        content={content}
        title={title}
        dirty={dirty}
        saving={savingVersion}
        selectionBusy={selectionBusy}
        selectionError={selectionError}
        selectionCandidate={selectionCandidate}
        selectionGuidance={selectionGuidance}
        evidenceSelection={evidenceSelection}
        audit={dirty ? null : activeAudit ?? null}
        onContentChange={(value) => { contentRef.current = value; setContent(value); dirtyRef.current = true; setDirty(true); setSaveState("offline"); editRevision.current += 1; }}
        onTitleChange={(value) => { titleRef.current = value; setTitle(value); dirtyRef.current = true; setDirty(true); setSaveState("offline"); editRevision.current += 1; }}
        onLockedRangesChange={(lockedRanges) => {
          if (!chapterQuery.data?.id) return;
          chapterQuery.setData({ ...chapterQuery.data, lockedRanges });
          chapterRef.current = { ...chapterQuery.data, lockedRanges };
          dirtyRef.current = true;
          setDirty(true);
          setSaveState("offline");
          editRevision.current += 1;
        }}
        onSave={() => {
          if (savingVersion) return;
          setSavingVersion(true);
          void saveNow()
            .catch(() => undefined)
            .finally(() => setSavingVersion(false));
        }}
        onToggleGenerate={toggleGenerate}
        onDismissGenerationPreview={() => resetGenerationPreview()}
        onOpenAiPanel={() => { setRightTab("ai"); setRightOpen(true); setMobilePane("contract"); }}
        onOpenVersions={() => {
          setRightTab("version");
          setRightOpen(true);
          setMobilePane("contract");
        }}
          onSelectionEdit={(payload) => {
            void runSelectionEdit(payload).catch(() => setSaveState("error"));
        }}
        onAcceptSelection={acceptSelection}
        onRejectSelection={rejectSelection}
        />
      </div>

      {!focusMode && (rightOpen || mobilePane === "contract" ? (
        <div className={cn("flex min-h-0 min-w-0 flex-1 overflow-hidden md:contents", mobilePane !== "contract" && "hidden md:contents")}>
          <RightPanel
          tab={rightTab}
          onTabChange={setRightTab}
          generating={generating}
          generatingStage={generatingStage}
          characters={characters}
          locations={locations}
          audit={activeAudit}
          auditTarget={auditTarget}
          versions={versions}
          versionBusyId={versionBusyId}
          chapter={chapterQuery.data?.id ? chapterQuery.data : null}
          contextSources={job?.result.contextSources ?? []}
          writingContract={job?.result.policySnapshot ?? (writingContractQuery.data?.ruleset ? writingContractQuery.data : null)}
          onGenerationOptionsChange={setGenerationOptions}
          onGenerate={() => startGeneration("generate").catch(() => setSaveState("error"))}
          onAudit={() => runAudit().catch(() => setSaveState("error"))}
          auditBusy={auditBusy}
          auditError={auditError}
          confirmBusy={confirmBusy}
          confirmError={confirmError}
          confirmSuccess={confirmSuccess}
          onRewrite={() => startGeneration("rewrite").catch(() => setSaveState("error"))}
          onConfirm={confirm}
          onAccept={(versionId) => accept(versionId).catch(() => setSaveState("error"))}
          onRestore={(versionId) => restore(versionId).catch(() => setSaveState("error"))}
          onDeleteVersion={(versionId) => deleteVersion(versionId).catch(() => setSaveState("error"))}
          onJumpToEvidence={jumpToEvidence}
          onRewriteIssue={rewriteAuditIssue}
          onCollapse={() => { setRightOpen(false); setMobilePane("editor"); }}
          />
        </div>
      ) : (
        <button
          onClick={() => setRightOpen(true)}
          className="hidden w-8 shrink-0 items-center justify-center border-l border-border bg-surface text-text-secondary transition-colors duration-150 hover:bg-surface-subtle md:flex"
          aria-label="展开右栏"
          title="展开右侧面板"
        >
          <PanelRightClose size={16} className="rotate-180 transition-transform duration-200" />
        </button>
      ))}
      </div>
    </div>
  );
}
