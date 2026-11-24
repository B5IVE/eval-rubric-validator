# eval-rubric-validator

A zero-dependency Python 3.10+ CLI pipeline for evaluation dataset schema validation, rubric score range verification, edge-case justification checks, and automated QA reporting.

Designed to catch malformed JSONL records, missing/shallow notes on lower rubric scores, out-of-range ratings, and duplicate task IDs before evaluation batches are submitted or aggregated.

## Features

- Schema & Type Enforcement (`VAL-001`–`VAL-004`): Verifies required fields (`task_id`, `category`, `score`), enforces integer score types within `[1, 5]`, and checks status values.
- Rubric Justification Check (`RUB-001`): Warns when a non-maximum score (`< 5`) lacks a sufficiently detailed observation note.
- Duplicate Detection (`DUP-001`): Tracks `task_id` occurrences across lines and flags duplicates with their original line number.
- Dual Output & CI Exit Codes: Generates both a structured JSON report (`eval_audit_report.json`) and a Markdown QA table (`eval_audit_summary.md`), exiting with code `1` when hard validation errors (`ERROR`) occur.

## Quickstart

Requires Python 3.10+ (standard library only—no external dependencies).

```bash
git clone [https://github.com/B5IVE/eval-rubric-validator.git](https://github.com/B5IVE/eval-rubric-validator.git)
cd eval-rubric-validator

python3 validate_evals.py sample_evals.jsonl
