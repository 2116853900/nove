import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "primary" | "info" | "warning" | "danger" | "success" | "twist" | "highlight";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-subtle text-text-secondary",
  primary: "bg-primary/10 text-primary",
  info: "bg-info/10 text-info",
  warning: "bg-[#FEF3C7] text-warning",
  danger: "bg-[#FEF2F2] text-danger",
  success: "bg-[#F0FDF4] text-success",
  twist: "bg-[#F3E8FF] text-twist",
  highlight: "bg-[#FFEDD5] text-highlight",
};

interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function Badge({ tone = "neutral", children, icon, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[4px] px-2 py-0.5 text-[12px] font-semibold leading-none",
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/**
 * Small status dot. Never used alone to convey status (§2.3) — always paired
 * with a text label by the caller. `className` sets the color.
 */
export function StatusDot({ className }: { className?: string }) {
  return <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", className)} aria-hidden />;
}
