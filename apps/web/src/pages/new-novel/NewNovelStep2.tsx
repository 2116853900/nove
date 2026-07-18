import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { WizardShell } from "./WizardShell";
import { Field, Select, TextArea } from "@/components/ui/form";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { readNewNovelDraft, updateNewNovelDraft } from "@/lib/api";

const GENRES = [
  "未分类", "玄幻", "仙侠", "都市", "历史", "科幻", "悬疑",
  "规则怪谈", "古代言情", "现代言情", "现实",
] as const;

const LENGTHS = [
  { chapters: 80, label: "先写第一卷", detail: "约 24 万字" },
  { chapters: 200, label: "中长篇", detail: "约 60 万字" },
  { chapters: 400, label: "长篇", detail: "约 120 万字" },
] as const;

function closestLength(chapters: number) {
  return LENGTHS.reduce((best, item) =>
    Math.abs(item.chapters - chapters) < Math.abs(best.chapters - chapters) ? item : best,
  ).chapters;
}

export function NewNovelStep2() {
  const navigate = useNavigate();
  const draft = readNewNovelDraft();
  const [idea, setIdea] = useState(draft.core_idea);
  const [genre, setGenre] = useState(draft.genre || "未分类");
  const [plannedChapters, setPlannedChapters] = useState(() => closestLength(draft.planned_chapters));

  const next = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const storyIdea = idea.trim();
    if (!storyIdea) return;
    updateNewNovelDraft({
      title: "",
      genre,
      language: "zh-CN",
      core_idea: storyIdea,
      planned_chapters: plannedChapters,
      target_words: plannedChapters * 3000,
      creation_mode: "scratch",
      writing_profile: { ...draft.writing_profile, strict_workflow: false },
    });
    navigate("/new/3");
  };

  return (
    <WizardShell current={2}>
      <form onSubmit={next} className="w-full max-w-[640px] rounded-card border border-border bg-surface p-6 sm:p-8">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-primary text-white">
            <Sparkles size={18} />
          </span>
          <div>
            <h2 className="text-[18px] font-semibold text-text-primary">你想写一个什么故事？</h2>
            <p className="mt-1 text-[13px] text-text-secondary">一句话就够，云端模型会生成书名、人物、世界和章节安排。</p>
          </div>
        </div>

        <div className="mt-6">
          <Field label="故事想法" htmlFor="idea">
            <TextArea
              id="idea"
              name="core_idea"
              required
              autoFocus
              rows={6}
              value={idea}
              onChange={(event) => setIdea(event.target.value)}
              placeholder="例如：一个只能看见别人剩余寿命的急诊医生，发现新来的病人没有死亡日期。"
            />
          </Field>
        </div>

        <div className="mt-6 border-t border-border pt-5">
          <p className="text-[13px] font-medium text-text-primary">偏好（可选）</p>
          <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Field label="故事类型" htmlFor="genre" hint="拿不准就交给云端模型判断。">
              <Select id="genre" value={genre} onChange={(event) => setGenre(event.target.value)}>
                {GENRES.map((item) => <option key={item} value={item}>{item === "未分类" ? "让 AI 判断" : item}</option>)}
              </Select>
            </Field>
            <div>
              <p className="mb-2 text-[13px] font-medium text-text-primary">预计篇幅</p>
              <div className="grid grid-cols-3 gap-2">
                {LENGTHS.map((item) => {
                  const active = plannedChapters === item.chapters;
                  return (
                    <button
                      key={item.chapters}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setPlannedChapters(item.chapters)}
                      className={cn(
                        "min-h-[62px] border px-2 py-2 text-center transition-colors",
                        active ? "border-primary bg-[#F0FDFA] text-primary" : "border-border text-text-secondary hover:bg-surface-subtle",
                      )}
                    >
                      <span className="block text-[12px] font-medium leading-tight">{item.label}</span>
                      <span className="mt-1 block text-[11px] leading-tight opacity-75">{item.detail}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-8 flex items-center justify-between">
          <Button type="button" variant="ghost" onClick={() => navigate("/new/1")}>上一步</Button>
          <Button type="submit" variant="primary" disabled={!idea.trim()}>下一步</Button>
        </div>
      </form>
    </WizardShell>
  );
}
