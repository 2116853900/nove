import { Suspense, useEffect } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useNovel } from "@/lib/api";
import { useWorkspaceStore } from "@/stores/workspace";
import { TopBar } from "./TopBar";
import { WorkspaceNav } from "./WorkspaceNav";

/**
 * Persistent workspace shell for all /novel/:id/* routes.
 * Top bar + module rail stay mounted across navigation so clicks feel like
 * content swap, not a full page reload.
 */
export function WorkspaceLayout() {
  const { id } = useParams();
  const { data: novel } = useNovel(id);
  const focusMode = useWorkspaceStore((s) => s.focusMode);
  const chapterLabel = useWorkspaceStore((s) => s.chapterLabel);
  const saveState = useWorkspaceStore((s) => s.saveState);
  const resetChrome = useWorkspaceStore((s) => s.resetChrome);

  useEffect(() => {
    resetChrome();
    return () => resetChrome();
  }, [id, resetChrome]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      {!focusMode && (
        <TopBar novel={novel} chapterLabel={chapterLabel} saveState={saveState} />
      )}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {!focusMode && <WorkspaceNav />}
        <main className="order-1 flex min-h-0 min-w-0 flex-1 md:order-none">
          <Suspense
            fallback={
              <div className="flex flex-1 items-center justify-center bg-background">
                <div className="flex flex-col items-center gap-3">
                  <div className="h-1.5 w-28 overflow-hidden rounded-full bg-surface-subtle">
                    <div className="h-full w-1/2 rounded-full bg-primary animate-nove-pulse" />
                  </div>
                  <p className="text-[13px] text-text-secondary">加载中…</p>
                </div>
              </div>
            }
          >
            <div className="flex min-h-0 min-w-0 flex-1 animate-nove-fade-in">
              <Outlet />
            </div>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
