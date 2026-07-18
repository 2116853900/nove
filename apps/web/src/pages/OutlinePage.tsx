import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  Lock,
  Sparkles,
  ArrowUp,
  ArrowDown,
  BookMarked,
  GitBranch,
  FileText,
  Check,
  X,
  Compass,
  Pencil,
  Loader2,
  Trash2,
} from "lucide-react";
import { Field, TextInput, TextArea } from "@/components/ui/form";
import { Button } from "@/components/ui/Button";
import { apiRequest, useApiQuery, type OutlineNode } from "@/lib/api";
import { cn } from "@/lib/cn";

const kindIcon = {
  volume: BookMarked,
  arc: GitBranch,
  chapter: FileText,
  scene: FileText,
} as const;

function nextChildKind(kind?: string): "volume" | "arc" | "chapter" | "scene" {
  if (kind === "volume") return "arc";
  if (kind === "arc") return "chapter";
  if (kind === "chapter") return "scene";
  if (kind === "scene") return "scene";
  return "volume";
}

const childKindLabel: Record<string, string> = {
  volume: "卷",
  arc: "剧情阶段",
  chapter: "章节",
  scene: "场景",
};

interface Blueprint {
  book_title?: string;
  genre?: string;
  logline?: string;
  theme?: string;
  tone?: string;
  tags?: string[];
  protagonist?: {
    name?: string;
    identity?: string;
    goal?: string;
    motivation?: string;
    flaw_or_start?: string;
    golden_finger?: string;
    golden_finger_cost?: string;
  };
  antagonist?: string;
  core_conflict?: string;
  world?: {
    setting?: string;
    power_system?: string;
    rules?: string[];
  };
  satisfaction_loop?: string;
  reader_hooks?: string[];
  opening_hook?: string;
  reader_contract?: { target_audience?: string; platform?: string; core_promise?: string };
  creative_constraints?: {
    anti_trope?: string;
    hard_constraints?: string[];
    antagonist_mirror?: string;
    do_not_copy?: string[];
  };
  arcs_outline?: string[];
}

interface BlueprintPreview {
  previewId: string;
  draftSource?: string;
  blueprint: Blueprint;
  expiresAt?: number;
}

interface PreviewNode {
  kind?: string;
  title: string;
  details?: Record<string, unknown>;
  selected?: boolean;
  previewId?: string;
  enrichmentStatus?: "pending" | "complete" | "failed";
}

interface OutlinePreview {
  previewId: string;
  parentId?: string | null;
  childKind: string;
  createChapters?: boolean;
  draftSource?: string;
  mode?: string;
  master?: boolean;
  stage?: string;
  suggestedVolumeCount?: number;
  volumeCountSource?: "ai" | "blueprint_ai" | "explicit";
  blueprintStageCount?: number;
  enrichmentPending?: boolean;
  plannedChapters?: number;
  modelFallback?: boolean;
  nodes: PreviewNode[];
  coherence?: {
    ok?: boolean;
    pass?: boolean;
    score?: number;
    issue_count?: number;
    issues?: Array<{ severity?: string; title?: string; reason?: string }>;
  };
}

function isUnreasonableMasterPreview(preview: OutlinePreview): boolean {
  if (preview.childKind !== "volume") return false;
  if (preview.parentId) return false;
  const budgetTotal = preview.nodes.reduce(
    (total, node) => total + Math.max(0, Number(node.details?.planned_chapters) || 0),
    0,
  );
  const planned = Math.max(0, Number(preview.plannedChapters) || budgetTotal);
  const minimumVolumes = planned > 0 ? Math.ceil(planned / 100) : 1;
  const hasOversizedVolume = preview.nodes.some(
    (node) => Number(node.details?.planned_chapters) > 100,
  );
  return preview.nodes.length < minimumVolumes || hasOversizedVolume;
}

function outlineKindLabel(kind: string): string {
  return {
    volume: "分卷",
    arc: "剧情阶段",
    chapter: "章节",
    scene: "场景",
  }[kind] || kind;
}

function friendlyOutlineTitle(title: string): string {
  return title.replace(/^剧情弧(?=\s*·)/, "剧情阶段");
}

