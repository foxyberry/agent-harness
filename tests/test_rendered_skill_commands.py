"""렌더된 SKILL.md 가 **존재하지 않는 명령**을 안내하지 않는지 검사한다.

없는 명령을 안내하면 사용자는 쳐도 아무 일이 안 일어나고, 모델은 안내를 따르지 못해
결국 로그를 손으로 뒤진다. 손 탐색에는 프로젝트 스코핑이 없다(이슈 #95).

이 검사가 필요한 이유는 같은 실수가 **두 번** 났기 때문이다: `/fw-claude`·`/continue-claude`
가 `handoff.py` 의 힌트 문구와 `build.sh` 의 `DEEP_RECOVERY` 렌더값 **양쪽**에 있었고,
한쪽만 고쳤다. 같은 사실이 여러 곳에 있으면 사람 눈으로는 반드시 하나를 놓친다.
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
            if path.suffix not in {".md", ".py", ".sh", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for dead in ("/fw-claude", "/continue-claude"):
                if dead in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {dead}")

        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
