#!/usr/bin/env python3
"""
eval-rubric-validator: Deterministic Schema, Score & Rubric QA Pipeline.

Validates JSONL evaluation or annotation records for required metadata, score
range compliance, edge-case justification notes on non-top scores, and duplicate
task IDs, producing a JSON audit report and a Markdown QA summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_SCORE = 1
MAX_SCORE = 5
MIN_NOTE_LENGTH_FOR_ARTIFACTS = 15


@dataclass
class Issue:
    line_number: int
    task_id: str
    severity: str  # ERROR, WARN
    code: str
    message: str


@dataclass
class AuditSummary:
    source_file: str
    generated_utc: str
    total_lines: int
    valid_records: int
    error_count: int
    warning_count: int
    score_distribution: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)


def validate_record(payload: dict[str, Any], line_number: int) -> tuple[bool, list[Issue]]:
    """Validates a parsed JSON object against evaluation record rules."""
    issues: list[Issue] = []
    task_id = str(payload.get("task_id", f"line-{line_number}")).strip() or f"line-{line_number}"
    is_valid = True

    required_fields = ("task_id", "category", "score")
    for req in required_fields:
        if req not in payload or payload[req] is None or str(payload[req]).strip() == "":
            issues.append(
                Issue(
                    line_number=line_number,
                    task_id=task_id,
                    severity="ERROR",
                    code="VAL-001",
                    message=f"Missing or empty required field '{req}'.",
                )
            )
            is_valid = False

    score_val = payload.get("score")
    numeric_score: int | None = None
    if score_val is not None:
        if isinstance(score_val, bool) or not isinstance(score_val, int):
            issues.append(
                Issue(
                    line_number=line_number,
                    task_id=task_id,
                    severity="ERROR",
                    code="VAL-002",
                    message=f"Score must be an integer, got {type(score_val).__name__} ({score_val!r}).",
                )
            )
            is_valid = False
        elif not (MIN_SCORE <= score_val <= MAX_SCORE):
            issues.append(
                Issue(
                    line_number=line_number,
                    task_id=task_id,
                    severity="ERROR",
                    code="VAL-003",
                    message=f"Score {score_val} outside valid range [{MIN_SCORE}, {MAX_SCORE}].",
                )
            )
            is_valid = False
        else:
            numeric_score = score_val

    notes = str(payload.get("notes", "")).strip()
    if numeric_score is not None and numeric_score < MAX_SCORE:
        if len(notes) < MIN_NOTE_LENGTH_FOR_ARTIFACTS:
            issues.append(
                Issue(
                    line_number=line_number,
                    task_id=task_id,
                    severity="WARN",
                    code="RUB-001",
                    message=(
                        f"Score {numeric_score} (< {MAX_SCORE}) has missing or brief notes "
                        f"({len(notes)} chars; recommend >= {MIN_NOTE_LENGTH_FOR_ARTIFACTS} chars)."
                    ),
                )
            )

    if "status" in payload and str(payload["status"]).strip().lower() not in {
        "completed",
        "pending_review",
        "flagged",
    }:
        issues.append(
            Issue(
                line_number=line_number,
                task_id=task_id,
                severity="WARN",
                code="VAL-004",
                message=f"Non-standard status value {payload['status']!r}.",
            )
        )

    return is_valid, issues


def render_markdown(summary: AuditSummary, issues: list[Issue]) -> str:
    lines = [
        "# Evaluation Dataset QA & Rubric Audit Report",
        "",
        f"- **Source File:** `{summary.source_file}`",
        f"- **Generated (UTC):** `{summary.generated_utc}`",
        f"- **Total Lines:** `{summary.total_lines}` | **Valid Records:** `{summary.valid_records}`",
        f"- **Errors:** `{summary.error_count}` | **Warnings:** `{summary.warning_count}`",
        "",
        "## Score Distribution",
        "",
    ]

    if summary.score_distribution:
        for score_key in sorted(summary.score_distribution.keys()):
            lines.append(f"- **Score {score_key}:** `{summary.score_distribution[score_key]}`")
    else:
        lines.append("_No valid numeric scores recorded._")

    lines.extend(["", "## Category Breakdown", ""])
    if summary.category_counts:
        for cat, count in sorted(summary.category_counts.items()):
            lines.append(f"- `{cat}`: `{count}`")
    else:
        lines.append("_No categories recorded._")

    lines.extend(["", "## Validation & Rubric Findings", ""])
    if not issues:
        lines.append("_All records passed schema and rubric checks cleanly._")
    else:
        lines.extend(
            [
                "| Line | Task ID | Severity | Code | Message |",
                "| :---: | :--- | :---: | :--- | :--- |",
            ]
        )
        for item in issues:
            lines.append(
                f"| {item.line_number} | `{item.task_id}` | **{item.severity}** | `{item.code}` | {item.message} |"
            )

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate JSONL evaluation records, rubric notes, and duplicate IDs."
    )
    parser.add_argument("input_file", type=Path, help="Path to evaluation .jsonl file")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("eval_audit_report.json"),
        help="Output JSON report path (default: eval_audit_report.json)",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=Path("eval_audit_summary.md"),
        help="Output Markdown report path (default: eval_audit_summary.md)",
    )
    args = parser.parse_args()

    if not args.input_file.is_file():
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        return 2

    issues: list[Issue] = []
    seen_task_ids: dict[str, int] = {}
    score_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()

    valid_records = 0
    total_lines = 0

    with args.input_file.open("r", encoding="utf-8") as handle:
        for line_num, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            total_lines += 1

            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                issues.append(
                    Issue(
                        line_number=line_num,
                        task_id=f"line-{line_num}",
                        severity="ERROR",
                        code="JSON-001",
                        message=f"Malformed JSON: {exc}",
                    )
                )
                continue

            if not isinstance(payload, dict):
                issues.append(
                    Issue(
                        line_number=line_num,
                        task_id=f"line-{line_num}",
                        severity="ERROR",
                        code="JSON-002",
                        message="Top-level JSON record must be an object.",
                    )
                )
                continue

            is_valid, rec_issues = validate_record(payload, line_num)
            issues.extend(rec_issues)

            task_id = str(payload.get("task_id", "")).strip()
            if task_id:
                if task_id in seen_task_ids:
                    issues.append(
                        Issue(
                            line_number=line_num,
                            task_id=task_id,
                            severity="WARN",
                            code="DUP-001",
                            message=f"Duplicate task_id first seen on line {seen_task_ids[task_id]}.",
                        )
                    )
                else:
                    seen_task_ids[task_id] = line_num

            if is_valid:
                valid_records += 1
                score_counter[str(payload["score"])] += 1
                category_counter[str(payload["category"]).strip()] += 1

    error_count = sum(1 for i in issues if i.severity == "ERROR")
    warning_count = sum(1 for i in issues if i.severity == "WARN")

    summary = AuditSummary(
        source_file=str(args.input_file),
        generated_utc=datetime.now(timezone.utc).isoformat(),
        total_lines=total_lines,
        valid_records=valid_records,
        error_count=error_count,
        warning_count=warning_count,
        score_distribution=dict(score_counter),
        category_counts=dict(category_counter),
    )

    report = {
        "summary": asdict(summary),
        "issues": [asdict(i) for i in issues],
    }

    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.md_out.write_text(render_markdown(summary, issues), encoding="utf-8")

    print(
        f"[+] Audited {total_lines} records ({valid_records} valid): "
        f"{error_count} errors, {warning_count} warnings."
    )
    print(f"[+] Saved {args.json_out} and {args.md_out}")

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
