import { describe, expect, it } from "vitest";
import {
  editorDocumentToText,
  markdownOffsetToPlainOffset,
  parseEditorText,
  plainOffsetToMarkdownOffset,
  textToEditorDocument,
} from "./editor-document";

describe("editor document conversion", () => {
  it("renders markdown headings without visible markers", () => {
    const blocks = parseEditorText("# 苏醒的神王\n\n黑暗。");
    expect(blocks[0]).toMatchObject({ type: "heading", text: "苏醒的神王" });
    expect(textToEditorDocument("# 苏醒的神王").content?.[0].type).toBe("heading");
  });

  it("preserves markdown heading level on editor round-trip", () => {
    const document = textToEditorDocument("# 苏醒的神王\n\n黑暗。");
    expect(editorDocumentToText(document)).toBe("# 苏醒的神王\n\n黑暗。");
    expect(editorDocumentToText(textToEditorDocument("## 副标题\n\n正文"))).toBe("## 副标题\n\n正文");
  });

  it("keeps standalone bold text as a paragraph", () => {
    const blocks = parseEditorText("**「神域经营系统初始化中……」**");
    const document = textToEditorDocument("**「神域经营系统初始化中……」**");
    expect(blocks[0]).toMatchObject({ type: "paragraph", text: "「神域经营系统初始化中……」" });
    expect(document.content?.[0]).toMatchObject({
      type: "paragraph",
      content: [{ text: "「神域经营系统初始化中……」", marks: [{ type: "bold" }] }],
    });
  });

  it("merges adjacent bold runs so highlight splits do not emit empty bold markers", () => {
    const document = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "「任务", marks: [{ type: "bold" }] },
            { type: "text", text: "清单", marks: [{ type: "bold" }] },
            { type: "text", text: "」", marks: [{ type: "bold" }] },
          ],
        },
      ],
    };
    expect(editorDocumentToText(document)).toBe("**「任务清单」**");
    expect(editorDocumentToText(document)).not.toContain("****");
  });

  it("maps offsets around hidden title markers", () => {
    const text = "## 苏醒的神王\n\n**黑暗。**";
    const bodyStart = text.indexOf("黑暗");
    expect(markdownOffsetToPlainOffset(text, bodyStart)).toBe("苏醒的神王\n\n".length);
    expect(plainOffsetToMarkdownOffset(text, "苏醒的神王\n\n".length)).toBe(bodyStart);
  });
});
