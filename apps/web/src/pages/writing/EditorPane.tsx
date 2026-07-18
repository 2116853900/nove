import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Extension } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Highlight from "@tiptap/extension-highlight";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import {
  Check,
  History,
  Heading2,
  Lock,
  Maximize2,
  Minimize2,
  Redo2,
  Save,
  Search,
  Sparkles,
  Square,
  Undo2,
  X,
  Loader2,
} from "lucide-react";
import type { AuditReport, ChapterDetail } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { useWorkspaceStore } from "@/stores/workspace";
import { cn } from "@/lib/cn";
import { buildEvidenceMarks, plainOffsetToPmPos } from "@/lib/text-marks";
import {
  editorDocumentToText,
  markdownOffsetToPlainOffset,
  parseEditorText,
  plainOffsetToMarkdownOffset,
  textToEditorDocument,
} from "@/lib/editor-document";

export type SelectionOp = "expand" | "shrink" | "rewrite" | "dialogue" | "style";

export interface SelectionCandidate {
  operation: SelectionOp;
  start: number;
  end: number;
  originalText: string;
  candidateText: string;
  mergedContent: string;
  modelName?: string;
}

export interface EvidenceSelectionRequest {
  start: number;
  end: number;
  requestId: number;
}

type SelectionSnapshot = ReturnType<typeof selectionOffsets>;

function selectionOffsets(editor: NonNullable<ReturnType<typeof useEditor>>) {
  const { from, to, empty } = editor.state.selection;
  if (empty) return null;
  const serialized = editorDocumentToText(editor.getJSON());
  const plainStart = editor.state.doc.textBetween(0, from, "\n\n").length;
  const plainSelected = editor.state.doc.textBetween(from, to, "\n\n");
  const start = plainOffsetToMarkdownOffset(serialized, plainStart);
  const end = plainOffsetToMarkdownOffset(serialized, plainStart + plainSelected.length);
  const selected = serialized.slice(start, end);
  return { start, end, selected, content: serialized, from, to };
}

const SELECTION_OPS: { op: SelectionOp; label: string }[] = [
  { op: "expand", label: "扩写" },
  { op: "shrink", label: "缩写" },
  { op: "rewrite", label: "改写" },
  { op: "dialogue", label: "对话" },
  { op: "style", label: "文风" },
];

const auditRewritePluginKey = new PluginKey<number | null>("auditRewriteInline");

const AuditRewriteInline = Extension.create({
  name: "auditRewriteInline",
  addProseMirrorPlugins() {
    return [
      new Plugin<number | null>({
        key: auditRewritePluginKey,
        state: {
          init: () => null,
          apply(transaction, position) {
            const next = transaction.getMeta(auditRewritePluginKey) as number | null | undefined;
            if (next === null || typeof next === "number") return next;
            return position == null ? null : transaction.mapping.map(position, 1);
          },
        },
        props: {
          decorations(state) {
            const position = auditRewritePluginKey.getState(state);
            if (position == null) return null;
            const safePosition = Math.max(1, Math.min(position, state.doc.content.size));
            return DecorationSet.create(state.doc, [
              Decoration.widget(
                safePosition,
                () => {
                  const host = document.createElement("span");
                  host.className = "nove-audit-rewrite-anchor";
                  host.setAttribute("contenteditable", "false");
                  host.setAttribute("data-audit-rewrite-host", "");
                  return host;
                },
                {
                  side: 1,
                  marks: [],
                  key: `audit-rewrite-${safePosition}`,
                  stopEvent: () => true,
                  ignoreSelection: true,
                },
              ),
            ]);
          },
        },
      }),
    ];
  },
});

