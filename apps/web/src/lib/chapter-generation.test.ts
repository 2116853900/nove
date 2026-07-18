import { describe, expect, it } from "vitest";
import { chapterGenerationPath } from "./chapter-generation";

describe("chapterGenerationPath", () => {
  it("keeps unconditional rewrite separate from audit-driven rewrite", () => {
    expect(chapterGenerationPath("chapter-1", "rewrite")).toBe(
      "/chapters/chapter-1/rewrite",
    );
    expect(chapterGenerationPath("chapter-1", "audit-and-rewrite")).toBe(
      "/chapters/chapter-1/audit-and-rewrite",
    );
  });
});
