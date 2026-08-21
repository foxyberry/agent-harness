#!/usr/bin/env python3
"""
세션 트랜스크립트(.jsonl) → 회고 입력용 압축 마크다운.
Claude Code 와 Codex rollout(`~/.codex/sessions/.../rollout-*.jsonl`) 두 포맷 모두 자동 감지·지원.

회고에 필요한 신호만 남긴다:
  - user 발화 전체 (지적·결정·피드백 — 가장 중요)
  - assistant 텍스트 (결론/판단, 길면 절단)
  - 도구 사용은 한 줄 요약만 (Edit/Write 대상 파일, Bash 명령 첫 줄)
도구 결과(tool_result) 본문은 버린다 — 여기가 용량의 대부분(수 MB~수십 MB).

사용:
  python3 compact_transcript.py <transcript.jsonl>        # stdout 으로 출력
  python3 compact_transcript.py <transcript.jsonl> -o out.md
  python3 compact_transcript.py <transcript.jsonl> --require-attributed-user  # 회고용 strict
"""
import argparse
import json
import os
import sys
from collections import namedtuple

ASSIST_MAX = 600  # assistant 텍스트 1개 절단 길이


def _text_blocks(content):
    """content(str|list) 에서 (kind, text) 리스트 추출."""
    out = []
    if isinstance(content, str):
        out.append(("text", content))
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                out.append(("text", b.get("text", "")))
            elif t == "tool_use":
                name = b.get("name", "")
                inp = b.get("input", {}) or {}
                if name in ("Edit", "Write", "MultiEdit", "Read", "NotebookEdit"):
                    out.append(("tool", f"{name}({inp.get('file_path', '')})"))
                elif name == "Bash":
                    cmd = (inp.get("command", "") or "").splitlines()
                    out.append(("tool", f"Bash: {cmd[0][:80] if cmd else ''}"))
                else:
                    out.append(("tool", name))
    return out


# 사용자가 친 것으로 인정하는 origin. 이 밖은 도구·시스템이 넣은 것이다.
HUMAN_PROMPT_SOURCES = {"typed", "queued", "suggestion_accepted"}

# origin 신호가 없는 옛 트랜스크립트용 폴백. 주입된 턴은 이걸로 **시작**한다.
# 시작 여부만 보므로, 이 마커를 본문에서 얘기하는 정상 발화는 안 죽는다.
#
# ⚠️ 개별 태그가 아니라 **계열 접두사**다. 처음엔 태그를 하나씩 적었는데 `<command-message>`
# 를 빠뜨렸다(실측 corpus 에 6건). 같은 계열은 변형이 계속 생긴다 — command-name/message/args,
# local-command-stdout/stderr/caveat, bash-input/stdout/stderr. 계열로 잡으면 새 변형도 덮는다.
# 사람이 친 메시지가 이런 태그로 **시작**하는 일은 사실상 없다.
_INJECTED_HEADS = (
    "<command-", "<local-command-", "<bash-",
    "<task-notification>", "<system-reminder>",
    "Base directory for this skill",   # 스킬 본문 주입 — 태그가 아니라 평문으로 시작한다
)


Turn = namedtuple("Turn", "role blocks provenance evidence")


def _claude_user_provenance(d, text):
    """이 user 턴이 **사람이 친 것**인가.

    Claude 트랜스크립트의 `role: "user"` 에는 사람 입력만 오지 않는다. 도구 알림
    (`<task-notification>`), 슬래시 명령 확장(`<command-name>`·`<local-command-stdout>`),
    시스템 리마인더, 그리고 **스킬 본문**이 같은 자리에 온다.

    회고 재료로는 치명적이다 — 스킬 본문이 "사용자가 한 말" 로 들어가면, 회고가 **하네스
    자신의 규칙**을 새 교훈으로 뽑아 승격 후보로 올린다. 이미 우리 문체라 진짜 교훈보다
    더 그럴듯해 보인다. 실측: 한 트랜스크립트에서 USER 블록 9개 중 6개가 주입이었다.

    ## 왜 양성 선택 하나로 안 끝나는가

    최근 트랜스크립트는 `origin: {kind: "human", promptSource: "typed"}` 를 달고 온다.
    그걸로 고르면 깨끗하다. 그런데 이 프로젝트 46개 중 **40개에 그 필드가 아예 없다** —
    필드가 생기기 전 파일들이다. 엄격하게 걸면 그 40개에서 사용자 발화가 **0건**이 되고,
    "회고할 게 없었다" 와 구별이 안 된다. 이 저장소가 계속 걸리는 실패 모드다.

    그래서 **파일이 아니라 레코드 단위로** 판단한다 — origin 이 붙어 있으면 그걸 믿고,
    없으면 마커로 거른다. 폴백을 썼다는 건 호출자가 알린다(compact 참조).
    """
    # ⚠️ promptSource 는 **레코드 최상위**에 있다. origin 안이 아니다(실측: origin.promptSource
    # 는 2616건 전부 None — 거기서 읽으면 죽은 조건이다). 그리고 이게 가장 정확한 신호다:
    # sdk 40건·system 22건이 origin.kind 없이 오므로, origin 만 보면 그것들이 마커 폴백으로
    # 떨어지고 평문이라 사람 입력으로 통과한다. 자동화가 넣은 프롬프트가 회고 재료가 된다.
    src = d.get("promptSource")
    if src is not None:
        return ("attributed" if src in HUMAN_PROMPT_SOURCES else "nonhuman",
                "promptSource", False)
    origin = d.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return ("attributed" if origin["kind"] == "human" else "nonhuman",
                "origin", False)
    if d.get("isMeta"):
        return "nonhuman", "isMeta", False
    # `in` 이 아니라 `startswith` 다. 주입된 턴은 마커로 **시작**한다. `in` 으로 보면
    # 마커를 얘기하는 정상 발화("압축기가 <task-notification> 을 왜 거르지?")까지 죽는다.
    head = text.lstrip()
    if head.startswith(_INJECTED_HEADS):
        return "nonhuman", "marker", True
    return "unattributed", "marker", True


