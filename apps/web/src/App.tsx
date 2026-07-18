import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { WorkspaceLayout } from "@/components/layout/WorkspaceLayout";

const ProjectListPage = lazy(() => import("@/pages/ProjectListPage").then((module) => ({ default: module.ProjectListPage })));
const NewNovelStep1 = lazy(() => import("@/pages/new-novel/NewNovelStep1").then((module) => ({ default: module.NewNovelStep1 })));
const NewNovelStep2 = lazy(() => import("@/pages/new-novel/NewNovelStep2").then((module) => ({ default: module.NewNovelStep2 })));
const NewNovelStep3 = lazy(() => import("@/pages/new-novel/NewNovelStep3").then((module) => ({ default: module.NewNovelStep3 })));
const NovelSetupPage = lazy(() => import("@/pages/NovelSetupPage").then((module) => ({ default: module.NovelSetupPage })));
const WritingWorkspacePage = lazy(() => import("@/pages/WritingWorkspacePage").then((module) => ({ default: module.WritingWorkspacePage })));
const OutlinePage = lazy(() => import("@/pages/OutlinePage").then((module) => ({ default: module.OutlinePage })));
const BiblePage = lazy(() => import("@/pages/BiblePage").then((module) => ({ default: module.BiblePage })));
const PlotPage = lazy(() => import("@/pages/PlotPage").then((module) => ({ default: module.PlotPage })));
const HighlightsPage = lazy(() => import("@/pages/HighlightsPage").then((module) => ({ default: module.HighlightsPage })));
const AuditCenterPage = lazy(() => import("@/pages/AuditCenterPage").then((module) => ({ default: module.AuditCenterPage })));
const VersionHistoryPage = lazy(() => import("@/pages/VersionHistoryPage").then((module) => ({ default: module.VersionHistoryPage })));
const ProjectSettingsPage = lazy(() => import("@/pages/ProjectSettingsPage").then((module) => ({ default: module.ProjectSettingsPage })));
const ImportReviewPage = lazy(() => import("@/pages/ImportReviewPage").then((module) => ({ default: module.ImportReviewPage })));
const ImportNovelPage = lazy(() => import("@/pages/ImportNovelPage").then((module) => ({ default: module.ImportNovelPage })));
const GlobalSettingsPage = lazy(() =>
  import("@/pages/GlobalSettingsPage").then((module) => ({ default: module.GlobalSettingsPage })),
);

function bare(element: React.ReactNode) {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen flex-col items-center justify-center gap-3 bg-background">
          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-surface-subtle">
            <div className="h-full w-1/2 rounded-full bg-primary animate-nove-pulse" />
          </div>
          <p className="text-[13px] text-text-secondary">正在加载…</p>
        </div>
      }
    >
      <div className="h-full min-h-0 animate-nove-fade-in">{element}</div>
    </Suspense>
  );
}

export const router = createBrowserRouter([
  { path: "/", element: bare(<ProjectListPage />) },
  { path: "/import", element: bare(<ImportNovelPage />) },
  { path: "/settings", element: bare(<GlobalSettingsPage />) },
  { path: "/new/1", element: bare(<NewNovelStep1 />) },
  { path: "/new/2", element: bare(<NewNovelStep2 />) },
  { path: "/new/3", element: bare(<NewNovelStep3 />) },
  { path: "/novel/:id/setup", element: bare(<NovelSetupPage />) },
  {
    path: "/novel/:id",
    element: <WorkspaceLayout />,
    children: [
      { path: "write", element: <WritingWorkspacePage /> },
      { path: "outline", element: <OutlinePage /> },
      { path: "bible", element: <Navigate to="characters" replace /> },
      { path: "bible/:section", element: <BiblePage /> },
      { path: "plot", element: <PlotPage /> },
      { path: "highlights", element: <HighlightsPage /> },
      { path: "audit", element: <AuditCenterPage /> },
      { path: "versions", element: <VersionHistoryPage /> },
      { path: "settings", element: <ProjectSettingsPage /> },
      { path: "import-review", element: <ImportReviewPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
