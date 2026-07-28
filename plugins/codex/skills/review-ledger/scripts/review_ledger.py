#!/usr/bin/env python3
"""Local PR review findings ledger with stable Markdown output."""

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


STATUSES = ("open", "fixed", "rejected", "withdrawn")
SEVERITIES = ("P1", "P2", "P3")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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
    branch = result.stdout.strip()
    if not branch:
        raise RuntimeError("detached HEAD에서는 review ledger를 시작할 수 없습니다")
    return branch


def ledger_path(root, pr):
    return root / ".claude" / ".cache" / "review-ledger" / f"pr-{pr}.json"


def load_ledger(root, pr):
    path = ledger_path(root, pr)
    if not path.exists():
        raise RuntimeError(f"원장 없음: 먼저 init --pr {pr} 실행")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if (
        not isinstance(data, dict)
        or data.get("pr") != pr
        or not isinstance(data.get("findings"), list)
        or not isinstance(data.get("reviewers", []), list)
    ):
        raise RuntimeError(f"잘못된 원장 형식: {path}")
    required = {"id", "severity", "claim", "status", "evidence"}
    if any(not isinstance(item, dict) or not required <= item.keys() for item in data["findings"]):
        raise RuntimeError(f"필수 finding 필드가 없습니다: {path}")
    return data


