"""문서가 조용히 묻히지 않는지 검사한다.

`docs/` 에 파일을 하나 더 두는 건 쉽고, README 에 링크를 거는 건 잊기 쉽다. 링크가 없으면
그 문서는 **저장소를 clone 해서 트리를 훑는 사람에게만** 존재한다. 실제로 이 저장소에서
`decision-mining.md` 와 `public-release-audit.md` 가 그렇게 몇 달을 지냈다 — 지워진 것도,
틀린 것도 아니고, 그냥 아무 데서도 안 걸려 있었다.

두 가지를 고정한다.

1. `docs/` 의 모든 파일이 **README.md 와 README.ko.md 양쪽**에서 링크된다.
2. 두 README 가 **같은 문서 집합**을 건다. 한쪽만 고치면 번역본이 뒤처지는데, 그게
   이 저장소에서 실제로 반복된 실수다(같은 사실이 두 곳에 있으면 하나를 놓친다).

`docs/` 만 보는 이유: 여기가 자라는 곳이다. `project-template/` 아래는 대부분 문서가
아니라 **예시 데이터**(routes·rules·메모리 샘플)라, 전부 링크를 요구하면 데이터를 추가할
때마다 README 를 고쳐야 한다. 그래서 루트의 사람이 읽는 문서만 이름으로 못박는다.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
READMES = ["README.md", "README.ko.md"]

# 링크가 반드시 있어야 하는 루트 문서 — 이름으로 못박는다(자주 안 늘어난다).
ROOT_DOCS = ["AGENTS.md", "SECURITY.md"]

# 마크다운 링크의 목적지만 뽑는다: [글자](대상)
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")


def _linked_targets(readme_name):
    text = (ROOT / readme_name).read_text(encoding="utf-8")
    return {t.split("#", 1)[0] for t in LINK_TARGET.findall(text)}


def _doc_files():
    """`docs/` 아래 사람이 읽는 파일. 없으면 테스트가 공허하게 통과하므로 함께 확인한다."""
    return sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "docs").rglob("*")
        if p.is_file() and p.suffix in {".md", ".html"}
    )


class DocLinkCoverageTest(unittest.TestCase):
    def test_fixture_is_not_empty(self):
        """`docs/` 를 못 찾으면 아래 검사는 전부 공허하게 통과한다."""
        self.assertGreater(len(_doc_files()), 1, "docs/ 를 못 읽었다 — 아래 검사가 무의미해진다")

    def test_every_doc_is_linked_from_both_readmes(self):
        docs = _doc_files()
        missing = []
        for readme in READMES:
            linked = _linked_targets(readme)
            for doc in docs + ROOT_DOCS:
                if doc not in linked:
                    missing.append(f"{readme}: {doc}")

        self.assertEqual(
            [], missing,
            "README 가 링크하지 않는 문서가 있다 — 문서를 추가했으면 README.md 와 "
            "README.ko.md 의 문서 표에 **양쪽 다** 걸어야 한다. 안 걸면 그 문서는 "
            "트리를 훑는 사람에게만 존재한다.",
        )

    def test_both_readmes_link_the_same_docs(self):
        """한쪽만 고치면 번역본이 뒤처진다 — 같은 사실이 두 곳에 있으면 하나를 놓친다."""
        docs = set(_doc_files()) | set(ROOT_DOCS)
        en = _linked_targets("README.md") & docs
        ko = _linked_targets("README.ko.md") & docs

        self.assertEqual(
            en, ko,
            "두 README 가 거는 문서 집합이 다르다 — "
            f"영어만: {sorted(en - ko)} / 한국어만: {sorted(ko - en)}",
        )

    def test_linked_repo_paths_actually_exist(self):
        """죽은 링크도 문서를 잃는 방법이다 — 이름을 바꾸면 링크가 조용히 끊긴다."""
        dead = []
        for readme in READMES:
            for target in _linked_targets(readme):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if not (ROOT / target).exists():
                    dead.append(f"{readme}: {target}")

        self.assertEqual([], dead, "README 의 저장소 내부 링크가 깨졌다")


if __name__ == "__main__":
    unittest.main()
