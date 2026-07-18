import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronDown, ChevronRight, Cloud, Plus } from "lucide-react";
import { WizardShell } from "./WizardShell";
import { Field, Select, TextInput } from "@/components/ui/form";
import { Button } from "@/components/ui/Button";
import {
  apiRequest,
  readNewNovelDraft,
  updateNewNovelDraft,
  useApiQuery,
  type ModelConfig,
} from "@/lib/api";
import { cn } from "@/lib/cn";

const PROVIDERS = ["OpenAI 兼容", "DeepSeek", "DashScope"] as const;

const PROVIDER_DEFAULTS: Record<string, { baseUrl: string; modelId: string }> = {
  "OpenAI 兼容": { baseUrl: "https://api.openai.com/v1", modelId: "" },
  DeepSeek: { baseUrl: "https://api.deepseek.com/v1", modelId: "deepseek-chat" },
  DashScope: {
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    modelId: "qwen-max",
  },
};

type ModelForm = {
  provider: string;
  modelId: string;
  apiKey: string;
  baseUrl: string;
};

function initialForm(): ModelForm {
  return {
    provider: "OpenAI 兼容",
    modelId: "",
    apiKey: "",
    baseUrl: PROVIDER_DEFAULTS["OpenAI 兼容"].baseUrl,
  };
}

function isCloudModel(model: ModelConfig) {
  return !["本地", "local", "Ollama", "vLLM"].includes(model.provider);
}

