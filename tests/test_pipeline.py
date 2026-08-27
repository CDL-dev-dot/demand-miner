import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_stage(filename, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = load_stage("01_collect.py", "stage_collect")
extract = load_stage("02_extract.py", "stage_extract")
report = load_stage("04_report.py", "stage_report")


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.app = {
            "trackId": 123,
            "trackName": "Shared Meds",
            "primaryGenreName": "Medical",
            "trackViewUrl": "https://apps.apple.com/us/app/id123",
            "averageUserRating": 4.1,
            "userRatingCount": 900,
        }
        self.entry = {
            "id": {"label": "review-1"},
            "author": {"name": {"label": "Reviewer One"}},
            "updated": {"label": "2026-08-20T10:30:00-07:00"},
            "im:rating": {"label": "2"},
            "im:version": {"label": "3.4.0"},
            "title": {"label": "Family sharing is broken"},
            "content": {"label": "My partner never sees medication updates."},
            "link": {"attributes": {"href": "https://itunes.apple.com/review?id=review-1"}},
            "im:voteSum": {"label": "8"},
            "im:voteCount": {"label": "10"},
        }

    def test_parse_review_entry_when_rating_allowed_returns_normalized_private_row(self):
        row = collect.parse_review_entry(
            self.entry,
            self.app,
            "us",
            ["pet medication", "family medication"],
            {1, 2, 3},
        )

        self.assertEqual("us:123:review-1", row["id"])
        self.assertEqual("app_store_review", row["source"])
        self.assertEqual("Shared Meds", row["app_name"])
        self.assertEqual(2, row["rating"])
        self.assertEqual("Family sharing is broken", row["title"])
        self.assertEqual("My partner never sees medication updates.", row["selftext"])
        self.assertEqual(["family medication", "pet medication"], row["matched_terms"])
        self.assertNotIn("author", row)
        self.assertEqual(16, len(row["reviewer_id"]))
        self.assertGreater(row["created_utc"], 0)

    def test_parse_review_entry_when_rating_disallowed_returns_none(self):
        self.entry["im:rating"]["label"] = "5"

        row = collect.parse_review_entry(self.entry, self.app, "us", ["pet medication"], {1, 2, 3})

        self.assertIsNone(row)


class ExtractTests(unittest.TestCase):
    def test_enrich_aggregates_reviewers_source_apps_and_payment_evidence(self):
        needs = [
            {
                "need_summary": "Shared medication updates",
                "reviewer_id": "reviewer-a",
                "source_app_id": 1,
                "source_app_name": "Meds One",
                "source_rating": 2,
                "created_utc": 1767225600.0,
                "permalink": "https://example.com/review/1",
                "pay_signal": "I pay for premium and sharing still fails.",
                "emotion": 5,
                "frequency": "daily",
            },
            {
                "need_summary": "Shared medication updates",
                "reviewer_id": "reviewer-b",
                "source_app_id": 2,
                "source_app_name": "Meds Two",
                "source_rating": 1,
                "created_utc": 1772323200.0,
                "permalink": "https://example.com/review/2",
                "pay_signal": None,
                "emotion": 4,
                "frequency": "daily",
            },
        ]
        clusters = [
            {
                "name": "Shared medication management",
                "need_statement": "Care teams need medication updates to sync reliably.",
                "member_idx": [0, 1],
                "appstore_keywords": ["shared medication tracker"],
            }
        ]

        rows = extract.enrich(clusters, needs)

        self.assertEqual(2, rows[0]["distinct_reviewers"])
        self.assertEqual(2, rows[0]["source_app_count"])
        self.assertEqual(["Meds One", "Meds Two"], rows[0]["source_apps"])
        self.assertEqual(1, rows[0]["payment_signals"])
        self.assertEqual(1.5, rows[0]["avg_source_rating"])


class ReportTests(unittest.TestCase):
    def test_deterministic_scores_uses_review_evidence(self):
        cluster = {
            "distinct_reviewers": 3,
            "payment_signals": 1,
            "first_seen": "2026-01-01",
            "last_seen": "2026-03-01",
            "appstore": {"top_apps": [], "swarm": False},
        }

        demand, _, _, _ = report.deterministic_scores(cluster)

        self.assertEqual(6, demand)


if __name__ == "__main__":
    unittest.main()
