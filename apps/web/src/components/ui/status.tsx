import {
  CheckCircle2,
  CircleCheck,
  AlertTriangle,
  Circle,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import type { ChapterStatus, IssueSeverity } from "@/lib/types";

// Status is never conveyed by color alone (§2.3 / §20): every status carries an
// icon and text label as well.
interface StatusMeta {
  label: string;
  icon: LucideIcon;
  className: string;
}

export const chapterStatusMeta: Record<ChapterStatus, StatusMeta> = {
  confirmed: { label: "已确认", icon: CircleCheck, className: "text-success" },
  pass: { label: "通过", icon: CheckCircle2, className: "text-success" },
  revise: { label: "待修改", icon: AlertTriangle, className: "text-warning" },
  fatal: { label: "致命问题", icon: AlertTriangle, className: "text-danger" },
  unaudited: { label: "未检查", icon: Circle, className: "text-text-secondary" },
  "memory-pending": { label: "记忆待同步", icon: RefreshCw, className: "text-info" },
};

interface SeverityMeta {
  label: string;
  tone: "danger" | "warning" | "info";
  className: string;
}

export const severityMeta: Record<IssueSeverity, SeverityMeta> = {
  fatal: { label: "致命", tone: "danger", className: "text-danger" },
  major: { label: "严重", tone: "warning", className: "text-warning" },
  minor: { label: "一般", tone: "info", className: "text-info" },
};
