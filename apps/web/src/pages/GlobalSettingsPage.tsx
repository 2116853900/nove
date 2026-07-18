import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Cpu,
  Info,
  KeyRound,
  Plug,
  Save,
  Settings2,
  Star,
  TestTube2,
  Trash2,
} from "lucide-react";
import { BrandBar } from "@/components/layout/BrandBar";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput, Toggle } from "@/components/ui/form";
import { apiRequest, useApiQuery, type ModelConfig, type SkillConfig } from "@/lib/api";
import { cn } from "@/lib/cn";

const TABS = [
  { key: "models", label: "AI 模型", icon: Cpu },
  { key: "connection", label: "访问安全", icon: KeyRound },
  { key: "preferences", label: "偏好", icon: Settings2 },
  { key: "about", label: "关于", icon: Info },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const PREFS_KEY = "nove:global-prefs";

interface GlobalPrefs {
  defaultAutoAudit: boolean;
  confirmBeforeDelete: boolean;
  editorFontSize: number;
}

const defaultPrefs: GlobalPrefs = {
  defaultAutoAudit: true,
  confirmBeforeDelete: true,
  editorFontSize: 16,
};

function readPrefs(): GlobalPrefs {
  try {
    return { ...defaultPrefs, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return defaultPrefs;
  }
}

function writePrefs(values: GlobalPrefs) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(values));
}

const statusMeta = {
  connected: { label: "已连接", icon: Check, className: "text-success" },
  error: { label: "连接失败", icon: AlertTriangle, className: "text-danger" },
  untested: { label: "未测试", icon: Circle, className: "text-text-secondary" },
};

/**
 * Global settings (IA §3.1) — workspace model library, API key, local prefs.
 * Distinct from per-novel project settings.
 */
export function GlobalSettingsPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab") as TabKey | null;
  const tab: TabKey = TABS.some((t) => t.key === tabParam) ? (tabParam as TabKey) : "models";

  const setTab = (key: TabKey) => {
    setParams(key === "models" ? {} : { tab: key }, { replace: true });
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <BrandBar showActions={false} />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[220px] shrink-0 flex-col border-r border-border bg-surface">
          <div className="border-b border-border px-5 py-4">
            <p className="text-[12px] text-text-secondary">全局</p>
            <h1 className="mt-0.5 text-[16px] font-semibold text-text-primary">设置</h1>
          </div>
          <nav className="flex flex-col gap-0.5 p-2">
            {TABS.map((item) => {
              const Icon = item.icon;
              const active = tab === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setTab(item.key)}
                  className={cn(
                    "flex items-center gap-2.5 rounded-control px-3 py-2.5 text-left text-[13px]",
                    active
                      ? "bg-surface-subtle font-medium text-text-primary"
                      : "text-text-secondary hover:bg-surface-subtle/70 hover:text-text-primary",
                  )}
                >
                  <Icon size={15} />
                  {item.label}
                </button>
              );
            })}
          </nav>
          <div className="mt-auto border-t border-border p-3">
            <Link
              to="/"
              className="flex h-9 items-center justify-center rounded-control border border-border text-[13px] text-text-secondary hover:bg-surface-subtle hover:text-text-primary"
            >
              返回项目列表
            </Link>
          </div>
        </aside>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[880px] px-8 py-8">
            {tab === "models" && <ModelsLibraryTab />}
            {tab === "connection" && <ConnectionTab />}
            {tab === "preferences" && <PreferencesTab />}
            {tab === "about" && <AboutTab />}
          </div>
        </main>
      </div>
    </div>
  );
}

