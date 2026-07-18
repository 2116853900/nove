/** Plain-text helpers for editor decorations (blockSeparator = "\\n\\n"). */

export type IssueSeverity = "fatal" | "major" | "minor";

export interface EvidenceMark {
  from: number;
  to: number;
  severity: IssueSeverity;
  evidence: string;
}

function findSharedFragment(content: string, evidence: string) {
  const maxLength = Math.min(32, evidence.length);
  for (let length = maxLength; length >= 4; length -= 1) {
    for (let start = 0; start + length <= evidence.length; start += 1) {
      const fragment = evidence.slice(start, start + length);
      if (/\s/.test(fragment) || /^[\p{P}\p{S}]+$/u.test(fragment)) continue;
      const index = content.indexOf(fragment);
      if (index >= 0) return { start: index, end: index + fragment.length };
    }
  }
  return null;
}

function expandToParagraph(content: string, range: { start: number; end: number }) {
  const previousBreak = content.lastIndexOf("\n\n", Math.max(0, range.start - 1));
  const nextBreak = content.indexOf("\n\n", range.end);
  const start = previousBreak >= 0 ? previousBreak + 2 : 0;
  const end = nextBreak >= 0 ? nextBreak : content.length;
  return end - start <= 600 ? { start, end } : range;
}

export function findEvidenceOffset(
  content: string,
  evidence: string,
): { start: number; end: number } | null {
  const raw = (evidence || "").trim();
  if (!raw || !content) return null;
  // Strip common quote wrappers from audit evidence.
  const cleaned = raw.replace(/^[「『“‘"']+|[」』”’"']+$/g, "").trim();
  const exact = content.indexOf(cleaned);
  if (exact >= 0) return { start: exact, end: exact + cleaned.length };

  // Audit models often abbreviate long evidence with an ellipsis. Select the
  // complete span between the first and last quoted fragments when possible.
  const fragments = cleaned
    .split(/(?:\.{3,}|…+)/)
    .map((fragment) => fragment.trim())
    .filter((fragment) => fragment.length >= 2);
  if (fragments.length > 1) {
    const first = content.indexOf(fragments[0]);
    const last = content.indexOf(fragments[fragments.length - 1], first + fragments[0].length);
    if (first >= 0 && last >= 0) {
      return { start: first, end: last + fragments[fragments.length - 1].length };
    }
  }

  const candidates = [cleaned.slice(0, 48), cleaned.slice(0, 24)].filter(
    (s) => s.length >= 2,
  );
  for (const needle of candidates) {
    const idx = content.indexOf(needle);
    if (idx >= 0) {
      return { start: idx, end: idx + needle.length };
    }
  }
  const shared = findSharedFragment(content, cleaned);
  return shared ? expandToParagraph(content, shared) : null;
}

export function buildEvidenceMarks(
  content: string,
  issues: Array<{ evidence: string; severity: IssueSeverity }>,
): EvidenceMark[] {
  const marks: EvidenceMark[] = [];
  const used: Array<[number, number]> = [];
  for (const issue of issues) {
    const hit = findEvidenceOffset(content, issue.evidence);
    if (!hit) continue;
    if (used.some(([a, b]) => !(hit.end <= a || hit.start >= b))) continue;
    used.push([hit.start, hit.end]);
    marks.push({
      from: hit.start,
      to: hit.end,
      severity: issue.severity,
      evidence: issue.evidence,
    });
  }
  return marks;
}

/** Map plain-text offset (with \\n\\n block separators) to ProseMirror doc position. */
export function plainOffsetToPmPos(
  doc: { content: { size: number }; textBetween: (from: number, to: number, blockSep?: string, leafSep?: string) => string },
  plainOffset: number,
): number {
  const full = doc.textBetween(0, doc.content.size, "\n\n", "\n\n");
  const clamped = Math.max(0, Math.min(plainOffset, full.length));
  if (clamped === 0) return 1;

  // Search by the document's own serialization so block separators contribute
  // to the offset. Summing text-node lengths drifts by two characters per
  // paragraph and eventually selects an unrelated earlier passage.
  let low = 1;
  let high = Math.max(1, doc.content.size);
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    const length = doc.textBetween(0, middle, "\n\n", "\n\n").length;
    if (length < clamped) low = middle + 1;
    else high = middle;
  }
  return low;
}
