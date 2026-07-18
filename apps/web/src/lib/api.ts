import { useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AuditDimension,
  AuditIssue,
  Chapter,
  ChapterVersion,
  CharacterSummary,
  FactionSummary,
  HighlightItem,
  ItemSummary,
  LocationSummary,
  ModelConfig,
  Novel,
  OutlineNode,
  PlotThread,
  TimelineEvent,
  Twist,
  WorldRule,
  WritingProfile,
} from "./types";

const API_ROOT = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function authHeaders(): Record<string, string> {
  const fromEnv = import.meta.env.VITE_API_KEY as string | undefined;
  const fromStore =
    typeof localStorage !== "undefined" ? localStorage.getItem("nove:api-key") : null;
  const key = (fromEnv || fromStore || "").trim();
  if (!key) return {};
  return { "X-API-Key": key };
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item?.msg).filter(Boolean).join("；") ||
            `请求失败 (${response.status})`
          : detail?.message || `请求失败 (${response.status})`;
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function useApiQuery<T>(path: string | null, initial: T) {
  const queryClient = useQueryClient();
  const queryKey = ["api", path] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => apiRequest<T>(path as string),
    enabled: Boolean(path),
  });
  const refetch = async () => {
    if (!path) return initial;
    const result = await query.refetch({ throwOnError: true });
    return result.data ?? initial;
  };
  const setData = (value: T | ((current: T) => T)) => {
    queryClient.setQueryData<T>(queryKey, (current) =>
      typeof value === "function"
        ? (value as (current: T) => T)(current ?? initial)
        : value,
    );
  };
  return {
    data: query.data ?? initial,
    loading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch,
    setData,
  };
}

export const emptyNovel: Novel = {
  id: "",
  title: "正在加载",
  genre: "",
  progress: { done: 0, total: 0 },
  words: 0,
  pendingAudits: 0,
  updatedLabel: "",
};

export function useNovel(novelId: string | undefined) {
  return useApiQuery<Novel>(novelId ? `/novels/${novelId}` : null, emptyNovel);
}

export interface ChapterDetail extends Chapter {
  novelId: string;
  state: string;
  targetWords: number;
  brief: Record<string, unknown>;
  currentVersionId: string | null;
  confirmedVersionId: string | null;
  content: string;
  lockedRanges: { start: number; end: number }[];
  memoryStatus: string;
}

export interface AuditReport {
  id: string;
  chapterId: string;
  versionId: string;
  totalScore: number;
  decision: "PASS" | "REVISE" | "REWRITE" | "REVIEW_REQUIRED";
  dimensions: AuditDimension[];
  fatalIssues: AuditIssue[];
  issues: AuditIssue[];
  strengths: string[];
  rewriteRequirements: Record<string, unknown>;
  createdAt: string;
}

export interface GenerationJob {
  id: string;
  state: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  stage: string;
  events: { type: string; stage?: string; index?: number }[];
  result: {
    versionId?: string;
    auditId?: string;
    decision?: string;
    attempts?: number;
    contextSources?: ContextSource[];
    policySnapshot?: WritingContract;
    promptManifest?: { ruleset: string; hash: string; autoAudit: boolean };
  };
  error: string | null;
}

export interface ContextSource {
  type: "chapter" | "memory" | string;
  id: string;
  label: string;
  score?: string;
}

export interface GateIssue {
  code: string;
  message: string;
  repair: string;
}

export interface WritingContract {
  ruleset: string;
  provenance: Array<{ ruleId: string; sourcePath: string; sourceLine: number; scope: string; severity: string }>;
  chapterIndex: number;
  chapterTitle: string;
  workflow: string[];
  taskbookOrder: string[];
  strict: boolean;
  ready: boolean;
  gate: {
    stage: "prewrite";
    status: "pass" | "warning" | "blocked";
    blockers: GateIssue[];
    warnings: GateIssue[];
    checks: Record<string, boolean>;
  };
  taskbook: {
    chapter_directive: Record<string, unknown>;
    story_nodes: {
      cbn: string;
      cpns: string[];
      cen: string;
      must_cover_nodes: string[];
      must_events: string[];
    };
    forbidden_zones: string[];
    style_guidance: Record<string, unknown>;
    dynamic_context: Record<string, unknown>;
  };
}

export interface AuditConfig {
  enabled?: boolean;
  rubricVersion?: number;
  passScore: number;
  reviseScore: number;
  maxRewriteAttempts: number;
  autoAudit: boolean;
  autoRevise: boolean;
  autoRewrite: boolean;
  fatalIssueForceRewrite: boolean;
  dimensions: AuditDimension[];
}

export interface SkillConfig {
  id: string;
  name: string;
  version: string;
  description: string;
  allowedAgents: string[];
  timeoutSeconds: number;
  enabled: boolean;
  isSystem: boolean;
  kind: "runtime" | "prompt";
}

export interface CharacterState {
  id: string;
  entityId: string;
  name: string;
  chapterId: string;
  chapterIndex: number;
  location: string;
  bodyStatus: string;
  alive: boolean;
  emotion: string;
  knownFacts: string[];
  beliefs: string[];
  inventory: string[];
  notes: string;
}

export type {
  AuditDimension,
  AuditIssue,
  Chapter,
  ChapterVersion,
  CharacterSummary,
  FactionSummary,
  HighlightItem,
  ItemSummary,
  LocationSummary,
  ModelConfig,
  Novel,
  OutlineNode,
  PlotThread,
  TimelineEvent,
  Twist,
  WorldRule,
  WritingProfile,
};

export interface NovelResources {
  chapters: Chapter[];
  characters: CharacterSummary[];
  locations: LocationSummary[];
  factions: FactionSummary[];
  items: ItemSummary[];
  rules: WorldRule[];
  outline: OutlineNode[];
  timeline: TimelineEvent[];
  threads: PlotThread[];
  highlights: HighlightItem[];
  twists: Twist[];
  models: ModelConfig[];
  versions: ChapterVersion[];
}

export function jobEventsUrl(jobId: string) {
  return `${API_ROOT}/jobs/${jobId}/events`;
}

export interface NewNovelDraft {
  title: string;
  genre: string;
  language: string;
  core_idea: string;
  target_words: number;
  planned_chapters: number;
  creation_mode: string;
  auto_audit: boolean;
  default_model_id?: string;
  plan_model_id?: string;
  write_model_id?: string;
  audit_model_id?: string;
  writing_profile: WritingProfile;
}

const NEW_NOVEL_KEY = "nove:new-novel";

export function readNewNovelDraft(): NewNovelDraft {
  const defaults: NewNovelDraft = {
    title: "",
    genre: "未分类",
    language: "zh-CN",
    core_idea: "",
    target_words: 240000,
    planned_chapters: 80,
    creation_mode: "scratch",
    auto_audit: true,
    writing_profile: {
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
    },
  };
  try {
    const stored = JSON.parse(sessionStorage.getItem(NEW_NOVEL_KEY) ?? "{}");
    return {
      ...defaults,
      ...stored,
      writing_profile: {
        ...defaults.writing_profile,
        ...(stored.writing_profile ?? {}),
      },
    };
  } catch {
    return defaults;
  }
}

export function updateNewNovelDraft(values: Partial<NewNovelDraft>) {
  sessionStorage.setItem(
    NEW_NOVEL_KEY,
    JSON.stringify({ ...readNewNovelDraft(), ...values }),
  );
}

export function clearNewNovelDraft() {
  sessionStorage.removeItem(NEW_NOVEL_KEY);
}