function ModelsLibraryTab() {
  const query = useApiQuery<ModelConfig[]>("/models", []);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeMode, setProbeMode] = useState<"test" | "fetch" | null>(null);
  const [saving, setSaving] = useState(false);
  const [remoteModels, setRemoteModels] = useState<Array<{ id: string; name: string }>>([]);
  const [connectionDetails, setConnectionDetails] = useState(false);
  const [form, setForm] = useState({
    name: "",
    provider: "OpenAI 兼容",
    modelId: "",
    baseUrl: "https://api.openai.com/v1",
    apiKey: "",
    temperature: 0.7,
    topP: 1,
    maxOutputTokens: 8192,
    contextSize: 128000,
    timeoutMs: 120000,
    isDefault: false,
  });

  const providerDefaults: Record<string, Partial<typeof form>> = {
    "OpenAI 兼容": { baseUrl: "https://api.openai.com/v1" },
    DeepSeek: { baseUrl: "https://api.deepseek.com/v1", modelId: "deepseek-chat" },
    DashScope: {
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      modelId: "qwen-plus",
    },
  };

  const probe = async (mode: "test" | "fetch") => {
    if (!form.baseUrl.trim()) {
      setConnectionDetails(true);
      setMessage("请先填写服务地址，再测试连接。");
      return;
    }
    setProbeBusy(true);
    setProbeMode(mode);
    setMessage(mode === "fetch" ? "正在获取模型列表…" : "正在测试连接…");
    try {
      const result = await apiRequest<{
        message: string;
        latencyMs: number;
        models: Array<{ id: string; name: string }>;
      }>("/models/probe", {
        method: "POST",
        body: JSON.stringify({
          provider: form.provider,
          base_url: form.baseUrl,
          api_key: form.apiKey,
          model_id: form.modelId,
          timeout_ms: form.timeoutMs,
        }),
      });
      setRemoteModels(result.models ?? []);
      if (mode === "fetch" && result.models?.length) {
        const pick = result.models.find((m) => m.id === form.modelId) || result.models[0];
        setForm((f) => ({
          ...f,
          modelId: pick.id,
          name: f.name.trim() || pick.name || pick.id,
        }));
      }
      setMessage(result.latencyMs ? `${result.message}（${result.latencyMs} ms）` : result.message);
    } catch (reason) {
      setRemoteModels([]);
      setMessage(reason instanceof Error ? reason.message : "连接失败");
    } finally {
      setProbeBusy(false);
      setProbeMode(null);
    }
  };

  const save = async () => {
    if (!form.modelId.trim()) {
      setMessage("请填写或选择一个模型");
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const created = await apiRequest<ModelConfig>("/models", {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim() || form.modelId.trim(),
          provider: form.provider,
          model_id: form.modelId.trim(),
          base_url: form.baseUrl.trim(),
          api_key: form.apiKey,
          roles: [],
          temperature: form.temperature,
          top_p: form.topP,
          max_output_tokens: form.maxOutputTokens,
          context_size: form.contextSize,
          timeout_ms: form.timeoutMs,
          is_default: form.isDefault,
          extra_body: {},
        }),
      });
      try {
        await apiRequest(`/models/${created.id}/test`, { method: "POST" });
      } catch {
        /* keep untested/error */
      }
      await query.refetch();
      setAdding(false);
      setRemoteModels([]);
      setForm({
        name: "",
        provider: "OpenAI 兼容",
        modelId: "",
        baseUrl: "https://api.openai.com/v1",
        apiKey: "",
        temperature: 0.7,
        topP: 1,
        maxOutputTokens: 8192,
        contextSize: 128000,
        timeoutMs: 120000,
        isDefault: false,
      });
      setMessage(`已保存「${created.name}」。新建/导入小说时可选用。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const test = async (id: string) => {
    setMessage("正在测试连接…");
    try {
      const result = await apiRequest<{ probe?: { message?: string } }>(`/models/${id}/test`, {
        method: "POST",
      });
      setMessage(result.probe?.message || "连接测试通过。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "连接测试失败");
    }
    await query.refetch();
  };

  const setDefault = async (id: string) => {
    await apiRequest(`/models/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_default: true }),
    });
    await query.refetch();
    setMessage("已设为工作区默认模型。");
  };

  const remove = async (model: ModelConfig) => {
    if (!window.confirm(`删除模型「${model.name}」？已创建的小说中的副本不受影响。`)) return;
    await apiRequest(`/models/${model.id}`, { method: "DELETE" });
    await query.refetch();
    setMessage("已删除。");
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-[20px] font-semibold text-text-primary">AI 模型</h2>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-text-secondary">
            连接后，新建故事会自动选择可用模型。已有模型通常不需要调整。
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Plug size={15} />}
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "收起" : "添加模型"}
        </Button>
      </div>

      {adding && (
        <div className="grid grid-cols-1 gap-4 rounded-card border border-border bg-surface p-5 sm:grid-cols-2">
          <Field label="供应商">
            <Select
              value={form.provider}
              onChange={(e) => {
                const provider = e.target.value;
                setForm((f) => ({ ...f, provider, ...(providerDefaults[provider] ?? {}) }));
                setRemoteModels([]);
              }}
            >
              {[
                "OpenAI 兼容",
                "DeepSeek",
                "DashScope",
              ].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="密钥" hint="会加密保存在本机服务中。">
            <TextInput
              type="password"
              autoComplete="new-password"
              value={form.apiKey}
              onChange={(e) => setForm((f) => ({ ...f, apiKey: e.target.value }))}
            />
          </Field>
          <Field label="服务地址" className="sm:col-span-2">
            <TextInput value={form.baseUrl} onChange={(e) => setForm((f) => ({ ...f, baseUrl: e.target.value }))} placeholder="https://api.openai.com/v1" />
          </Field>
          <div className="sm:col-span-2 flex flex-wrap gap-2">
            <Button
              icon={<TestTube2 size={14} />}
              disabled={probeBusy}
              onClick={() => void probe("test")}
            >
              {probeMode === "test" ? "测试中…" : "测试连接"}
            </Button>
            <Button disabled={probeBusy} onClick={() => void probe("fetch")}>
              {probeMode === "fetch" ? "获取中…" : "获取模型"}
            </Button>
            {message && <p className="basis-full text-[13px] text-text-secondary" role="status" aria-live="polite">{message}</p>}
          </div>
          <Field label="模型" className="sm:col-span-2">
            {remoteModels.length > 0 ? (
              <Select
                value={form.modelId}
                onChange={(e) => setForm((f) => ({ ...f, modelId: e.target.value }))}
              >
                {remoteModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </Select>
            ) : (
              <TextInput
                value={form.modelId}
                onChange={(e) => setForm((f) => ({ ...f, modelId: e.target.value }))}
                placeholder="例如 deepseek-chat"
              />
            )}
          </Field>
          <button
            type="button"
            onClick={() => setConnectionDetails((value) => !value)}
            className="sm:col-span-2 flex items-center gap-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary"
          >
            {connectionDetails ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            连接细节
          </button>
          {connectionDetails && (
            <div className="sm:col-span-2 grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2">
              <Field label="配置名称">
                <TextInput value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="默认使用模型名称" />
              </Field>
              <Field label="等待时间（毫秒）">
                <TextInput type="number" value={form.timeoutMs} onChange={(e) => setForm((f) => ({ ...f, timeoutMs: Number(e.target.value) || 120000 }))} />
              </Field>
              <Field label="随机度">
                <TextInput type="number" step="0.1" value={form.temperature} onChange={(e) => setForm((f) => ({ ...f, temperature: Number(e.target.value) || 0 }))} />
              </Field>
              <Field label="采样范围">
                <TextInput type="number" step="0.05" value={form.topP} onChange={(e) => setForm((f) => ({ ...f, topP: Number(e.target.value) || 1 }))} />
              </Field>
              <Field label="单次输出上限">
                <TextInput type="number" value={form.maxOutputTokens} onChange={(e) => setForm((f) => ({ ...f, maxOutputTokens: Number(e.target.value) || 8192 }))} />
              </Field>
            </div>
          )}
          <div className="sm:col-span-2 flex items-center justify-between rounded-control border border-border px-3 py-2">
            <span className="text-[13px] text-text-secondary">设为工作区默认</span>
            <Toggle
              checked={form.isDefault}
              onChange={(v) => setForm((f) => ({ ...f, isDefault: v }))}
              label="默认"
            />
          </div>
          <div className="sm:col-span-2 flex justify-end gap-2">
            <Button onClick={() => setAdding(false)}>取消</Button>
            <Button
              variant="primary"
              icon={<Save size={14} />}
              disabled={saving}
              onClick={() => void save()}
            >
              {saving ? "保存中…" : "保存到模型库"}
            </Button>
          </div>
        </div>
      )}

      {!adding && message && (
        <p className="text-[13px] text-text-secondary" role="status">
          {message}
        </p>
      )}

      <div className="overflow-x-auto rounded-card border border-border">
        <table className="w-full min-w-[720px] text-left text-[13px]">
          <thead className="bg-surface-subtle text-text-secondary">
            <tr>
              {["名称", "模型", "状态", "延迟", "操作"].map((h) => (
                <th key={h} className="px-4 py-2.5 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {query.loading && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-text-secondary">
                  加载中…
                </td>
              </tr>
            )}
            {!query.loading && query.data.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-text-secondary">
                  暂无模型。添加后可在新建/导入时选择。
                </td>
              </tr>
            )}
            {query.data.map((model) => {
              const meta = statusMeta[model.status];
              const Icon = meta.icon;
              return (
                <tr key={model.id}>
                  <td className="px-4 py-3">
                    <span className="font-medium text-text-primary">{model.name}</span>
                    {model.isDefault && (
                      <span className="ml-2 inline-flex items-center gap-0.5 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">
                        <Star size={10} /> 默认
                      </span>
                    )}
                    <div className="text-[12px] text-text-secondary">{model.provider}</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px] text-text-secondary">
                    {model.modelId}
                  </td>
                  <td className={cn("px-4 py-3", meta.className)}>
                    <span className="inline-flex items-center gap-1">
                      <Icon size={14} />
                      {meta.label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{model.latency || "—"}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <Button size="sm" icon={<TestTube2 size={13} />} onClick={() => void test(model.id)}>
                        测试
                      </Button>
                      {!model.isDefault && (
                        <Button size="sm" onClick={() => void setDefault(model.id)}>
                          设默认
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={13} />}
                        onClick={() => void remove(model)}
                      >
                        删除
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConnectionTab() {
  const { data: auth } = useApiQuery<{
    authenticated: boolean;
    mode: string;
    workspaceId: string;
    apiKeyRequired: boolean;
    activeJobs: number;
  }>("/auth/status", {
    authenticated: false,
    mode: "unknown",
    workspaceId: "",
    apiKeyRequired: false,
    activeJobs: 0,
  });
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem("nove:api-key") || "",
  );
  const [message, setMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const saveKey = () => {
    const value = apiKey.trim();
    if (value) localStorage.setItem("nove:api-key", value);
    else localStorage.removeItem("nove:api-key");
    setMessage(value ? "API Key 已保存到本机浏览器。" : "已清除本机 API Key。");
  };

  const testConnection = async () => {
    setTesting(true);
    setMessage(null);
    try {
      const status = await apiRequest<{ mode: string; workspaceId: string }>("/auth/status");
      setMessage(`连接正常 · 模式 ${status.mode} · 工作区 ${status.workspaceId}`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "连接失败");
    } finally {
      setTesting(false);
    }
  };

  const deleteAccount = async () => {
    const confirmation = window.prompt("此操作会永久删除当前账号的全部小说、模型和 Skills。请输入 DELETE 确认：", "");
    if (confirmation !== "DELETE") return;
    setDeleting(true);
    try {
      await apiRequest("/account", { method: "DELETE", body: JSON.stringify({ confirmation }) });
      localStorage.removeItem("nove:api-key");
      localStorage.removeItem(PREFS_KEY);
      window.location.assign("/");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "删除账号失败");
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-[20px] font-semibold text-text-primary">连接与鉴权</h2>
        <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-text-secondary">
          配置前端访问后端的 API Key（存于本机 localStorage）。生产环境若启用了服务端
          API_KEY，此处必须填写一致的密钥。
        </p>
      </div>

      <div className="rounded-card border border-border bg-surface p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="鉴权模式" value={auth.mode} />
          <Stat label="工作区" value={auth.workspaceId || "—"} />
          <Stat label="要求 API Key" value={auth.apiKeyRequired ? "是" : "否"} />
        </div>
      </div>

        <div className="rounded-card border border-border bg-surface p-5 space-y-4">
        <Field
          label="API Key"
          hint="仅保存在当前浏览器，不会上传到第三方。请求头：X-API-Key。"
        >
          <TextInput
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={auth.apiKeyRequired ? "必填" : "开发模式可留空"}
          />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" icon={<Save size={14} />} onClick={saveKey}>
            保存
          </Button>
          <Button disabled={testing} onClick={() => void testConnection()}>
            {testing ? "检测中…" : "检测连接"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setApiKey("");
              localStorage.removeItem("nove:api-key");
              setMessage("已清除。");
            }}
          >
            清除
          </Button>
        </div>
        {message && (
          <p className="text-[13px] text-text-secondary" role="status">
            {message}
          </p>
        )}
        </div>
        <div className="rounded-card border border-danger/30 bg-surface p-5">
          <h3 className="text-[14px] font-semibold text-danger">删除账号</h3>
          <p className="mt-1 text-[13px] text-text-secondary">永久删除当前工作区的全部小说、章节、模型配置、Skills 与运行记录。</p>
          <Button className="mt-4" size="sm" variant="danger" icon={<Trash2 size={14} />} disabled={deleting} onClick={() => void deleteAccount()}>
            {deleting ? "删除中…" : "删除账号"}
          </Button>
        </div>
      </div>
  );
}

function PreferencesTab() {
  const [prefs, setPrefs] = useState<GlobalPrefs>(() => readPrefs());
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    writePrefs(prefs);
    setSaved(true);
    const t = window.setTimeout(() => setSaved(false), 1200);
    return () => window.clearTimeout(t);
  }, [prefs]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-[20px] font-semibold text-text-primary">偏好</h2>
        <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-text-secondary">
          保存在本机浏览器，不随账号同步。影响新建向导默认项与部分 UI 行为。
        </p>
      </div>

      <div className="divide-y divide-border rounded-card border border-border bg-surface">
        <PrefRow
          title="新建项目默认开启质量检查"
          desc="章节生成后自动检查人物、情节与表达。"
        >
          <Toggle
            checked={prefs.defaultAutoAudit}
            onChange={(v) => setPrefs((p) => ({ ...p, defaultAutoAudit: v }))}
            label="自动质量检查"
          />
        </PrefRow>
        <PrefRow title="删除前二次确认" desc="永久删除项目时弹出确认对话框。">
          <Toggle
            checked={prefs.confirmBeforeDelete}
            onChange={(v) => setPrefs((p) => ({ ...p, confirmBeforeDelete: v }))}
            label="删除确认"
          />
        </PrefRow>
        <PrefRow title="编辑器字号" desc="写作页正文字号偏好（像素）。">
          <div className="w-[120px]">
            <TextInput
              type="number"
              min={14}
              max={22}
              value={prefs.editorFontSize}
              onChange={(e) =>
                setPrefs((p) => ({
                  ...p,
                  editorFontSize: Math.min(22, Math.max(14, Number(e.target.value) || 16)),
                }))
              }
            />
          </div>
        </PrefRow>
      </div>
      {saved && (
        <p className="text-[12px] text-success" role="status">
          已自动保存
        </p>
      )}

      <SkillsReadonly />
    </div>
  );
}

function SkillsReadonly() {
  const { data: skills } = useApiQuery<SkillConfig[]>("/skills", []);
  return (
    <div className="rounded-card border border-border bg-surface p-5">
      <h3 className="text-[14px] font-semibold text-text-primary">工作区 Skills</h3>
      <p className="mt-1 text-[12px] text-text-secondary">
        全局已安装的 Agent Skills。启用状态可在项目设置中按小说调整（若支持）。
      </p>
      <ul className="mt-3 space-y-2">
        {skills.length === 0 && (
          <li className="text-[13px] text-text-secondary">暂无 Skill</li>
        )}
        {skills.map((skill) => (
          <li
            key={skill.id}
            className="flex items-center justify-between rounded-control border border-border px-3 py-2 text-[13px]"
          >
            <span>
              <span className="font-medium text-text-primary">{skill.name}</span>
              <span className="ml-2 text-text-secondary">v{skill.version}</span>
            </span>
            <span className={skill.enabled ? "text-success" : "text-text-secondary"}>
              {skill.enabled ? "启用" : "停用"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AboutTab() {
  const [info, setInfo] = useState<{
    status: string;
    env: string;
    database: string;
    pgvector?: boolean;
  }>({ status: "…", env: "—", database: "—" });

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((data) =>
        setInfo({
          status: data.status,
          env: data.env,
          database: data.database,
          pgvector: Boolean(data.pgvector?.pgvector),
        }),
      )
      .catch(() => setInfo({ status: "unreachable", env: "—", database: "—" }));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-[20px] font-semibold text-text-primary">关于 Nove</h2>
        <p className="mt-1 text-[13px] text-text-secondary">
          面向长篇小说作者的 AI 创作工作台。
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Stat label="前端" value="0.1.0" />
        <Stat label="API 状态" value={info.status} />
        <Stat label="运行环境" value={info.env} />
        <Stat label="数据库" value={info.database} />
        <Stat label="pgvector" value={info.pgvector ? "启用" : "未启用"} />
      </div>
      <div className="rounded-card border border-border bg-surface p-5 text-[13px] leading-relaxed text-text-secondary">
        <p>数据按工作区隔离。模型 API Key 在服务端加密存储；前端仅保存访问后端用的 API Key。</p>
        <p className="mt-2">
          项目级设置（AI 分工、质量检查、使用情况）请在打开小说后进入「项目设置」。
        </p>
      </div>
    </div>
  );
}

function PrefRow({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-4">
      <div className="min-w-0">
        <p className="text-[14px] font-medium text-text-primary">{title}</p>
        <p className="mt-0.5 text-[12px] text-text-secondary">{desc}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-control border border-border bg-surface-subtle/40 px-3 py-3">
      <p className="text-[11px] text-text-secondary">{label}</p>
      <p className="mt-1 text-[14px] font-medium text-text-primary">{value}</p>
    </div>
  );
}
