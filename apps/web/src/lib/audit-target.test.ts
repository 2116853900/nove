import { describe, expect, it } from "vitest";
import type { ChapterDetail, ChapterVersion, GenerationJob } from "./api";
import { findAuditForVersion, resolveAuditTarget } from "./audit-target";

const baseChapter = {
  id: "ch-1",
  novelId: "n-1",
  index: 1,
  title: "测试章",
  words: 0,
  score: null,
  status: "unaudited" as const,
  state: "DRAFT",
  targetWords: 3500,
  brief: {},
  currentVersionId: null,
  confirmedVersionId: null,
  content: "",
  lockedRanges: [],
  memoryStatus: "NOT_INDEXED",
} satisfies ChapterDetail;

const candidate: ChapterVersion = {
  id: "v-ai",
  label: "v1",
  source: "generate",
  model: "test",
  score: 90,
  time: "2026-07-17",
  words: 5000,
  current: false,
};

describe("resolveAuditTarget", () => {
  it("prefers the formal current version when present", () => {
    const current: ChapterVersion = {
      ...candidate,
      id: "v-current",
      label: "v2",
      source: "user",
      current: true,
      words: 1200,
    };
    const target = resolveAuditTarget({
      chapter: { ...baseChapter, currentVersionId: "v-current", content: "正文" },
      versions: [current, candidate],
    });
    expect(target).toMatchObject({
      versionId: "v-current",
      isCandidate: false,
    });
  });

  it("falls back to job candidate when chapter has no current version", () => {
    const job = {
      id: "job-1",
      state: "COMPLETED",
      stage: "已完成",
      events: [],
      result: { versionId: "v-ai", auditId: "a-1" },
      error: null,
    } satisfies GenerationJob;
    const target = resolveAuditTarget({
      chapter: baseChapter,
      versions: [candidate],
      job,
    });
    expect(target).toMatchObject({
      versionId: "v-ai",
      isCandidate: true,
      label: "v1",
    });
  });

  it("falls back to newest AI version without a job", () => {
    const older: ChapterVersion = { ...candidate, id: "v-old", label: "v0", words: 100 };
    // list is typically sequence-desc; first AI wins
    const target = resolveAuditTarget({
      chapter: baseChapter,
      versions: [candidate, older],
    });
    expect(target?.versionId).toBe("v-ai");
    expect(target?.isCandidate).toBe(true);
  });

  it("returns null when nothing is auditable", () => {
    expect(
      resolveAuditTarget({ chapter: baseChapter, versions: [] }),
    ).toBeNull();
  });
});

describe("findAuditForVersion", () => {
  it("matches by versionId", () => {
    const audits = [
      {
        id: "a1",
        chapterId: "ch-1",
        versionId: "v-ai",
        totalScore: 90,
        decision: "PASS" as const,
        dimensions: [],
        fatalIssues: [],
        issues: [],
        strengths: [],
        rewriteRequirements: {},
        createdAt: "2026-07-17",
      },
    ];
    expect(findAuditForVersion(audits, "v-ai")?.id).toBe("a1");
    expect(findAuditForVersion(audits, "missing")).toBeUndefined();
  });
});
