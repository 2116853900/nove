// @vitest-environment jsdom

import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditIssue, AuditReport, ChapterDetail } from "@/lib/api";
import { RightPanel } from "./RightPanel";

const issue: AuditIssue = {
  id: "issue-1",
  severity: "major",
  type: "伏笔植入不足",
  evidence: "光柱升起，一道身影缓缓凝聚",
  conflictsWith: "细纲要求提前提示",
  suggestion: "增加一句边界异动的提示",
};

const audit: AuditReport = {
  id: "audit-1",
  chapterId: "chapter-1",
  versionId: "version-1",
  totalScore: 76,
  decision: "REVISE",
  dimensions: [{ name: "连续性", score: 76, max: 100 }],
  fatalIssues: [],
  issues: [issue],
  strengths: [],
  rewriteRequirements: {},
  createdAt: "2026-07-17T00:00:00Z",
};

describe("RightPanel audit actions", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    localStorage.clear();
  });

  function render(overrides: Partial<ComponentProps<typeof RightPanel>> = {}) {
    const props: ComponentProps<typeof RightPanel> = {
      tab: "audit",
      onTabChange: vi.fn(),
      generating: false,
      characters: [],
      locations: [],
      audit,
      versions: [],
      chapter: null,
      contextSources: [],
      onGenerate: vi.fn(),
      onGenerationOptionsChange: vi.fn(),
      onAudit: vi.fn(),
      onRewrite: vi.fn(),
      onConfirm: vi.fn(),
      onAccept: vi.fn(),
      onRestore: vi.fn(),
      onDeleteVersion: vi.fn(),
      ...overrides,
    };
    act(() => root.render(<RightPanel {...props} />));
  }

  function button(label: string) {
    const match = Array.from(container.querySelectorAll("button")).find(
      (item) => item.textContent?.trim() === label,
    );
    if (!match) throw new Error(`Button not found: ${label}`);
    return match;
  }

  function setTextAreaValue(textarea: HTMLTextAreaElement, value: string) {
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    act(() => {
      valueSetter?.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  it("confirms a passing audit and exposes request feedback", () => {
    const onConfirm = vi.fn();
    render({
      onConfirm,
      audit: { ...audit, decision: "PASS", issues: [] },
      auditTarget: {
        versionId: "version-1",
        isCandidate: false,
        label: "v1",
        words: 1200,
      },
    });

    act(() => button("确认当前版本").click());
    expect(onConfirm).toHaveBeenCalledWith();

    render({
      onConfirm,
      audit: { ...audit, decision: "PASS", issues: [] },
      auditTarget: {
        versionId: "version-1",
        isCandidate: false,
        label: "v1",
        words: 1200,
      },
      confirmBusy: true,
      confirmError: "确认请求失败",
    });
    expect(button("确认中…").disabled).toBe(true);
    expect(container.textContent).toContain("确认请求失败");
  });

  it("shows candidate audit target and accept action", () => {
    const onAccept = vi.fn();
    const onAudit = vi.fn();
    render({
      audit: undefined,
      auditTarget: {
        versionId: "candidate-1",
        isCandidate: true,
        label: "v1",
        words: 5455,
        source: "generate",
      },
      onAccept,
      onAudit,
    });

    expect(container.textContent).toContain("AI 候选（未接受）");
    expect(container.textContent).toContain("目标：v1");
    act(() => button("检查候选").click());
    expect(onAudit).toHaveBeenCalled();
    act(() => button("接受此候选为正文").click());
    expect(onAccept).toHaveBeenCalledWith("candidate-1");
    expect(button("请先接受候选再确认").disabled).toBe(true);
  });

  it("requires a reason before confirming an audit with fatal issues", () => {
    const fatalIssue: AuditIssue = { ...issue, id: "fatal-1", severity: "fatal" };
    const onConfirm = vi.fn();
    render({
      audit: { ...audit, fatalIssues: [fatalIssue] },
      auditTarget: {
        versionId: "version-1",
        isCandidate: false,
        label: "v1",
        words: 1200,
      },
      onConfirm,
    });

    act(() => button("确认当前版本").click());
    expect(onConfirm).not.toHaveBeenCalled();
    expect(container.textContent).toContain("当前检查仍有严重问题");
    expect(button("仍然确认").disabled).toBe(true);

    const textarea = container.querySelector<HTMLTextAreaElement>(
      "#fatal-override-reason",
    );
    expect(textarea).not.toBeNull();
    setTextAreaValue(textarea!, "这是作者明确保留的剧情安排");
    expect(button("仍然确认").disabled).toBe(false);

    act(() => button("仍然确认").click());
    expect(onConfirm).toHaveBeenCalledWith("这是作者明确保留的剧情安排");
  });

  it("locates evidence and generates a rewrite candidate", async () => {
    const onJumpToEvidence = vi.fn(() => true);
    const onRewriteIssue = vi.fn(async () => undefined);
    render({ onJumpToEvidence, onRewriteIssue });

    act(() => button("定位正文").click());
    expect(onJumpToEvidence).toHaveBeenCalledWith(issue.evidence);
    expect(container.textContent).toContain("已在正文中选中");

    await act(async () => {
      button("去改写").click();
      await Promise.resolve();
    });
    expect(onRewriteIssue).toHaveBeenCalledWith(issue);
    expect(container.textContent).toContain("改写候选已生成");
  });

  it("labels non-content evidence without offering invalid location actions", () => {
    render({
      audit: {
        ...audit,
        issues: [
          {
            ...issue,
            locatable: false,
            evidenceSource: "outline",
            evidenceQuote: "",
          },
        ],
      },
    });

    expect(container.textContent).toContain("证据来源：章节大纲");
    expect(container.textContent).not.toContain("定位正文");
    expect(container.textContent).not.toContain("去改写");
  });

  it("ignores an issue and supports undo", () => {
    render();

    act(() => button("忽略一次").click());
    expect(container.textContent).toContain("已忽略");
    expect(container.textContent).not.toContain(issue.evidence);
    expect(JSON.parse(localStorage.getItem("nove:audit-actions:audit-1") || "{}"))
      .toEqual({ "issue-1": { action: "ignored" } });

    act(() => button("撤销").click());
    expect(container.textContent).toContain(issue.evidence);
    expect(container.textContent).toContain("已撤销");
  });

  it("requires and stores a note for an intentional setting", () => {
    render();

    act(() => button("标记为有意设定").click());
    const textarea = container.querySelector("textarea");
    expect(textarea).not.toBeNull();
    expect(button("确认标记").disabled).toBe(true);

    setTextAreaValue(textarea!, "这是第三章才会揭示的有意伏笔");
    expect(button("确认标记").disabled).toBe(false);

    act(() => button("确认标记").click());
    expect(container.textContent).toContain("已将");
    expect(JSON.parse(localStorage.getItem("nove:audit-actions:audit-1") || "{}"))
      .toEqual({
        "issue-1": {
          action: "intentional",
          note: "这是第三章才会揭示的有意伏笔",
        },
      });
  });

  it("shows an outline-driven one-click writing view by default", () => {
    const chapter: ChapterDetail = {
      id: "chapter-1",
      novelId: "novel-1",
      index: 1,
      title: "旧信",
      outlineNodeId: "node-1",
      words: 0,
      score: null,
      status: "unaudited",
      state: "PLANNED",
      targetWords: 3500,
      brief: {
        goal: "查清旧信的寄件人",
        must_events: ["主角找到被涂掉的邮戳"],
      },
      currentVersionId: null,
      confirmedVersionId: null,
      content: "",
      lockedRanges: [],
      memoryStatus: "NOT_INDEXED",
    };
    render({ tab: "ai", chapter });

    expect(container.textContent).toContain("本章安排");
    expect(container.textContent).toContain("查清旧信的寄件人");
    expect(container.textContent).toContain("主角找到被涂掉的邮戳");
    expect(button("生成本章")).toBeDefined();
    expect(container.textContent).not.toContain("目标字数");
    expect(container.textContent).not.toContain("对话比例");

    act(() => button("更多设置").click());
    expect(container.textContent).toContain("本章想达到的结果");
    expect(container.textContent).toContain("对话多少");
  });
});
