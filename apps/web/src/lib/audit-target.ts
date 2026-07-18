import type { AuditReport, ChapterDetail, ChapterVersion, GenerationJob } from "./api";

const AI_SOURCES = new Set(["generate", "revise", "rewrite"]);

export interface AuditTarget {
  versionId: string;
  /** True when the target is not the chapter's current formal version. */
  isCandidate: boolean;
  label: string;
  words: number;
  source?: string;
}

/**
 * Prefer the formal current version; otherwise the latest job candidate or
 * newest AI-generated version so audit works before "接受候选".
 */
export function resolveAuditTarget(options: {
  chapter: ChapterDetail | null | undefined;
  versions: ChapterVersion[];
  job?: GenerationJob | null;
}): AuditTarget | null {
  const { chapter, versions, job } = options;
  const currentId = chapter?.currentVersionId ?? null;
  if (currentId) {
    const current = versions.find((version) => version.id === currentId);
    const words = current?.words ?? (chapter?.content?.trim().length ?? 0);
    if (words > 0 || chapter?.content?.trim()) {
      return {
        versionId: currentId,
        isCandidate: false,
        label: current?.label ?? "当前版本",
        words: words || chapter!.content.trim().length,
        source: current?.source,
      };
    }
  }

  const jobVersionId = job?.result?.versionId;
  if (jobVersionId) {
    const fromJob = versions.find((version) => version.id === jobVersionId);
    if (fromJob && fromJob.words > 0) {
      return {
        versionId: fromJob.id,
        isCandidate: true,
        label: fromJob.label,
        words: fromJob.words,
        source: fromJob.source,
      };
    }
  }

  const latestAi = versions.find(
    (version) => AI_SOURCES.has(version.source) && version.words > 0,
  );
  if (latestAi) {
    return {
      versionId: latestAi.id,
      isCandidate: true,
      label: latestAi.label,
      words: latestAi.words,
      source: latestAi.source,
    };
  }

  return null;
}

export function findAuditForVersion(
  audits: AuditReport[],
  versionId: string | null | undefined,
): AuditReport | undefined {
  if (!versionId) return undefined;
  return audits.find((audit) => audit.versionId === versionId);
}