def save_ledger(root, pr, ledger):
    if ledger.get("pr") != pr:
        raise RuntimeError(f"원장 PR 불일치: 요청 #{pr}, 내용 #{ledger.get('pr')}")
    path = ledger_path(root, pr)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = now_iso()
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(ledger, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


@contextlib.contextmanager
def ledger_lock(root, pr):
    """Cross-process exclusive lock for one PR ledger."""
    path = ledger_path(root, pr)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    handle = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if os.path.getsize(lock_path) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def ensure_local_exclude(root):
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = ".claude/.cache/"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if entry not in existing.splitlines():
        with path.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(entry + "\n")


def event(ledger, action, finding=None, **extra):
    item = {
        "round": ledger.get("round", 1),
        "action": action,
        "finding": finding,
        "at": now_iso(),
    }
    item.update(extra)
    ledger.setdefault("events", []).append(item)


ABSENCE_PATTERN = re.compile(
    r"(없(?:다|음|는)|누락|존재하지|missing|does not exist|doesn't exist|"
    r"no (?:test|file|case|reference|implementation|guard|handler|function|method)|lacks?\b)",
    re.IGNORECASE,
)


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
    events = ledger.get("events", [])
    current_actions = [
        item.get("action") for item in events if item.get("round") == current_round
    ]
    round_counts = {
        "new": current_actions.count("opened"),
        "fixed": current_actions.count("fixed"),
        "rejected": current_actions.count("rejected"),
        "withdrawn": current_actions.count("withdrawn"),
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
    if events:
        lines.extend(["", "### Round history", "", "| Round | New | Fixed | Rejected | Withdrawn |", "|---|---|---|---|---|"])
        for round_number in range(1, current_round + 1):
            actions = [item.get("action") for item in events if item.get("round") == round_number]
            lines.append(
                f"| {round_number} | {actions.count('opened')} | {actions.count('fixed')} | "
                f"{actions.count('rejected')} | {actions.count('withdrawn')} |"
            )
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
            lines.append(
                "| "
                + " | ".join(
                    str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")
                    for value in values
                )
                + " |"
            )
    return "\n".join(lines)


def cmd_init(args):
    root = repo_root(args.project_dir)
    path = ledger_path(root, args.pr)
    ensure_local_exclude(root)
    with ledger_lock(root, args.pr):
        if path.exists() and not args.force:
            raise RuntimeError(f"원장이 이미 있습니다: {path}")
        if path.exists():
            backup = path.with_name(f"pr-{args.pr}.{now_iso().replace(':', '-')}.bak.json")
            shutil.copy2(path, backup)
        ledger = {
            "version": 1,
            "pr": args.pr,
            "branch": current_branch(root),
            "round": 1,
            "reviewers": [],
            "findings": [],
            "events": [],
            "created_at": now_iso(),
        }
        save_ledger(root, args.pr, ledger)
    print(path.relative_to(root))


def cmd_add(args):
    root = repo_root(args.project_dir)
    evidence = args.evidence or []
    absence = args.absence or (
        not args.not_absence and bool(ABSENCE_PATTERN.search(args.claim))
    )
    if absence and not evidence:
        raise RuntimeError("부재 주장은 --evidence 검색 명령 없이는 open 등록할 수 없습니다")
    with ledger_lock(root, args.pr):
        ledger = load_ledger(root, args.pr)
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
            "absence_claim": absence,
            "round_opened": ledger.get("round", 1),
            "updated_at": now_iso(),
        }
        ledger["findings"].append(finding)
        event(ledger, "opened", finding["id"])
        ledger["branch"] = current_branch(root)
        save_ledger(root, args.pr, ledger)
    print(finding["id"])


def cmd_update(args):
    root = repo_root(args.project_dir)
    with ledger_lock(root, args.pr):
        ledger = load_ledger(root, args.pr)
        finding = finding_by_id(ledger, args.id)
        previous = finding["status"]
        finding["status"] = args.status
        finding["round_updated"] = ledger.get("round", 1)
        if args.status == "open" and previous != "open":
            finding["round_opened"] = ledger.get("round", 1)
        if args.evidence:
            finding.setdefault("evidence", []).extend(args.evidence)
        finding["updated_at"] = now_iso()
        if args.status == previous:
            action = "evidence_updated"
        elif args.status == "open":
            action = "opened"
        else:
            action = args.status
        event(ledger, action, args.id, previous=previous, evidence=args.evidence or [])
        ledger["branch"] = current_branch(root)
        save_ledger(root, args.pr, ledger)
    print(f"{args.id}: {args.status}")


def cmd_round(args):
    root = repo_root(args.project_dir)
    with ledger_lock(root, args.pr):
        ledger = load_ledger(root, args.pr)
        open_ids = [
            item["id"] for item in ledger["findings"] if item.get("status") == "open"
        ]
        if open_ids and not args.acknowledge_open:
            raise RuntimeError(
                "기존 open finding을 먼저 재검수하세요. 계속하려면 "
                f"--acknowledge-open 사용: {', '.join(open_ids)}"
            )
        ledger["round"] = int(ledger.get("round", 1)) + 1
        event(ledger, "round_started", acknowledged_open=open_ids)
        ledger["branch"] = current_branch(root)
        save_ledger(root, args.pr, ledger)
    print(ledger["round"])


def cmd_reviewer(args):
    root = repo_root(args.project_dir)
    with ledger_lock(root, args.pr):
        ledger = load_ledger(root, args.pr)
        reviewer = {"name": args.name}
        if args.thread is not None:
            reviewer["thread"] = args.thread
        existing = next(
            (item for item in ledger["reviewers"] if item.get("name") == args.name),
            None,
        )
        if existing:
            existing.update(reviewer)
        else:
            ledger["reviewers"].append(reviewer)
        ledger["branch"] = current_branch(root)
        save_ledger(root, args.pr, ledger)
    print(args.name)


def cmd_show(args):
    root = repo_root(args.project_dir)
    with ledger_lock(root, args.pr):
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
    absence = add.add_mutually_exclusive_group()
    absence.add_argument("--absence", action="store_true")
    absence.add_argument(
        "--not-absence",
        action="store_true",
        help="부재처럼 보이는 문구지만 부재 주장이 아님을 명시",
    )
    add.set_defaults(func=cmd_add)

    update = subparsers.add_parser("update")
    update.add_argument("--pr", type=int, required=True)
    update.add_argument("id")
    update.add_argument("--status", choices=STATUSES, required=True)
    update.add_argument("--evidence", action="append")
    update.set_defaults(func=cmd_update)

    round_parser = subparsers.add_parser("round")
    round_parser.add_argument("--pr", type=int, required=True)
    round_parser.add_argument("--acknowledge-open", action="store_true")
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
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return result or 0


if __name__ == "__main__":
    sys.exit(main())
