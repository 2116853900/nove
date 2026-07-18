import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Cloud, Sparkles } from "lucide-react";
import { WizardShell } from "./WizardShell";
import { Button } from "@/components/ui/Button";
import {
  apiRequest,
  clearNewNovelDraft,
  readNewNovelDraft,
  useApiQuery,
  type ModelConfig,
  type Novel,
} from "@/lib/api";

function isCloudModel(model: ModelConfig) {
  return !["本地", "local", "Ollama", "vLLM"].includes(model.provider);
}

export function NewNovelStep3() {
  const navigate = useNavigate();
  const draft = readNewNovelDraft();
  const modelsQuery = useApiQuery<ModelConfig[]>("/models", []);
  const usableModel = useMemo(
    () => modelsQuery.data.find(
      (model) => model.id === draft.default_model_id && model.status === "connected" && isCloudModel(model),
    ),
    [draft.default_model_id, modelsQuery.data],
  );
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createNovel = async () => {
    if (!usableModel || !draft.core_idea.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const novel = await apiRequest<Novel>("/novels", {
        method: "POST",
        body: JSON.stringify({
          title: "未命名小说",
          genre: draft.genre,
          language: draft.language,
          core_idea: draft.core_idea,
          target_words: draft.target_words,
          planned_chapters: draft.planned_chapters,
          creation_mode: "scratch",
          auto_audit: true,
          auto_bootstrap: true,
          writing_profile: { ...draft.writing_profile, strict_workflow: false },
          default_model_id: usableModel.id,
          plan_model_id: usableModel.id,
          write_model_id: usableModel.id,
          audit_model_id: usableModel.id,
        }),
      });
      clearNewNovelDraft();
      sessionStorage.removeItem("nove:import-text");
      navigate(`/novel/${novel.id}/setup`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const missingIdea = !draft.core_idea.trim();

  return (
    <WizardShell current={3}>
      <div className="w-full max-w-[640px] rounded-card border border-border bg-surface p-6 sm:p-8">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-primary text-white">
            <Sparkles size={18} />
          </span>
          <div>
            <h2 className="text-[18px] font-semibold text-text-primary">准备自动搭建故事</h2>
            <p className="mt-1 text-[13px] text-text-secondary">
              确认后，云端模型会生成书名、人物、世界、全书规划和首批章节。
            </p>
          </div>
        </div>

        <dl className="mt-6 divide-y divide-border border-y border-border">
          <div className="py-4">
            <dt className="flex items-center gap-1.5 text-[12px] text-text-secondary"><Cloud size={14} /> 云端模型</dt>
            <dd className="mt-1 text-[14px] font-medium text-text-primary">
              {modelsQuery.loading ? "正在检查…" : usableModel ? usableModel.name : "尚未连接"}
            </dd>
          </div>
          <div className="py-4">
            <dt className="text-[12px] text-text-secondary">故事想法</dt>
            <dd className="mt-1 text-[14px] leading-6 text-text-primary">{draft.core_idea || "尚未填写"}</dd>
          </div>
          <div className="grid grid-cols-2 gap-4 py-4">
            <div>
              <dt className="text-[12px] text-text-secondary">故事类型</dt>
              <dd className="mt-1 text-[14px] text-text-primary">{draft.genre === "未分类" ? "由 AI 判断" : draft.genre}</dd>
            </div>
            <div>
              <dt className="text-[12px] text-text-secondary">预计篇幅</dt>
              <dd className="mt-1 text-[14px] text-text-primary">约 {draft.planned_chapters} 章</dd>
            </div>
          </div>
        </dl>

        {!modelsQuery.loading && !usableModel && (
          <div className="mt-5 border-l-2 border-danger pl-4">
            <p className="text-[13px] font-medium text-text-primary">云端模型未连接或连接已失效</p>
            <p className="mt-1 text-[12px] text-text-secondary">返回第一步重新测试连接后才能开始。</p>
          </div>
        )}
        {missingIdea && (
          <p className="mt-5 text-[13px] text-danger">请返回第二步填写故事想法。</p>
        )}

        <div className="mt-8 flex items-center justify-between gap-3">
          <Button variant="ghost" onClick={() => navigate("/new/2")}>上一步</Button>
          {!modelsQuery.loading && !usableModel ? (
            <Button variant="primary" onClick={() => navigate("/new/1")}>连接模型</Button>
          ) : (
            <Button
              variant="primary"
              disabled={creating || modelsQuery.loading || !usableModel || missingIdea}
              onClick={() => void createNovel()}
            >
              {creating ? "正在创建…" : "开始自动搭建"}
            </Button>
          )}
        </div>
        {error && <p className="mt-4 text-right text-[13px] text-danger" role="alert">{error}</p>}
      </div>
    </WizardShell>
  );
}
