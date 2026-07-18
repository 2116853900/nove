import { describe, expect, it } from "vitest";
import { Schema } from "@tiptap/pm/model";
import { buildEvidenceMarks, findEvidenceOffset } from "./text-marks";
import { plainOffsetToPmPos } from "./text-marks";

describe("findEvidenceOffset", () => {
  it("finds quoted evidence", () => {
    const content = "他站在窗前。他早就知道信标来自泽塔星。然后离开。";
    const hit = findEvidenceOffset(content, "「他早就知道信标来自泽塔星」");
    expect(hit).not.toBeNull();
    expect(content.slice(hit!.start, hit!.end)).toBe("他早就知道信标来自泽塔星");
  });

  it("finds the complete span for abbreviated evidence", () => {
    const content = "光柱升起，一道身影缓缓凝聚。那是一个身穿银色长袍的男人，他的身影已经凝聚了九成，身体轮廓清晰可见。";
    const hit = findEvidenceOffset(content, "“光柱升起，一道身影缓缓凝聚……身体轮廓清晰可见”");
    expect(hit).not.toBeNull();
    expect(content.slice(hit!.start, hit!.end)).toBe(content.slice(0, -1));
  });

  it("falls back to the relevant paragraph for paraphrased evidence", () => {
    const content = [
      "暗渊沉默片刻，重新衡量自己仅存的神力。",
      "“明天开始，开垦荒地。”暗渊说，语气里没有动摇。",
      "三名信徒对视一眼，开始整理工具。",
    ].join("\n\n");
    const hit = findEvidenceOffset(
      content,
      "暗渊在听完信徒描述后立刻做出开垦荒地的决定，心理转变稍显仓促。",
    );
    expect(hit).not.toBeNull();
    expect(content.slice(hit!.start, hit!.end)).toBe(
      "“明天开始，开垦荒地。”暗渊说，语气里没有动摇。",
    );
  });

  it("returns null when missing", () => {
    expect(findEvidenceOffset("abc", "xyz")).toBeNull();
  });
});

describe("buildEvidenceMarks", () => {
  it("dedupes overlapping ranges", () => {
    const content = "林远推开舱门，继续指挥。";
    const marks = buildEvidenceMarks(content, [
      { evidence: "林远", severity: "fatal" },
      { evidence: "林远推开", severity: "major" },
    ]);
    expect(marks.length).toBe(1);
  });
});

describe("plainOffsetToPmPos", () => {
  it("accounts for separators between paragraphs", () => {
    const schema = new Schema({
      nodes: {
        doc: { content: "paragraph+" },
        paragraph: { content: "text*" },
        text: {},
      },
    });
    const doc = schema.node("doc", null, [
      schema.node("paragraph", null, schema.text("第一段文字")),
      schema.node("paragraph", null, schema.text("第二段文字")),
      schema.node("paragraph", null, schema.text("开始开垦荒地")),
    ]);
    const plain = doc.textBetween(0, doc.content.size, "\n\n", "\n\n");
    const offset = plain.indexOf("开垦荒地");
    const from = plainOffsetToPmPos(doc, offset);
    const to = plainOffsetToPmPos(doc, offset + "开垦荒地".length);

    expect(doc.textBetween(from, to, "\n\n", "\n\n")).toBe("开垦荒地");
  });
});
