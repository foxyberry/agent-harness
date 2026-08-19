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
"""
import json
import sys

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


def _claude_msg(d):
    """Claude Code .jsonl: {"message": {"role","content"}} → (role, blocks)."""
    m = d.get("message")
    if isinstance(m, dict):
        return m.get("role"), _text_blocks(m.get("content"))
    return None, None


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
        return None, None
    p = d.get("payload") or {}
    if p.get("type") != "user_message":
        return None, None
    text = p.get("message")
    if not isinstance(text, str) or not text.strip():
        return None, None
    return "user", [("text", text)]


def _codex_msg(d):
    """Codex rollout .jsonl: {"type":"response_item","payload":{"type":"message",
    "role","content":[{"type":"input_text"|"output_text","text"}]}} → (role, blocks).
    tool(function_call) 항목은 v1 에서 생략 — user/assistant 텍스트만 추출."""
    if d.get("type") != "response_item":
        return None, None
    p = d.get("payload") or {}
    if p.get("type") != "message":
        return None, None
    # assistant 만 본다. role="user" 는 주입이 섞이므로 _codex_user_message 가 따로 맡고,
    # role="developer" 는 시스템 지시라 회고 재료가 아니다.
    if p.get("role") != "assistant":
        return None, None
    blocks = [
        ("text", b.get("text", ""))
        for b in (p.get("content") or [])
        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")
    ]
    return p.get("role"), blocks


def compact(path):
    # 라인 단위 스트리밍 — read().splitlines() 는 전체 문자열 + 전체 리스트를 동시에 물어
    # 대용량(수십 MB) 트랜스크립트에서 피크 메모리가 2배가 된다. 한 줄씩만 필요하므로 iterate.
    md = []
    n = 0
    # errors="replace": 트랜스크립트 한 줄에 깨진 바이트가 있어도 잡 전체가 죽으면 안 된다.
    # 죽으면 그 세션은 이미 seen 처리돼 **영영 재시도되지 않는다**.
    # handoff.py 는 같은 파일을 세 곳에서 이미 이렇게 연다 — 여기만 빠져 있었다.
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            n += 1
            try:
                d = json.loads(ln)
            except Exception:
                continue
            role, blocks = _claude_msg(d)
            if role is None:
                role, blocks = _codex_user_message(d)   # Codex 실제 사용자 발화
            if role is None:
                role, blocks = _codex_msg(d)            # Codex assistant
            if role is None:
                continue
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
    return "\n".join(md), n


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: compact_transcript.py <transcript.jsonl> [-o out.md]")
    path = sys.argv[1]
    out, n = compact(path)
    if "-o" in sys.argv:
        oi = sys.argv.index("-o")
        if oi + 1 >= len(sys.argv):
            sys.exit("usage: compact_transcript.py <transcript.jsonl> [-o out.md]")
        dst = sys.argv[oi + 1]
        open(dst, "w", encoding="utf-8").write(out)
        sys.stderr.write(f"[compact] {n} 줄 → {dst} ({len(out)}자 ~{len(out)//4} 토큰)\n")
    else:
        print(out)
        sys.stderr.write(f"[compact] {n} 줄 → {len(out)}자 (~{len(out)//4} 토큰)\n")


if __name__ == "__main__":
    main()
