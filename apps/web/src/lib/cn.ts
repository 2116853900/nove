// Tiny classnames joiner — avoids pulling in clsx for a UI-only build.
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
