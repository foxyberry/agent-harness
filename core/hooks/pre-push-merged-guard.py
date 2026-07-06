#!/usr/bin/env python3
"""
pre-push 가드 hook (PreToolUse / Bash) — 머지된 PR 의 브랜치에 후속 작업을 push 하는 실수를 차단한다.

배경: PR 이 머지되면 그 브랜치는 죽은 브랜치다. 거기 push 한 커밋은 새 PR 을 따로 열지 않는 한
main 에 영영 안 닿는다("배포됐으니 새 커밋 올리면 됨"은 OPEN 일 때만 참).

동작:
- Bash 명령이 `git push` 이고(브랜치 삭제 push 제외), 현재 브랜치의 PR state == MERGED 면 deny.
- 그 외(푸시 아님 / PR 없음 / OPEN / gh·네트워크 실패)는 모두 통과(fail-open) — 정상 작업을 막지 않는다.

deny 시 안내: 최신 origin/main 에서 새 브랜치 + 새 PR, main 에 없는 델타만 cherry-pick.

이 hook 은 툴 무관 generic — git/gh 만 쓰고 프로젝트 특정 로직·경로가 없다.
"""
import json
import re
import subprocess
import sys


def _allow():
    sys.exit(0)


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _git(args):
    return subprocess.run(
        ["git"] + args, capture_output=True, text=True, timeout=5
    ).stdout.strip()


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        _allow()

    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd:
        _allow()

    # git push 인지 (브랜치 삭제 push 는 정상 정리이므로 제외)
    if not re.search(r"\bgit\s+push\b", cmd):
        _allow()
    if re.search(r"\bgit\s+push\b.*(--delete|--prune|\s-d\b)", cmd):
        _allow()

    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if not branch or branch == "HEAD":
            _allow()

        # 현재 브랜치의 PR state 조회 (없으면 비어있음 → 통과)
        state = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "state", "-q", ".state"],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip().upper()
    except Exception:
        _allow()  # gh/네트워크/타임아웃 → 막지 않음

    if state == "MERGED":
        _deny(
            f"브랜치 '{branch}' 의 PR 은 이미 MERGED 입니다. 머지된 브랜치에 push 하면 "
            f"그 커밋은 새 PR 없이는 main 에 닿지 않습니다.\n"
            f"→ 최신 origin/main 에서 새 브랜치를 만들고, main 에 없는 델타만 cherry-pick 한 뒤 새 PR 을 여세요. "
            f"(이 가드를 우회해야 하면 사용자에게 확인받으세요.)"
        )

    _allow()


if __name__ == "__main__":
    main()
