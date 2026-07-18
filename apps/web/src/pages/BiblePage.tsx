import { useParams, Navigate } from "react-router-dom";
import { Lock, Plus } from "lucide-react";
import { BibleSubNav } from "@/components/layout/BibleSubNav";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import { useState } from "react";
import {
  apiRequest,
  useApiQuery,
  type CharacterState,
  type CharacterSummary,
  type FactionSummary,
  type ItemSummary,
  type LocationSummary,
  type WorldRule,
} from "@/lib/api";
import { cn } from "@/lib/cn";

const validSections = ["characters", "locations", "factions", "items", "world-rules"];

export function BiblePage() {
  const { section } = useParams();
  if (!section || !validSections.includes(section)) {
    return <Navigate to="characters" replace />;
  }

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
        <BibleSubNav />
        <div className="min-h-0 flex-1 overflow-y-auto md:overflow-hidden">
          {section === "characters" && <CharactersSection />}
          {section === "locations" && <LocationsSection />}
          {section === "factions" && <FactionsSection />}
          {section === "items" && <ItemsSection />}
          {section === "world-rules" && <WorldRulesSection />}
        </div>
      </div>
  );
}

/* ----------------------------- Characters ------------------------------ */
// Left list, center detail with grouped tabs, right chapter-state + relations (§12.1)
function CharactersSection() {
  const { id } = useParams();
  const { data: characters, refetch } = useApiQuery<CharacterSummary[]>(id ? `/novels/${id}/characters` : null, []);
  const [activeId, setActiveId] = useState("");
  const [tab, setTab] = useState("profile");
  const active = characters.find((c) => c.id === activeId) ?? characters[0];
  const { data: stateHistory } = useApiQuery<CharacterState[]>(
    active?.id ? `/story-entities/${active.id}/states` : null,
    [],
  );
  const latestState = stateHistory.length ? stateHistory[stateHistory.length - 1] : null;
  const create = async () => {
    if (!id) return;
    const name = window.prompt("人物姓名")?.trim();
    if (!name) return;
    const role = window.prompt("人物角色", "配角")?.trim() || "配角";
    const item = await apiRequest<CharacterSummary>(`/novels/${id}/characters`, { method: "POST", body: JSON.stringify({ name, summary: "", data: { role, status: "未登场" }, locked_fields: [] }) });
    await refetch(); setActiveId(item.id);
  };
  const edit = async () => {
    if (!active) return;
    const summary = window.prompt("人物画像摘要", active.summary ?? "");
    if (summary === null) return;
    const status = window.prompt("当前状态", active.status);
    if (status === null) return;
    await apiRequest(`/story-entities/${active.id}`, { method: "PATCH", body: JSON.stringify({ summary, data: { role: active.role, status } }) });
    await refetch();
  };
  if (!characters.length) return <EmptySection label="暂无人物，点击「新建」添加" />;
  if (!active) return <EmptySection label="正在加载人物…" />;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
      {/* list */}
      <aside className="flex w-full shrink-0 flex-col border-b border-border bg-surface md:w-[260px] md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-[13px] font-semibold text-text-primary">人物</span>
          <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={() => void create()}>
            新建
          </Button>
        </div>
        <div className="flex min-h-0 max-h-[150px] flex-1 overflow-x-auto md:max-h-none md:flex-col md:overflow-x-hidden md:overflow-y-auto">
          {characters.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveId(c.id)}
              className={cn(
                "flex min-w-[170px] items-center gap-3 border-b-2 px-3 py-2.5 text-left transition-colors duration-150 md:w-full md:min-w-0 md:border-b-0 md:border-l-2 md:px-4",
                c.id === activeId
                  ? "border-primary bg-[#F0FDFA]"
                  : "border-transparent hover:bg-surface-subtle",
              )}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-subtle text-[13px] font-semibold text-text-secondary">
                {c.name.slice(0, 1)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span className="truncate text-[14px] text-text-primary">{c.name}</span>
                  {c.locked && <Lock size={11} className="text-text-secondary" />}
                </span>
                <span className="block truncate text-[12px] text-text-secondary">{c.role}</span>
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* detail */}
      <section className="flex min-w-0 shrink-0 flex-col bg-background md:flex-1">
        <div className="border-b border-border bg-surface px-4 pt-4 sm:px-6">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
            <h1 className="text-[20px] font-semibold text-text-primary">{active.name}</h1>
            <span className="rounded bg-surface-subtle px-2 py-0.5 text-[12px] text-text-secondary">
              {active.role}
            </span>
            </div>
            <Button size="sm" onClick={() => void edit()}>编辑人物</Button>
          </div>
          <Tabs
            className="mt-3"
            value={tab}
            onChange={setTab}
            items={[
              { key: "profile", label: "画像" },
              { key: "background", label: "背景" },
              { key: "personality", label: "性格与动机" },
              { key: "voice", label: "说话方式" },
              { key: "history", label: "状态历史" },
            ]}
          />
        </div>
        <div className="min-h-0 flex-1 p-4 md:overflow-y-auto md:p-6">
          {tab === "history" ? (
            <StateHistoryList states={stateHistory} />
          ) : (
            <DefList
              rows={[
                { k: "姓名", v: active.name, locked: active.locked },
                { k: "画像摘要", v: active.summary || "尚未填写" },
                { k: "当前状态", v: active.status },
                {
                  k: "最新位置",
                  v: latestState?.location || "尚无章节状态",
                },
                {
                  k: "身体",
                  v: latestState
                    ? `${latestState.alive ? "存活" : "死亡"} · ${latestState.bodyStatus || "—"}`
                    : "—",
                },
                {
                  k: "已知事实",
                  v: latestState?.knownFacts?.length
                    ? latestState.knownFacts.join("；")
                    : "—",
                },
              ]}
            />
          )}
        </div>
      </section>

      {/* right — chapter state + relations */}
      <aside className="flex w-full shrink-0 flex-col border-t border-border bg-surface md:w-[300px] md:border-l md:border-t-0">
        <h3 className="px-4 pb-2 pt-4 text-[12px] font-semibold uppercase tracking-wide text-text-secondary">
          章节状态
        </h3>
        <ul className="flex flex-col gap-2 px-4 pb-4 text-[13px]">
          {stateHistory.length === 0 && (
            <li className="rounded-control border border-border p-3 text-text-secondary">
              确认章节后会在此沉淀状态。
            </li>
          )}
          {[...stateHistory].reverse().slice(0, 6).map((s) => (
            <li key={s.id} className="rounded-control border border-border p-3">
              <p className="text-text-secondary">第 {s.chapterIndex} 章</p>
              <p className="mt-0.5 text-text-primary">
                {[s.location && `位于${s.location}`, s.emotion, s.notes]
                  .filter(Boolean)
                  .join(" · ") || (s.alive ? "存活" : "死亡")}
              </p>
            </li>
          ))}
        </ul>
        <CharacterRelationsPanel entityId={active.id} />
      </aside>
    </div>
  );
}