def _claude_msg(d):
    """Claude Code 레코드 → Turn 또는 None.

    provenance 는 user 레코드에만 attributed/unattributed/nonhuman 중 하나다. strict 회고가
    파일 전체가 아니라 레코드 구간 단위로 선택할 수 있게 분류를 이 경계에서 버리지 않는다.
    """
    m = d.get("message")
    if not isinstance(m, dict):
        return None
    blocks = _text_blocks(m.get("content"))
    if m.get("role") != "user":
        role = m.get("role")
        return Turn(role, blocks, None, None) if role == "assistant" else None
    user_texts = [t for k, t in blocks if k == "text" and t.strip()]
    # tool_result 도 Claude JSONL 에서는 role=user 다. 회고 텍스트가 없고 아래 출력에서도
    # 버리는 레코드이므로 provenance 판정 대상이 아니다. 이걸 fallback 으로 세면 거의 모든
    # 도구 사용 세션이 strict 회고에서 거부된다.
    if not user_texts:
        return None
    text = " ".join(user_texts)
    provenance, evidence, _fallback = _claude_user_provenance(d, text)
    return Turn("user", blocks, provenance, evidence)


def _codex_user_message(d):
    """Codex rollout 의 **실제 사용자 발화** — `event_msg.user_message` 의 `message`.

    ⚠️ `response_item` 의 `role: "user"` 를 사용자 발화로 읽으면 안 된다. Codex 는 주입한
    컨텍스트도 거기에 `role: "user"` 로 넣는다 — `<user_action>` 래퍼, 환경 정보, 프로젝트의
    AGENTS.md 본문 같은 것들. 8개 세션을 실측하니 그 17건 중 **8건이 주입**이었다.

    회고 재료로는 치명적이다. AGENTS.md 전문이 "사용자가 한 말" 로 들어가면, 회고가 그걸
    새 교훈으로 뽑아 메모리 승격 후보로 올린다 — 프로젝트의 기존 규칙이 사용자 피드백으로
    둔갑해 규칙이 자기복제한다.

    Codex 는 둘을 구분해 준다. 실제 입력은 `event_msg.user_message` 에만 온다.
    """
    if d.get("type") != "event_msg":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "user_message":
        return None
    text = p.get("message")
    if not isinstance(text, str) or not text.strip():
        return None
    return Turn("user", [("text", text)], "attributed", "codex-channel")


def _codex_msg(d):
    """Codex rollout .jsonl: {"type":"response_item","payload":{"type":"message",
    "role","content":[{"type":"input_text"|"output_text","text"}]}} → (role, blocks).
    tool(function_call) 항목은 v1 에서 생략 — user/assistant 텍스트만 추출."""
    if d.get("type") != "response_item":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "message":
        return None
    # assistant 만 본다. role="user" 는 주입이 섞이므로 _codex_user_message 가 따로 맡고,
    # role="developer" 는 시스템 지시라 회고 재료가 아니다.
    if p.get("role") != "assistant":
        return None
    blocks = [
        ("text", b.get("text", ""))
        for b in (p.get("content") or [])
        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")
    ]
    return Turn("assistant", blocks, None, None)


def iter_turns(path, stats=None):
    """JSONL 을 정책과 무관한 Turn 스트림으로 파싱한다.

    nonhuman 턴도 버리지 않는다. 해당 턴을 숨길지, 신뢰 구간을 끊을지는 소비 정책의
    책임이다. ``stats`` 는 전체 줄 수와 marker fallback 사용 여부를 호출자에게 돌려준다.
    """
    if stats is None:
        stats = {}
    stats.update(lines=0, used_fallback=False)
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            stats["lines"] += 1
            try:
                d = json.loads(ln)
            except Exception:
                continue
            turn = _claude_msg(d)
            if turn is None:
                turn = _codex_user_message(d)
            if turn is None:
                turn = _codex_msg(d)
            if turn is None:
                continue
            if turn.evidence == "marker":
                stats["used_fallback"] = True
            yield turn


