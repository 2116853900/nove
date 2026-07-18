// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Chapter } from "@/lib/api";
import { ChapterList } from "./ChapterList";

const chapters: Chapter[] = [
  {
    id: "written",
    index: 3,
    title: "已有正文",
    words: 1200,
    score: 90,
    status: "pass",
    needsCheck: true,
  },
  {
    id: "planned",
    index: 4,
    title: "尚未写作",
    words: 0,
    score: null,
    status: "unaudited",
    needsCheck: true,
  },
];

describe("ChapterList pending checks", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("audits only written chapters and labels unwritten outlines separately", () => {
    const onAuditPending = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <ChapterList
              activeId="written"
              chapters={chapters}
              onSelect={vi.fn()}
              onCreate={vi.fn()}
              onAuditPending={onAuditPending}
              bulkAudit={{ busy: false, completed: 0, total: 0, failed: 0, error: null }}
            />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });

    const auditButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("检查待处理 1"),
    );
    expect(auditButton).toBeDefined();
    expect(container.textContent).toContain("安排待核对");
    expect(container.textContent).toContain("1 个未写章节的安排待核对");

    act(() => auditButton!.click());
    expect(onAuditPending).toHaveBeenCalledOnce();
  });
});