export function EditorPane({
  generating,
  generationPreview = null,
  generationPreviewActive = false,
  chapter,
  content,
  title,
  dirty = false,
  saving = false,
  selectionBusy = false,
  selectionError = null,
  selectionCandidate = null,
  selectionGuidance = null,
  onContentChange,
  onTitleChange,
  onLockedRangesChange,
  onSave,
  onToggleGenerate,
  onDismissGenerationPreview,
  onOpenVersions,
  onOpenAiPanel,
  onSelectionEdit,
  onAcceptSelection,
  onRejectSelection,
  evidenceSelection,
  audit = null,
}: {
  generating: boolean;
  generationPreview?: string | null;
  generationPreviewActive?: boolean;
  chapter: ChapterDetail | null;
  content: string;
  title: string;
  dirty?: boolean;
  saving?: boolean;
  selectionBusy?: boolean;
  selectionError?: string | null;
  selectionCandidate?: SelectionCandidate | null;
  selectionGuidance?: string | null;
  onContentChange: (content: string) => void;
  onTitleChange: (title: string) => void;
  onLockedRangesChange: (ranges: { start: number; end: number }[]) => void;
  onSave: () => void;
  onToggleGenerate: () => void;
  onDismissGenerationPreview: () => void;
  onOpenVersions: () => void;
  onOpenAiPanel: () => void;
  onSelectionEdit: (payload: {
    operation: SelectionOp;
    start: number;
    end: number;
    selectedText: string;
    content: string;
  }) => void;
  onAcceptSelection: () => void;
  onRejectSelection: () => void;
  evidenceSelection?: EvidenceSelectionRequest | null;
  audit?: AuditReport | null;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [showGenerationPreview, setShowGenerationPreview] = useState(false);
  const [auditRewriteHost, setAuditRewriteHost] = useState<HTMLElement | null>(null);
  const selectionRef = useRef<SelectionSnapshot>(null);
  const reportedContentRef = useRef(content);
  const { focusMode, toggleFocusMode } = useWorkspaceStore();
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: "从这里开始写作…" }),
      Highlight.configure({ multicolor: true }),
      AuditRewriteInline,
    ],
    content: textToEditorDocument(content),
    editorProps: {
      attributes: {
        class:
          "nove-editor min-h-full w-full font-serif text-body-edit text-text-primary outline-none",
        "aria-label": "章节正文",
        spellcheck: "false",
      },
    },
    onUpdate: ({ editor: instance, transaction }) => {
      if (instance.isDestroyed) return;
      // Programmatic highlight/mark decorations must not create a user edit version.
      if (transaction.getMeta("noveIgnoreUpdate")) return;
      const nextContent = editorDocumentToText(instance.getJSON());
      if (nextContent === reportedContentRef.current) return;
      reportedContentRef.current = nextContent;
      onContentChange(nextContent);
    },
    onSelectionUpdate: ({ editor: instance }) => {
      if (instance.isDestroyed) return;
      const nextSelection = selectionOffsets(instance);
      selectionRef.current = nextSelection;
    },
  });

  useEffect(() => {
    reportedContentRef.current = content;
  }, [content]);

  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const current = editorDocumentToText(editor.getJSON());
    if (current !== content) {
      editor.commands.setContent(textToEditorDocument(content), { emitUpdate: false });
    }
  }, [content, editor]);

  useEffect(() => {
    if (generationPreview !== null) setShowGenerationPreview(true);
  }, [generationPreview]);

  // Apply audit issue decorations (and locked ranges as muted marks).
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const issues = [
      ...(audit?.fatalIssues ?? []),
      ...(audit?.issues ?? []),
    ];
    const marks = buildEvidenceMarks(
      content,
      issues.map((i) => ({ evidence: i.evidence, severity: i.severity })),
    );
    const { state, view } = editor;
    const tr = state.tr;
    // Clear existing highlights
    state.doc.descendants((node, pos) => {
      if (!node.isText) return true;
      if (node.marks.some((m) => m.type.name === "highlight")) {
        tr.removeMark(pos, pos + node.nodeSize, state.schema.marks.highlight);
      }
      return true;
    });
    for (const mark of marks) {
      const from = plainOffsetToPmPos(state.doc, markdownOffsetToPlainOffset(content, mark.from));
      const to = plainOffsetToPmPos(state.doc, markdownOffsetToPlainOffset(content, mark.to));
      if (to <= from) continue;
      const color =
        mark.severity === "fatal"
          ? "var(--audit-fatal-bg)"
          : mark.severity === "major"
            ? "var(--audit-major-bg)"
            : "var(--audit-minor-bg)";
      tr.addMark(from, to, state.schema.marks.highlight.create({ color }));
    }
    if (tr.steps.length) {
      tr.setMeta("addToHistory", false);
      tr.setMeta("noveIgnoreUpdate", true);
      view.dispatch(tr);
    }
  }, [editor, content, audit]);

  useEffect(() => {
    if (!editor || editor.isDestroyed || !evidenceSelection) return;
    const from = plainOffsetToPmPos(
      editor.state.doc,
      markdownOffsetToPlainOffset(content, evidenceSelection.start),
    );
    const to = plainOffsetToPmPos(
      editor.state.doc,
      markdownOffsetToPlainOffset(content, evidenceSelection.end),
    );
    editor
      .chain()
      .focus()
      .setTextSelection(to > from ? { from, to } : from)
      .scrollIntoView()
      .run();
  }, [content, editor, evidenceSelection]);

  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    if (!selectionGuidance || !evidenceSelection) {
      if (auditRewritePluginKey.getState(editor.state) != null) {
        editor.view.dispatch(editor.state.tr.setMeta(auditRewritePluginKey, null));
      }
      setAuditRewriteHost(null);
      return;
    }

    const rawEnd = selectionCandidate?.end ?? evidenceSelection.end;
    const end = plainOffsetToPmPos(
      editor.state.doc,
      markdownOffsetToPlainOffset(content, rawEnd),
    );
    const resolved = editor.state.doc.resolve(end);
    let depth = resolved.depth;
    while (depth > 0 && !resolved.node(depth).isTextblock) depth -= 1;
    const position = depth > 0 ? resolved.end(depth) : end;
    editor.view.dispatch(editor.state.tr.setMeta(auditRewritePluginKey, position));

    const frame = window.requestAnimationFrame(() => {
      if (editor.isDestroyed) return;
      const host = editor.view.dom.querySelector<HTMLElement>("[data-audit-rewrite-host]");
      setAuditRewriteHost(host);
      host?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [content, editor, evidenceSelection, selectionCandidate?.end, selectionGuidance]);

  const matchCount = useMemo(() => {
    if (!search.trim()) return 0;
    return content.toLocaleLowerCase().split(search.toLocaleLowerCase()).length - 1;
  }, [content, search]);

  const lockSelection = () => {
    if (!editor) return;
    const offsets = selectionRef.current ?? selectionOffsets(editor);
    if (!offsets) return;
    const ranges = chapter?.lockedRanges ?? [];
    if (!ranges.some((range) => range.start === offsets.start && range.end === offsets.end)) {
      onLockedRangesChange([...ranges, { start: offsets.start, end: offsets.end }]);
    }
  };

  const runSelectionOp = (operation: SelectionOp) => {
    if (!editor || selectionBusy) return;
    const offsets = selectionOffsets(editor);
    if (!offsets || !offsets.selected.trim()) return;
    onSelectionEdit({
      operation,
      start: offsets.start,
      end: offsets.end,
      selectedText: offsets.selected,
      content: offsets.content,
    });
  };

  const closeSelectionMenu = () => {
    const end = selectionRef.current?.to;
    selectionRef.current = null;
    if (editor && end != null) editor.commands.setTextSelection(end);
  };

  const memoryLabel =
    chapter?.memoryStatus === "INDEXED"
      ? "记忆已同步"
      : chapter?.memoryStatus === "PENDING"
        ? "记忆待同步"
        : "草稿未入记忆";

  const lockedPreview = (chapter?.lockedRanges ?? [])
    .slice(0, 3)
    .map((range) => content.slice(range.start, range.end).slice(0, 24))
    .filter(Boolean);

  return (
    <section className="flex min-w-0 flex-1 flex-col bg-background">
      <div className="border-b border-border bg-surface px-3 py-3 sm:px-6">
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <input
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            className="min-w-0 flex-1 bg-transparent text-[20px] font-semibold text-text-primary outline-none placeholder:text-text-secondary"
            aria-label="章节标题"
          />
          <div className="grid shrink-0 grid-cols-2 gap-2 sm:flex sm:items-center">
            <Button
              variant="secondary"
              disabled={!dirty || saving}
              onClick={onSave}
              icon={saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            >
              {saving ? "保存中…" : dirty ? "保存版本" : "版本已保存"}
            </Button>
            <Button
              variant={generating ? "danger" : "primary"}
              disabled={!generating && dirty}
              onClick={onToggleGenerate}
              icon={generating ? <Square size={15} /> : <Sparkles size={15} />}
            >
              {generating ? "停止生成" : dirty ? "先保存版本" : "生成本章"}
            </Button>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[13px] text-text-secondary">
          <span>
            <span className="text-text-primary">{content.length.toLocaleString()}</span> /{" "}
            {chapter?.targetWords.toLocaleString() ?? "—"} 字
          </span>
          <span>大纲关键情节 {(chapter?.brief.must_events as string[] | undefined)?.length ?? 0} 项</span>
          <span
            className={
              chapter?.memoryStatus === "INDEXED"
                ? "flex items-center gap-1 text-success"
                : "text-text-secondary"
            }
          >
            {chapter?.memoryStatus === "INDEXED" && <Check size={13} />} {memoryLabel}
          </span>
          {!!chapter?.lockedRanges.length && (
            <span title={lockedPreview.join(" · ")}>
              {chapter.lockedRanges.length} 处内容已锁定
            </span>
          )}
          {!!audit?.issues?.length && (
            <span className="text-warning">
              检查标记 {(audit.fatalIssues?.length ?? 0) + (audit.issues?.length ?? 0)} 处
            </span>
          )}
        </div>
      </div>

      <div className="flex min-h-12 flex-wrap items-center gap-1 border-b border-border bg-surface px-4 py-1.5">
        <IconButton
          label="撤销"
          icon={<Undo2 size={16} />}
          disabled={!editor?.can().undo()}
          onClick={() => editor?.chain().focus().undo().run()}
        />
        <IconButton
          label="重做"
          icon={<Redo2 size={16} />}
          disabled={!editor?.can().redo()}
          onClick={() => editor?.chain().focus().redo().run()}
        />
        <IconButton
          label="查找"
          active={searchOpen}
          icon={<Search size={16} />}
          onClick={() => setSearchOpen((open) => !open)}
        />
        <IconButton label="锁定选区" icon={<Lock size={16} />} onClick={lockSelection} />
        <IconButton
          label="标题"
          active={editor?.isActive("heading", { level: 2 })}
          icon={<Heading2 size={16} />}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
        />
        <IconButton label="AI 面板" icon={<Sparkles size={16} />} onClick={onOpenAiPanel} />
        <IconButton
          label={focusMode ? "退出专注模式" : "专注模式"}
          active={focusMode}
          icon={focusMode ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          onClick={toggleFocusMode}
        />
        <div className="mx-1 h-5 w-px bg-border" />
        <IconButton label="版本历史" icon={<History size={16} />} onClick={onOpenVersions} />
        {generationPreview !== null && (
          <div className="ml-auto flex items-center gap-1 rounded-control bg-surface-subtle p-1">
            <button
              type="button"
              className={cn(
                "rounded px-2.5 py-1 text-[12px]",
                !showGenerationPreview ? "bg-surface text-text-primary shadow-sm" : "text-text-secondary",
              )}
              onClick={() => setShowGenerationPreview(false)}
            >
              正文
            </button>
            <button
              type="button"
              className={cn(
                "rounded px-2.5 py-1 text-[12px]",
                showGenerationPreview ? "bg-surface text-primary shadow-sm" : "text-text-secondary",
              )}
              onClick={() => setShowGenerationPreview(true)}
            >
              AI 草稿
            </button>
            <button
              type="button"
              className="rounded p-1 text-text-secondary hover:bg-surface hover:text-text-primary"
              aria-label="关闭 AI 草稿预览"
              onClick={onDismissGenerationPreview}
            >
              <X size={13} />
            </button>
          </div>
        )}
        {searchOpen && (
          <div className="ml-2 flex h-9 min-w-[220px] items-center gap-2 rounded-control border border-border bg-background px-2">
            <Search size={14} className="text-text-secondary" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="查找正文"
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
              autoFocus
            />
            <span className="text-[12px] tabular-nums text-text-secondary">{matchCount}</span>
            <button
              aria-label="关闭查找"
              onClick={() => {
                setSearchOpen(false);
                setSearch("");
              }}
              className="text-text-secondary hover:text-text-primary"
            >
              <X size={14} />
            </button>
          </div>
        )}
      </div>

      {!!chapter?.lockedRanges?.length && (
        <div className="border-b border-border bg-[#FFFBEB] px-4 py-2 text-[12px] text-text-secondary">
          <span className="mr-2 font-medium text-warning">锁定段</span>
          {lockedPreview.map((snippet, index) => (
            <span key={`${snippet}-${index}`} className="mr-3 inline-block max-w-[180px] truncate align-bottom">
              「{snippet}{snippet.length >= 24 ? "…" : ""}」
            </span>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto min-h-full w-full max-w-[840px] px-4 py-6 sm:px-10 sm:py-10">
          {editor && !showGenerationPreview && !selectionGuidance && (
            <BubbleMenu
              editor={editor}
              pluginKey="selectionAiMenu"
              updateDelay={80}
              appendTo={() => document.body}
              options={{
                strategy: "fixed",
                placement: "bottom-start",
                offset: 10,
                flip: true,
                shift: { padding: 12 },
              }}
              shouldShow={({ from, to }) => from !== to}
            >
              <div
                className="w-[min(440px,calc(100vw-32px))] overflow-hidden rounded-[8px] border border-border bg-surface shadow-[0_16px_42px_rgba(31,41,55,0.16)]"
                onMouseDown={(event) => event.preventDefault()}
              >
                <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-control bg-primary/10 text-primary">
                      <Sparkles size={14} />
                    </span>
                    <div className="min-w-0">
                      <p className="text-[13px] font-semibold text-text-primary">AI 修改</p>
                      {selectionCandidate?.modelName && (
                        <p className="truncate text-[11px] text-text-secondary">{selectionCandidate.modelName}</p>
                      )}
                    </div>
                  </div>
                  {selectionCandidate && (
                    <span className="text-[11px] text-text-secondary">候选结果</span>
                  )}
                </div>

                {!selectionCandidate && !selectionBusy && (
                  <div className="grid grid-cols-5 gap-1.5 p-2.5">
                    {SELECTION_OPS.map((item) => (
                      <button
                        key={item.op}
                        type="button"
                        onClick={() => runSelectionOp(item.op)}
                        className="h-9 rounded-control border border-transparent bg-surface-subtle px-2 text-[12px] font-medium text-text-primary transition-colors duration-150 hover:border-border hover:bg-surface active:translate-y-px"
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                )}

                {selectionBusy && (
                  <div className="flex items-center gap-3 px-3 py-4 text-[13px] text-text-secondary">
                    <Loader2 size={16} className="shrink-0 animate-spin text-primary" />
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-text-primary">正在修改选区</p>
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-subtle">
                        <div className="h-full w-1/2 animate-pulse rounded-full bg-primary/60" />
                      </div>
                    </div>
                  </div>
                )}

                {selectionError && !selectionBusy && (
                  <div className="border-t border-[#FECACA] bg-[#FEF2F2] px-3 py-2 text-[12px] text-danger" role="alert">
                    {selectionError}
                  </div>
                )}

                {selectionCandidate && (
                  <>
                    <div className="max-h-48 overflow-y-auto px-4 py-3">
                      <p className="whitespace-pre-wrap font-serif text-[14px] leading-7 text-text-primary">
                        {selectionCandidate.candidateText}
                      </p>
                    </div>
                    <div className="flex items-center justify-end gap-2 border-t border-border bg-surface-subtle px-3 py-2.5">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          onRejectSelection();
                          closeSelectionMenu();
                        }}
                        icon={<X size={14} />}
                      >
                        拒绝
                      </Button>
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => {
                          onAcceptSelection();
                          closeSelectionMenu();
                        }}
                        icon={<Check size={14} />}
                      >
                        接受修改
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </BubbleMenu>
          )}
          {auditRewriteHost && selectionGuidance && createPortal(
            <AuditRewritePanel
              guidance={selectionGuidance}
              candidate={selectionCandidate}
              busy={selectionBusy}
              error={selectionError}
              onReject={() => {
                onRejectSelection();
                closeSelectionMenu();
              }}
              onAccept={() => {
                onAcceptSelection();
                closeSelectionMenu();
              }}
            />,
            auditRewriteHost,
          )}
          {showGenerationPreview && generationPreview !== null ? (
            <GenerationPreview content={generationPreview} active={generationPreviewActive} />
          ) : (
            <EditorContent editor={editor} className="min-h-[calc(100vh-230px)]" />
          )}
        </div>
      </div>
    </section>
  );
}

function AuditRewritePanel({
  guidance,
  candidate,
  busy,
  error,
  onReject,
  onAccept,
}: {
  guidance: string;
  candidate: SelectionCandidate | null;
  busy: boolean;
  error: string | null;
  onReject: () => void;
  onAccept: () => void;
}) {
  return (
    <section className="nove-audit-rewrite-card overflow-hidden rounded-card border border-primary/25 bg-surface font-sans text-text-primary shadow-[0_8px_24px_rgba(31,41,55,0.10)]">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <span className="flex items-center gap-2 text-[13px] font-semibold">
          <Sparkles size={15} className="text-primary" />
          按检查建议改写
        </span>
        {candidate?.modelName && (
          <span className="max-w-[220px] truncate text-[11px] text-text-secondary">
            {candidate.modelName}
          </span>
        )}
      </header>

      <div className="border-b border-border bg-primary/5 px-4 py-3">
        <p className="text-[11px] font-semibold text-primary">质量建议</p>
        <p className="mt-1 text-[13px] leading-6 text-text-secondary">{guidance}</p>
      </div>

      {busy && (
        <div className="flex items-center gap-3 px-4 py-5 text-[13px] text-text-secondary" role="status">
          <Loader2 size={16} className="shrink-0 animate-spin text-primary" />
          <span>正在根据质量建议改写…</span>
        </div>
      )}

      {error && !busy && (
        <div className="flex items-center justify-between gap-4 px-4 py-4" role="alert">
          <p className="text-[12px] leading-5 text-danger">{error}</p>
          <Button size="sm" variant="ghost" onClick={onReject}>关闭</Button>
        </div>
      )}

      {candidate && !busy && (
        <>
          <div className="px-4 py-4">
            <p className="mb-2 text-[11px] font-semibold text-text-secondary">改写内容</p>
            <p className="max-h-64 overflow-y-auto whitespace-pre-wrap font-serif text-[15px] leading-8 text-text-primary">
              {candidate.candidateText}
            </p>
          </div>
          <footer className="flex items-center justify-end gap-2 border-t border-border bg-surface-subtle px-4 py-3">
            <Button size="sm" variant="ghost" onClick={onReject} icon={<X size={14} />}>
              保留原文
            </Button>
            <Button size="sm" variant="primary" onClick={onAccept} icon={<Check size={14} />}>
              应用改写
            </Button>
          </footer>
        </>
      )}
    </section>
  );
}

function GenerationPreview({ content, active }: { content: string; active: boolean }) {
  const blocks = parseEditorText(content);
  if (!content) {
    return (
      <div className="flex min-h-[calc(100vh-230px)] items-center justify-center font-serif text-[15px] text-text-secondary">
        <span className="inline-flex items-center gap-2">
          <Loader2 size={15} className="animate-spin" /> 正在等待正文输出…
        </span>
      </div>
    );
  }

  return (
    <article className="nove-rich-text min-h-[calc(100vh-230px)] font-serif text-body-edit text-text-primary">
      {blocks.map((block, index) => {
        const isLast = index === blocks.length - 1;
        const children = (
          <>
            {block.runs.map((run, runIndex) => (
              run.bold
                ? <strong key={`${block.sourceStart}-${runIndex}`}>{run.text}</strong>
                : <span key={`${block.sourceStart}-${runIndex}`}>{run.text}</span>
            ))}
            {active && isLast && <span className="nove-stream-caret" aria-hidden="true" />}
          </>
        );
        return block.type === "heading" ? (
          <h2 key={`${block.sourceStart}-${index}`}>{children}</h2>
        ) : (
          <p key={`${block.sourceStart}-${index}`}>{children}</p>
        );
      })}
    </article>
  );
}
