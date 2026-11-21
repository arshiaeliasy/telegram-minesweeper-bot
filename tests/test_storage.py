"""تست‌های ذخیره‌سازی آمار (تک‌نفره + دوئل گروهی)."""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import StatsStorage  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent
GROUP = -100987


class StatsStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = TMP_ROOT / f"stats-{uuid.uuid4().hex}.json"
        self.storage = StatsStorage(self.path)

    def tearDown(self) -> None:
        for candidate in (self.path, Path(str(self.path) + ".tmp")):
            candidate.unlink(missing_ok=True)

    def record_duel(self, winner=(1, "آرش"), loser=(2, "سارا"), level="easy", seconds=30, at=None):
        return self.storage.record_duel(
            chat_id=GROUP,
            winner_id=winner[0],
            winner_name=winner[1],
            loser_id=loser[0],
            loser_name=loser[1],
            level=level,
            seconds=seconds,
            group_title="گروه تست",
            at=at,
        )

    # --------------------------------------------------------- تک‌نفره
    def test_empty_storage(self):
        self.assertIsNone(self.storage.get(1))
        self.assertEqual(self.storage.top("easy"), [])
        self.assertEqual(self.storage.group_table(GROUP), [])

    def test_records_games_and_best_time(self):
        self.storage.record(5, "سارا", "easy", True, 40)
        self.storage.record(5, "سارا", "easy", True, 25)
        self.storage.record(5, "سارا", "easy", False, 10)
        data = self.storage.get(5)
        self.assertEqual(data["played"], 3)
        self.assertEqual(data["wins"], 2)
        self.assertEqual(data["best"]["easy"], 25)

    def test_persists_between_instances(self):
        self.storage.record(9, "رضا", "hard", True, 90)
        reloaded = StatsStorage(self.path)
        self.assertEqual(reloaded.get(9)["best"]["hard"], 90)

    def test_top_is_sorted_and_limited(self):
        self.storage.record(1, "الف", "easy", True, 60)
        self.storage.record(2, "ب", "easy", True, 20)
        self.storage.record(3, "پ", "easy", True, 45)
        top = self.storage.top("easy", limit=2)
        self.assertEqual([row["name"] for row in top], ["ب", "پ"])

    def test_broken_file_falls_back_to_empty(self):
        self.path.write_text("{ این json خراب است", encoding="utf-8")
        storage = StatsStorage(self.path)
        self.assertEqual(storage.top("easy"), [])

    # ------------------------------------------------------------ دوئل
    def test_duel_updates_group_table_and_totals(self):
        self.record_duel()
        self.record_duel(loser=(1, "آرش"), winner=(2, "سارا"))
        rows = self.storage.group_table(GROUP)
        self.assertEqual([(row["name"], row["wins"], row["losses"]) for row in rows],
                         [("آرش", 1, 1), ("سارا", 1, 1)])
        self.assertEqual(self.storage.group_info(GROUP)["matches"], 2)

        arash = self.storage.duel_stats(1)
        self.assertEqual((arash["matches"], arash["wins"], arash["losses"]), (2, 1, 1))

    def test_group_table_ranking_prefers_wins(self):
        self.record_duel(winner=(1, "آرش"), loser=(2, "سارا"))
        self.record_duel(winner=(1, "آرش"), loser=(2, "سارا"))
        self.record_duel(winner=(2, "سارا"), loser=(1, "آرش"))
        rows = self.storage.group_table(GROUP)
        self.assertEqual(rows[0]["name"], "آرش")
        self.assertEqual(rows[0]["wins"], 2)
        self.assertEqual(rows[1]["losses"], 2)

    def test_history_is_newest_first_and_capped(self):
        for index in range(35):
            self.record_duel(winner=(1, "آرش"), loser=(2, "سارا"), seconds=index + 1, at=1000 + index)
        history = self.storage.group_history(GROUP, limit=3)
        self.assertEqual([item["seconds"] for item in history], [35, 34, 33])
        self.assertEqual(len(self.storage._data["groups"][str(GROUP)]["matches"]), 30)
        self.assertEqual(self.storage.group_info(GROUP)["matches"], 35)

    def test_head_to_head(self):
        self.record_duel(winner=(1, "آرش"), loser=(2, "سارا"))
        self.record_duel(winner=(1, "آرش"), loser=(2, "سارا"))
        self.record_duel(winner=(2, "سارا"), loser=(1, "آرش"))
        h2h = self.storage.head_to_head(GROUP, 1, 2)
        self.assertEqual(h2h, {"1": 2, "2": 1})
        self.assertEqual(self.storage.head_to_head(GROUP, 2, 1), {"2": 1, "1": 2})

    def test_record_duel_returns_head_to_head(self):
        summary = self.record_duel()
        self.assertEqual(summary["head_to_head"], {"1": 1})
        self.assertEqual(summary["winner"]["wins"], 1)
        self.assertEqual(summary["loser"]["losses"], 1)

    def test_duel_persists_between_instances(self):
        self.record_duel()
        reloaded = StatsStorage(self.path)
        self.assertEqual(reloaded.group_table(GROUP)[0]["wins"], 1)
        self.assertEqual(reloaded.group_info(GROUP)["title"], "گروه تست")

    def test_record_without_user_is_noop(self):
        self.assertIsNone(self.storage.record(None, "بی‌نام", "easy", True, 10))
        self.assertIsNone(self.storage.duel_stats(None))


    # --------------------------------------------------- تاپیک پیش‌فرض
    def test_topic_setting_persists(self):
        self.assertIsNone(self.storage.get_topic(GROUP))
        self.storage.set_topic(GROUP, 777)
        self.assertEqual(self.storage.get_topic(GROUP), 777)
        self.assertEqual(StatsStorage(self.path).get_topic(GROUP), 777)
        self.storage.set_topic(GROUP, 0)
        self.assertEqual(self.storage.get_topic(GROUP), 0, "۰ یعنی General و باید حفظ شود")
        self.storage.clear_topic(GROUP)
        self.assertIsNone(self.storage.get_topic(GROUP))


if __name__ == "__main__":
    unittest.main()
