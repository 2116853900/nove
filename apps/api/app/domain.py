from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChapterState(StrEnum):
    PLANNED = "PLANNED"
    GENERATING = "GENERATING"
    DRAFT = "DRAFT"
    AUDITING = "AUDITING"
    REVISING = "REVISING"
    REWRITING = "REWRITING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"
    OUTDATED = "OUTDATED"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VersionConflictError(RuntimeError):
    """Raised when an autosave was based on a stale chapter version."""


@dataclass(frozen=True)
class AuditPolicy:
    pass_score: int = 85
    revise_score: int = 70
    max_rewrite_attempts: int = 1
    fatal_issue_force_rewrite: bool = True

    def decision(self, score: int, has_fatal_issue: bool) -> str:
        if has_fatal_issue and self.fatal_issue_force_rewrite:
            return "REWRITE"
        if score >= self.pass_score:
            return "PASS"
        if score >= self.revise_score:
            return "REVISE"
        return "REWRITE"