function CharacterRelationsPanel({ entityId }: { entityId: string }) {
  const { id } = useParams();
  const { data: all, refetch } = useApiQuery<
    Array<{ fromId: string; fromName: string; toName: string; type: string; note: string }>
  >(entityId && id ? `/novels/${id}/relations` : null, []);
  const mine = all.filter((r) => r.fromId === entityId);
  const [busy, setBusy] = useState(false);
  const addRelation = async () => {
    const to = window.prompt("关系对象姓名")?.trim();
    if (!to) return;
    const type = window.prompt("关系类型", "同僚")?.trim() || "同僚";
    const note = window.prompt("备注（可选）", "")?.trim() || "";
    setBusy(true);
    try {
      const next = [
        ...mine.map((r) => ({ to: r.toName, type: r.type, note: r.note })),
        { to, type, note },
      ];
      await apiRequest(`/story-entities/${entityId}/relations`, {
        method: "PUT",
        body: JSON.stringify({ relations: next }),
      });
      await refetch();
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <h3 className="flex items-center justify-between px-4 pb-2 pt-2 text-[12px] font-semibold uppercase tracking-wide text-text-secondary">
        <span>关系</span>
        <button
          type="button"
          disabled={busy}
          onClick={() => void addRelation()}
          className="text-[12px] font-medium normal-case text-primary hover:underline"
        >
          添加
        </button>
      </h3>
      <ul className="flex flex-col gap-1 px-4 pb-6 text-[13px] text-text-primary">
        {mine.length === 0 && (
          <li className="text-text-secondary">暂无关系，点击添加</li>
        )}
        {mine.map((r, i) => (
          <li key={`${r.toName}-${i}`} className="flex items-center justify-between gap-2">
            <span>{r.toName}</span>
            <span className="text-[12px] text-text-secondary">
              {r.type}
              {r.note ? ` · ${r.note}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function StateHistoryList({ states }: { states: CharacterState[] }) {
  if (!states.length) {
    return <p className="text-[14px] text-text-secondary">暂无状态历史。确认含该人物的章节后自动生成。</p>;
  }
  return (
    <ul className="flex max-w-[720px] flex-col gap-3">
      {states.map((s) => (
        <li key={s.id} className="rounded-card border border-border bg-surface p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[14px] font-medium text-text-primary">第 {s.chapterIndex} 章</p>
            <p className="text-[12px] text-text-secondary">
              {s.alive ? "存活" : "死亡"} · {s.bodyStatus || "—"}
            </p>
          </div>
          <p className="mt-2 text-[13px] text-text-primary">位置：{s.location || "—"}</p>
          {s.emotion && <p className="mt-1 text-[13px] text-text-secondary">情绪：{s.emotion}</p>}
          {!!s.knownFacts?.length && (
            <p className="mt-1 text-[13px] text-text-secondary">已知：{s.knownFacts.join("；")}</p>
          )}
          {!!s.beliefs?.length && (
            <p className="mt-1 text-[13px] text-text-secondary">信念：{s.beliefs.join("；")}</p>
          )}
          {s.notes && <p className="mt-1 text-[13px] text-text-secondary">{s.notes}</p>}
        </li>
      ))}
    </ul>
  );
}

function DefList({ rows }: { rows: { k: string; v: string; locked?: boolean }[] }) {
  return (
    <dl className="max-w-[720px] divide-y divide-border rounded-card border border-border">
      {rows.map((r) => (
        <div key={r.k} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:gap-4">
          <dt className="flex w-full shrink-0 items-center gap-1 text-[13px] text-text-secondary sm:w-24">
            {r.k}
            {r.locked && <Lock size={11} />}
          </dt>
          <dd className="min-w-0 flex-1 break-words text-[14px] text-text-primary">{r.v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------ Locations ------------------------------ */
function LocationsSection() {
  const { id } = useParams();
  const { data: locations, refetch } = useApiQuery<LocationSummary[]>(id ? `/novels/${id}/locations` : null, []);
  const [activeId, setActiveId] = useState("");
  const active = locations.find((l) => l.id === activeId) ?? locations[0];
  const create = async () => {
    if (!id) return; const name = window.prompt("地点名称")?.trim(); if (!name) return;
    const item = await apiRequest<LocationSummary>(`/novels/${id}/locations`, {method:"POST",body:JSON.stringify({name,summary:"",data:{region:"未分类",state:"正常",depth:0}})});
    await refetch();setActiveId(item.id);
  };
  if (!locations.length) return <EmptySection label="暂无地点，点击「新建」添加" />;
  if (!active) return <EmptySection label="正在加载地点…" />;
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
      <aside className="flex w-full shrink-0 flex-col border-b border-border bg-surface md:w-[260px] md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-[13px] font-semibold text-text-primary">地点</span>
          <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={() => void create()}>
            新建
          </Button>
        </div>
        <div className="flex min-h-0 max-h-[150px] flex-1 overflow-x-auto py-1 md:max-h-none md:flex-col md:overflow-x-hidden md:overflow-y-auto">
          {locations.map((l) => (
            <button
              key={l.id}
              onClick={() => setActiveId(l.id)}
              style={{ paddingLeft: 16 + l.depth * 16 }}
              className={cn(
                "flex min-w-[190px] items-center justify-between border-b-2 py-2.5 pr-4 text-left transition-colors md:w-full md:min-w-0 md:border-b-0 md:border-l-2",
                l.id === activeId
                  ? "border-primary bg-[#F0FDFA]"
                  : "border-transparent hover:bg-surface-subtle",
              )}
            >
              <span className="truncate text-[14px] text-text-primary">{l.name}</span>
              <span className="shrink-0 text-[12px] text-text-secondary">{l.state}</span>
            </button>
          ))}
        </div>
      </aside>
      <section className="flex min-w-0 shrink-0 flex-col bg-background md:flex-1">
        <div className="border-b border-border bg-surface px-4 py-4 sm:px-6">
          <div className="flex items-center justify-between"><h1 className="text-[20px] font-semibold text-text-primary">{active.name}</h1><Button size="sm" onClick={async()=>{const summary=window.prompt("地点描述",active.summary??"");if(summary===null)return;await apiRequest(`/story-entities/${active.id}`,{method:"PATCH",body:JSON.stringify({summary,data:{region:active.region,state:active.state,depth:active.depth}})});await refetch();}}>编辑地点</Button></div>
          <p className="mt-1 text-[13px] text-text-secondary">
            {active.region} · {active.state}
          </p>
        </div>
        <div className="min-h-0 flex-1 p-4 md:overflow-y-auto md:p-6">
          <DefList
            rows={[
              { k: "所属区域", v: active.region },
              { k: "当前状态", v: active.state },
              { k: "地点描述", v: active.summary || "尚未填写" },
            ]}
          />
        </div>
      </section>
      <aside className="flex w-full shrink-0 flex-col border-t border-border bg-surface p-4 md:w-[300px] md:border-l md:border-t-0">
        <h3 className="pb-2 text-[12px] font-semibold uppercase tracking-wide text-text-secondary">
          相关
        </h3>
        <p className="text-[13px] text-text-secondary">确认章节后会在此汇总关联章节与人物。</p>
      </aside>
    </div>
  );
}

/* ------------------------------- Factions ------------------------------ */
function FactionsSection() {
  const { id } = useParams();
  const { data: factions, refetch } = useApiQuery<FactionSummary[]>(id ? `/novels/${id}/factions` : null, []);
  return (
    <TablePage
      title="势力"
      columns={["名称", "类型", "立场", "势力范围"]}
      rows={factions.map((f) => [f.name, f.kind, f.stance, f.power])}
      onCreate={async()=>{if(!id)return;const name=window.prompt("势力名称")?.trim();if(!name)return;await apiRequest(`/novels/${id}/factions`,{method:"POST",body:JSON.stringify({name,data:{kind:"未分类",stance:"中立",power:"中"}})});await refetch();}}
    />
  );
}

/* -------------------------------- Items -------------------------------- */
function ItemsSection() {
  const { id } = useParams();
  const { data: items, refetch } = useApiQuery<ItemSummary[]>(id ? `/novels/${id}/items` : null, []);
  return (
    <TablePage
      title="物品"
      columns={["名称", "类型", "归属", "状态"]}
      rows={items.map((it) => [it.name, it.kind, it.owner, it.state])}
      onCreate={async()=>{if(!id)return;const name=window.prompt("物品名称")?.trim();if(!name)return;await apiRequest(`/novels/${id}/items`,{method:"POST",body:JSON.stringify({name,data:{kind:"普通物品",owner:"无",state:"正常"}})});await refetch();}}
    />
  );
}

/* ----------------------------- World rules ----------------------------- */
function WorldRulesSection() {
  const { id } = useParams();
  const { data: worldRules, refetch } = useApiQuery<WorldRule[]>(id ? `/novels/${id}/world-rules` : null, []);
  const create = async()=>{if(!id)return;const rule=window.prompt("输入不可被 AI 违反的世界规则")?.trim();if(!rule)return;await apiRequest(`/novels/${id}/world-rules`,{method:"POST",body:JSON.stringify({rule,rule_type:"世界设定",importance:"高",locked:true})});await refetch();};
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-4">
        <h1 className="text-[20px] font-semibold text-text-primary">世界规则</h1>
        <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => void create()}>
          新建规则
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="min-w-[720px] text-left text-[13px]">
            <thead className="bg-surface-subtle text-text-secondary">
              <tr>
                {["规则", "类型", "重要级别", "生效章节", "锁定", "违反次数"].map((h) => (
                  <th key={h} className="px-4 py-2.5 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {worldRules.map((r) => (
                <tr key={r.id}>
                  <td className="px-4 py-3 text-text-primary">{r.rule}</td>
                  <td className="px-4 py-3 text-text-secondary">{r.type}</td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[12px] font-medium",
                        r.importance === "高" && "bg-[#FEF2F2] text-danger",
                        r.importance === "中" && "bg-[#FEF3C7] text-warning",
                        r.importance === "低" && "bg-surface-subtle text-text-secondary",
                      )}
                    >
                      {r.importance}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{r.since}</td>
                  <td className="px-4 py-3">
                    {r.locked ? (
                      <span className="inline-flex items-center gap-1 text-text-primary">
                        <Lock size={12} /> 已锁定
                      </span>
                    ) : (
                      <span className="text-text-secondary">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "font-semibold tabular-nums",
                        r.violations > 0 ? "text-danger" : "text-text-secondary",
                      )}
                    >
                      {r.violations}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function EmptySection({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center text-[13px] text-text-secondary animate-nove-fade-in">
      {label}
    </div>
  );
}

/* Reusable simple table page for factions / items. */
function TablePage({
  title,
  columns,
  rows,
  onCreate,
}: {
  title: string;
  columns: string[];
  rows: string[][];
  onCreate: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex items-center justify-between border-b border-border bg-surface px-6 py-4">
        <h1 className="text-[20px] font-semibold text-text-primary">{title}</h1>
        <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={onCreate}>
          新建
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="min-w-[620px] text-left text-[13px]">
            <thead className="bg-surface-subtle text-text-secondary">
              <tr>
                {columns.map((h) => (
                  <th key={h} className="px-4 py-2.5 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {rows.map((r, i) => (
                <tr key={i}>
                  {r.map((cell, j) => (
                    <td
                      key={j}
                      className={cn(
                        "px-4 py-3",
                        j === 0 ? "font-medium text-text-primary" : "text-text-secondary",
                      )}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
