#!/usr/bin/env python3
"""Verify whether tests fail against pre-fix source without touching the worktree."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command, cwd, **kwargs):
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        **kwargs,
    )


def repo_root(project_dir=None):
    result = run(
        ["git", "rev-parse", "--show-toplevel"],
        os.path.abspath(project_dir or os.getcwd()),
    )
    if result.returncode:
        raise RuntimeError("git 저장소를 찾을 수 없습니다")
    return Path(result.stdout.strip())


def git_output(root, *args):
    result = run(["git", *args], root)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} 실패")
    return result.stdout


def resolve_base(root, base, base_ref):
    if base == "HEAD":
        return git_output(root, "rev-parse", "--verify", "HEAD").strip()
    ref = base_ref or "origin/main"
    return git_output(root, "merge-base", "HEAD", ref).strip()


def validate_relative_paths(root, paths, label):
    normalized = []
    for raw in paths:
        path = Path(raw)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(root.resolve())
            except ValueError as error:
                raise RuntimeError(f"{label}가 프로젝트 밖입니다: {raw}") from error
        if ".." in path.parts:
            raise RuntimeError(f"{label}에 상위 경로를 쓸 수 없습니다: {raw}")
        normalized.append(path.as_posix())
    return normalized


def copy_untracked_files(root, worktree):
    untracked = [
        line for line in git_output(root, "ls-files", "--others", "--exclude-standard").splitlines()
        if line
    ]
    for item in untracked:
        source = root / item
        if not source.is_file():
            continue
        target = worktree / item
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def command_for_test(template, test):
    parts = shlex.split(template)
    if not parts:
        raise RuntimeError("--command가 비어 있습니다")
    if not any("{test}" in part for part in parts):
        raise RuntimeError("--command에 {test} placeholder가 필요합니다")
    return [part.replace("{test}", test) for part in parts]


def clip_output(value, limit=500):
    value = " ".join(value.strip().split())
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def ensure_local_exclude(root):
    exclude = Path(git_output(root, "rev-parse", "--git-path", "info/exclude").strip())
    if not exclude.is_absolute():
        exclude = root / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    entry = ".claude/.cache/"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry not in existing.splitlines():
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(entry + "\n")


def execute_test(argv, cwd, timeout):
    try:
        completed = run(argv, cwd, timeout=timeout)
        return {
            "exit_code": completed.returncode,
            "output": clip_output(completed.stdout or completed.stderr).replace(
                str(cwd), "<temp-worktree>"
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": None,
            "output": f"timeout after {timeout}s",
        }


def remove_worktree(root, path):
    removed = run(["git", "worktree", "remove", "--force", str(path)], root)
    if removed.returncode:
        run(["git", "worktree", "unlock", str(path)], root)
        removed = run(["git", "worktree", "remove", "--force", str(path)], root)
    if removed.returncode:
        return removed.stderr.strip() or str(path)
    shutil.rmtree(path, ignore_errors=True)
    return ""


def render_markdown(result):
    lines = [
        "## Regression verification",
        "",
        f"- Base: `{result['base']}`",
        f"- Source files: {', '.join(f'`{item}`' for item in result['sources'])}",
        f"- Command: `{result['command']}`",
        f"- Original worktree unchanged: {'yes' if result['worktree_unchanged'] else 'NO'}",
        "",
        "| Test | Pre-fix | Classification | Exit | Output |",
        "|---|---|---|---|---|",
    ]
    for item in result["tests"]:
        values = [
            item["test"],
            item["pre_fix"],
            item["classification"],
            item.get("exit_code", "-"),
            item.get("output") or "-",
        ]
        escaped = [
            str(value).replace("|", "\\|").replace("\n", "<br>") for value in values
        ]
        lines.append("| " + " | ".join(escaped) + " |")
    lines.extend([
        "",
        "> Pre-fix PASS는 삭제 대상이 아니라, 해당 테스트가 회귀 재현이 아닌 신규 로직 가드라는 분류입니다.",
    ])
    for warning in result.get("cleanup_warnings", []):
        lines.append(f"> ⚠️ Cleanup: {warning}")
    return "\n".join(lines)


def verify(root, tests, sources, base, command, timeout):
    ensure_local_exclude(root)
    before = git_output(root, "status", "--porcelain=v1", "-uall")
    cache = root / ".claude" / ".cache" / "verify-regression"
    cache.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="run-", dir=cache))
    worktree_added = False
    results = []
    cleanup_warnings = []
    try:
        add = run(
            ["git", "worktree", "add", "--detach", str(temp_dir), "HEAD"],
            root,
        )
        if add.returncode:
            raise RuntimeError(add.stderr.strip() or "임시 worktree 생성 실패")
        worktree_added = True

        diff = run(["git", "diff", "--binary", "HEAD"], root)
        if diff.returncode:
            raise RuntimeError(diff.stderr.strip() or "현재 diff 수집 실패")
        if diff.stdout:
            applied = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=temp_dir,
                text=True,
                input=diff.stdout,
                capture_output=True,
            )
            if applied.returncode:
                raise RuntimeError(applied.stderr.strip() or "현재 diff 복제 실패")
        copy_untracked_files(root, temp_dir)

        baselines = {}
        for test in tests:
            if not (temp_dir / test).exists():
                results.append({
                    "test": test,
                    "pre_fix": "ERROR",
                    "classification": "inconclusive (test path missing)",
                    "exit_code": None,
                    "output": "test path does not exist in current snapshot",
                })
                continue
            argv = command_for_test(command, test)
            baseline = execute_test(argv, temp_dir, timeout)
            baselines[test] = (argv, baseline)
            if baseline["exit_code"] != 0:
                results.append({
                    "test": test,
                    "pre_fix": "NOT RUN",
                    "classification": "inconclusive (fixed baseline failed)",
                    "exit_code": baseline["exit_code"],
                    "output": baseline["output"],
                })
        for source in sources:
            exists = run(["git", "cat-file", "-e", f"{base}:{source}"], temp_dir)
            target = temp_dir / source
            if exists.returncode == 0:
                checkout = run(["git", "checkout", base, "--", source], temp_dir)
                if checkout.returncode:
                    raise RuntimeError(checkout.stderr.strip() or f"base source 복원 실패: {source}")
            elif target.exists():
                target.unlink() if target.is_file() or target.is_symlink() else shutil.rmtree(target)

        for test in tests:
            if test not in baselines or baselines[test][1]["exit_code"] != 0:
                continue
            argv = baselines[test][0]
            completed = execute_test(argv, temp_dir, timeout)
            if completed["exit_code"] is None:
                results.append({
                    "test": test,
                    "pre_fix": "ERROR",
                    "classification": "inconclusive (timeout)",
                    "exit_code": None,
                    "output": completed["output"],
                })
                continue
            passed = completed["exit_code"] == 0
            results.append({
                "test": test,
                "pre_fix": "PASS" if passed else "FAIL",
                "classification": (
                    "not regression (new-logic guard)"
                    if passed
                    else "regression test (catches bug)"
                ),
                "exit_code": completed["exit_code"],
                "output": completed["output"],
            })
    finally:
        if worktree_added:
            warning = remove_worktree(root, temp_dir)
            if warning:
                cleanup_warnings.append(warning)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)

    after = git_output(root, "status", "--porcelain=v1", "-uall")
    results.sort(key=lambda item: tests.index(item["test"]))
    return {
        "base": base,
        "command": command,
        "sources": sources,
        "tests": results,
        "worktree_unchanged": before == after,
        "cleanup_warnings": cleanup_warnings,
        "conclusive": all(
            not item["classification"].startswith("inconclusive") for item in results
        ),
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--base", choices=("HEAD", "merge-base"), default="merge-base")
    parser.add_argument("--base-ref", help="merge-base 상대 ref (기본 origin/main)")
    parser.add_argument("--command", required=True, help="{test} placeholder 필수")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("tests", nargs="+")
    return parser


def main():
    args = build_parser().parse_args()
    try:
        root = repo_root(args.project_dir)
        tests = validate_relative_paths(root, args.tests, "test")
        sources = validate_relative_paths(root, args.source, "source")
        if args.timeout <= 0:
            raise RuntimeError("--timeout은 1초 이상이어야 합니다")
        base = resolve_base(root, args.base, args.base_ref)
        result = verify(root, tests, sources, base, args.command, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_markdown(result))
        return (
            0
            if result["worktree_unchanged"]
            and not result["cleanup_warnings"]
            and result["conclusive"]
            else 2
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: interrupted; temporary worktree cleanup attempted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
