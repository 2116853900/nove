import type { ButtonHTMLAttributes, ReactNode } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { cn } from "@/lib/cn";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name — required so icon-only buttons are labelled (§20). */
  label: string;
  icon: ReactNode;
  active?: boolean;
}

/**
 * Icon-only button. Click target is 44x44 (spec §4) even though the icon is
 * smaller; the label becomes both aria-label and native tooltip.
 */
export function IconButton({ label, icon, active, className, ...rest }: IconButtonProps) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-control",
            "text-text-secondary nove-interactive",
            "hover:bg-surface-subtle hover:text-text-primary",
            active && "bg-surface-subtle text-text-primary",
            className,
          )}
          {...rest}
        >
          {icon}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          sideOffset={6}
          className="z-50 rounded-control bg-text-primary px-2 py-1 text-[12px] text-surface"
        >
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
