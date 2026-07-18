import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

// Visible labels, never placeholder-as-label (§7 / UI-DESIGN form rules).
export function Field({
  label,
  hint,
  htmlFor,
  children,
  className,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-label font-medium text-text-primary">
        {label}
      </label>
      {children}
      {hint && <p className="text-assist text-text-secondary">{hint}</p>}
    </div>
  );
}

const controlBase =
  "w-full rounded-control border border-border bg-surface px-3 text-[14px] text-text-primary " +
  "placeholder:text-text-secondary focus:border-primary focus:outline-none " +
  "transition-[border-color,box-shadow] duration-150 ease-out nove-control";

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(controlBase, "h-10", className)} {...rest} />;
}

export function TextArea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(controlBase, "py-2 resize-y min-h-[80px]", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select
        className={cn(controlBase, "h-10 appearance-none pr-9 cursor-pointer", className)}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown
        size={16}
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary"
      />
    </div>
  );
}

// Accessible on/off switch. Toggles a boolean; label is the accessible name.
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-6 w-11 shrink-0 overflow-hidden rounded-full transition-colors duration-200 ease-out",
        checked ? "bg-primary" : "bg-border",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200 ease-out",
          checked ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

// Range slider styled to the token palette. Used for dialogue ratio in the AI
// panel (§8.5). Track + fill + thumb are rendered manually for consistent look.
export function Slider({
  value,
  onChange,
  min = 0,
  max = 100,
  className,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  className?: string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className={cn("relative flex h-5 items-center", className)}>
      <div className="h-1 w-full rounded-full bg-surface-subtle">
        <div className="h-full rounded-full bg-primary transition-[width] duration-150 ease-out" style={{ width: `${pct}%` }} />
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="滑块"
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
      <span
        className="pointer-events-none absolute h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-primary bg-surface shadow-sm transition-[left] duration-150 ease-out"
        style={{ left: `${pct}%` }}
        aria-hidden
      />
    </div>
  );
}
