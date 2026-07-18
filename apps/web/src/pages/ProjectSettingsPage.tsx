import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertTriangle, Check, ChevronDown, ChevronRight, Circle, Cloud, Cpu, Download, HardDrive, Plug, Save, ShieldCheck, TestTube2, Trash2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextArea, TextInput, Toggle } from "@/components/ui/form";
import { apiRequest, useApiQuery, type AuditConfig, type ModelConfig, type Novel, type SkillConfig, type WritingProfile } from "@/lib/api";
import { cn } from "@/lib/cn";

const tabs = [
  { key: "models", label: "AI 模型" },
  { key: "roles", label: "AI 分工" },
  { key: "usage", label: "使用情况" },
  { key: "writing", label: "故事偏好" },
  { key: "audit", label: "质量检查" },
  { key: "skills", label: "扩展能力" },
];
const modelRoles = ["大纲", "写作", "审计", "连续性", "润色", "记忆提取", "Embedding"];
const modelRoleLabels: Record<string, string> = {
  大纲: "故事规划",
  写作: "正文写作",
  审计: "质量检查",
  连续性: "前后检查",
  润色: "表达优化",
  记忆提取: "资料整理",
  Embedding: "智能记忆",
};
const agentNames = ["Outline", "Plot", "Writer", "Continuity", "Auditor", "Style", "Memory"];