export function NewNovelStep1() {
  const navigate = useNavigate();
  const draft = readNewNovelDraft();
  const modelsQuery = useApiQuery<ModelConfig[]>("/models", []);
  const connected = useMemo(
    () => modelsQuery.data.filter((model) => model.status === "connected" && isCloudModel(model)),
    [modelsQuery.data],
  );
  const [selectedId, setSelectedId] = useState(draft.default_model_id ?? "");
  const [showForm, setShowForm] = useState(false);
  const [details, setDetails] = useState(false);
  const [form, setForm] = useState<ModelForm>(initialForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const usableId = connected.some((model) => model.id === selectedId)
    ? selectedId
    : connected[0]?.id ?? "";

  const saveModel = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    let createdId = "";
    try {
      if (!form.modelId.trim()) throw new Error("请填写模型标识");
      if (!form.apiKey.trim()) throw new Error("请填写云端模型密钥");
      if (!form.baseUrl.trim()) throw new Error("请填写云端模型服务地址");
      const created = await apiRequest<ModelConfig>("/models", {
        method: "POST",
        body: JSON.stringify({
          name: form.modelId.trim(),
          provider: form.provider,
          model_id: form.modelId.trim(),
          base_url: form.baseUrl.trim(),
          api_key: form.apiKey.trim(),
          roles: [],
          is_default: modelsQuery.data.length === 0,
        }),
      });
      createdId = created.id;
      const tested = await apiRequest<ModelConfig>(`/models/${created.id}/test`, {
        method: "POST",
      });
      if (tested.status !== "connected") throw new Error("模型连接测试未通过");
      await modelsQuery.refetch();
      setSelectedId(created.id);
      setShowForm(false);
      setForm(initialForm());
      setMessage(`已连接「${created.name}」`);
    } catch (reason) {
      if (createdId) {
        await apiRequest(`/models/${createdId}`, { method: "DELETE" }).catch(() => undefined);
        await modelsQuery.refetch().catch(() => undefined);
      }
      setError(reason instanceof Error ? reason.message : "模型连接失败");
    } finally {
      setSaving(false);
    }
  };

  const next = () => {
    if (!usableId) return;
    updateNewNovelDraft({
      default_model_id: usableId,
      plan_model_id: usableId,
      write_model_id: usableId,
      audit_model_id: usableId,
    });
    navigate("/new/2");
  };

  return (
    <WizardShell current={1}>
      <div className="w-full max-w-[640px] rounded-card border border-border bg-surface p-6 sm:p-8">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-primary text-white">
            <Cloud size={18} />
          </span>
          <div>
            <h2 className="text-[18px] font-semibold text-text-primary">先连接云端模型</h2>
            <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
              Nove 只使用已连接的云端模型。连接成功后，故事设定和章节都由这个模型完成。
            </p>
          </div>
        </div>

        {modelsQuery.loading ? (
          <p className="mt-6 border-y border-border py-5 text-[13px] text-text-secondary">正在检查模型…</p>
        ) : connected.length > 0 ? (
          <div className="mt-6 space-y-2 border-y border-border py-5">
            <p className="mb-3 text-[13px] font-medium text-text-primary">选择已连接模型</p>
            {connected.map((model) => {
              const active = model.id === usableId;
              return (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => setSelectedId(model.id)}
                  className={cn(
                    "flex w-full items-center justify-between border px-4 py-3 text-left transition-colors",
                    active ? "border-primary bg-[#F0FDFA]" : "border-border hover:bg-surface-subtle",
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] font-medium text-text-primary">{model.name}</span>
                    <span className="mt-0.5 block text-[12px] text-text-secondary">{model.provider} · {model.modelId}</span>
                  </span>
                  {active && <Check size={17} className="shrink-0 text-primary" />}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="mt-6 border-y border-border py-5 text-[13px] text-text-secondary">
            还没有可用模型，请完成下面的连接。
          </p>
        )}

        {connected.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            icon={<Plus size={14} />}
            className="mt-4"
            onClick={() => setShowForm((value) => !value)}
          >
            {showForm ? "收起模型连接" : "连接新的云端模型"}
          </Button>
        )}

        {(showForm || (!modelsQuery.loading && connected.length === 0)) && (
          <div className="mt-5 border-t border-border pt-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="服务商">
                <Select
                  value={form.provider}
                  onChange={(event) => {
                    const provider = event.target.value;
                    setForm((current) => ({ ...current, provider, ...PROVIDER_DEFAULTS[provider] }));
                  }}
                >
                  {PROVIDERS.map((provider) => <option key={provider}>{provider}</option>)}
                </Select>
              </Field>
              <Field label="模型标识" hint="例如 deepseek-chat 或 gpt-5">
                <TextInput
                  required
                  value={form.modelId}
                  onChange={(event) => setForm((current) => ({ ...current, modelId: event.target.value }))}
                  placeholder="模型标识"
                />
              </Field>
              <Field label="密钥" className="sm:col-span-2">
                <TextInput
                  required
                  type="password"
                  autoComplete="new-password"
                  value={form.apiKey}
                  onChange={(event) => setForm((current) => ({ ...current, apiKey: event.target.value }))}
                  placeholder="仅保存在当前 Nove 服务中"
                />
              </Field>
            </div>

            <button
              type="button"
              onClick={() => setDetails((value) => !value)}
              className="mt-4 flex items-center gap-1 text-[12px] text-text-secondary hover:text-text-primary"
            >
              {details ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              连接细节
            </button>
            {details && (
              <div className="mt-4">
                <Field label="云端服务地址">
                  <TextInput
                    value={form.baseUrl}
                    onChange={(event) => setForm((current) => ({ ...current, baseUrl: event.target.value }))}
                  />
                </Field>
              </div>
            )}

            <div className="mt-5 flex justify-end">
              <Button
                type="button"
                variant="primary"
                disabled={saving || !form.modelId.trim() || !form.apiKey.trim()}
                onClick={() => void saveModel()}
              >
                {saving ? "正在测试连接…" : "保存并测试连接"}
              </Button>
            </div>
          </div>
        )}

        {message && <p className="mt-4 text-[13px] text-success">{message}</p>}
        {error && <p className="mt-4 text-[13px] text-danger" role="alert">{error}</p>}

        <div className="mt-8 flex justify-end">
          <Button type="button" variant="primary" disabled={!usableId} onClick={next}>
            下一步
          </Button>
        </div>
      </div>
    </WizardShell>
  );
}
