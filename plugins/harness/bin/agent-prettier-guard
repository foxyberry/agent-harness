#!/usr/bin/env python3
"""
prettier-guard — main 기준으로 이미 prettier-clean 이 아닌 파일을 --write 후보에서 보호한다.

파괴적 작업은 하지 않는다. prettier 는 stdin 포맷 비교와 --check 명령 제안에만 사용하고,
실제 --write 는 실행하지 않는다.
"""
import argparse
import fnmatch
import json
import os
import shlex
import shutil
import subprocess


DEFAULT_EXTENSIONS = [
    ".css", ".graphql", ".gql", ".html", ".js", ".jsx", ".json", ".jsonc",
    ".less", ".md", ".mdx", ".mjs", ".scss", ".ts", ".tsx", ".vue", ".yaml", ".yml",
]


def _run(cmd, cwd, timeout=20, input_bytes=None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
    )


def _out(cmd, cwd, timeout=20):
    r = _run(cmd, cwd, timeout=timeout)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace").strip()


def _git_root(project_dir):
    root = _out(["git", "rev-parse", "--show-toplevel"], project_dir)
    return root or project_dir


def _default_base_ref(root):
    ref = _out(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], root)
    if ref:
        return ref
    for candidate in ("origin/main", "origin/master", "origin/develop"):
        if _run(["git", "rev-parse", "--verify", candidate], root).returncode == 0:
            return candidate
    return "origin/main"


def _load_config(root, explicit):
    path = explicit or os.path.join(root, ".claude", "memory", "prettier-guard.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _prettier_cmd(root, explicit):
    if explicit:
        return shlex.split(explicit)
    local = os.path.join(root, "node_modules", ".bin", "prettier")
    if os.path.exists(local):
        return [local]
    prettier = shutil.which("prettier")
    if prettier:
        return [prettier]
    return None


def _changed_files(root, base_ref, explicit_paths):
    if explicit_paths:
        return _dedupe([_normalize_path(p) for p in explicit_paths])
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "--cached"],
        ["git", "diff", "--name-only", "--diff-filter=ACMR"],
    ]
    paths = []
    for cmd in commands:
        raw = _out(cmd, root)
        if raw:
            paths.extend(raw.splitlines())
    return _dedupe([_normalize_path(p) for p in paths])


def _normalize_path(path):
    return path.strip().replace("\\", "/")


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _matches_any(path, patterns):
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _is_prettier_target(path, extensions):
    return os.path.splitext(path)[1].lower() in extensions


def _base_content(root, base_ref, path):
    r = _run(["git", "show", f"{base_ref}:{path}"], root)
    if r.returncode != 0:
        return None
    return r.stdout


def _base_prettier_clean(root, prettier_cmd, path, content):
    cmd = prettier_cmd + ["--stdin-filepath", path]
    r = _run(cmd, root, timeout=30, input_bytes=content)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace").strip()
        return {"ok": False, "clean": None, "error": err or "prettier failed"}
    return {"ok": True, "clean": r.stdout == content, "error": ""}


def _quote_paths(paths):
    return " ".join(shlex.quote(p) for p in paths)