export function ProjectSettingsPage() {
  const [tab, setTab] = useState("writing");
  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
        <div className="flex items-center gap-1 overflow-x-auto border-b border-border bg-surface px-4">
          <span className="mr-3 shrink-0 whitespace-nowrap py-3 text-[13px] font-semibold">项目设置</span>
          {tabs.map((item) => (
            <button key={item.key} onClick={() => setTab(item.key)} className={cn("relative shrink-0 whitespace-nowrap px-3 py-3 text-[13px]", tab === item.key ? "font-medium text-text-primary" : "text-text-secondary")}>
              {item.label}
              {tab === item.key && <span className="absolute inset-x-2 bottom-0 h-0.5 bg-primary" />}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-8">
          {tab === "models" && <ModelsTab />}
          {tab === "roles" && <RolesTab />}
          {tab === "usage" && <UsageTab />}
          {tab === "writing" && <WritingRulesTab />}
          {tab === "audit" && <AuditRulesTab />}
          {tab === "skills" && <SkillsTab />}
        </div>
      </div>
  );
}

const modelSchema = z.object({
  name: z.string(),
  provider: z.string().min(1),
  modelId: z.string().min(1, "请输入模型标识"),
  baseUrl: z.string().url("请输入完整的云端 URL"),
  apiKey: z.string(),
  temperature: z.number().min(0).max(2),
  topP: z.number().gt(0).max(1),
  maxOutputTokens: z.number().int().min(128).max(131072),
  contextSize: z.number().int().min(1024).max(2_000_000),
  timeoutMs: z.number().int().min(1000).max(600000),
});
type ModelForm = z.infer<typeof modelSchema>;

const modelProviderDefaults: Record<string, Partial<ModelForm>> = {
  "OpenAI 兼容": { baseUrl: "https://api.openai.com/v1", modelId: "" },
  DeepSeek: { baseUrl: "https://api.deepseek.com/v1", modelId: "deepseek-chat" },
  DashScope: {
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    modelId: "qwen-plus",
  },
};

const statusMeta = {
  connected: { label: "已连接", icon: Check, className: "text-success" },
  error: { label: "连接失败", icon: AlertTriangle, className: "text-danger" },
  untested: { label: "未测试", icon: Circle, className: "text-text-secondary" },
};

function ModelsTab() {
  const { id } = useParams();
  const query = useApiQuery<ModelConfig[]>(id ? `/novels/${id}/models` : null, []);
  const [adding, setAdding] = useState(false);
  const [connectionDetails, setConnectionDetails] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeMode, setProbeMode] = useState<"test" | "fetch" | null>(null);
  const [remoteModels, setRemoteModels] = useState<Array<{ id: string; name: string }>>([]);
  const [savedRemoteModels, setSavedRemoteModels] = useState<Record<string, Array<{ id: string; name: string }>>>({});
  const [savedSelections, setSavedSelections] = useState<Record<string, string>>({});
  const [savedAction, setSavedAction] = useState<{ id: string; mode: "test" | "fetch" | "apply" } | null>(null);
  const { register, handleSubmit, reset, watch, setValue, formState: { errors, isSubmitting } } = useForm<ModelForm>({
    resolver: zodResolver(modelSchema),
    defaultValues: {
      provider: "OpenAI 兼容",
      temperature: 0.7,
      topP: 1,
      maxOutputTokens: 8192,
      contextSize: 128000,
      timeoutMs: 120000,
      baseUrl: "https://api.openai.com/v1",
      apiKey: "",
      name: "",
      modelId: "",
    },
  });
  const watched = watch();
  const changeProvider = (provider: string) => {
    setValue("provider", provider, { shouldDirty: true });
    const defaults = modelProviderDefaults[provider];
    if (defaults?.baseUrl !== undefined) setValue("baseUrl", defaults.baseUrl, { shouldDirty: true });
    if (defaults?.modelId !== undefined) setValue("modelId", defaults.modelId, { shouldDirty: true });
    if (defaults?.apiKey !== undefined) setValue("apiKey", defaults.apiKey, { shouldDirty: true });
    setRemoteModels([]);
    setMessage(null);
  };
  const submit = handleSubmit(async (values) => {
    if (!id) return;
    const created = await apiRequest<ModelConfig>(`/novels/${id}/models`, {
      method: "POST",
      body: JSON.stringify({
        name: values.name.trim() || values.modelId,
        provider: values.provider,
        model_id: values.modelId,
        base_url: values.baseUrl,
        api_key: values.apiKey,
        roles: [],
        temperature: values.temperature,
        top_p: values.topP,
        max_output_tokens: values.maxOutputTokens,
        context_size: values.contextSize,
        timeout_ms: values.timeoutMs,
        extra_body: {},
      }),
    });
    try {
      await apiRequest(`/models/${created.id}/test`, { method: "POST" });
    } catch {
      /* status updated on server */
    }
    await query.refetch();
    reset();
    setRemoteModels([]);
    setAdding(false);
    setMessage("模型配置已保存；连接测试通过后才会进入生成工作流。");
  });
  const probe = async (mode: "test" | "fetch") => {
    if (!watched.baseUrl?.trim()) {
      setConnectionDetails(true);
      setMessage("请先填写服务地址，再测试连接。");
      return;
    }
    setProbeBusy(true);
    setProbeMode(mode);
    setMessage(mode === "fetch" ? "正在获取模型列表…" : "正在测试连接…");
    try {
      const result = await apiRequest<{
        ok: boolean;
        latencyMs: number;
        models: Array<{ id: string; name: string }>;
        message: string;
      }>("/models/probe", {
        method: "POST",
        body: JSON.stringify({
          provider: watched.provider,
          base_url: watched.baseUrl,
          api_key: watched.apiKey,
          model_id: watched.modelId,
          timeout_ms: watched.timeoutMs,
        }),
      });
      setRemoteModels(result.models ?? []);
      if (mode === "fetch" && result.models?.length) {
        const pick = result.models.find((m) => m.id === watched.modelId) || result.models[0];
        setValue("modelId", pick.id);
        if (!watched.name) setValue("name", pick.name || pick.id);
      }
      setMessage(
        result.latencyMs ? `${result.message}（${result.latencyMs} ms）` : result.message,
      );
    } catch (reason) {
      setRemoteModels([]);
      setMessage(reason instanceof Error ? reason.message : "连接测试失败");
    } finally {
      setProbeBusy(false);
      setProbeMode(null);
    }
  };
  const test = async (modelId: string) => {
    setSavedAction({ id: modelId, mode: "test" });
    setMessage("正在测试连接…");
    try {
      const result = await apiRequest<{ probe?: { message?: string; latencyMs?: number } }>(
        `/models/${modelId}/test`,
        { method: "POST" },
      );
      setMessage(result.probe?.message || "连接测试通过。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "连接测试失败");
    }
    await query.refetch();
    setSavedAction(null);
  };
  const fetchRemote = async (modelId: string) => {
    setSavedAction({ id: modelId, mode: "fetch" });
    setMessage("正在获取模型列表…");
    try {
      const result = await apiRequest<{ models: Array<{ id: string; name: string }>; message: string }>(
        `/models/${modelId}/remote-models`,
        { method: "GET" },
      );
      const models = result.models ?? [];
      setSavedRemoteModels((current) => ({ ...current, [modelId]: models }));
      const currentModel = query.data.find((model) => model.id === modelId)?.modelId;
      setSavedSelections((current) => ({
        ...current,
        [modelId]: models.some((model) => model.id === currentModel)
          ? currentModel || ""
          : models[0]?.id || "",
      }));
      setMessage(models.length ? `已获取 ${models.length} 个模型，请选择后应用。` : result.message);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "获取模型失败");
    } finally {
      setSavedAction(null);
    }
  };
  const applyRemoteModel = async (configId: string) => {
    const modelId = savedSelections[configId];
    if (!modelId) return;
    setSavedAction({ id: configId, mode: "apply" });
    setMessage("正在应用模型…");
    try {
      await apiRequest(`/models/${configId}`, {
        method: "PATCH",
        body: JSON.stringify({ model_id: modelId }),
      });
      await apiRequest(`/models/${configId}/test`, { method: "POST" });
      await query.refetch();
      setSavedRemoteModels((current) => {
        const next = { ...current };
        delete next[configId];
        return next;
      });
      setMessage(`已切换并连接到 ${modelId}。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "应用模型失败");
    } finally {
      setSavedAction(null);
    }
  };
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-page-title font-semibold">本书使用的 AI</h1>
          <p className="mt-1 text-[13px] text-text-secondary">
            创建小说时已自动分配。只有需要更换服务时才连接其他模型。
          </p>
        </div>
        <Button variant="primary" icon={<Plug size={15} />} onClick={() => setAdding((value) => !value)}>连接其他模型</Button>
      </div>
      {adding && (
        <form onSubmit={submit} className="grid grid-cols-2 gap-4 border-y border-border bg-surface py-5">
          <Field label="供应商"><Select value={watched.provider} onChange={(event) => changeProvider(event.target.value)}><option>OpenAI 兼容</option><option>DeepSeek</option><option>DashScope</option></Select></Field>
          <Field label="密钥" hint="会加密保存在本机服务中。"><TextInput type="password" autoComplete="new-password" {...register("apiKey")} /></Field>
          <Field label="服务地址" className="col-span-2"><TextInput placeholder="https://api.openai.com/v1" {...register("baseUrl")} />{errors.baseUrl && <ErrorText>{errors.baseUrl.message}</ErrorText>}</Field>
          <div className="col-span-2 flex flex-wrap gap-2">
            <Button type="button" icon={<TestTube2 size={14} />} disabled={probeBusy} onClick={() => void probe("test")}>{probeMode === "test" ? "测试中…" : "测试连接"}</Button>
            <Button type="button" disabled={probeBusy} onClick={() => void probe("fetch")}>{probeMode === "fetch" ? "获取中…" : "获取模型"}</Button>
            {message && <p className="basis-full text-[13px] text-text-secondary" role="status" aria-live="polite">{message}</p>}
          </div>
          <Field label="模型" hint="可点“获取模型”后直接选择" className="col-span-2">
            {remoteModels.length > 0 ? (
              <Select value={watched.modelId} onChange={(e) => setValue("modelId", e.target.value, { shouldValidate: true })}>
                {remoteModels.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
              </Select>
            ) : (
              <TextInput {...register("modelId")} />
            )}
            {errors.modelId && <ErrorText>{errors.modelId.message}</ErrorText>}
          </Field>
          <button
            type="button"
            onClick={() => setConnectionDetails((value) => !value)}
            className="col-span-2 flex items-center gap-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary"
          >
            {connectionDetails ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            连接细节
          </button>
          {connectionDetails && (
            <div className="col-span-2 grid grid-cols-2 gap-4 border-t border-border pt-4">
              <Field label="配置名称"><TextInput placeholder="默认使用模型名称" {...register("name")} /></Field>
              <Field label="等待时间（毫秒）"><TextInput type="number" {...register("timeoutMs", { valueAsNumber: true })} /></Field>
              <Field label="随机度"><TextInput type="number" step="0.1" {...register("temperature", { valueAsNumber: true })} /></Field>
              <Field label="采样范围"><TextInput type="number" step="0.05" {...register("topP", { valueAsNumber: true })} /></Field>
              <Field label="单次输出上限"><TextInput type="number" {...register("maxOutputTokens", { valueAsNumber: true })} /></Field>
              <Field label="可参考内容容量"><TextInput type="number" {...register("contextSize", { valueAsNumber: true })} /></Field>
            </div>
          )}
          <div className="col-span-2 flex justify-end gap-2"><Button onClick={() => setAdding(false)}>取消</Button><Button type="submit" variant="primary" icon={<Save size={14} />} disabled={isSubmitting}>保存配置</Button></div>
        </form>
      )}
      {!adding && message && <p className="text-[13px] text-text-secondary" role="status" aria-live="polite">{message}</p>}
      <div className="overflow-x-auto border-y border-border"><table className="w-full min-w-[760px] text-left text-[13px]"><thead className="bg-surface-subtle text-text-secondary"><tr>{["名称","供应商 / 模型","状态","任务","密钥","操作"].map((item)=><th key={item} className="px-4 py-2.5 font-medium">{item}</th>)}</tr></thead><tbody className="divide-y divide-border bg-surface">
        {query.data.map((model) => { const meta = statusMeta[model.status]; const Icon = meta.icon; const options = savedRemoteModels[model.id] ?? []; const busy = savedAction?.id === model.id; return <tr key={model.id}><td className="px-4 py-3 font-medium">{model.name}</td><td className="px-4 py-3 text-text-secondary">{model.provider}<br/><span className="text-[12px]">{model.modelId}</span></td><td className={cn("px-4 py-3",meta.className)}><span className="inline-flex items-center gap-1"><Icon size={14}/>{meta.label}</span></td><td className="px-4 py-3 text-text-secondary">{model.roles.map((role) => modelRoleLabels[role] || role).join("、") || "未分配"}</td><td className="px-4 py-3 text-text-secondary">{model.apiKeyMasked || "未填写"}</td><td className="px-4 py-3"><div className="flex min-w-[220px] flex-col gap-2"><div className="flex flex-wrap gap-2"><Button size="sm" icon={<TestTube2 size={14}/>} disabled={busy} onClick={() => void test(model.id)}>{busy && savedAction?.mode === "test" ? "测试中…" : "测试连接"}</Button><Button size="sm" disabled={busy} onClick={() => void fetchRemote(model.id)}>{busy && savedAction?.mode === "fetch" ? "获取中…" : "获取模型"}</Button></div>{options.length > 0 && <div className="flex items-center gap-2"><Select className="min-w-0" value={savedSelections[model.id] || ""} onChange={(event) => setSavedSelections((current) => ({ ...current, [model.id]: event.target.value }))}>{options.map((option) => <option key={option.id} value={option.id}>{option.id}</option>)}</Select><Button size="sm" variant="primary" disabled={busy} onClick={() => void applyRemoteModel(model.id)}>{busy && savedAction?.mode === "apply" ? "应用中…" : "应用"}</Button></div>}</div></td></tr>; })}
      </tbody></table></div>
    </div>
  );
}

interface EmbeddingCatalogItem {
  key: string;
  tier: string;
  tierLabel: string;
  name: string;
  modelId: string;
  sizeLabel: string;
  sizeBytesApprox: number;
  dimensions: number;
  description: string;
  suitableFor: string;
  recommended: boolean;
  downloaded: boolean;
  cachePath?: string;
  cacheRoot?: string;
  downloadSource?: string;
  hfEndpoint?: string;
}

interface EmbeddingDownloadStatus {
  novelId?: string;
  catalogKey: string;
  state: "idle" | "downloading" | "ready" | "error" | string;
  progress: number;
  message: string;
  modelId: string;
  error?: string | null;
  cachePath?: string;
  bytesDownloaded?: number;
  bytesTotalApprox?: number;
}

function formatBytes(n?: number): string {
  if (n == null || n <= 0) return "—";
  if (n >= 1024 * 1024 * 1024) return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function RolesTab() {
  const { id } = useParams();
  const query = useApiQuery<ModelConfig[]>(id ? `/novels/${id}/models` : null, []);
  const catalogQuery = useApiQuery<{
    items: EmbeddingCatalogItem[];
    downloadSource?: { hfEndpoint?: string; label?: string; hint?: string };
  }>("/embedding/local-catalog", { items: [] });
  const [embedPanel, setEmbedPanel] = useState<null | "local" | "cloud">(null);
  const [downloadStatus, setDownloadStatus] = useState<EmbeddingDownloadStatus | null>(null);
  const [embedMessage, setEmbedMessage] = useState<string | null>(null);
  const [cloudForm, setCloudForm] = useState({
    name: "",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    apiKey: "",
    modelId: "text-embedding-v3",
    provider: "DashScope",
  });
  const [cloudBusy, setCloudBusy] = useState(false);
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);

  const assign = async (role: string, modelId: string) => {
    const requests = query.data
      .filter((model) => model.roles.includes(role) || model.id === modelId)
      .map((model) => {
        const roles =
          model.id === modelId
            ? Array.from(new Set([...model.roles, role]))
            : model.roles.filter((item) => item !== role);
        return apiRequest(`/models/${model.id}`, {
          method: "PATCH",
          body: JSON.stringify({ roles }),
        });
      });
    await Promise.all(requests);
    await query.refetch();
  };

  const embedModel = query.data.find((model) =>
    (model.roles || []).some((r) => r === "Embedding" || r.toLowerCase() === "embedding"),
  );
  const embedAssigned = Boolean(embedModel);
  const agentRoles = modelRoles.filter((role) => role !== "Embedding");

  useEffect(() => {
    if (!id || !downloadingKey) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await apiRequest<EmbeddingDownloadStatus>(
          `/novels/${id}/embedding/local/status`,
        );
        if (cancelled) return;
        setDownloadStatus(status);
        if (status.state === "ready") {
          setDownloadingKey(null);
          setEmbedMessage(`已启用本地模型 ${status.modelId || ""}。若已有旧向量，建议在记忆面板重建索引。`);
          await query.refetch();
          await catalogQuery.refetch();
        } else if (status.state === "error") {
          setDownloadingKey(null);
          setEmbedMessage(status.message || status.error || "下载失败");
        }
      } catch (reason) {
        if (!cancelled) {
          setDownloadingKey(null);
          setEmbedMessage(reason instanceof Error ? reason.message : "无法获取下载状态");
        }
      }
    };
    void tick();
    // Poll frequently so progress bar tracks disk growth during long pulls.
    const timer = window.setInterval(() => void tick(), 400);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [id, downloadingKey]);

  const startLocalDownload = async (catalogKey: string) => {
    if (!id) return;
    setEmbedMessage(null);
    setDownloadingKey(catalogKey);
    setDownloadStatus({
      catalogKey,
      state: "downloading",
      progress: 0,
      message: "开始下载…",
      modelId: "",
    });
    try {
      const status = await apiRequest<EmbeddingDownloadStatus>(
        `/novels/${id}/embedding/local/download`,
        { method: "POST", body: JSON.stringify({ catalog_key: catalogKey }) },
      );
      setDownloadStatus(status);
      if (status.state === "ready") {
        setDownloadingKey(null);
        setEmbedMessage(`已启用本地模型 ${status.modelId || ""}。若已有旧向量，建议重建索引。`);
        await query.refetch();
        await catalogQuery.refetch();
      } else if (status.state === "error") {
        setDownloadingKey(null);
        setEmbedMessage(status.message || "下载失败");
      }
    } catch (reason) {
      setDownloadingKey(null);
      setEmbedMessage(reason instanceof Error ? reason.message : "下载失败");
    }
  };

  const saveCloudEmbedding = async () => {
    if (!id) return;
    if (!cloudForm.baseUrl.trim() || !cloudForm.modelId.trim()) {
      setEmbedMessage("请填写服务地址与模型名称");
      return;
    }
    setCloudBusy(true);
    setEmbedMessage(null);
    try {
      const created = await apiRequest<ModelConfig>(`/novels/${id}/embedding/cloud`, {
        method: "POST",
        body: JSON.stringify({
          name: cloudForm.name,
          base_url: cloudForm.baseUrl,
          api_key: cloudForm.apiKey,
          model_id: cloudForm.modelId,
          provider: cloudForm.provider,
        }),
      });
      setEmbedPanel(null);
      setEmbedMessage(
        created.status === "connected"
          ? `已分配云端 Embedding：${created.name}`
          : `已保存 ${created.name}（状态：${created.status === "error" ? "连接失败，请检查端点" : created.status}）`,
      );
      await query.refetch();
    } catch (reason) {
      setEmbedMessage(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setCloudBusy(false);
    }
  };

  const clearEmbedding = async () => {
    if (!id) return;
    await apiRequest(`/novels/${id}/embedding/assignment`, { method: "DELETE" });
    setEmbedMessage("已关闭增强记忆，系统将继续使用基础记忆。");
    await query.refetch();
  };

  const applyCloudPreset = (preset: "dashscope" | "openai") => {
    if (preset === "dashscope") {
      setCloudForm({
        name: "通义 Embedding",
        baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        apiKey: cloudForm.apiKey,
        modelId: "text-embedding-v3",
        provider: "DashScope",
      });
    } else {
      setCloudForm({
        name: "OpenAI Embedding",
        baseUrl: "https://api.openai.com/v1",
        apiKey: cloudForm.apiKey,
        modelId: "text-embedding-3-small",
        provider: "OpenAI 兼容",
      });
    }
  };

  return (
    <div>
      <h1 className="mb-1 text-page-title font-semibold">AI 分工</h1>
      <p className="mb-5 text-[13px] text-text-secondary">
        系统已按任务自动分配模型。只有需要更换某项任务的模型时才调整。
      </p>
      {!embedAssigned && (
        <p className="mb-4 rounded-control border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-[13px] text-text-secondary">
          智能记忆正在使用基础模式，不影响写作。启用增强记忆后，较早章节的细节检索会更准确。
        </p>
      )}

      <div className="space-y-2">
        {agentRoles.map((role) => {
          const current = query.data.find((model) => model.roles.includes(role));
          return (
            <div
              key={role}
              className="flex items-center justify-between border-b border-border bg-surface px-4 py-3"
            >
              <span className="flex items-center gap-3 text-[14px] font-medium">
                <Cpu size={16} />
                {modelRoleLabels[role] || role}
              </span>
              <div className="w-[280px]">
                <Select
                  value={current?.id ?? ""}
                  onChange={(event) => void assign(role, event.target.value)}
                >
                  <option value="">未分配</option>
                  {query.data.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name} · {model.status === "connected" ? "已连接" : "未连接"}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
          );
        })}

        {/* Embedding dedicated card */}
        <section className="border border-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[14px] font-medium">
                <HardDrive size={16} />
                智能记忆
              </div>
              <p className="mt-1 text-[12px] text-text-secondary">
                {embedModel ? (
                  <>
                    当前：
                    <span className="font-medium text-text-primary"> {embedModel.name}</span>
                    <span className="text-text-secondary">
                      {" · "}
                      {embedModel.provider === "内嵌" ? "本地" : "云端"}
                      {" · "}
                      {embedModel.modelId}
                      {" · "}
                      {embedModel.status === "connected" ? "已连接" : embedModel.status}
                    </span>
                  </>
                ) : (
                  "基础模式"
                )}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                icon={<Download size={14} />}
                variant={embedPanel === "local" ? "primary" : "secondary"}
                onClick={() => setEmbedPanel((p) => (p === "local" ? null : "local"))}
              >
                启用本地增强
              </Button>
              <Button
                size="sm"
                icon={<Cloud size={14} />}
                variant={embedPanel === "cloud" ? "primary" : "secondary"}
                onClick={() => setEmbedPanel((p) => (p === "cloud" ? null : "cloud"))}
              >
                连接云端增强
              </Button>
              {embedAssigned && (
                <Button size="sm" icon={<X size={14} />} onClick={() => void clearEmbedding()}>
                  使用基础模式
                </Button>
              )}
            </div>
          </div>

          {embedPanel === "local" && (
            <div className="space-y-3 px-4 py-4">
              <p className="text-[13px] text-text-secondary">
                首次启用需要下载模型并占用磁盘空间；普通电脑建议选择“性价比”档。
              </p>
              <div className="space-y-1.5 rounded-control border border-border bg-surface-subtle px-3 py-2 text-[12px] text-text-secondary">
                <p className="break-all font-mono">
                  保存目录：
                  {catalogQuery.data.items[0]?.cacheRoot ||
                    downloadStatus?.cachePath ||
                    "apps/api/data/embeddings/"}
                </p>
                <p className="break-all font-mono">
                  下载源：
                  {catalogQuery.data.downloadSource?.label || "国内 HF 镜像"}
                  {" · "}
                  {catalogQuery.data.downloadSource?.hfEndpoint ||
                    catalogQuery.data.items[0]?.hfEndpoint ||
                    "https://hf-mirror.com"}
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                {catalogQuery.data.items.map((item) => {
                  const active =
                    embedModel?.provider === "内嵌" &&
                    (embedModel.modelId === item.modelId ||
                      (embedModel.extraBody as { catalogKey?: string } | undefined)?.catalogKey ===
                        item.key);
                  const isDownloading =
                    downloadingKey === item.key ||
                    (downloadStatus?.catalogKey === item.key &&
                      downloadStatus.state === "downloading");
                  const progress =
                    isDownloading && downloadStatus ? Math.round((downloadStatus.progress || 0) * 100) : 0;
                  return (
                    <div
                      key={item.key}
                      className={cn(
                        "flex flex-col rounded-card border p-3",
                        active ? "border-primary bg-surface-subtle" : "border-border bg-surface",
                      )}
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="text-[12px] font-medium text-primary">{item.tierLabel}</span>
                        {item.recommended && (
                          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
                            推荐
                          </span>
                        )}
                      </div>
                      <h3 className="text-[14px] font-semibold">{item.name}</h3>
                      <p className="mt-0.5 text-[11px] text-text-secondary">{item.modelId}</p>
                      <p className="mt-2 text-[12px] text-text-secondary">{item.description}</p>
                      <dl className="mt-2 space-y-1 text-[12px] text-text-secondary">
                        <div className="flex justify-between gap-2">
                          <dt>下载大小</dt>
                          <dd className="font-medium text-text-primary">{item.sizeLabel}</dd>
                        </div>
                        <div className="flex justify-between gap-2">
                          <dt>维度</dt>
                          <dd>{item.dimensions}</dd>
                        </div>
                      </dl>
                      <p className="mt-2 text-[12px] leading-relaxed text-text-secondary">
                        <span className="font-medium text-text-primary">适用：</span>
                        {item.suitableFor}
                      </p>
                      {isDownloading && (
                        <div className="mt-3">
                          <div className="mb-1 flex justify-between gap-2 text-[11px] text-text-secondary">
                            <span className="min-w-0 truncate">
                              {downloadStatus?.message || "下载中…"}
                            </span>
                            <span className="shrink-0 tabular-nums">{progress}%</span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-surface-subtle">
                            <div
                              className="h-full bg-primary transition-[width] duration-200 ease-out"
                              style={{ width: `${Math.max(progress, 2)}%` }}
                            />
                          </div>
                          <p className="mt-1 text-[11px] tabular-nums text-text-secondary">
                            {(() => {
                              const got = downloadStatus?.bytesDownloaded ?? 0;
                              const total = Math.max(
                                downloadStatus?.bytesTotalApprox ?? 0,
                                item.sizeBytesApprox ?? 0,
                                got,
                              );
                              return `${formatBytes(got)} / ${formatBytes(total)}`;
                            })()}
                          </p>
                          {downloadStatus?.cachePath && (
                            <p className="mt-1 break-all font-mono text-[10px] text-text-secondary">
                              {downloadStatus.cachePath}
                            </p>
                          )}
                        </div>
                      )}
                      <div className="mt-auto pt-3">
                        <Button
                          size="sm"
                          variant={active ? "secondary" : "primary"}
                          className="w-full"
                          disabled={Boolean(downloadingKey) || active}
                          icon={<Download size={14} />}
                          onClick={() => void startLocalDownload(item.key)}
                        >
                          {active
                            ? "当前启用"
                            : item.downloaded
                              ? "启用本地模型"
                              : "下载并启用"}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
              {catalogQuery.data.items.length === 0 && (
                <p className="text-[13px] text-text-secondary">正在加载模型目录…</p>
              )}
            </div>
          )}

          {embedPanel === "cloud" && (
            <div className="space-y-4 px-4 py-4">
              <p className="text-[13px] text-text-secondary">
                使用已有的云端记忆服务；通义和 OpenAI 可直接选择预设。
              </p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => applyCloudPreset("dashscope")}>
                  预设：通义 text-embedding-v3
                </Button>
                <Button size="sm" onClick={() => applyCloudPreset("openai")}>
                  预设：OpenAI text-embedding-3-small
                </Button>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="配置名称">
                  <TextInput
                    value={cloudForm.name}
                    onChange={(e) => setCloudForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder="例如 通义 Embedding"
                  />
                </Field>
                <Field label="供应商">
                  <Select
                    value={cloudForm.provider}
                    onChange={(e) => setCloudForm((f) => ({ ...f, provider: e.target.value }))}
                  >
                    {["OpenAI 兼容", "DashScope", "DeepSeek", "TEI", "vLLM"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="服务地址" className="sm:col-span-2">
                  <TextInput
                    value={cloudForm.baseUrl}
                    onChange={(e) => setCloudForm((f) => ({ ...f, baseUrl: e.target.value }))}
                    placeholder="https://.../v1"
                  />
                </Field>
                <Field label="密钥" hint="服务端加密保存">
                  <TextInput
                    type="password"
                    autoComplete="new-password"
                    value={cloudForm.apiKey}
                    onChange={(e) => setCloudForm((f) => ({ ...f, apiKey: e.target.value }))}
                  />
                </Field>
                <Field label="模型">
                  <TextInput
                    value={cloudForm.modelId}
                    onChange={(e) => setCloudForm((f) => ({ ...f, modelId: e.target.value }))}
                    placeholder="text-embedding-v3"
                  />
                </Field>
              </div>
              <div className="flex justify-end gap-2">
                <Button onClick={() => setEmbedPanel(null)}>取消</Button>
                <Button
                  variant="primary"
                  icon={<Save size={14} />}
                  disabled={cloudBusy}
                  onClick={() => void saveCloudEmbedding()}
                >
                  保存并分配
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>

      {embedMessage && (
        <p className="mt-4 text-[13px] text-text-secondary" role="status">
          {embedMessage}
        </p>
      )}
    </div>
  );
}

interface UsageStats {
  calls: number;
  errors: number;
  errorRate: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  avgLatencyMs: number;
  estimatedCostUsd: number;
  skillRuns: number;
  byModel: Array<{ name: string; calls: number; errors: number; inputTokens: number; outputTokens: number; durationMs: number }>;
  byAgent: Array<{ name: string; calls: number; errors: number; inputTokens: number; outputTokens: number; durationMs: number }>;
  recent: Array<{ id: string; agentName: string; modelName: string; operation: string; status: string; durationMs: number; inputTokens?: number; outputTokens?: number; createdAt?: string }>;
}

function UsageTab() {
  const { id } = useParams();
  const { data } = useApiQuery<UsageStats>(id ? `/novels/${id}/usage` : null, {
    calls: 0, errors: 0, errorRate: 0, inputTokens: 0, outputTokens: 0, totalTokens: 0,
    avgLatencyMs: 0, estimatedCostUsd: 0, skillRuns: 0, byModel: [], byAgent: [], recent: [],
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-page-title font-semibold">用量统计</h1>
        <p className="mt-1 text-[13px] text-text-secondary">
          基于后台任务调用记录汇总；未返回用量的云端服务可能显示为空。费用为示意估算。
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="调用次数" value={String(data.calls)} />
        <StatCard label="总用量" value={data.totalTokens.toLocaleString()} />
        <StatCard label="平均延迟" value={`${data.avgLatencyMs} ms`} />
        <StatCard label="错误率" value={`${(data.errorRate * 100).toFixed(1)}%`} />
        <StatCard label="输入用量" value={data.inputTokens.toLocaleString()} />
        <StatCard label="输出用量" value={data.outputTokens.toLocaleString()} />
        <StatCard label="扩展任务" value={String(data.skillRuns)} />
        <StatCard label="估算费用 USD" value={data.estimatedCostUsd.toFixed(4)} />
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <UsageTable title="按模型" rows={data.byModel} />
        <UsageTable title="按后台任务" rows={data.byAgent} />
      </div>
      <div>
        <h2 className="mb-2 text-[14px] font-semibold">最近调用</h2>
        <div className="overflow-x-auto border-y border-border">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead className="bg-surface-subtle text-text-secondary">
              <tr>
                {["时间", "后台任务", "模型", "操作", "状态", "耗时", "用量"].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {data.recent.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-6 text-text-secondary">尚无调用记录。生成或选区改写后会出现。</td></tr>
              )}
              {data.recent.map((row) => (
                <tr key={row.id}>
                  <td className="px-3 py-2 text-text-secondary">{row.createdAt?.slice(0, 19) ?? "—"}</td>
                  <td className="px-3 py-2">{row.agentName}</td>
                  <td className="px-3 py-2 text-text-secondary">{row.modelName || "—"}</td>
                  <td className="px-3 py-2">{row.operation || "—"}</td>
                  <td className={cn("px-3 py-2", row.status === "ok" ? "text-success" : "text-danger")}>{row.status}</td>
                  <td className="px-3 py-2 tabular-nums">{row.durationMs} ms</td>
                  <td className="px-3 py-2 tabular-nums text-text-secondary">
                    {(row.inputTokens ?? 0) + (row.outputTokens ?? 0) || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <p className="text-[12px] text-text-secondary">{label}</p>
      <p className="mt-1 text-[20px] font-semibold tabular-nums text-text-primary">{value}</p>
    </div>
  );
}

function UsageTable({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ name: string; calls: number; errors: number; inputTokens: number; outputTokens: number; durationMs: number }>;
}) {
  return (
    <div>
      <h2 className="mb-2 text-[14px] font-semibold">{title}</h2>
      <div className="overflow-hidden rounded-card border border-border">
        <table className="w-full text-left text-[13px]">
          <thead className="bg-surface-subtle text-text-secondary">
            <tr>
              <th className="px-3 py-2 font-medium">名称</th>
              <th className="px-3 py-2 font-medium">调用</th>
              <th className="px-3 py-2 font-medium">错误</th>
              <th className="px-3 py-2 font-medium">用量</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {rows.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-4 text-text-secondary">暂无数据</td></tr>
            )}
            {rows.map((row) => (
              <tr key={row.name}>
                <td className="px-3 py-2 font-medium">{row.name}</td>
                <td className="px-3 py-2 tabular-nums">{row.calls}</td>
                <td className="px-3 py-2 tabular-nums text-danger">{row.errors}</td>
                <td className="px-3 py-2 tabular-nums text-text-secondary">
                  {(row.inputTokens + row.outputTokens).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const emptyAudit: AuditConfig = { passScore: 85, reviseScore: 70, maxRewriteAttempts: 1, autoAudit: true, autoRevise: true, autoRewrite: true, fatalIssueForceRewrite: true, dimensions: [] };

const emptyWritingProfile: WritingProfile = {
  strict_workflow: false,
  target_audience: "",
  platform: "",
  protagonist_name: "",
  protagonist_desire: "",
  protagonist_flaw: "",
  world_scale: "",
  power_system: "",
  golden_finger: "",
  golden_finger_cost: "",
  antagonist_mirror: "",
  anti_trope: "",
  hard_constraints: [],
  anti_patterns: [],
  learned_patterns: [],
};

function WritingRulesTab() {
  const { id } = useParams();
  const query = useApiQuery<Novel>(id ? `/novels/${id}` : null, {
    id: "",
    title: "",
    genre: "",
    progress: { done: 0, total: 0 },
    words: 0,
    pendingAudits: 0,
    updatedLabel: "",
  });
  const health = useApiQuery<{
    ruleset: string;
    healthy: boolean;
    chapters: number;
    blockedChapters: unknown[];
    unauditedVersions: number;
    nonPassingAudits: number;
    memoryPending: number;
  }>(id ? `/novels/${id}/writing-health` : null, {
    ruleset: "",
    healthy: false,
    chapters: 0,
    blockedChapters: [],
    unauditedVersions: 0,
    nonPassingAudits: 0,
    memoryPending: 0,
  });
  const [profile, setProfile] = useState<WritingProfile>(emptyWritingProfile);
  const [message, setMessage] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  useEffect(() => {
    setProfile({ ...emptyWritingProfile, ...(query.data.writingProfile ?? {}) });
  }, [query.data.writingProfile]);
  const lines = (value: string) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  const save = async () => {
    if (!id) return;
    setMessage(null);
    try {
      await apiRequest(`/novels/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ writing_profile: profile }),
      });
      await query.refetch();
      await health.refetch();
      setMessage("故事偏好已保存；新的规划、生成、质量检查与确认将使用这些设置。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "写作规则保存失败");
    }
  };
  return (
    <div className="mx-auto max-w-[900px] space-y-5">
      <div>
        <h1 className="text-page-title font-semibold">故事与写作偏好</h1>
        <p className="mt-1 text-[13px] text-text-secondary">人物、世界和写作边界由 AI 自动维护，你只需补充真正重要的偏好。</p>
      </div>

      <dl className="grid grid-cols-1 gap-x-10 gap-y-5 border-y border-border py-5 sm:grid-cols-2">
        <div>
          <dt className="text-[12px] text-text-secondary">主角与目标</dt>
          <dd className="mt-1 text-[14px] leading-6 text-text-primary">
            {profile.protagonist_name || "AI 正在整理"} · {profile.protagonist_desire || "根据故事推进自动确定"}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] text-text-secondary">故事世界</dt>
          <dd className="mt-1 text-[14px] leading-6 text-text-primary">
            {profile.world_scale || "AI 正在整理"}{profile.power_system ? ` · ${profile.power_system}` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] text-text-secondary">独特能力与限制</dt>
          <dd className="mt-1 text-[14px] leading-6 text-text-primary">
            {profile.golden_finger || "无特殊能力"}{profile.golden_finger_cost ? ` · ${profile.golden_finger_cost}` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] text-text-secondary">预期读者</dt>
          <dd className="mt-1 text-[14px] leading-6 text-text-primary">
            {profile.target_audience || "由 AI 根据题材判断"}{profile.platform ? ` · ${profile.platform}` : ""}
          </dd>
        </div>
      </dl>

      <Field label="作者特别在意的事（可选）" hint="每行一条；AI 已生成的内容可以直接保留。">
        <TextArea
          rows={4}
          value={profile.hard_constraints.join("\n")}
          onChange={(event) => setProfile({ ...profile, hard_constraints: lines(event.target.value) })}
          placeholder="例如：主角不能靠误会推动感情；关键胜利必须付出代价。"
        />
      </Field>

      <button
        type="button"
        onClick={() => setAdvanced((value) => !value)}
        className="flex items-center gap-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary"
      >
        {advanced ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {advanced ? "收起高级编辑" : "高级编辑与诊断"}
      </button>

      {advanced && (
        <div className="space-y-5 border-t border-border pt-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-[13px] font-medium text-text-primary">自动质量保护</p>
              <p className="mt-0.5 text-[12px] text-text-secondary">生成前自动补齐章节安排并检查内部规则。</p>
            </div>
            <Toggle checked={profile.strict_workflow} onChange={(strict_workflow) => setProfile({ ...profile, strict_workflow })} label="自动质量保护" />
          </div>

          <div className="grid grid-cols-2 gap-px border-y border-border bg-border text-[12px] sm:grid-cols-5">
            {[
              ["章节", health.data.chapters],
              ["安排待补", health.data.blockedChapters.length],
              ["版本待检查", health.data.unauditedVersions],
              ["检查未通过", health.data.nonPassingAudits],
              ["资料待整理", health.data.memoryPending],
            ].map(([label, value]) => (
              <div key={String(label)} className="bg-surface px-3 py-2.5">
                <p className="text-text-secondary">{label}</p>
                <p className="mt-0.5 text-[16px] font-semibold text-text-primary">{value}</p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="主角姓名"><TextInput value={profile.protagonist_name} onChange={(e) => setProfile({ ...profile, protagonist_name: e.target.value })} /></Field>
            <Field label="主角最想得到什么"><TextInput value={profile.protagonist_desire} onChange={(e) => setProfile({ ...profile, protagonist_desire: e.target.value })} /></Field>
            <Field label="主角容易犯的错" className="sm:col-span-2"><TextArea rows={2} value={profile.protagonist_flaw} onChange={(e) => setProfile({ ...profile, protagonist_flaw: e.target.value })} /></Field>
            <Field label="故事世界范围"><TextInput value={profile.world_scale} onChange={(e) => setProfile({ ...profile, world_scale: e.target.value })} /></Field>
            <Field label="成长或能力体系"><TextInput value={profile.power_system} onChange={(e) => setProfile({ ...profile, power_system: e.target.value })} /></Field>
            <Field label="主角独特能力"><TextInput value={profile.golden_finger} onChange={(e) => setProfile({ ...profile, golden_finger: e.target.value })} /></Field>
            <Field label="能力限制"><TextInput value={profile.golden_finger_cost} onChange={(e) => setProfile({ ...profile, golden_finger_cost: e.target.value })} /></Field>
            <Field label="主要对手与主角的差异" className="sm:col-span-2"><TextInput value={profile.antagonist_mirror} onChange={(e) => setProfile({ ...profile, antagonist_mirror: e.target.value })} /></Field>
            <Field label="想避免的常见套路" className="sm:col-span-2"><TextArea rows={2} value={profile.anti_trope} onChange={(e) => setProfile({ ...profile, anti_trope: e.target.value })} /></Field>
            <Field label="不喜欢的表达方式" hint="每行一条。" className="sm:col-span-2"><TextArea rows={3} value={profile.anti_patterns.join("\n")} onChange={(e) => setProfile({ ...profile, anti_patterns: lines(e.target.value) })} /></Field>
            <Field label="目标读者"><TextInput value={profile.target_audience} onChange={(e) => setProfile({ ...profile, target_audience: e.target.value })} /></Field>
            <Field label="发布平台"><TextInput value={profile.platform} onChange={(e) => setProfile({ ...profile, platform: e.target.value })} /></Field>
          </div>

          <div className="border-y border-border py-4">
            <p className="text-[13px] font-medium text-text-primary">AI 已学习的写作偏好</p>
            {profile.learned_patterns.length ? (
              <ul className="mt-2 space-y-1 text-[12px] leading-5 text-text-secondary">
                {profile.learned_patterns.map((item) => <li key={item}>· {item}</li>)}
              </ul>
            ) : (
              <p className="mt-1 text-[12px] text-text-secondary">确认更多章节后，系统会在这里记录稳定偏好。</p>
            )}
            <p className="mt-3 text-[11px] text-text-secondary">内部规则版本：{profile.ruleset || "兼容模式"}</p>
          </div>
        </div>
      )}
      <div className="flex items-center justify-end gap-3">
        {message && <span className="text-[13px] text-text-secondary" role="status">{message}</span>}
        <Button variant="primary" icon={<Save size={14} />} onClick={() => void save()}>保存偏好</Button>
      </div>
    </div>
  );
}

function AuditRulesTab() {
  const { id } = useParams();
  const query = useApiQuery<AuditConfig>(id ? `/novels/${id}/audit-config` : null, emptyAudit);
  const [draft, setDraft] = useState(emptyAudit);
  const [saved, setSaved] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  useEffect(() => setDraft(query.data), [query.data]);
  const sum = draft.dimensions.reduce((total, item) => total + item.max, 0);
  const valid = sum === 100 && draft.reviseScore <= draft.passScore;
  const save = async () => {
    if (!id || !valid) return;
    await apiRequest(`/novels/${id}/audit-config`, { method: "PATCH", body: JSON.stringify({
      enabled: draft.enabled ?? true, pass_score: draft.passScore, revise_score: draft.reviseScore, max_rewrite_attempts: draft.maxRewriteAttempts,
      auto_audit: draft.autoAudit, auto_revise: draft.autoRevise, auto_rewrite: draft.autoRewrite, fatal_issue_force_rewrite: draft.fatalIssueForceRewrite, dimensions: draft.dimensions,
    }) });
    await query.refetch(); setSaved(true);
  };
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-page-title font-semibold">章节质量检查</h1>
        <p className="mt-1 text-[13px] text-text-secondary">检查人物一致性、情节推进、时间连续性和表达质量，不会自动覆盖正文。</p>
      </div>
      <ToggleRow title="章节生成后自动检查" checked={draft.autoAudit} onChange={(autoAudit)=>setDraft({...draft,autoAudit})}/>
      <p className="text-[12px] leading-5 text-text-secondary">发现问题时会给出定位和修改建议；需要重写时也只生成候选版本。</p>

      <button
        type="button"
        onClick={() => setAdvanced((value) => !value)}
        className="flex items-center gap-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary"
      >
        {advanced ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {advanced ? "收起评分细节" : "评分细节"}
      </button>

      {advanced && (
        <div className="space-y-4 border-t border-border pt-5">
          <ToggleRow title="严重问题要求重写" checked={draft.fatalIssueForceRewrite} onChange={(fatalIssueForceRewrite)=>setDraft({...draft,fatalIssueForceRewrite})}/>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <NumberInput label="通过分数" value={draft.passScore} onChange={(passScore)=>setDraft({...draft,passScore})}/>
            <NumberInput label="建议修改分数" value={draft.reviseScore} onChange={(reviseScore)=>setDraft({...draft,reviseScore})}/>
          </div>
          <div className="border-y border-border py-4">
            <div className="mb-3 flex justify-between">
              <h2 className="font-semibold">检查项目</h2>
              <span className={sum===100?"text-success":"text-danger"}>合计 {sum} / 100</span>
            </div>
            <div className="grid grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-2">
              {draft.dimensions.map((item,index)=><div key={item.name} className="flex items-center justify-between"><span className="text-[14px]">{item.name}</span><TextInput type="number" className="w-20 text-center" value={item.max} onChange={(event)=>{ const dimensions=[...draft.dimensions]; dimensions[index]={...item,max:Number(event.target.value)}; setDraft({...draft,dimensions}); }}/></div>)}
            </div>
          </div>
        </div>
      )}

      {!valid && <p className="text-[13px] text-danger">检查项目需合计 100，且建议修改分数不能高于通过分数。</p>}
      <div className="flex items-center justify-end gap-3">
        {saved&&<span className="text-[13px] text-success">质量检查设置已保存。</span>}
        <Button variant="primary" icon={<Save size={14}/>} disabled={!valid} onClick={()=>void save()}>保存检查设置</Button>
      </div>
    </div>
  );
}

function SkillsTab() {
  const query = useApiQuery<SkillConfig[]>("/skills", []);
  const update = async (skill: SkillConfig, values: Partial<{enabled:boolean;allowed_agents:string[]}>) => { await apiRequest(`/skills/${skill.id}`, {method:"PATCH",body:JSON.stringify(values)}); await query.refetch(); };
  const fileInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const importSkill = async (file?: File) => {
    if (!file) return;
    setImporting(true); setMessage(null);
    try {
      const content = await file.text();
      const skill = await apiRequest<SkillConfig>("/skills/import", {method:"POST", body:JSON.stringify({content})});
      await query.refetch(); setMessage(`已导入 ${skill.name}`);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "导入失败"); }
    finally { setImporting(false); if (fileInput.current) fileInput.current.value = ""; }
  };
  const remove = async (skill: SkillConfig) => { await apiRequest(`/skills/${skill.id}`, {method:"DELETE"}); await query.refetch(); };
  return <div><div className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><h1 className="mb-1 text-page-title font-semibold">Skill 管理</h1><p className="text-[13px] text-text-secondary">系统 Skill 是固定运行能力；用户 Skill 可导入 SKILL.md 并授权给指定 Agent。</p></div><input ref={fileInput} type="file" accept=".md,text/markdown,text/plain" className="hidden" onChange={(event)=>void importSkill(event.target.files?.[0])}/><Button size="sm" variant="primary" icon={<Upload size={14}/>} disabled={importing} onClick={()=>fileInput.current?.click()}>{importing ? "导入中…" : "导入 SKILL.md"}</Button></div>{message && <p role="status" className="mb-4 text-[13px] text-text-secondary">{message}</p>}<div className="space-y-3">{query.data.map((skill)=><section key={skill.id} className="border-y border-border bg-surface px-4 py-4"><div className="flex items-start justify-between gap-4"><div><h2 className="flex items-center gap-2 font-semibold"><ShieldCheck size={16}/>{skill.name}<span className="text-[12px] font-normal text-text-secondary">v{skill.version}</span><span className={cn("border px-1.5 py-0.5 text-[11px] font-medium", skill.isSystem ? "border-info/30 bg-info/10 text-info" : "border-border bg-surface-subtle text-text-secondary")}>{skill.isSystem ? "系统内置" : "用户导入"}</span></h2><p className="mt-1 text-[13px] text-text-secondary">{skill.description}</p></div>{skill.isSystem ? <span className="text-[12px] text-text-secondary">固定授权</span> : <div className="flex items-center gap-2"><Toggle checked={skill.enabled} label={`${skill.name} 启用状态`} onChange={(enabled)=>void update(skill,{enabled})}/><button type="button" className="text-text-secondary hover:text-danger" aria-label={`删除 ${skill.name}`} title="删除" onClick={()=>void remove(skill)}><Trash2 size={16}/></button></div>}</div>{skill.isSystem ? <p className="mt-4 text-[12px] text-text-secondary">系统按内置职责自动授权，无需手动勾选。</p> : <div className="mt-4 flex flex-wrap gap-2">{agentNames.map((agent)=>{const checked=skill.allowedAgents.includes(agent);return <label key={agent} className="flex items-center gap-2 border border-border px-2 py-1 text-[12px]"><input type="checkbox" checked={checked} onChange={()=>{const allowed_agents=checked?skill.allowedAgents.filter((item)=>item!==agent):[...skill.allowedAgents,agent];void update(skill,{allowed_agents});}}/>{agent}</label>;})}</div>}</section>)}</div></div>;
}

function ToggleRow({title,checked,onChange}:{title:string;checked:boolean;onChange:(value:boolean)=>void}) { return <div className="flex items-center justify-between border-b border-border bg-surface px-4 py-3"><span className="text-[14px] font-medium">{title}</span><Toggle checked={checked} onChange={onChange} label={title}/></div>; }
function NumberInput({label,value,onChange}:{label:string;value:number;onChange:(value:number)=>void}) { return <Field label={label}><TextInput type="number" value={value} onChange={(event)=>onChange(Number(event.target.value))}/></Field>; }
function ErrorText({children}:{children?:string}) { return <span className="text-[12px] text-danger">{children}</span>; }
