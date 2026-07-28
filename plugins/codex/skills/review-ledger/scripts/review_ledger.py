#!/usr/bin/env python3
"""Local PR review findings ledger with stable Markdown output."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


STATUSES = ("open", "fixed", "rejected", "withdrawn")
SEVERITIES = ("P1", "P2", "P3")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def repo_root(project_dir=None):
    cwd = os.path.abspath(project_dir or os.getcwd())
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("git 저장소를 찾을 수 없습니다")
    return Path(result.stdout.strip())


def current_branch(root):
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def ledger_path(root, pr):
    return root / ".claude" / ".cache" / "review-ledger" / f"pr-{pr}.json"


def load_ledger(root, pr):
    path = ledger_path(root, pr)
    if not path.exists():
        raise RuntimeError(f"원장 없음: 먼저 init --pr {pr} 실행")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise RuntimeError(f"잘못된 원장 형식: {path}")
    return data


def save_ledger(root, ledger):
    path = ledger_path(root, ledger["pr"])
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = now_iso()
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(ledger, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, path)
    return path


def finding_by_id(ledger, finding_id):
    for finding in ledger["findings"]:
        if finding.get("id") == finding_id:
            return finding
    raise RuntimeError(f"finding 없음: {finding_id}")


def next_id(ledger):
    numbers = []
    for finding in ledger["findings"]:
        value = str(finding.get("id", ""))
        if value.startswith("F-") and value[2:].isdigit():
            numbers.append(int(value[2:]))
    return f"F-{max(numbers, default=0) + 1:03d}"


def location(finding):
    file_name = finding.get("file") or "-"
    line = finding.get("line")
    return f"{file_name}:{line}" if line else file_name


def render_markdown(ledger):
    findings = ledger["findings"]
    current_round = ledger.get("round", 1)
    round_counts = {
        "new": sum(item.get("round_opened") == current_round for item in findings),
        "fixed": sum(
            item.get("status") == "fixed" and item.get("round_updated") == current_round
            for item in findings
        ),
        "rejected": sum(
            item.get("status") == "rejected" and item.get("round_updated") == current_round
            for item in findings
        ),
        "withdrawn": sum(
            item.get("status") == "withdrawn" and item.get("round_updated") == current_round
            for item in findings
        ),
    }
    groups = [
        ("Open", [item for item in findings if item.get("status") == "open"]),
        ("Resolved", [item for item in findings if item.get("status") != "open"]),
    ]
    lines = [
        f"## Review ledger — PR #{ledger['pr']}",
        "",
        f"- Branch: `{ledger.get('branch') or '-'}`",
        f"- Rounds: {current_round}",
        (
            f"- Round {current_round}: new {round_counts['new']} / "
            f"fixed {round_counts['fixed']} / rejected {round_counts['rejected']} / "
            f"withdrawn {round_counts['withdrawn']}"
        ),
    ]
    reviewers = ledger.get("reviewers", [])
    if reviewers:
        rendered = ", ".join(
            f"{item['name']}" + (f" (`{item['thread']}`)" if item.get("thread") else "")
            for item in reviewers
        )
        lines.append(f"- Reviewers: {rendered}")
    for title, items in groups:
        lines.extend(["", f"### {title}"])
        if not items:
            lines.append("- None")
            continue
        lines.extend([
            "",
            "| ID | Severity | Location | Claim | Status | Reviewer/thread | Evidence |",
            "|---|---|---|---|---|---|---|",
        ])
        for item in items:
            evidence = "<br>".join(item.get("evidence", [])) or "-"
            values = [
                item["id"],
                item["severity"],
                location(item),
                item["claim"],
                item["status"],
                (item.get("reviewer") or "-")
                + (f" / `{item['thread']}`" if item.get("thread") else ""),
                evidence,
            ]
            lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines)


def cmd_init(args):
    root = repo_root(args.project_dir)
    path = ledger_path(root, args.pr)
    if path.exists() and not args.force:
        raise RuntimeError(f"원장이 이미 있습니다: {path}")
    ledger = {
        "version": 1,
        "pr": args.pr,
        "branch": current_branch(root),
        "round": 1,
        "reviewers": [],
        "findings": [],
        "created_at": now_iso(),
    }
    save_ledger(root, ledger)
    print(path.relative_to(root))


def cmd_add(args):
    root = repo_root(args.project_dir)
    ledger = load_ledger(root, args.pr)
    evidence = args.evidence or []
    if args.absence and not evidence:
        raise RuntimeError("부재 주장은 --evidence 검색 명령 없이는 open 등록할 수 없습니다")
    finding = {
        "id": next_id(ledger),
        "severity": args.severity,
        "file": args.file,
        "line": args.line,
        "claim": args.claim,
        "status": "open",
        "evidence": evidence,
        "reviewer": args.reviewer,
        "thread": args.thread,
        "absence_claim": args.absence,
        "round_opened": ledger.get("round", 1),
        "updated_at": now_iso(),
    }
    ledger["findings"].append(finding)
    save_ledger(root, ledger)
    print(finding["id"])


def cmd_update(args):
    root = repo_root(args.project_dir)
    ledger = load_ledger(root, args.pr)
    finding = finding_by_id(ledger, args.id)
    finding["status"] = args.status
    finding["round_updated"] = ledger.get("round", 1)
    if args.evidence:
        finding.setdefault("evidence", []).extend(args.evidence)
    finding["updated_at"] = now_iso()
    save_ledger(root, ledger)
    print(f"{args.id}: {args.status}")


def cmd_round(args):
    root = repo_root(args.project_dir)
    ledger = load_ledger(root, args.pr)
    ledger["round"] = int(ledger.get("round", 1)) + 1
    save_ledger(root, ledger)
    print(ledger["round"])


def cmd_reviewer(args):
    root = repo_root(args.project_dir)
    ledger = load_ledger(root, args.pr)
    reviewer = {"name": args.name, "thread": args.thread}
    existing = next(
        (item for item in ledger["reviewers"] if item.get("name") == args.name),
        None,
    )
    if existing:
        existing.update(reviewer)
    else:
        ledger["reviewers"].append(reviewer)
    save_ledger(root, ledger)
    print(args.name)


def cmd_show(args):
    root = repo_root(args.project_dir)
    ledger = load_ledger(root, args.pr)
    if args.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(ledger))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--pr", type=int, required=True)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    add = subparsers.add_parser("add")
    add.add_argument("--pr", type=int, required=True)
    add.add_argument("--severity", choices=SEVERITIES, required=True)
    add.add_argument("--file")
    add.add_argument("--line", type=int)
    add.add_argument("--claim", required=True)
    add.add_argument("--evidence", action="append")
    add.add_argument("--reviewer")
    add.add_argument("--thread")
    add.add_argument("--absence", action="store_true")
    add.set_defaults(func=cmd_add)

    update = subparsers.add_parser("update")
    update.add_argument("--pr", type=int, required=True)
    update.add_argument("id")
    update.add_argument("--status", choices=STATUSES, required=True)
    update.add_argument("--evidence", action="append")
    update.set_defaults(func=cmd_update)

    round_parser = subparsers.add_parser("round")
    round_parser.add_argument("--pr", type=int, required=True)
    round_parser.set_defaults(func=cmd_round)

    reviewer = subparsers.add_parser("reviewer")
    reviewer.add_argument("--pr", type=int, required=True)
    reviewer.add_argument("--name", required=True)
    reviewer.add_argument("--thread")
    reviewer.set_defaults(func=cmd_reviewer)

    show = subparsers.add_parser("show")
    show.add_argument("--pr", type=int, required=True)
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        result = args.func(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return result or 0


if __name__ == "__main__":
    sys.exit(main())