def collect(project_dir, base_ref=None, prettier=None, paths=None, config=None):
    root = _git_root(os.path.abspath(project_dir))
    cfg = _load_config(root, config)
    base = base_ref or cfg.get("baseRef") or _default_base_ref(root)
    prettier_cmd = _prettier_cmd(root, prettier)
    extensions = set(cfg.get("extensions") or DEFAULT_EXTENSIONS)
    known_non_clean = set(cfg.get("knownNonClean") or [])
    exclude = list(cfg.get("exclude") or [])
    changed = _changed_files(root, base, paths or [])

    result = {
        "project_dir": root,
        "base_ref": base,
        "prettier_cmd": prettier_cmd,
        "config": cfg,
        "changed_files": changed,
        "safe_files": [],
        "protected_files": [],
        "skipped_files": [],
        "prettier_available": bool(prettier_cmd),
    }

    for path in changed:
        full = os.path.join(root, path)
        if not os.path.exists(full):
            result["skipped_files"].append({"path": path, "reason": "missing in working tree"})
            continue
        if _matches_any(path, exclude):
            result["skipped_files"].append({"path": path, "reason": "excluded by config"})
            continue
        if not _is_prettier_target(path, extensions):
            result["skipped_files"].append({"path": path, "reason": "not a prettier target extension"})
            continue
        if not prettier_cmd:
            result["protected_files"].append({"path": path, "reason": "prettier command unavailable"})
            continue
        if path in known_non_clean:
            result["protected_files"].append({"path": path, "reason": "known non-clean config"})
            continue
        content = _base_content(root, base, path)
        if content is None:
            result["safe_files"].append({"path": path, "reason": "new file at base"})
            continue
        check = _base_prettier_clean(root, prettier_cmd, path, content)
        if not check["ok"]:
            result["protected_files"].append({"path": path, "reason": check["error"]})
        elif check["clean"]:
            result["safe_files"].append({"path": path, "reason": f"clean at {base}"})
        else:
            result["protected_files"].append({"path": path, "reason": f"non-clean at {base}"})

    return result


def render(result):
    lines = []
    safe = [item["path"] for item in result["safe_files"]]
    protected = result["protected_files"]
    skipped = result["skipped_files"]
    prettier = result["prettier_cmd"]
    prettier_display = " ".join(shlex.quote(x) for x in prettier) if prettier else "(not found)"

    lines.append("prettier-guard 리포트")
    lines.append(f"project: {result['project_dir']}")
    lines.append(f"base: {result['base_ref']}")
    lines.append(f"prettier: {prettier_display}")
    lines.append("advisory-only: prettier --write 는 자동 실행하지 않음")
    lines.append("")

    lines.append(f"■ safe prettier 대상 ({len(safe)})")
    if safe:
        for item in result["safe_files"]:
            lines.append(f"  {item['path']}  ({item['reason']})")
        lines.append("")
        lines.append(f"  check-only 후보: {prettier_display} --check {_quote_paths(safe)}")
        lines.append(f"  safe-write 후보: {prettier_display} --write {_quote_paths(safe)}")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append(f"■ protected non-clean 대상 ({len(protected)})")
    if protected:
        for item in protected:
            lines.append(f"  {item['path']}  — {item['reason']}")
        lines.append("  처리: 전체 prettier --write 금지. 변경 주변만 수동 삽입하거나 파일 단위 포맷은 별도 리뷰.")
    else:
        lines.append("  (없음)")
    lines.append("")

    lines.append(f"■ skipped ({len(skipped)})")
    if skipped:
        for item in skipped:
            lines.append(f"  {item['path']}  — {item['reason']}")
    else:
        lines.append("  (없음)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="main 기준 non-clean prettier 파일 보호 리포트")
    ap.add_argument("--project-dir", default=None, help="대상 프로젝트 절대경로(기본: cwd)")
    ap.add_argument("--base-ref", default=None, help="비교 기준 ref(기본: origin/HEAD)")
    ap.add_argument("--prettier", default=None, help="prettier 명령(기본: local prettier 또는 PATH prettier)")
    ap.add_argument("--config", default=None, help="prettier-guard JSON 설정 경로")
    ap.add_argument("--json", action="store_true", help="사람용 리포트 대신 JSON 출력")
    ap.add_argument("--fail-on-protected", action="store_true", help="protected 파일이 있으면 exit 2")
    ap.add_argument("paths", nargs="*", help="명시 파일 목록(생략 시 base 대비 변경 파일)")
    args = ap.parse_args(argv)

    result = collect(
        args.project_dir or os.getcwd(),
        base_ref=args.base_ref,
        prettier=args.prettier,
        paths=args.paths,
        config=args.config,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    if args.fail_on_protected and result["protected_files"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
