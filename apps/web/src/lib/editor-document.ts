export interface EditorJsonNode {
  type?: string;
  attrs?: Record<string, unknown>;
  text?: string;
  marks?: Array<{ type: string }>;
  content?: EditorJsonNode[];
}

export interface EditorTextRun {
  text: string;
  bold: boolean;
}

export interface EditorTextBlock {
  type: "heading" | "paragraph";
  level: number;
  text: string;
  runs: EditorTextRun[];
  source: string;
  sourceStart: number;
  sourceEnd: number;
  prefixLength: number;
  suffixLength: number;
}

function splitBlocks(text: string): Array<{ value: string; start: number; end: number }> {
  if (!text) return [{ value: "", start: 0, end: 0 }];
  const blocks: Array<{ value: string; start: number; end: number }> = [];
  const separator = /\n{2,}/g;
  let start = 0;
  let match: RegExpExecArray | null;
  while ((match = separator.exec(text))) {
    blocks.push({ value: text.slice(start, match.index), start, end: match.index });
    start = match.index + match[0].length;
  }
  blocks.push({ value: text.slice(start), start, end: text.length });
  return blocks;
}

function parseInlineMarkdown(source: string): EditorTextRun[] {
  const runs: EditorTextRun[] = [];
  let bold = false;
  let buffer = "";

  const flush = () => {
    if (!buffer) return;
    runs.push({ text: buffer, bold });
    buffer = "";
  };

  for (let index = 0; index < source.length;) {
    if (source.startsWith("**", index)) {
      flush();
      bold = !bold;
      index += 2;
      continue;
    }
    buffer += source[index];
    index += 1;
  }
  flush();
  return runs;
}

export function parseEditorText(text: string): EditorTextBlock[] {
  return splitBlocks(text).map(({ value, start, end }) => {
    const markdownHeading = value.match(/^(#{1,6})([ \t]+)([\s\S]*)$/)
      ?? value.match(/^(#{1,6})()()$/);
    let type: EditorTextBlock["type"] = "paragraph";
    let level = 0;
    let prefixLength = 0;
    let suffixLength = 0;
    let inlineSource = value;

    if (markdownHeading) {
      type = "heading";
      level = Math.min(3, markdownHeading[1].length);
      prefixLength = markdownHeading[1].length + markdownHeading[2].length;
      inlineSource = markdownHeading[3];
      const closingHashes = inlineSource.match(/[ \t]+#+[ \t]*$/)?.[0] ?? "";
      suffixLength = closingHashes.length;
      if (suffixLength) inlineSource = inlineSource.slice(0, -suffixLength);
    }

    const runs = parseInlineMarkdown(inlineSource);
    return {
      type,
      level,
      text: runs.map((run) => run.text).join(""),
      runs,
      source: value,
      sourceStart: start,
      sourceEnd: end,
      prefixLength,
      suffixLength,
    };
  });
}

export function textToEditorDocument(text: string): EditorJsonNode {
  return {
    type: "doc",
    content: parseEditorText(text).map((block) => ({
      type: block.type,
      attrs: block.type === "heading" ? { level: block.level } : undefined,
      content: block.runs.length
        ? block.runs.map((run) => ({
            type: "text",
            text: run.text,
            marks: run.bold ? [{ type: "bold" }] : undefined,
          }))
        : undefined,
    })),
  };
}

function collectTextRuns(node: EditorJsonNode): EditorTextRun[] {
  if (typeof node.text === "string") {
    return [
      {
        text: node.text,
        bold: Boolean(node.marks?.some((mark) => mark.type === "bold")),
      },
    ];
  }
  return (node.content ?? []).flatMap(collectTextRuns);
}

/** Merge adjacent runs with the same bold state so highlight-mark splits don't emit `****`. */
function mergeTextRuns(runs: EditorTextRun[]): EditorTextRun[] {
  const merged: EditorTextRun[] = [];
  for (const run of runs) {
    if (!run.text) continue;
    const last = merged[merged.length - 1];
    if (last && last.bold === run.bold) {
      last.text += run.text;
      continue;
    }
    merged.push({ text: run.text, bold: run.bold });
  }
  return merged;
}

function runsToMarkdown(runs: EditorTextRun[]): string {
  return mergeTextRuns(runs)
    .map((run) => (run.bold ? `**${run.text}**` : run.text))
    .join("");
}

function headingPrefix(level: unknown): string {
  const normalized = Math.min(3, Math.max(1, Number(level) || 2));
  return `${"#".repeat(normalized)} `;
}

export function editorDocumentToText(document: EditorJsonNode): string {
  return (document.content ?? [])
    .map((node) => {
      const text = runsToMarkdown(collectTextRuns(node));
      return node.type === "heading" ? `${headingPrefix(node.attrs?.level)}${text}` : text;
    })
    .join("\n\n");
}

function sourceOffsetToVisibleOffset(block: EditorTextBlock, sourceOffset: number): number {
  const contentEnd = block.source.length - block.suffixLength;
  const target = Math.max(block.prefixLength, Math.min(sourceOffset, contentEnd));
  let sourceIndex = block.prefixLength;
  let visibleOffset = 0;
  while (sourceIndex < target) {
    if (block.source.startsWith("**", sourceIndex)) {
      sourceIndex += 2;
      continue;
    }
    sourceIndex += 1;
    visibleOffset += 1;
  }
  return visibleOffset;
}

function visibleOffsetToSourceOffset(block: EditorTextBlock, visibleOffset: number): number {
  const target = Math.max(0, Math.min(visibleOffset, block.text.length));
  const contentEnd = block.source.length - block.suffixLength;
  let sourceIndex = block.prefixLength;
  let visibleIndex = 0;
  while (sourceIndex < contentEnd) {
    if (block.source.startsWith("**", sourceIndex)) {
      sourceIndex += 2;
      continue;
    }
    if (visibleIndex >= target) break;
    sourceIndex += 1;
    visibleIndex += 1;
  }
  while (sourceIndex < contentEnd && block.source.startsWith("**", sourceIndex)) {
    sourceIndex += 2;
  }
  return sourceIndex;
}

export function markdownOffsetToPlainOffset(text: string, markdownOffset: number): number {
  const clamped = Math.max(0, Math.min(markdownOffset, text.length));
  const blocks = parseEditorText(text);
  let plainStart = 0;
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    if (clamped <= block.sourceEnd) {
      return plainStart + sourceOffsetToVisibleOffset(block, clamped - block.sourceStart);
    }
    plainStart += block.text.length;
    if (index < blocks.length - 1) {
      if (clamped < blocks[index + 1].sourceStart) {
        return plainStart + Math.min(2, clamped - block.sourceEnd);
      }
      plainStart += 2;
    }
  }
  return plainStart;
}

export function plainOffsetToMarkdownOffset(text: string, plainOffset: number): number {
  const blocks = parseEditorText(text);
  const plainLength = blocks.reduce(
    (length, block, index) => length + block.text.length + (index < blocks.length - 1 ? 2 : 0),
    0,
  );
  const clamped = Math.max(0, Math.min(plainOffset, plainLength));
  let plainStart = 0;
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    const plainEnd = plainStart + block.text.length;
    if (clamped <= plainEnd) {
      return block.sourceStart + visibleOffsetToSourceOffset(block, clamped - plainStart);
    }
    if (index < blocks.length - 1 && clamped < plainEnd + 2) {
      return block.sourceEnd + clamped - plainEnd;
    }
    plainStart = plainEnd + 2;
  }
  return text.length;
}