/** Outline page (§11): tree + preview-confirm generation. */
export function OutlinePage() {
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: outlineTree, refetch } = useApiQuery<OutlineNode[]>(
    id ? `/novels/${id}/outline` : null,
    [],
  );
  const [selected, setSelected] = useState("");
  const [mobileView, setMobileView] = useState<"structure" | "editor">("structure");
  const [advancedDetails, setAdvancedDetails] = useState(false);
  const selectedNode = findNode(outlineTree, selected);

  useEffect(() => setAdvancedDetails(false), [selected]);

  useEffect(() => {
    if (!selected && outlineTree.length) {
      setSelected(
        findFirstKind(outlineTree, "arc")?.id ??
          findFirstKind(outlineTree, "volume")?.id ??
          findFirstChapter(outlineTree)?.id ??
          outlineTree[0].id,
      );
    }
  }, [outlineTree, selected]);

  const [generating, setGenerating] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [genMessage, setGenMessage] = useState<string | null>(null);
  const [blueprintPreview, setBlueprintPreview] = useState<BlueprintPreview | null>(null);
  const [preview, setPreview] = useState<OutlinePreview | null>(null);

  // Open master wizard from ?wizard=1 (new novel flow)
  useEffect(() => {
    if (!id) return;
    if (searchParams.get("wizard") !== "1") return;
    void beginMasterWizard();
    const next = new URLSearchParams(searchParams);
    next.delete("wizard");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const updateNode = async (values: Record<string, unknown>) => {
    if (!selectedNode) return;
    await apiRequest(`/outline-nodes/${selectedNode.id}`, {
      method: "PATCH",
      body: JSON.stringify(values),
    });
    await refetch();
  };

  const moveNode = async (direction: "up" | "down") => {
    if (!selectedNode) return;
    await apiRequest(`/outline-nodes/${selectedNode.id}/move`, {
      method: "POST",
      body: JSON.stringify({ direction }),
    });
    await refetch();
  };

  const deleteSelectedNode = async () => {
    if (!selectedNode || !["volume", "arc"].includes(selectedNode.kind)) return;
    const label = selectedNode.kind === "volume" ? "卷" : "剧情阶段";
    if (!window.confirm(`删除「${friendlyOutlineTitle(selectedNode.title)}」及其所有下级章节？此操作不可撤销。`)) return;
    try {
      const result = await apiRequest<{ parentId?: string | null; deletedNodes: number; deletedChapters: number }>(
        `/outline-nodes/${selectedNode.id}`,
        { method: "DELETE" },
      );
      setSelected(result.parentId ?? "");
      await refetch();
      setGenMessage(`已删除${label}，以及 ${result.deletedNodes} 项规划、${result.deletedChapters} 个章节`);
    } catch (reason) {
      setGenMessage(reason instanceof Error ? reason.message : `删除${label}失败`);
    }
  };

  const runPreview = async (opts: {
    mode: "batch_chapters" | "children" | "master_outline";
    parentId?: string | null;
    childKind?: string;
    count: number;
  }) => {
    if (!id) return;
    setGenerating(true);
    setGenMessage(null);
    try {
      if (opts.mode === "batch_chapters" && opts.childKind === "chapter" && opts.count > 1) {
        const nodes: PreviewNode[] = [];
        for (let offset = 0; offset < opts.count; offset += 1) {
          const result = await apiRequest<OutlinePreview>(`/novels/${id}/outline/preview`, {
            method: "POST",
            body: JSON.stringify({
              parent_id: opts.parentId ?? null,
              child_kind: "chapter",
              count: 1,
              create_chapters: true,
              mode: "batch_chapters",
              run_coherence: false,
              chapter_offset: offset,
              prior_drafts: nodes.map((node) => ({
                title: node.title,
                ...(node.details || {}),
              })),
            }),
          });
          const next = (result.nodes || []).map((node) => ({
            ...node,
            previewId: result.previewId,
            selected: node.selected !== false,
          }));
          nodes.push(...next);
          setPreview({
            ...result,
            previewId: result.previewId,
            nodes: [...nodes],
          });
          setGenMessage(`正在生成章节安排：${nodes.length} / ${opts.count}`);
        }
        setGenMessage(`已生成 ${nodes.length} 条章节草案（${sourceLabel("model")}）`);
        return;
      }
      const result = await apiRequest<OutlinePreview>(`/novels/${id}/outline/preview`, {
        method: "POST",
        body: JSON.stringify({
          parent_id: opts.parentId ?? null,
          child_kind: opts.childKind ?? null,
          count: opts.count,
          create_chapters: (opts.childKind ?? "chapter") === "chapter",
          mode: opts.mode,
          run_coherence: true,
        }),
      });
      setPreview({
        ...result,
        nodes: (result.nodes || []).map((n) => ({ ...n, selected: n.selected !== false })),
      });
      const issues = result.coherence?.issue_count ?? 0;
      setGenMessage(
        `已生成 ${result.nodes?.length ?? 0} 条草案（${sourceLabel(result.draftSource)}）` +
          (issues ? ` · 连贯提示 ${issues} 条` : " · 连贯检查通过"),
      );
    } catch (reason) {
      setGenMessage(reason instanceof Error ? reason.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const runChildrenPreview = async () => {
    // At the root, "生成卷" must use the same blueprint-first AI planning as
    // the master wizard. The generic child generator defaults to two nodes.
    if (!selectedNode) {
      await beginMasterWizard();
      return;
    }
    const childKind = nextChildKind(selectedNode?.kind);
    const isArc = selectedNode?.kind === "arc";
    const plannedChapters = Math.max(
      1,
      Number(selectedNode?.details?.planned_chapters) || 12,
    );
    await runPreview({
      mode: isArc ? "batch_chapters" : "children",
      parentId: selectedNode?.id ?? null,
      childKind,
      count: isArc ? plannedChapters : selectedNode?.kind === "volume" ? 0 : 2,
    });
  };

  const requestMasterVolumes = async (novelId: string) => {
    const result = await apiRequest<OutlinePreview>(
      `/novels/${novelId}/outline/master-preview`,
      {
        method: "POST",
        body: JSON.stringify({ run_coherence: true }),
      },
    );
    const skeletons = (result.nodes || []).map((node) => ({
      ...node,
      selected: node.selected !== false,
      enrichmentStatus: "pending" as const,
    }));
    setPreview({
      ...result,
      nodes: skeletons,
    });
    setGenMessage(`分卷结构已生成，正在补全 0 / ${skeletons.length} 卷…`);

    let cursor = 0;
    let completed = 0;
    let failed = 0;
    const enrichNext = async () => {
      while (cursor < skeletons.length) {
        const index = cursor;
        cursor += 1;
        try {
          const enriched = await apiRequest<{
            index: number;
            node: PreviewNode;
            draftSource?: string;
            modelFallback?: boolean;
          }>(`/novels/${novelId}/outline/master-preview/${result.previewId}/enrich`, {
            method: "POST",
            body: JSON.stringify({ index }),
          });
          completed += 1;
          setPreview((current) => {
            if (!current || current.previewId !== result.previewId) return current;
            const nodes = [...current.nodes];
            nodes[index] = {
              ...enriched.node,
              selected: nodes[index]?.selected !== false,
              enrichmentStatus: "complete",
            };
            return {
              ...current,
              nodes,
              draftSource: enriched.draftSource || current.draftSource,
              modelFallback: current.modelFallback || enriched.modelFallback,
            };
          });
        } catch {
          failed += 1;
          setPreview((current) => {
            if (!current || current.previewId !== result.previewId) return current;
            const nodes = [...current.nodes];
            nodes[index] = { ...nodes[index], enrichmentStatus: "failed" };
            return { ...current, nodes };
          });
        }
        setGenMessage(`正在补全分卷：${completed + failed} / ${skeletons.length}`);
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(3, skeletons.length) }, () => enrichNext()),
    );
    setPreview((current) =>
      current?.previewId === result.previewId
        ? { ...current, enrichmentPending: false }
        : current,
    );
    setGenMessage(
      `AI 规划全书 ${skeletons.length} 卷` +
        (result.volumeCountSource === "blueprint_ai" ? "（依据故事蓝图阶段）" : "") +
        (failed ? ` · ${failed} 卷保留蓝图草案` : " · 已全部补全") +
        "— 请确认后写入",
    );
  };

  // Vite HMR preserves component state. If a browser tab still holds an old
  // two-volume preview, replace it automatically with the current AI plan.
  useEffect(() => {
    if (!id || !preview || generating || !isUnreasonableMasterPreview(preview)) return;
    const stalePreviewId = preview.previewId;
    setPreview(null);
    setGenerating(true);
    setGenMessage("检测到旧版不合理分卷，正在依据故事蓝图重新规划…");
    void (async () => {
      try {
        await apiRequest(`/novels/${id}/outline/preview/${stalePreviewId}`, {
          method: "DELETE",
        });
      } catch {
        /* expired previews are already discarded */
      }
      try {
        await requestMasterVolumes(id);
      } catch (reason) {
        setGenMessage(reason instanceof Error ? reason.message : "重新规划分卷失败");
      } finally {
        setGenerating(false);
      }
    })();
    // requestMasterVolumes is intentionally omitted: clearing preview before
    // the async request prevents duplicate regeneration after rerenders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, preview, generating]);

  const beginMasterWizard = async () => {
    if (!id) return;
    if (findFirstKind(outlineTree, "volume")) {
      setGenMessage("已存在全书规划；请选择一个分卷生成剧情阶段，或继续追加分卷");
      return;
    }
    setGenerating(true);
    setGenMessage(null);
    try {
      const current = await apiRequest<{ blueprint: Blueprint | null }>(`/novels/${id}/blueprint`);
      if (current.blueprint) {
        await requestMasterVolumes(id);
        return;
      }
      const result = await apiRequest<BlueprintPreview>(`/novels/${id}/blueprint/preview`, {
        method: "POST",
      });
      setBlueprintPreview(result);
      setGenMessage(`故事方向已生成（${sourceLabel(result.draftSource)}）— 确认后进入全书规划`);
    } catch (reason) {
      setGenMessage(reason instanceof Error ? reason.message : "故事蓝图生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const commitBlueprintPreview = async () => {
    if (!id || !blueprintPreview) return;
    setCommitting(true);
    setGenMessage(null);
    try {
      await apiRequest(`/novels/${id}/blueprint/commit`, {
        method: "POST",
        body: JSON.stringify({
          preview_id: blueprintPreview.previewId,
          blueprint: blueprintPreview.blueprint,
        }),
      });
      setBlueprintPreview(null);
      setGenerating(true);
      try {
        await requestMasterVolumes(id);
      } finally {
        setGenerating(false);
      }
    } catch (reason) {
      setGenMessage(reason instanceof Error ? reason.message : "故事蓝图确认失败");
    } finally {
      setCommitting(false);
    }
  };

  const discardBlueprintPreview = async () => {
    if (!id || !blueprintPreview) {
      setBlueprintPreview(null);
      return;
    }
    try {
      await apiRequest(`/novels/${id}/outline/preview/${blueprintPreview.previewId}`, {
        method: "DELETE",
      });
    } catch {
      /* expired previews are already discarded */
    }
    setBlueprintPreview(null);
    setGenMessage("已丢弃故事蓝图草案");
  };

  const runRegenerateNode = async () => {
    if (!id || !selectedNode) return;
    if (selectedNode.locked) {
      setGenMessage("这部分已锁定，请先解锁再重新生成");
      return;
    }
    setGenerating(true);
    setGenMessage(null);
    try {
      const result = await apiRequest<OutlinePreview & { targetNodeId?: string }>(
        `/novels/${id}/outline/regenerate`,
        {
          method: "POST",
          body: JSON.stringify({ node_id: selectedNode.id, run_coherence: true }),
        },
      );
      setPreview({
        ...result,
        nodes: (result.nodes || []).map((n) => ({ ...n, selected: n.selected !== false })),
      });
      setGenMessage(
        `已重写「${friendlyOutlineTitle(selectedNode.title)}」草案（${sourceLabel(result.draftSource)}）— 确认后更新当前安排`,
      );
    } catch (reason) {
      setGenMessage(reason instanceof Error ? reason.message : "重新生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const commitPreview = async () => {
    if (!id || !preview) return;
    setCommitting(true);
    setGenMessage(null);
    try {
      if (preview.nodes.some((node) => node.previewId)) {
        const selectedNodes = preview.nodes.filter((node) => node.selected !== false);
        let created = 0;
        let chaptersCreated = 0;
        let firstId = "";
        for (const node of selectedNodes) {
          const result = await apiRequest<{
            created?: Array<{ id: string; title: string }>;
            chaptersCreated?: number;
          }>(`/novels/${id}/outline/commit`, {
            method: "POST",
            body: JSON.stringify({ preview_id: node.previewId, nodes: [node] }),
          });
          created += result.created?.length ?? 0;
          chaptersCreated += result.chaptersCreated ?? 0;
          firstId ||= result.created?.[0]?.id ?? "";
        }
        await refetch();
        setPreview(null);
        setGenMessage(`已写入 ${created} 项规划${chaptersCreated ? `，同步 ${chaptersCreated} 个章节` : ""}`);
        if (firstId) setSelected(firstId);
        return;
      }
      const result = await apiRequest<{
        created?: Array<{ id: string; title: string }>;
        chaptersCreated?: number;
        chaptersUpdated?: number;
        draftSource?: string;
        mode?: string;
        replacedNodeId?: string;
      }>(`/novels/${id}/outline/commit`, {
        method: "POST",
        body: JSON.stringify({
          preview_id: preview.previewId,
          nodes: preview.nodes,
        }),
      });
      await refetch();
      setPreview(null);
      if (result.mode === "regenerate_node" || result.replacedNodeId) {
        setGenMessage(
          `已覆盖本章大纲` +
            (result.chaptersUpdated ? "（章节 brief 已同步）" : ""),
        );
        if (result.replacedNodeId) setSelected(result.replacedNodeId);
      } else {
        const n = result.created?.length ?? 0;
        setGenMessage(
          n > 0
            ? `已写入 ${n} 项规划` +
              (result.chaptersCreated ? `，同步 ${result.chaptersCreated} 个章节` : "")
            : "未写入规划",
        );
        if (result.created?.[0]?.id) setSelected(result.created[0].id);
      }
    } catch (reason) {
      setGenMessage(reason instanceof Error ? reason.message : "确认写入失败");
    } finally {
      setCommitting(false);
    }
  };

  const discardPreview = async () => {
    if (!id || !preview) {
      setPreview(null);
      return;
    }
    try {
      const previewIds = new Set(
        preview.nodes.map((node) => node.previewId).filter((previewId): previewId is string => Boolean(previewId)),
      );
      if (previewIds.size === 0) previewIds.add(preview.previewId);
      await Promise.all([...previewIds].map((previewId) =>
        apiRequest(`/novels/${id}/outline/preview/${previewId}`, { method: "DELETE" }),
      ));
    } catch {
      /* expired is fine */
    }
    setPreview(null);
    setGenMessage("已丢弃预览草案");
  };

  const selectedCount = useMemo(
    () => (preview?.nodes || []).filter((n) => n.selected !== false).length,
    [preview],
  );

  const pendingChildKind = nextChildKind(selectedNode?.kind);
  const selectedArcChapterCount = Math.max(
    1,
    Number(selectedNode?.details?.planned_chapters) || 12,
  );
  const selectedGoalKey = selectedNode?.kind === "volume" ? "stage_goal" : "goal";
  const selectedGoalLabel = selectedNode?.kind === "volume"
    ? "本卷阶段目标"
    : selectedNode?.kind === "chapter"
      ? "本章目标"
      : "本段目标";
  const selectedConflictKey = selectedNode?.kind === "volume" ? "core_conflict" : "conflict";

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <div className="grid shrink-0 grid-cols-2 gap-1 border-b border-border bg-surface p-1 md:hidden" aria-label="大纲视图">
        <button
          type="button"
          aria-pressed={mobileView === "structure"}
          onClick={() => setMobileView("structure")}
          className={cn(
            "flex h-10 items-center justify-center gap-1.5 rounded-control text-[13px]",
            mobileView === "structure" ? "bg-surface-subtle font-medium text-primary" : "text-text-secondary",
          )}
        >
          <GitBranch size={15} />
          结构
        </button>
        <button
          type="button"
          aria-pressed={mobileView === "editor"}
          onClick={() => setMobileView("editor")}
          className={cn(
            "flex h-10 items-center justify-center gap-1.5 rounded-control text-[13px]",
            mobileView === "editor" ? "bg-surface-subtle font-medium text-primary" : "text-text-secondary",
          )}
        >
          <Pencil size={15} />
          编辑
        </button>
      </div>
      <div className="flex min-h-0 flex-1">
      <aside className={cn("w-full shrink-0 flex-col border-r border-border bg-surface md:w-[320px]", mobileView === "structure" ? "flex" : "hidden md:flex")}>
        <div className="border-b border-border px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 className="text-panel-title font-semibold text-text-primary">大纲树</h2>
              {selectedNode && (
                <p className="mt-0.5 truncate text-[11px] text-text-secondary">
                  当前：{friendlyOutlineTitle(selectedNode.title)}
                </p>
              )}
            </div>
          </div>
          <div className="mt-3 flex flex-col gap-2">
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="primary"
                className="flex-1"
                icon={<Sparkles size={14} />}
                disabled={generating || committing}
                onClick={() => { setMobileView("editor"); void runChildrenPreview(); }}
              >
                {generating
                  ? "生成中…"
                  : selectedNode?.kind === "arc"
                    ? `生成完整章节安排（${selectedArcChapterCount}章）`
                    : selectedNode?.kind === "volume"
                      ? "AI 规划剧情阶段"
                      : `生成${childKindLabel[pendingChildKind] || pendingChildKind}`}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="flex-1"
                disabled={generating || committing}
                onClick={() => { setMobileView("editor"); void beginMasterWizard(); }}
              >
                {generating ? "生成中…" : "自动规划全书"}
              </Button>
            </div>
            <p className="text-[11px] text-text-secondary">
              {selectedNode?.kind === "arc"
                ? `将按本阶段预算一次生成 ${selectedArcChapterCount} 章；结果先预览，确认后才写入。`
                : selectedNode?.kind === "volume"
                  ? "AI 将根据本卷篇幅自动决定剧情阶段数量，并分配章节。"
                : `结果先预览，确认后才写入。`}
            </p>
          </div>
        </div>
        {generating && (
          <div
            className="flex items-center gap-2 border-b border-border bg-surface-subtle px-4 py-2 text-[12px] text-text-primary"
            role="status"
            aria-live="polite"
          >
            <Loader2 size={14} className="shrink-0 animate-spin" aria-hidden="true" />
            <span>AI 正在生成大纲，请勿离开当前页面</span>
          </div>
        )}
        {genMessage && (
          <p className="border-b border-border px-4 py-2 text-[12px] text-text-secondary" role="status">
            {genMessage}
          </p>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {!outlineTree.length && (
            <p className="px-4 py-8 text-center text-[13px] text-text-secondary animate-nove-fade-in">
              暂无故事规划，可点击“自动规划全书”生成
            </p>
          )}
          {outlineTree.map((node) => (
            <TreeNode
              key={node.id}
              node={node}
              depth={0}
              selected={selected}
              onSelect={(nodeId) => { setSelected(nodeId); setMobileView("editor"); }}
            />
          ))}
        </div>
      </aside>

      <section className={cn("min-h-0 w-full flex-1 overflow-y-auto bg-background md:block", mobileView !== "editor" && "hidden md:block")}>
        <div className="px-4 py-5 sm:px-10 sm:py-8">
          {blueprintPreview ? (
            <BlueprintPreviewPanel
              preview={blueprintPreview}
              committing={committing}
              onChange={(next) => setBlueprintPreview(next)}
              onCommit={() => void commitBlueprintPreview()}
              onDiscard={() => void discardBlueprintPreview()}
            />
          ) : preview ? (
            <PreviewPanel
              preview={preview}
              selectedCount={selectedCount}
              committing={committing}
              generating={generating}
              onChange={(nodes) => setPreview({ ...preview, nodes })}
              onCommit={() => void commitPreview()}
              onDiscard={() => void discardPreview()}
            />
          ) : !selectedNode ? (
            <div className="flex h-48 items-center justify-center text-[13px] text-text-secondary">
                {outlineTree.length ? "选择左侧内容开始查看" : "暂无规划，点击“自动规划全书”开始生成"}
            </div>
          ) : (
            <>
              <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[12px] text-text-secondary">{outlineKindLabel(selectedNode.kind)}</p>
                  <h1 className="mt-0.5 text-page-title font-semibold text-text-primary">
                    {friendlyOutlineTitle(selectedNode.title)}
                  </h1>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<Sparkles size={14} />}
                    disabled={generating || committing || selectedNode.locked}
                    onClick={() => void runRegenerateNode()}
                  >
                    {generating
                      ? "生成中…"
                      : selectedNode.kind === "chapter"
                        ? "重新生成本章安排"
                        : "重新生成当前安排"}
                  </Button>
                  <IconGhost
                    label="上移"
                    onClick={() => {
                      void moveNode("up");
                    }}
                  >
                    <ArrowUp size={16} />
                  </IconGhost>
                  <IconGhost
                    label="下移"
                    onClick={() => {
                      void moveNode("down");
                    }}
                  >
                    <ArrowDown size={16} />
                  </IconGhost>
                  <IconGhost
                    label="锁定"
                    onClick={() => updateNode({ locked: !selectedNode.locked })}
                  >
                    <Lock size={16} />
                  </IconGhost>
                  {(selectedNode.kind === "volume" || selectedNode.kind === "arc") && (
                    <IconGhost label={`删除${selectedNode.kind === "volume" ? "卷" : "剧情阶段"}`} onClick={() => void deleteSelectedNode()}>
                      <Trash2 size={16} />
                    </IconGhost>
                  )}
                </div>
              </div>
              {selectedNode.locked && (
                <p className="mb-4 text-[12px] text-text-secondary">
                  已锁定：不会被「重新生成本章大纲」覆盖。先解锁再操作。
                </p>
              )}

              <div className="flex flex-col gap-5 animate-nove-fade-in">
                {!advancedDetails ? (
                  selectedNode.kind === "chapter" ? <>
                    <Field label="本章目标">
                      <TextArea
                        key={`${selected}-simple-goal`}
                        rows={2}
                        defaultValue={String(selectedNode.details?.goal ?? "")}
                        onBlur={(event) => updateNode({
                          details: { ...selectedNode.details, goal: event.target.value },
                        })}
                      />
                    </Field>
                    <Field label="本章阻力">
                      <TextArea
                        key={`${selected}-simple-conflict`}
                        rows={2}
                        defaultValue={String(selectedNode.details?.conflict ?? selectedNode.details?.obstacle ?? "")}
                        onBlur={(event) => updateNode({
                          details: {
                            ...selectedNode.details,
                            conflict: event.target.value,
                            obstacle: event.target.value,
                          },
                        })}
                      />
                    </Field>
                    <Field label="关键情节" hint="每行一件必须发生的事。">
                      <TextArea
                        key={`${selected}-simple-events`}
                        rows={4}
                        defaultValue={
                          Array.isArray(selectedNode.details?.must_events)
                            ? (selectedNode.details.must_events as string[]).join("\n")
                            : ""
                        }
                        onBlur={(event) => {
                          const events = event.target.value
                            .split("\n")
                            .map((item) => item.trim())
                            .filter(Boolean);
                          void updateNode({
                            details: {
                              ...selectedNode.details,
                              must_events: events,
                              must_cover_nodes: events.slice(0, 4),
                            },
                          });
                        }}
                      />
                    </Field>
                    <Field label="章节结尾" hint="这一章结束时，读者最想知道什么？">
                      <TextArea
                        key={`${selected}-simple-ending`}
                        rows={2}
                        defaultValue={String(
                          selectedNode.details?.chapter_end_open_question
                          ?? selectedNode.details?.hook
                          ?? "",
                        )}
                        onBlur={(event) => updateNode({
                          details: {
                            ...selectedNode.details,
                            hook: event.target.value,
                            chapter_end_open_question: event.target.value,
                          },
                        })}
                      />
                    </Field>
                    <div className="border-y border-border py-4 text-[13px] text-text-secondary">
                      <p className="font-medium text-text-primary">AI 已准备的出场信息</p>
                      <p className="mt-1 leading-6">
                        人物：{Array.isArray(selectedNode.details?.characters) && selectedNode.details.characters.length
                          ? (selectedNode.details.characters as string[]).join("、")
                          : "将根据上下文自动选择"}
                        <br />
                        地点：{Array.isArray(selectedNode.details?.locations) && selectedNode.details.locations.length
                          ? (selectedNode.details.locations as string[]).join("、")
                          : "将根据上下文自动选择"}
                      </p>
                    </div>
                  </> : selectedNode.kind === "volume" ? <>
                    <Field label="本卷目标">
                      <TextArea
                        key={`${selected}-simple-volume-goal`}
                        rows={3}
                        defaultValue={String(selectedNode.details?.stage_goal ?? "")}
                        onBlur={(event) => updateNode({ details: { ...selectedNode.details, stage_goal: event.target.value } })}
                      />
                    </Field>
                    <Field label="本卷剧情">
                      <TextArea
                        key={`${selected}-simple-volume-summary`}
                        rows={4}
                        defaultValue={String(selectedNode.details?.arc_summary ?? "")}
                        onBlur={(event) => updateNode({ details: { ...selectedNode.details, arc_summary: event.target.value } })}
                      />
                    </Field>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="预计章节数">
                        <TextInput
                          key={`${selected}-simple-volume-count`}
                          type="number"
                          min={1}
                          defaultValue={String(selectedNode.details?.planned_chapters ?? "")}
                          onBlur={(event) => updateNode({ details: { ...selectedNode.details, planned_chapters: Math.max(1, Number(event.target.value) || 1) } })}
                        />
                      </Field>
                      <Field label="本卷结尾">
                        <TextInput
                          key={`${selected}-simple-volume-hook`}
                          defaultValue={String(selectedNode.details?.hook ?? "")}
                          onBlur={(event) => updateNode({ details: { ...selectedNode.details, hook: event.target.value } })}
                        />
                      </Field>
                    </div>
                  </> : <>
                    <Field label="本阶段目标">
                      <TextArea
                        key={`${selected}-simple-arc-goal`}
                        rows={2}
                        defaultValue={String(selectedNode.details?.goal ?? "")}
                        onBlur={(event) => updateNode({ details: { ...selectedNode.details, goal: event.target.value } })}
                      />
                    </Field>
                    <Field label="本阶段阻力">
                      <TextArea
                        key={`${selected}-simple-arc-conflict`}
                        rows={2}
                        defaultValue={String(selectedNode.details?.conflict ?? "")}
                        onBlur={(event) => updateNode({ details: { ...selectedNode.details, conflict: event.target.value } })}
                      />
                    </Field>
                    <Field label="关键情节" hint="每行一件必须发生的事。">
                      <TextArea
                        key={`${selected}-simple-arc-events`}
                        rows={3}
                        defaultValue={Array.isArray(selectedNode.details?.must_events) ? (selectedNode.details.must_events as string[]).join("\n") : ""}
                        onBlur={(event) => updateNode({ details: { ...selectedNode.details, must_events: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) } })}
                      />
                    </Field>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="预计章节数">
                        <TextInput
                          key={`${selected}-simple-arc-count`}
                          type="number"
                          min={1}
                          defaultValue={String(selectedNode.details?.planned_chapters ?? "")}
                          onBlur={(event) => updateNode({ details: { ...selectedNode.details, planned_chapters: Math.max(1, Number(event.target.value) || 1) } })}
                        />
                      </Field>
                      <Field label="阶段结尾">
                        <TextInput
                          key={`${selected}-simple-arc-hook`}
                          defaultValue={String(selectedNode.details?.hook ?? "")}
                          onBlur={(event) => updateNode({ details: { ...selectedNode.details, hook: event.target.value } })}
                        />
                      </Field>
                    </div>
                  </>
                ) : (
                  <>
                <Field label={selectedGoalLabel}>
                  <TextArea
                    key={`${selected}-goal`}
                    rows={2}
                    defaultValue={String(selectedNode.details?.[selectedGoalKey] ?? "")}
                    onBlur={(e) =>
                      updateNode({
                        details: { ...selectedNode.details, [selectedGoalKey]: e.target.value },
                      })
                    }
                  />
                </Field>
                {selectedNode.kind === "volume" && (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label="本卷章节预算">
                      <TextInput
                        key={`${selected}-planned-chapters`}
                        type="number"
                        min={1}
                        defaultValue={String(selectedNode.details?.planned_chapters ?? "")}
                        onBlur={(e) =>
                          updateNode({
                            details: {
                              ...selectedNode.details,
                              planned_chapters: Math.max(1, Number(e.target.value) || 1),
                            },
                          })
                        }
                      />
                    </Field>
                    <Field label="本卷剧情梗概">
                      <TextInput
                        key={`${selected}-arc-summary`}
                        defaultValue={String(selectedNode.details?.arc_summary ?? "")}
                        onBlur={(e) =>
                          updateNode({
                            details: { ...selectedNode.details, arc_summary: e.target.value },
                          })
                        }
                      />
                    </Field>
                  </div>
                )}
                {selectedNode.kind === "arc" && (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label="本阶段章节数">
                      <TextInput
                        key={`${selected}-arc-budget`}
                        type="number"
                        min={1}
                        defaultValue={String(selectedNode.details?.planned_chapters ?? "")}
                        onBlur={(e) =>
                          updateNode({
                            details: {
                              ...selectedNode.details,
                              planned_chapters: Math.max(1, Number(e.target.value) || 1),
                            },
                          })
                        }
                      />
                    </Field>
                    <Field label="弧线结束状态">
                      <TextInput
                        key={`${selected}-closing-state`}
                        defaultValue={String(selectedNode.details?.closing_state ?? "")}
                        onBlur={(e) =>
                          updateNode({
                            details: { ...selectedNode.details, closing_state: e.target.value },
                          })
                        }
                      />
                    </Field>
                  </div>
                )}
                <Field label="核心冲突">
                  <TextInput
                    key={`${selected}-conflict`}
                    defaultValue={String(selectedNode.details?.[selectedConflictKey] ?? "")}
                    onBlur={(e) =>
                      updateNode({
                        details: { ...selectedNode.details, [selectedConflictKey]: e.target.value },
                      })
                    }
                  />
                </Field>
                {selectedNode.kind === "chapter" && (
                  <>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="具体阻力">
                        <TextInput key={`${selected}-obstacle`} defaultValue={String(selectedNode.details?.obstacle ?? selectedNode.details?.conflict ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, obstacle: e.target.value } })} />
                      </Field>
                      <Field label="本章代价">
                        <TextInput key={`${selected}-cost`} defaultValue={String(selectedNode.details?.cost ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, cost: e.target.value } })} />
                      </Field>
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="故事发生时间">
                        <TextInput key={`${selected}-time-anchor`} defaultValue={String(selectedNode.details?.time_anchor ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, time_anchor: e.target.value } })} />
                      </Field>
                      <Field label="本章经过多久">
                        <TextInput key={`${selected}-chapter-span`} defaultValue={String(selectedNode.details?.chapter_span ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, chapter_span: e.target.value } })} />
                      </Field>
                      <Field label="距上一章多久">
                        <TextInput key={`${selected}-previous-gap`} defaultValue={String(selectedNode.details?.gap_from_previous ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, gap_from_previous: e.target.value } })} />
                      </Field>
                      <Field label="倒计时（如有）">
                        <TextInput key={`${selected}-countdown`} defaultValue={String(selectedNode.details?.countdown ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, countdown: e.target.value } })} />
                      </Field>
                    </div>
                  </>
                )}
                {selectedNode.kind === "volume" ? (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label="关键转折">
                      <TextArea
                        key={`${selected}-key-turns`}
                        rows={3}
                        defaultValue={
                          Array.isArray(selectedNode.details?.key_turns)
                            ? (selectedNode.details?.key_turns as string[]).join("\n")
                            : ""
                        }
                        onBlur={(e) =>
                          updateNode({
                            details: {
                              ...selectedNode.details,
                              key_turns: e.target.value.split("\n").filter(Boolean),
                            },
                          })
                        }
                      />
                    </Field>
                    <Field label="卷末钩子">
                      <TextArea
                        key={`${selected}-volume-hook`}
                        rows={3}
                        defaultValue={String(selectedNode.details?.hook ?? "")}
                        onBlur={(e) =>
                          updateNode({
                            details: { ...selectedNode.details, hook: e.target.value },
                          })
                        }
                      />
                    </Field>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label="关键情节">
                      <TextArea
                        key={`${selected}-must`}
                        rows={3}
                        defaultValue={
                          Array.isArray(selectedNode.details?.must_events)
                            ? (selectedNode.details?.must_events as string[]).join("\n")
                            : ""
                        }
                        onBlur={(e) =>
                          updateNode({
                            details: {
                              ...selectedNode.details,
                              must_events: e.target.value.split("\n").filter(Boolean),
                            },
                          })
                        }
                      />
                    </Field>
                    <Field label="不能发生">
                      <TextArea
                        key={`${selected}-forbidden`}
                        rows={3}
                        defaultValue={
                          Array.isArray(selectedNode.details?.forbidden_events)
                            ? (selectedNode.details?.forbidden_events as string[]).join("\n")
                            : ""
                        }
                        onBlur={(e) =>
                          updateNode({
                            details: {
                              ...selectedNode.details,
                              forbidden_events: e.target.value.split("\n").filter(Boolean),
                            },
                          })
                        }
                      />
                    </Field>
                  </div>
                )}
                {selectedNode.kind === "chapter" && (
                  <div className="border-y border-border py-5">
                    <h3 className="mb-4 text-[14px] font-semibold text-text-primary">章节内部结构</h3>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="开场动作">
                        <TextArea key={`${selected}-cbn`} rows={2} defaultValue={String(selectedNode.details?.cbn ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, cbn: e.target.value } })} />
                      </Field>
                      <Field label="收束变化">
                        <TextArea key={`${selected}-cen`} rows={2} defaultValue={String(selectedNode.details?.cen ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, cen: e.target.value } })} />
                      </Field>
                      <Field label="中段推进" hint="每行一个，按故事时间排列，共 2-4 个。" className="sm:col-span-2">
                        <TextArea key={`${selected}-cpns`} rows={4} defaultValue={Array.isArray(selectedNode.details?.cpns) ? (selectedNode.details?.cpns as string[]).join("\n") : ""} onBlur={(e) => updateNode({ details: { ...selectedNode.details, cpns: e.target.value.split("\n").map((item) => item.trim()).filter(Boolean) } })} />
                      </Field>
                      <Field label="必须写到" hint="最多 4 个。">
                        <TextArea key={`${selected}-must-cover`} rows={3} defaultValue={Array.isArray(selectedNode.details?.must_cover_nodes) ? (selectedNode.details?.must_cover_nodes as string[]).join("\n") : ""} onBlur={(e) => updateNode({ details: { ...selectedNode.details, must_cover_nodes: e.target.value.split("\n").map((item) => item.trim()).filter(Boolean) } })} />
                      </Field>
                      <Field label="不能提前发生" hint="最多 5 个。">
                        <TextArea key={`${selected}-forbidden-zones`} rows={3} defaultValue={Array.isArray(selectedNode.details?.forbidden_zones) ? (selectedNode.details?.forbidden_zones as string[]).join("\n") : ""} onBlur={(e) => updateNode({ details: { ...selectedNode.details, forbidden_zones: e.target.value.split("\n").map((item) => item.trim()).filter(Boolean) } })} />
                      </Field>
                    </div>
                  </div>
                )}
                {selectedNode.kind === "volume" && (
                  <Field label="本卷剧情阶段">
                    <TextArea
                      key={`${selected}-plot-arcs`}
                      rows={4}
                      defaultValue={
                        Array.isArray(selectedNode.details?.plot_arcs)
                          ? (selectedNode.details?.plot_arcs as string[]).join("\n")
                          : ""
                      }
                      onBlur={(e) =>
                        updateNode({
                          details: {
                            ...selectedNode.details,
                            plot_arcs: e.target.value
                              .split("\n")
                              .map((value) => value.trim())
                              .filter(Boolean),
                          },
                        })
                      }
                      placeholder="每行一个阶段"
                    />
                  </Field>
                )}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="出场人物">
                    <TextInput
                      key={`${selected}-cast`}
                      defaultValue={
                        Array.isArray(selectedNode.details?.characters)
                          ? (selectedNode.details?.characters as string[]).join("、")
                          : String(selectedNode.details?.cast ?? "")
                      }
                      onBlur={(e) =>
                        updateNode({
                          details: {
                            ...selectedNode.details,
                            characters: e.target.value
                              .split(/[,，、]/)
                              .map((s) => s.trim())
                              .filter(Boolean),
                          },
                        })
                      }
                      placeholder="逗号分隔"
                    />
                  </Field>
                  <Field label="出场地点">
                    <TextInput
                      key={`${selected}-places`}
                      defaultValue={
                        Array.isArray(selectedNode.details?.locations)
                          ? (selectedNode.details?.locations as string[]).join("、")
                          : String(selectedNode.details?.locations ?? "")
                      }
                      onBlur={(e) =>
                        updateNode({
                          details: {
                            ...selectedNode.details,
                            locations: e.target.value
                              .split(/[,，、]/)
                              .map((s) => s.trim())
                              .filter(Boolean),
                          },
                        })
                      }
                      placeholder="逗号分隔"
                    />
                  </Field>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <Field label="亮点">
                    <TextInput
                      key={`${selected}-highlight`}
                      defaultValue={String(selectedNode.details?.highlight ?? "")}
                      onBlur={(e) =>
                        updateNode({
                          details: { ...selectedNode.details, highlight: e.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="转折">
                    <TextInput
                      key={`${selected}-twist`}
                      defaultValue={String(selectedNode.details?.twist ?? "")}
                      onBlur={(e) =>
                        updateNode({
                          details: { ...selectedNode.details, twist: e.target.value },
                        })
                      }
                    />
                  </Field>
                  <Field label="结尾钩子">
                    <TextInput
                      key={`${selected}-hook`}
                      defaultValue={String(selectedNode.details?.hook ?? "")}
                      onBlur={(e) =>
                        updateNode({
                          details: { ...selectedNode.details, hook: e.target.value },
                        })
                      }
                    />
                  </Field>
                </div>
                {selectedNode.kind === "chapter" && (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label="本章主线"><TextInput key={`${selected}-strand`} defaultValue={String(selectedNode.details?.strand ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, strand: e.target.value } })} /></Field>
                    <Field label="视角角色"><TextInput key={`${selected}-pov-character`} defaultValue={String(selectedNode.details?.pov_character ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, pov_character: e.target.value } })} /></Field>
                    <Field label="本章对手"><TextInput key={`${selected}-antagonist-level`} defaultValue={String(selectedNode.details?.antagonist_level ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, antagonist_level: e.target.value } })} /></Field>
                    <Field label="本章变化"><TextInput key={`${selected}-chapter-change`} defaultValue={String(selectedNode.details?.chapter_change ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, chapter_change: e.target.value } })} /></Field>
                    <Field label="留给下一章的问题" className="sm:col-span-2"><TextInput key={`${selected}-open-question`} defaultValue={String(selectedNode.details?.chapter_end_open_question ?? selectedNode.details?.hook ?? "")} onBlur={(e) => updateNode({ details: { ...selectedNode.details, chapter_end_open_question: e.target.value } })} /></Field>
                  </div>
                )}
                  </>
                )}

                <button
                  type="button"
                  onClick={() => setAdvancedDetails((value) => !value)}
                  className="flex items-center gap-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary"
                >
                  {advancedDetails ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  {advancedDetails ? "收起更多细节" : "更多规划细节"}
                </button>

                <div className="flex items-center justify-between border-y border-border py-4">
                  <div>
                    <p className="text-[14px] font-medium text-text-primary">当前状态</p>
                    <p className="mt-0.5 text-[13px] text-text-secondary">
                      {selectedNode.locked ? "已锁定，AI 不会改写这部分" : "未锁定，可随时调整"}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "rounded px-2 py-1 text-[12px] font-medium",
                      selectedNode.locked
                        ? "bg-warning/10 text-warning"
                        : "bg-surface-subtle text-text-secondary",
                    )}
                  >
                    {selectedNode.locked ? "已锁定" : "可编辑"}
                  </span>
                </div>

                <p className="text-[12px] text-text-secondary">修改后会自动保存。</p>
              </div>
            </>
          )}
        </div>
      </section>
      </div>
    </div>
  );
}

