import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

const steps = [
  { n: 1, name: "AI 模型" },
  { n: 2, name: "故事想法" },
  { n: 3, name: "开始搭建" },
];

/**
 * Shared shell for the 3-step new-novel wizard (§7). Provides the wizard top bar,
 * the numbered step indicator, and a centered form card slot.
 */
export function WizardShell({
  current,
  children,
}: {
  current: number;
  children: ReactNode;
}) {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="flex h-topbar shrink-0 items-center justify-between border-b border-border bg-surface px-4 sm:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-control bg-primary text-[14px] font-bold text-white">
            N
          </span>
          <span className="text-[16px] text-text-primary">新建小说</span>
        </div>
        <Link
          to="/"
          className="flex h-9 items-center rounded-control border border-border bg-surface px-3 text-[13px] text-text-secondary hover:bg-surface-subtle"
        >
          取消
        </Link>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[720px] px-4 py-7 sm:px-8 sm:py-10">
          {/* Step indicator */}
          <ol className="mb-8 flex items-center">
            {steps.map((s, i) => {
              const done = s.n < current;
              const active = s.n === current;
              return (
                <li key={s.n} className="flex flex-1 items-center last:flex-none">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={cn(
                        "flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-semibold",
                        done && "bg-primary text-white",
                        active && "bg-primary text-white",
                        !done && !active && "border border-border bg-surface text-text-secondary",
                      )}
                    >
                      {done ? <Check size={16} /> : s.n}
                    </span>
                    <span
                      className={cn(
                        "text-[13px]",
                        active ? "font-medium text-text-primary" : "text-text-secondary",
                      )}
                    >
                      {s.name}
                    </span>
                  </div>
                  {i < steps.length - 1 && (
                    <span
                      className={cn(
                        "mx-4 h-px flex-1",
                        done ? "bg-primary" : "bg-border",
                      )}
                    />
                  )}
                </li>
              );
            })}
          </ol>

          <div className="animate-nove-fade-up" key={current}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export function WizardCard({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-card border border-border bg-surface p-7">
      <h1 className="text-[20px] font-medium text-text-primary">{title}</h1>
      <p className="mt-1 text-[14px] text-text-secondary">{desc}</p>
      <div className="mt-6 flex flex-col gap-5">{children}</div>
    </div>
  );
}

export function WizardFooter({
  backTo,
  nextTo,
  nextLabel = "下一步",
  onNext,
}: {
  backTo?: string;
  nextTo: string;
  nextLabel?: string;
  onNext?: () => void;
}) {
  return (
    <div className="mt-6 flex items-center justify-between">
      {backTo ? (
        <Link
          to={backTo}
          className="flex h-10 items-center rounded-control border border-border bg-surface px-4 text-[14px] text-text-primary hover:bg-surface-subtle"
        >
          上一步
        </Link>
      ) : (
        <span />
      )}
      <Link
        to={nextTo}
        onClick={onNext}
        className="flex h-10 items-center rounded-control bg-primary px-5 text-[14px] font-semibold text-white hover:bg-primary-hover"
      >
        {nextLabel}
      </Link>
    </div>
  );
}