def select_recovery(turns, stats=None):
    """일반 CLI 용 best-effort 정책: 주입만 빼고 출처 불명 사용자 턴은 보존한다."""
    for turn in turns:
        if turn.provenance != "nonhuman":
            yield turn


def select_attributed(turns, stats=None):
    """회고용 fail-closed 정책: 확인된 사용자 턴에서 시작한 구간만 보존한다.

    단순 알림·메타 nonhuman 턴은 투명하지만, 출처가 명시된 자동화 턴과 출처 불명 사용자
    턴은 뒤 assistant 응답도 신뢰할 수 없으므로 구간 신뢰를 해제한다.
    """
    if stats is None:
        stats = {}
    stats.update(attributed_users=0, unattributed_users=0, nonhuman_users=0)
    trusted_segment = False
    for turn in turns:
        if turn.role == "user":
            if turn.provenance == "attributed":
                trusted_segment = True
                stats["attributed_users"] += 1
                yield turn
            elif turn.provenance == "unattributed":
                stats["unattributed_users"] += 1
                trusted_segment = False
            elif turn.provenance == "nonhuman":
                stats["nonhuman_users"] += 1
                if turn.evidence in ("promptSource", "origin"):
                    trusted_segment = False
            continue
        if turn.role == "assistant" and trusted_segment:
            yield turn


def render(turns):
    """선택된 Turn 스트림을 기존 압축 마크다운 형식으로 렌더한다."""
    md = []
    for turn in turns:
        role, blocks = turn.role, turn.blocks
        if role == "user":
            for kind, txt in blocks:
                if kind == "text" and txt.strip():
                    md.append(f"\n### 👤 USER\n{txt.strip()}")
        elif role == "assistant":
            texts = [t for k, t in blocks if k == "text" and t.strip()]
            tools = [t for k, t in blocks if k == "tool"]
            if texts:
                joined = "\n".join(texts).strip()
                if len(joined) > ASSIST_MAX:
                    joined = joined[:ASSIST_MAX] + " …(절단)"
                md.append(f"\n**🤖 ASSISTANT:** {joined}")
            if tools:
                md.append(f"  ↳ 도구: {', '.join(tools[:8])}" + (" …" if len(tools) > 8 else ""))
    return "\n".join(md)


def compact(path, require_attributed_user=False):
    """트랜스크립트를 압축한다.

    `require_attributed_user=True` 는 메모리 회고용 fail-closed 모드다. 출처 불명 user 턴과
    그 뒤 assistant 구간만 버리고, 양성 귀속 user 턴에서 시작한 구간은 유지한다. 양성 귀속
    user 턴이 하나도 없으면 전체를 비운다. 기본값 False 는 일반 CLI 호환 모드다.
    """
    parse_stats = {}
    policy_stats = {}
    turns = iter_turns(path, parse_stats)
    if require_attributed_user:
        selected = select_attributed(turns, policy_stats)
    else:
        selected = select_recovery(turns, policy_stats)
    out = render(selected)
    if parse_stats["used_fallback"] and not require_attributed_user:
        # 조용히 퇴화하지 않는다. 마커 폴백은 origin 기반 선택보다 약하므로, 이 압축본으로
        # 회고하는 쪽이 "덜 걸러졌을 수 있다" 를 알아야 한다.
        sys.stderr.write(
            "[compact] origin 없는 옛 레코드가 있어 마커 기반으로 걸렀다 — 주입이 남았을 수 있다\n")
    if require_attributed_user and policy_stats["attributed_users"] == 0:
        sys.stderr.write("[compact] 회고 거부: 출처가 확실한 user 턴이 없다\n")
        return "", parse_stats["lines"]
    if require_attributed_user:
        sys.stderr.write(
            "[compact] strict user 턴: "
            f"귀속 {policy_stats['attributed_users']}, "
            f"출처 불명 제외 {policy_stats['unattributed_users']}, "
            f"주입 제외 {policy_stats['nonhuman_users']}\n")
    return out, parse_stats["lines"]


def main():
    parser = argparse.ArgumentParser(description="Claude/Codex transcript compactor")
    parser.add_argument("transcript")
    parser.add_argument("-o", "--output")
    parser.add_argument("--require-attributed-user", action="store_true")
    # 기존 실행성 계약: 무인자 호출은 훅의 "차단" 의미로도 쓰이는 exit 2를 피한다.
    # 알 수 없는 옵션은 아래 parse_args 가 exit 2로 fail-closed 처리한다.
    if len(sys.argv) == 1:
        parser.print_usage(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()
    out, n = compact(args.transcript, require_attributed_user=args.require_attributed_user)
    if args.require_attributed_user and not out.strip():
        if args.output and os.path.exists(args.output):
            os.remove(args.output)
        sys.exit(3)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(out)
        sys.stderr.write(f"[compact] {n} 줄 → {args.output} ({len(out)}자 ~{len(out)//4} 토큰)\n")
    else:
        print(out)
        sys.stderr.write(f"[compact] {n} 줄 → {len(out)}자 (~{len(out)//4} 토큰)\n")


if __name__ == "__main__":
    main()
