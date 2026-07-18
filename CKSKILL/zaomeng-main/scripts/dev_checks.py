#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SMOKE_TEST_MODULES = [
    "tests.test_cli_structure",
    "tests.test_package_skill_script",
    "tests.test_release_skill",
    "tests.test_skill_version_sync",
    "tests.test_install_skill",
    "tests.test_novel_preparation",
    "tests.test_prompt_payloads",
    "tests.test_packaging_docs",
    "tests.test_web_import_boundaries",
]

CHAT_HELPER_TYPE_TARGETS = [
    "src/web/chat/event_signals.py",
    "src/web/chat/io_utils.py",
    "src/web/chat/memory_summary.py",
    "src/web/chat/persona_context.py",
    "src/web/chat/prompt_rules.py",
    "src/web/chat/relation_excerpt.py",
    "src/web/chat/relation_state.py",
    "src/web/chat/runtime_overview.py",
    "src/web/chat/scene_signals.py",
    "src/web/chat/state_utils.py",
    "src/web/chat/text_utils.py",
]


def run_step(title: str, command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"[step] {title}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local development checks.")
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run prompt-first guardrail tests without the full test suite.",
    )
    parser.add_argument(
        "--release-tag",
        default="",
        help="Optional release tag for cross-platform regression gate, for example v2026.05.16.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_step("run smoke guardrails", [sys.executable, "-m", "unittest", *SMOKE_TEST_MODULES])
    run_step("run mypy", [sys.executable, "-m", "mypy", "--config-file", "mypy.ini"])
    run_step(
        "run chat helper mypy",
        [
            sys.executable,
            "-m",
            "mypy",
            "--python-version",
            "3.10",
            "--explicit-package-bases",
            "--ignore-missing-imports",
            "--follow-imports=skip",
            "--warn-redundant-casts",
            "--warn-unused-configs",
            "--warn-unused-ignores",
            *CHAT_HELPER_TYPE_TARGETS,
        ],
    )
    if args.smoke_only:
        print("[done] smoke checks passed")
        return 0

    gate_command = [sys.executable, "scripts/release_regression_gate.py"]
    if str(args.release_tag or "").strip():
        gate_command.extend(["--release-tag", str(args.release_tag).strip()])
    run_step("run release regression gate", gate_command)
    run_step("run unit tests", [sys.executable, "-m", "pytest", "-q"])
    print("[done] development checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
