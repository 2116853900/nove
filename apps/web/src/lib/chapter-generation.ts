export type ChapterGenerationOperation =
  | "generate"
  | "continue"
  | "rewrite"
  | "audit-and-rewrite";

export function chapterGenerationPath(
  chapterId: string,
  operation: ChapterGenerationOperation,
) {
  return `/chapters/${chapterId}/${operation}`;
}
