import pathlib
import sys
import unittest
from unittest.mock import patch


SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import stale  # noqa: E402
import stale_resolve  # noqa: E402


def pr_event(number, will_close=False, closing_issues=None):
    return {
        "__typename": "CrossReferencedEvent",
        "willCloseTarget": will_close,
        "source": {
            "__typename": "PullRequest",
            "number": number,
            "url": f"https://example.test/pr/{number}",
            "merged": True,
            "mergedAt": "2026-01-02T03:04:05Z",
            "closingIssuesReferences": {
                "nodes": [
                    {
                        "number": issue,
                        "repository": {"nameWithOwner": "owner/repo"},
                    }
                    for issue in (closing_issues or [])
                ],
            },
        },
    }


class ResolveTests(unittest.TestCase):
    def test_exposes_will_close_and_preserves_true_across_duplicate_events(self):
        result = {"41": []}

        stale_resolve.add_merged_prs(
            result,
            41,
            [pr_event(55, will_close=True), pr_event(55, will_close=False)],
            "owner/repo",
        )

        self.assertEqual(
            result["41"],
            [{
                "pr": 55,
                "url": "https://example.test/pr/55",
                "merged_at": "2026-01-02T03:04:05Z",
                "will_close": True,
            }],
        )

    def test_non_cross_reference_connection_is_not_a_close_declaration(self):
        event = {
            "__typename": "ConnectedEvent",
            "subject": pr_event(56)["source"],
        }
        result = {"42": []}

        stale_resolve.add_merged_prs(result, 42, [event], "owner/repo")

        self.assertFalse(result["42"][0]["will_close"])

    def test_closing_reference_preserves_declaration_after_merge(self):
        result = {"21": []}

        stale_resolve.add_merged_prs(
            result,
            21,
            [pr_event(22, will_close=False, closing_issues=[21])],
            "owner/repo",
        )

        self.assertTrue(result["21"][0]["will_close"])


class ReportTests(unittest.TestCase):
    def test_close_declarations_sort_first_and_labels_are_rendered(self):
        candidates = [
            {"issue": 1, "title": "mention", "age_days": 200, "url": "issue/1"},
            {"issue": 2, "title": "declaration", "age_days": 100, "url": "issue/2"},
        ]
        linked = {
            "1": [{
                "pr": 10, "url": "pr/10", "merged_at": "2026-01-01T00:00:00Z",
                "will_close": False,
            }],
            "2": [{
                "pr": 20, "url": "pr/20", "merged_at": "2026-01-02T00:00:00Z",
                "will_close": True,
            }],
        }

        with (
            patch.object(stale, "partition", return_value=(candidates, [], 2)),
            patch.object(stale, "resolve", return_value=linked),
        ):
            result = stale.judge("owner/repo", None, set(), 500)

        self.assertEqual([row["issue"] for row in result["closable"]], [2, 1])
        report = stale.render_text(result)
        self.assertIn("[닫기 선언] PR #20", report)
        self.assertIn("[단순 언급] PR #10", report)


if __name__ == "__main__":
    unittest.main()
