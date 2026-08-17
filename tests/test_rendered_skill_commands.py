"""렌더된 SKILL.md 가 **존재하지 않는 명령**을 안내하지 않는지 검사한다.

없는 명령을 안내하면 사용자는 쳐도 아무 일이 안 일어나고, 모델은 안내를 따르지 못해
결국 로그를 손으로 뒤진다. 손 탐색에는 프로젝트 스코핑이 없다(이슈 #95).

이 검사가 필요한 이유는 같은 실수가 **두 번** 났기 때문이다: `/fw-claude`·`/continue-claude`
가 `handoff.py` 의 힌트 문구와 `build.sh` 의 `DEEP_RECOVERY` 렌더값 **양쪽**에 있었고,
한쪽만 고쳤다. 같은 사실이 여러 곳에 있으면 사람 눈으로는 반드시 하나를 놓친다.

그 뒤로 다시 두 번 났다.

- PR #105: 스킬 다섯을 저장소에서 빼면서 `docs/overview.html` 을 놓쳤다. README 가 "그림이
  있는 설계 개요"로 링크하는 문서라, 따라간 사람은 **없는 명령의 사용법**을 읽게 된다.
  원인은 참조를 훑은 grep 이 `--include` 로 `.html` 을 빼놨던 것.
- 같은 PR: **이 파일의 회귀 가드 자체도** 확장자를 `{md, py, sh, json}` 으로 걸러
  `.html` 을 안 보고 있었다. 이 실수를 막으려고 만든 가드가 같은 맹점을 갖고 있었다.

그래서 이제 **확장자로 거르지 않는다.** 텍스트로 읽히는 파일은 전부 본다.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "core" / "skills"
RENDERED = [ROOT / "plugins" / "harness" / "skills", ROOT / "plugins" / "codex" / "skills"]

# 백틱으로 감싼 슬래시 명령만 본다: `/fw`, `/memory-update`.
# 경로(`/Users/x`, `~/.codex/sessions`)는 이름 뒤에 닫는 백틱이 바로 오지 않아 안 잡힌다.
COMMAND = re.compile(r"`/([a-z][a-z0-9-]*)`")

# 스킬이 아니지만 실제로 존재하는 것들 — 호스트 툴의 내장 명령.
BUILTIN = {"clear", "hooks", "plugin", "compact", "help", "config", "codex"}

# 문서용: Markdown 백틱과 HTML <code> 를 둘 다 받는다. overview.html 이 <code> 를 쓴다.
DOC_COMMAND = re.compile(r"(?:`|<code>)/([a-z][a-z0-9-]*)(?:`|</code>)")


def _skill_names():
    return {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}


class RenderedSkillCommandTest(unittest.TestCase):
    def test_every_slash_command_in_rendered_skills_exists(self):
        known = _skill_names() | BUILTIN
        unknown = []
        for base in RENDERED:
            for path in base.rglob("SKILL.md"):
                for name in COMMAND.findall(path.read_text(encoding="utf-8")):
                    if name not in known:
                        unknown.append(f"{path.relative_to(ROOT)}: /{name}")

        self.assertEqual(
            [], unknown,
            "존재하지 않는 명령을 안내하고 있다 — 스킬을 추가했거나 이름을 바꿨다면 "
            f"양쪽 어댑터를 함께 확인하라. 알려진 스킬: {sorted(known)}",
        )

    def test_the_two_names_that_slipped_through_twice_are_gone(self):
        """회귀 가드. 이 이름들은 한 번도 존재한 적 없는데 두 곳에 적혀 있었다.

        사용자에게 나가는 것만 본다(core·plugins·docs·build.sh·README). `tests/` 는 제외 —
        "이 이름이 안 나와야 한다" 를 단언하려면 테스트는 이름을 적을 수밖에 없다.
        """
        targets = [ROOT / "core", ROOT / "plugins", ROOT / "docs"]
        files = [p for base in targets for p in base.rglob("*") if p.is_file()]
        files += [ROOT / "build.sh", ROOT / "README.md", ROOT / "README.ko.md"]

        offenders = []
        for path in files:
            # ⚠️ 확장자로 거르지 않는다. 예전엔 {md, py, sh, json} 만 봤고 .html 을 놓쳤다.
            # 읽히면 본다 — 바이너리는 UnicodeDecodeError 로 알아서 빠진다.
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for dead in ("/fw-claude", "/continue-claude"):
                if dead in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {dead}")

        self.assertEqual([], offenders)


class UserFacingDocCommandTest(unittest.TestCase):
    """사용자가 읽는 문서가 **존재하지 않는 스킬**을 안내하지 않는지.

    위 검사는 렌더된 SKILL.md 만 본다. 그런데 사람이 실제로 먼저 읽는 건 README 와
    `docs/` 다. PR #105 에서 스킬 다섯을 뺐을 때 `docs/overview.html` 이 그대로 남아
    그 다섯을 설치된 기능으로 소개하고 있었다.

    HTML 은 `<code>/name</code>`, Markdown 은 `` `/name` `` 으로 쓴다 — 둘 다 잡는다.
    """

    # 스킬이 아니지만 실제로 존재하는 것 — 호스트 툴 내장 명령.
    ALLOWED = BUILTIN

    def _doc_files(self):
        paths = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md",
                 ROOT / "README.md", ROOT / "README.ko.md"]
        for base in ("docs", "project-template"):
            paths += sorted((ROOT / base).rglob("*"))
        return [p for p in paths if p.is_file() and p.suffix in {".md", ".html"}]

    def test_docs_never_advertise_a_skill_that_does_not_exist(self):
        known = _skill_names() | self.ALLOWED
        unknown = []
        for path in self._doc_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name in DOC_COMMAND.findall(text):
                if name not in known:
                    unknown.append(f"{path.relative_to(ROOT)}: /{name}")

        self.assertEqual(
            [], unknown,
            "사용자가 읽는 문서가 없는 스킬을 안내하고 있다 — 스킬을 빼거나 이름을 바꿨다면 "
            f"README·docs 도 같이 고쳐야 한다. 알려진 스킬: {sorted(known)}",
        )


if __name__ == "__main__":
    unittest.main()