function sourceLabel(source?: string) {
    if (source === "model") return "模型";
    if (source === "heuristic") return "云端模型";
    if (source === "blueprint") return "故事蓝图";
    return source || "skill";
}

function BlueprintPreviewPanel({
  preview,
  committing,
  onChange,
  onCommit,
  onDiscard,
}: {
  preview: BlueprintPreview;
  committing: boolean;
  onChange: (preview: BlueprintPreview) => void;
  onCommit: () => void;
  onDiscard: () => void;
}) {
  const blueprint = preview.blueprint;
  const protagonist = blueprint.protagonist ?? {};
  const world = blueprint.world ?? {};
  const readerContract = blueprint.reader_contract ?? {};
  const creativeConstraints = blueprint.creative_constraints ?? {};
  const update = (patch: Partial<Blueprint>) =>
    onChange({ ...preview, blueprint: { ...blueprint, ...patch } });
  const updateProtagonist = (patch: Partial<NonNullable<Blueprint["protagonist"]>>) =>
    update({ protagonist: { ...protagonist, ...patch } });
  const updateWorld = (patch: Partial<NonNullable<Blueprint["world"]>>) =>
    update({ world: { ...world, ...patch } });
  const updateReaderContract = (patch: Partial<NonNullable<Blueprint["reader_contract"]>>) =>
    update({ reader_contract: { ...readerContract, ...patch } });
  const updateCreativeConstraints = (patch: Partial<NonNullable<Blueprint["creative_constraints"]>>) =>
    update({ creative_constraints: { ...creativeConstraints, ...patch } });

  return (
    <div className="animate-nove-fade-in">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[12px] text-text-secondary">故事蓝图预览 · {sourceLabel(preview.draftSource)}</p>
          <h1 className="mt-0.5 text-page-title font-semibold text-text-primary">确认故事蓝图</h1>
        </div>
        <div className="flex gap-2">
          <Button size="sm" icon={<X size={14} />} disabled={committing} onClick={onDiscard}>
            丢弃
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon={<Check size={14} />}
            disabled={committing}
            onClick={onCommit}
          >
            {committing ? "写入中…" : "确认并生成分卷"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Field label="一句话卖点" className="lg:col-span-2">
          <TextArea
            rows={2}
            value={blueprint.logline ?? ""}
            onChange={(event) => update({ logline: event.target.value })}
          />
        </Field>
        <Field label="主角">
          <TextInput
            value={protagonist.name ?? ""}
            onChange={(event) => updateProtagonist({ name: event.target.value })}
          />
        </Field>
        <Field label="初始身份">
          <TextInput
            value={protagonist.identity ?? ""}
            onChange={(event) => updateProtagonist({ identity: event.target.value })}
          />
        </Field>
        <Field label="贯穿目标">
          <TextArea
            rows={2}
            value={protagonist.goal ?? ""}
            onChange={(event) => updateProtagonist({ goal: event.target.value })}
          />
        </Field>
        <Field label="核心动机">
          <TextArea
            rows={2}
            value={protagonist.motivation ?? ""}
            onChange={(event) => updateProtagonist({ motivation: event.target.value })}
          />
        </Field>
        <Field label="主角缺陷">
          <TextArea rows={2} value={protagonist.flaw_or_start ?? ""} onChange={(event) => updateProtagonist({ flaw_or_start: event.target.value })} />
        </Field>
        <Field label="独特优势">
          <TextInput
            value={protagonist.golden_finger ?? ""}
            onChange={(event) => updateProtagonist({ golden_finger: event.target.value })}
          />
        </Field>
        <Field label="能力代价 / 边界">
          <TextInput value={protagonist.golden_finger_cost ?? ""} onChange={(event) => updateProtagonist({ golden_finger_cost: event.target.value })} />
        </Field>
        <Field label="主要对立面">
          <TextInput
            value={blueprint.antagonist ?? ""}
            onChange={(event) => update({ antagonist: event.target.value })}
          />
        </Field>
        <Field label="核心矛盾" className="lg:col-span-2">
          <TextArea
            rows={2}
            value={blueprint.core_conflict ?? ""}
            onChange={(event) => update({ core_conflict: event.target.value })}
          />
        </Field>
        <Field label="世界观核心">
          <TextArea
            rows={2}
            value={world.setting ?? ""}
            onChange={(event) => updateWorld({ setting: event.target.value })}
          />
        </Field>
        <Field label="力量体系">
          <TextArea
            rows={2}
            value={world.power_system ?? ""}
            onChange={(event) => updateWorld({ power_system: event.target.value })}
          />
        </Field>
        <Field label="爽点循环">
          <TextArea
            rows={2}
            value={blueprint.satisfaction_loop ?? ""}
            onChange={(event) => update({ satisfaction_loop: event.target.value })}
          />
        </Field>
        <Field label="开篇钩子">
          <TextArea
            rows={2}
            value={blueprint.opening_hook ?? ""}
            onChange={(event) => update({ opening_hook: event.target.value })}
          />
        </Field>
        <Field label="反套路约束">
          <TextArea rows={2} value={creativeConstraints.anti_trope ?? ""} onChange={(event) => updateCreativeConstraints({ anti_trope: event.target.value })} />
        </Field>
        <Field label="主要对手与主角的差异">
          <TextArea rows={2} value={creativeConstraints.antagonist_mirror ?? ""} onChange={(event) => updateCreativeConstraints({ antagonist_mirror: event.target.value })} />
        </Field>
        <Field label="创作硬约束" className="lg:col-span-2">
          <TextArea rows={3} value={(creativeConstraints.hard_constraints ?? []).join("\n")} onChange={(event) => updateCreativeConstraints({ hard_constraints: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} />
        </Field>
        <Field label="目标读者">
          <TextInput value={readerContract.target_audience ?? ""} onChange={(event) => updateReaderContract({ target_audience: event.target.value })} />
        </Field>
        <Field label="目标平台">
          <TextInput value={readerContract.platform ?? ""} onChange={(event) => updateReaderContract({ platform: event.target.value })} />
        </Field>
        <Field label="读者承诺" className="lg:col-span-2">
          <TextArea rows={2} value={readerContract.core_promise ?? ""} onChange={(event) => updateReaderContract({ core_promise: event.target.value })} />
        </Field>
        <Field label="全书阶段" className="lg:col-span-2">
          <TextArea
            rows={4}
            value={(blueprint.arcs_outline ?? []).join("\n")}
            onChange={(event) =>
              update({
                arcs_outline: event.target.value
                  .split("\n")
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
          />
        </Field>
      </div>
    </div>
  );
}

function PreviewPanel({
  preview,
  selectedCount,
  committing,
  generating,
  onChange,
  onCommit,
  onDiscard,
}: {
  preview: OutlinePreview;
  selectedCount: number;
  committing: boolean;
  generating: boolean;
  onChange: (nodes: PreviewNode[]) => void;
  onCommit: () => void;
  onDiscard: () => void;
}) {
  const issues = preview.coherence?.issues || [];
  const toggle = (index: number) => {
    const nodes = preview.nodes.map((n, i) =>
      i === index ? { ...n, selected: n.selected === false } : n,
    );
    onChange(nodes);
  };
  const setTitle = (index: number, title: string) => {
    const nodes = preview.nodes.map((n, i) => (i === index ? { ...n, title } : n));
    onChange(nodes);
  };
  const setDetails = (index: number, patch: Record<string, unknown>) => {
    const nodes = preview.nodes.map((node, nodeIndex) =>
      nodeIndex === index
        ? { ...node, details: { ...(node.details || {}), ...patch } }
        : node,
    );
    onChange(nodes);
  };

  return (
    <div className="animate-nove-fade-in">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[12px] text-text-secondary">
            {preview.stage === "volumes"
              ? "全书分卷预览"
              : preview.master || preview.mode === "master_outline"
                ? "全书规划预览"
                : "生成预览"}
            {" · "}
            {childKindLabel[preview.childKind] || preview.childKind}
            {" · "}
            {sourceLabel(preview.draftSource)}
          </p>
          <h1 className="mt-0.5 text-page-title font-semibold text-text-primary">
            确认写入大纲
          </h1>
          <p className="mt-1 text-[13px] text-text-secondary">
            已选 {selectedCount} / {preview.nodes.length}。取消勾选可跳过；确认前不会写入数据库。
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" icon={<X size={14} />} disabled={committing} onClick={onDiscard}>
            丢弃
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon={<Check size={14} />}
            disabled={committing || generating || selectedCount === 0}
            onClick={onCommit}
          >
            {committing
              ? "写入中…"
              : generating
                ? "补全中…"
                : `确认写入（${selectedCount}）`}
          </Button>
        </div>
      </div>

      {issues.length > 0 && (
        <div className="mb-4 rounded-card border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3">
          <p className="text-[13px] font-medium text-text-primary">
            连贯检查
            {typeof preview.coherence?.score === "number"
              ? ` · 评分 ${preview.coherence.score}`
              : ""}
            {preview.coherence?.pass === false ? " · 存在需关注问题" : ""}
          </p>
          <ul className="mt-2 space-y-1 text-[12px] text-text-secondary">
            {issues.slice(0, 8).map((issue, i) => (
              <li key={i}>
                [{issue.severity || "info"}] {issue.title}：{issue.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-2">
        {preview.nodes.map((node, index) => {
          const details = node.details || {};
          const selected = node.selected !== false;
          const kind = node.kind || preview.childKind;
          const goal = kind === "volume" ? details.stage_goal : details.goal;
          const pacing =
            details.pacing && typeof details.pacing === "object"
              ? (details.pacing as Record<string, unknown>)
              : {};
          return (
            <div
              key={index}
              className={cn(
                "rounded-card border px-4 py-3",
                selected ? "border-border bg-surface" : "border-border/60 bg-surface-subtle opacity-70",
              )}
            >
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-2"
                  checked={selected}
                  onChange={() => toggle(index)}
                  aria-label={`选择 ${friendlyOutlineTitle(node.title)}`}
                />
                <div className="min-w-0 flex-1">
                  <TextInput
                    value={friendlyOutlineTitle(node.title)}
                    onChange={(e) => setTitle(index, e.target.value)}
                    className="font-medium"
                  />
                  <p className="mt-2 text-[13px] text-text-secondary">
                    <span className="font-medium text-text-primary">
                      {kind === "volume" ? "阶段目标：" : "目标："}
                    </span>
                    {String(goal || "—")}
                  </p>
                  {kind === "volume" && (
                    <>
                      <div className="mt-2 flex max-w-[180px] items-center gap-2">
                        <span className="shrink-0 text-[12px] text-text-secondary">章节预算</span>
                        <TextInput
                          type="number"
                          min={1}
                          value={String(details.planned_chapters ?? "")}
                          onChange={(event) =>
                            setDetails(index, {
                              planned_chapters: Math.max(1, Number(event.target.value) || 1),
                            })
                          }
                        />
                      </div>
                      {details.arc_summary ? (
                        <p className="mt-2 text-[12px] text-text-secondary">
                          梗概：{String(details.arc_summary)}
                        </p>
                      ) : null}
                      {Array.isArray(details.plot_arcs) && details.plot_arcs.length > 0 ? (
                        <p className="mt-2 text-[12px] text-text-secondary">
                          剧情阶段：{(details.plot_arcs as string[]).join("；")}
                        </p>
                      ) : null}
                    </>
                  )}
                  {kind === "arc" && details.planned_chapters ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      预算：{String(details.planned_chapters)} 章
                    </p>
                  ) : null}
                  {Array.isArray(details.must_events) && details.must_events.length > 0 && (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      关键情节：{(details.must_events as string[]).join("；")}
                    </p>
                  )}
                  {kind === "chapter" && details.time_anchor ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      时间：{String(details.time_anchor)} · {String(details.chapter_span || "由 AI 补齐")}
                    </p>
                  ) : null}
                  {kind === "chapter" && (details.cbn || details.cen) ? (
                    <p className="mt-1 line-clamp-2 text-[12px] text-text-secondary">
                      章节推进：{String(details.cbn || "开场待补")} → {String(details.cen || "收束待补")}
                    </p>
                  ) : null}
                  {Array.isArray(details.characters) && details.characters.length > 0 ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      出场人物：{(details.characters as string[]).join("、")}
                    </p>
                  ) : null}
                  {Array.isArray(details.locations) && details.locations.length > 0 ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      出场地点：{(details.locations as string[]).join("、")}
                    </p>
                  ) : null}
                  {details.highlight ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      亮点：{String(details.highlight)}
                    </p>
                  ) : null}
                  {details.twist ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      转折：{String(details.twist)}
                    </p>
                  ) : null}
                  {details.hook ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      钩子：{String(details.hook)}
                    </p>
                  ) : null}
                  {kind === "chapter" && pacing.phaseLabel ? (
                    <p className="mt-1 text-[12px] text-text-secondary">
                      节奏：{String(pacing.phaseLabel)}
                      {pacing.arcPosition && pacing.arcTotal
                        ? ` · 本阶段第 ${String(pacing.arcPosition)} / ${String(pacing.arcTotal)} 章`
                        : ""}
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function IconGhost({
  children,
  label,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      className="flex h-9 w-9 items-center justify-center rounded-control text-text-secondary hover:bg-surface-subtle"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function findNode(nodes: OutlineNode[], id: string): OutlineNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findNode(node.children ?? [], id);
    if (child) return child;
  }
}

function findFirstChapter(nodes: OutlineNode[]): OutlineNode | undefined {
  return findFirstKind(nodes, "chapter");
}

function findFirstKind(
  nodes: OutlineNode[],
  kind: OutlineNode["kind"],
): OutlineNode | undefined {
  for (const node of nodes) {
    if (node.kind === kind) return node;
    const child = findFirstKind(node.children ?? [], kind);
    if (child) return child;
  }
}

function TreeNode({
  node,
  depth,
  selected,
  onSelect,
}: {
  node: OutlineNode;
  depth: number;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasChildren = !!node.children?.length;
  const Icon = kindIcon[node.kind];
  const active = node.id === selected;

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-1.5 rounded-control py-1.5 pr-2 text-left text-[13px] transition-colors duration-150",
          active ? "bg-[#F0FDFA] text-text-primary" : "text-text-primary hover:bg-surface-subtle",
        )}
        style={{ paddingLeft: 8 + depth * 16 }}
      >
        {hasChildren ? (
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex h-5 w-5 shrink-0 items-center justify-center text-text-secondary"
            aria-label={open ? "折叠" : "展开"}
          >
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )}
        <button
          onClick={() => onSelect(node.id)}
          className="flex min-w-0 flex-1 items-center gap-1.5"
        >
          <Icon size={14} className="shrink-0 text-text-secondary" />
          <span className={cn("truncate", node.kind === "volume" && "font-medium")}>
            {friendlyOutlineTitle(node.title)}
          </span>
          {node.locked && <Lock size={12} className="shrink-0 text-text-secondary" />}
        </button>
      </div>
      {hasChildren && open && (
        <div>
          {node.children!.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}
