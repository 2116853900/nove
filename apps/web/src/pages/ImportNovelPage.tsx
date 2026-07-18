import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileText, Upload, BookOpen, Check } from "lucide-react";
import { Field, Select, TextInput, TextArea } from "@/components/ui/form";
import { Button } from "@/components/ui/Button";
import { apiRequest, useApiQuery, type ModelConfig, type Novel } from "@/lib/api";
import { cn } from "@/lib/cn";

/** Mirrors backend CHAPTER_SPLIT_RE for live preview. */
const CHAPTER_SPLIT_RE =
  /^(?:#{1,3}\s*)?(第\s*[0-9一二三四五六七八九十百千零〇两]+\s*章[^\n]*|Chapter\s+\d+[^\n]*)$/gim;

function splitManuscriptPreview(text: string): Array<{ title: string; words: number; excerpt: string }> {
  const raw = (text || "").replace(/\r\n/g, "\n").trim();
  if (!raw) return [];
  const matches = [...raw.matchAll(CHAPTER_SPLIT_RE)];
  if (!matches.length) {
    return [
      {
        title: "第 1 章 · 导入正文",
        words: raw.length,
        excerpt: raw.slice(0, 80).replace(/\s+/g, " "),
      },
    ];
  }
  const chapters: Array<{ title: string; words: number; excerpt: string }> = [];
  if (matches[0].index && matches[0].index > 40) {
    const preamble = raw.slice(0, matches[0].index).trim();
    if (preamble) {
      chapters.push({
        title: "序章 · 导入前言",
        words: preamble.length,
        excerpt: preamble.slice(0, 80).replace(/\s+/g, " "),
      });
    }
  }
  matches.forEach((match, index) => {
    const title = match[0].replace(/^#+\s*/, "").trim();
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < matches.length ? (matches[index + 1].index ?? raw.length) : raw.length;
    const body = raw.slice(start, end).trim();
    chapters.push({
      title,
      words: body.length,
      excerpt: (body || "（正文为空）").slice(0, 80).replace(/\s+/g, " "),
    });
  });
  return chapters;
}

function modelLabel(model: ModelConfig) {
  const status =
    model.status === "connected" ? "已连接" : model.status === "error" ? "连接失败" : "未测试";
  return `${model.modelId || model.name}（${status}）`;
}

/**
 * Dedicated import flow (PRD §7.2 / IA §3.1) — not the new-novel wizard.
 * 粘贴/上传 → 预览切分 → 选择模型 → 导入审阅。
 */
export function ImportNovelPage() {
  const navigate = useNavigate();
  const modelsQuery = useApiQuery<ModelConfig[]>("/models", []);
  const models = modelsQuery.data;

  const [title, setTitle] = useState("");
  const [genre, setGenre] = useState("导入");
  const [coreIdea, setCoreIdea] = useState("");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [modelId, setModelId] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const defaultModelId = useMemo(() => {
    if (!models.length) return "";
    return (
      models.find((m) => m.id === modelId)?.id ||
      models.find((m) => m.isDefault)?.id ||
      models.find((m) => m.status === "connected")?.id ||
      models[0].id
    );
  }, [models, modelId]);

  const chapters = useMemo(() => splitManuscriptPreview(text), [text]);
  const totalWords = useMemo(() => text.replace(/\s/g, "").length, [text]);
  const canSubmit = title.trim().length > 0 && text.trim().length >= 20 && !busy;

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    const content = await file.text();
    setText(content);
    setFileName(file.name);
    if (!title.trim()) {
      setTitle(file.name.replace(/\.(txt|md|markdown)$/i, ""));
    }
  };

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiRequest<{ novel: Novel; import: { novelId: string; chapterCount: number } }>(
        "/novels/import",
        {
          method: "POST",
          body: JSON.stringify({
            title: title.trim(),
            text,
            genre: genre.trim() || "导入",
            core_idea: coreIdea.trim(),
            confirm_all: confirmAll,
            default_model_id: modelId || defaultModelId || undefined,
          }),
        },
      );
      navigate(`/novel/${result.novel.id}/import-review`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="flex h-topbar shrink-0 items-center justify-between border-b border-border bg-surface px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-control bg-primary text-[14px] font-bold text-white">
            N
          </span>
          <span className="text-[16px] text-text-primary">导入小说</span>
        </div>
        <Link
          to="/"
          className="flex h-9 items-center rounded-control border border-border bg-surface px-3 text-[13px] text-text-secondary hover:bg-surface-subtle"
        >
          取消
        </Link>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid w-full max-w-[1100px] gap-6 px-8 py-8 lg:grid-cols-[1fr_340px]">
          <div className="flex flex-col gap-5">
            <div>
              <h1 className="text-[22px] font-semibold text-text-primary">从已有正文继续</h1>
              <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-text-secondary">
                粘贴或上传 TXT / Markdown。系统按「第 N 章」或 Markdown 标题切分章节，导入后进入审阅页核对切分与人物，再开始写作。
              </p>
            </div>

            <div className="rounded-card border border-border bg-surface p-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="书名" htmlFor="import-title">
                  <TextInput
                    id="import-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="导入后的项目名称"
                    required
                  />
                </Field>
                <Field label="类型" htmlFor="import-genre">
                  <Select
                    id="import-genre"
                    value={genre}
                    onChange={(e) => setGenre(e.target.value)}
                  >
                    <option value="导入">导入 / 未分类</option>
                    <option value="玄幻">玄幻</option>
                    <option value="奇幻">奇幻</option>
                    <option value="都市">都市</option>
                    <option value="科幻">科幻</option>
                    <option value="悬疑">悬疑</option>
                    <option value="言情">言情</option>
                    <option value="武侠">武侠</option>
                    <option value="仙侠">仙侠</option>
                  </Select>
                </Field>
                <Field label="一句话梗概（可选）" htmlFor="import-idea" className="sm:col-span-2">
                  <TextInput
                    id="import-idea"
                    value={coreIdea}
                    onChange={(e) => setCoreIdea(e.target.value)}
                    placeholder="便于后续大纲与记忆检索"
                  />
                </Field>
              </div>
            </div>

            <div className="rounded-card border border-border bg-surface p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-semibold text-text-primary">正文文稿</h2>
                  <p className="mt-0.5 text-[12px] text-text-secondary">
                    支持「第 N 章 …」或 <code className="text-[11px]"># 第 N 章</code> 标题切分
                  </p>
                </div>
                <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-control border border-border bg-surface-subtle px-3 text-[13px] text-text-primary hover:bg-border/40">
                  <Upload size={14} />
                  选择文件
                  <input
                    type="file"
                    accept=".txt,.md,.markdown,text/plain,text/markdown"
                    className="hidden"
                    onChange={(e) => void onFile(e.target.files?.[0])}
                  />
                </label>
              </div>
              {fileName && (
                <p className="mt-2 flex items-center gap-1.5 text-[12px] text-text-secondary">
                  <FileText size={13} />
                  已加载 {fileName}
                </p>
              )}
              <TextArea
                className="mt-3 min-h-[280px] font-mono text-[13px] leading-relaxed"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={"第 1 章 开端\n……\n\n第 2 章 转折\n……"}
              />
              <div className="mt-2 flex flex-wrap gap-4 text-[12px] text-text-secondary">
                <span>约 {totalWords.toLocaleString()} 字</span>
                <span>{chapters.length} 章（预览）</span>
                {text.trim().length > 0 && text.trim().length < 20 && (
                  <span className="text-warning">正文至少 20 字</span>
                )}
              </div>
            </div>

            <div className="rounded-card border border-border bg-surface p-6">
              <h2 className="text-[15px] font-semibold text-text-primary">模型（可选）</h2>
              <p className="mt-0.5 text-[12px] text-text-secondary">
                导入后克隆到本书，用于后续提取与写作。可在项目设置中修改。
              </p>
              <div className="mt-4">
                <Field label="默认模型" htmlFor="import-model">
                  <Select
                    id="import-model"
                    value={modelId || defaultModelId}
                    onChange={(e) => setModelId(e.target.value)}
                    disabled={!models.length}
                  >
                    {!models.length && <option value="">暂无模型库配置</option>}
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {modelLabel(m)}
                        {m.isDefault ? " · 默认" : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <label className="mt-4 flex cursor-pointer items-start gap-2.5 text-[13px] text-text-secondary">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={confirmAll}
                  onChange={(e) => setConfirmAll(e.target.checked)}
                />
                <span>
                  导入后自动确认全部章节并建立记忆索引
                  <span className="mt-0.5 block text-[12px] text-text-secondary">
                    建议先进入审阅页核对切分，再手动确认。
                  </span>
                </span>
              </label>
            </div>

            <div className="flex items-center justify-between pb-8">
              <Link
                to="/new/1"
                className="text-[13px] text-text-secondary hover:text-text-primary"
              >
                没有文稿？去新建小说
              </Link>
              <Button variant="primary" disabled={!canSubmit} onClick={() => void submit()}>
                {busy ? "正在导入…" : "导入并进入审阅"}
              </Button>
            </div>
            {error && (
              <p className="pb-6 text-right text-[13px] text-danger" role="alert">
                {error}
              </p>
            )}
          </div>

          <aside className="flex flex-col gap-4 lg:sticky lg:top-8 lg:self-start">
            <div className="rounded-card border border-border bg-surface p-5">
              <div className="flex items-center gap-2 text-[14px] font-semibold text-text-primary">
                <BookOpen size={16} />
                切分预览
              </div>
              <p className="mt-1 text-[12px] text-text-secondary">
                与后端规则一致，导入前可先核对章节数。
              </p>
              <div className="mt-4 max-h-[480px] space-y-2 overflow-y-auto">
                {chapters.length === 0 && (
                  <p className="rounded-control bg-surface-subtle px-3 py-6 text-center text-[13px] text-text-secondary">
                    粘贴正文后显示章节列表
                  </p>
                )}
                {chapters.map((ch, index) => (
                  <div
                    key={`${ch.title}-${index}`}
                    className={cn(
                      "rounded-control border border-border bg-surface-subtle/50 px-3 py-2.5",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[13px] font-medium text-text-primary">{ch.title}</p>
                      <span className="shrink-0 text-[11px] tabular-nums text-text-secondary">
                        {ch.words.toLocaleString()} 字
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-text-secondary">
                      {ch.excerpt}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-card border border-border bg-surface p-5">
              <p className="text-[13px] font-medium text-text-primary">导入后你会</p>
              <ul className="mt-3 space-y-2 text-[12px] leading-relaxed text-text-secondary">
                <li className="flex gap-2">
                  <Check size={14} className="mt-0.5 shrink-0 text-primary" />
                  在审阅页检查章节切分与人物
                </li>
                <li className="flex gap-2">
                  <Check size={14} className="mt-0.5 shrink-0 text-primary" />
                  确认章节后写入长期记忆
                </li>
                <li className="flex gap-2">
                  <Check size={14} className="mt-0.5 shrink-0 text-primary" />
                  从下一章继续 AI 写作与质量检查
                </li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
