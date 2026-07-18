// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readNewNovelDraft } from "@/lib/api";
import { NewNovelStep1 } from "./NewNovelStep1";
import { NewNovelStep2 } from "./NewNovelStep2";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    useApiQuery: () => ({
      data: [],
      loading: false,
      error: null,
      refetch: vi.fn(),
      setData: vi.fn(),
    }),
  };
});

describe("new novel wizard", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    sessionStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    sessionStorage.clear();
  });

  it("requires a connected cloud model before asking for the story idea", () => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={["/new/1"]}>
          <Routes>
            <Route path="/new/1" element={<NewNovelStep1 />} />
            <Route path="/new/2" element={<div>故事想法步骤</div>} />
          </Routes>
        </MemoryRouter>,
      );
    });

    expect(container.textContent).toContain("先连接云端模型");
    expect(container.textContent).toContain("只使用已连接的云端模型");
    expect(container.querySelector("textarea[name='core_idea']")).toBeNull();
    expect(container.querySelectorAll("[required]")).toHaveLength(2);
    const next = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "下一步",
    );
    expect(next?.disabled).toBe(true);
  });

  it("keeps the second step to one required natural-language story idea", () => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={["/new/2"]}>
          <Routes>
            <Route path="/new/2" element={<NewNovelStep2 />} />
            <Route path="/new/3" element={<div>开始搭建步骤</div>} />
          </Routes>
        </MemoryRouter>,
      );
    });

    const required = container.querySelectorAll("[required]");
    expect(required).toHaveLength(1);
    const textarea = required[0] as HTMLTextAreaElement;
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    act(() => {
      valueSetter?.call(textarea, "一个只能看见别人剩余寿命的医生，遇到没有死亡日期的病人。");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const form = container.querySelector("form");
    act(() => form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));

    expect(container.textContent).toContain("开始搭建步骤");
    const draft = readNewNovelDraft();
    expect(draft.core_idea).toContain("剩余寿命");
    expect(draft.title).toBe("");
  });
});
