import { useState } from "react";
import { useParams } from "react-router-dom";
import { Star } from "lucide-react";
import { SegControl } from "@/components/ui/Tabs";
import { useApiQuery, type HighlightItem, type Twist } from "@/lib/api";

/** Highlights & twists (§13.3). Scannable, edit-friendly, no decorative timeline. */
export function HighlightsPage() {
  const [tab, setTab] = useState("twists");
  const { id } = useParams();
  const { data } = useApiQuery<{ highlights: HighlightItem[]; twists: Twist[] }>(id ? `/novels/${id}/beats` : null, { highlights: [], twists: [] });
  const { highlights, twists } = data;

  return (
    <div className="min-h-0 w-full flex-1 overflow-y-auto px-8 py-8">
        <h1 className="text-page-title font-semibold text-text-primary">亮点与转折</h1>
        <p className="mt-1 text-[13px] text-text-secondary">
          转折需要表面预期、真实变化与支撑线索；缺少铺垫会在质量检查中提示。
        </p>

        <SegControl
          className="mt-4"
          items={[
            { key: "twists", label: "转折" },
            { key: "highlights", label: "亮点" },
          ]}
          value={tab}
          onChange={setTab}
        />

        {tab === "twists" ? (
          <div className="mt-5 flex flex-col gap-4">
            {twists.map((t) => (
              <div key={t.id} className="rounded-card border border-border bg-surface p-5">
                <div className="mb-3 flex items-center gap-2">
                  <span className="rounded bg-[#F3E8FF] px-2 py-0.5 text-[12px] font-semibold text-twist">
                    转折
                  </span>
                  <span className="text-[13px] text-text-secondary">{t.chapter}</span>
                </div>
                <dl className="grid grid-cols-[88px_1fr] gap-x-4 gap-y-2 text-[14px]">
                  <dt className="text-text-secondary">表面预期</dt>
                  <dd className="text-text-primary">{t.surface}</dd>
                  <dt className="text-text-secondary">真实变化</dt>
                  <dd className="text-text-primary">{t.reality}</dd>
                  <dt className="text-text-secondary">支撑线索</dt>
                  <dd className="text-text-primary">{t.clues}</dd>
                  <dt className="text-text-secondary">影响人物</dt>
                  <dd className="text-text-primary">{t.characters}</dd>
                  <dt className="text-text-secondary">后续影响</dt>
                  <dd className="text-text-primary">{t.aftermath}</dd>
                </dl>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-5 flex flex-col gap-3">
            {highlights.map((h) => (
              <div
                key={h.id}
                className="flex items-start gap-3 rounded-card border border-border bg-surface p-4"
              >
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-[#FFEDD5] text-highlight">
                  <Star size={15} />
                </span>
                <div>
                  <p className="text-[13px] text-text-secondary">{h.chapter}</p>
                  <p className="mt-0.5 text-[14px] text-text-primary">{h.text}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
  );
}
