"""اعتبارسنجی متن‌های HTML که به تلگرام فرستاده می‌شوند.

تلگرام با parse_mode=HTML هر تگ نامتوازن یا کاراکتر escape‌نشده را رد می‌کند،
پس همهٔ متن‌های تولیدی را با یک پارسر XML بررسی می‌کنیم.
"""

from __future__ import annotations

import random
import sys
import unittest
import uuid
import xml.etree.ElementTree as ElementTree
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ui  # noqa: E402
from bot import MinesweeperBot  # noqa: E402
from duel import PLAYING, DuelMatch, Lobby, Player  # noqa: E402
from minesweeper import DIFFICULTIES, Board  # noqa: E402
from storage import StatsStorage  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent


def assert_valid_html(case: unittest.TestCase, text: str, label: str = "") -> None:
    case.assertTrue(text.strip(), f"متن خالی: {label}")
    try:
        ElementTree.fromstring(f"<root>{text}</root>")
    except ElementTree.ParseError as exc:  # pragma: no cover - پیام کمکی
        case.fail(f"HTML نامعتبر در {label}: {exc}\n---\n{text}\n---")


class HtmlRenderingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = TMP_ROOT / f"stats-{uuid.uuid4().hex}.json"
        self.storage = StatsStorage(self.path)
        self.bot = MinesweeperBot(api=None, storage=self.storage)

    def tearDown(self) -> None:
        for candidate in (self.path, Path(str(self.path) + ".tmp")):
            candidate.unlink(missing_ok=True)

    def test_static_texts(self):
        for label, text in (
            ("WELCOME", ui.WELCOME_TEXT),
            ("MENU", ui.MENU_TEXT),
            ("DUEL_INTRO", ui.DUEL_INTRO_TEXT),
            ("HELP", ui.HELP_TEXT),
        ):
            assert_valid_html(self, text, label)

    def test_solo_texts(self):
        board = Board(DIFFICULTIES["easy"], rng=random.Random(3))
        assert_valid_html(self, ui.build_text(board, elapsed=0), "solo-ready")
        board.tap(0, 0)
        assert_valid_html(self, ui.build_text(board, flag_mode=True, elapsed=12.5), "solo-playing")
        mine = next(
            (r, c) for r in range(board.rows) for c in range(board.cols) if board.cell(r, c).mine
        )
        board.tap(*mine)
        assert_valid_html(self, ui.build_text(board, elapsed=20), "solo-lost")

    def test_duel_texts(self):
        players = [Player(7, "آرش"), Player(8, "سارا")]
        match = DuelMatch(chat_id=-100, difficulty=DIFFICULTIES["medium"], players=players,
                          rng=random.Random(11))
        lobby = Lobby(chat_id=-100, host=players[0], difficulty_key="medium", created_at=0.0)
        assert_valid_html(self, ui.duel_lobby_text(lobby), "lobby")

        assert_valid_html(self, ui.duel_text(match), "duel-ready")
        match.play(7, 2, 2)
        self.assertEqual(match.status, PLAYING)
        assert_valid_html(self, ui.duel_text(match), "duel-playing")

        # بازی با پیدا شدن همهٔ مین‌ها تمام می‌شود
        guard = 0
        while not match.is_finished and guard < 100:
            guard += 1
            mine = next(
                (
                    (r, c)
                    for r in range(match.board.rows)
                    for c in range(match.board.cols)
                    if match.board.cell(r, c).mine and not match.board.cell(r, c).revealed
                ),
                None,
            )
            if mine is None:
                break
            match.play(match.current.user_id, *mine)
        self.assertTrue(match.is_finished)
        match.summary = {"head_to_head": {"7": 2, "8": 1}}
        assert_valid_html(self, ui.duel_text(match), "duel-finished")

    def test_duel_timeout_and_draw_texts(self):
        players = [Player(7, "آرش"), Player(8, "سارا")]
        # تایم‌اوت با برنده
        match = DuelMatch(chat_id=-100, difficulty=DIFFICULTIES["easy"], players=players,
                          rng=random.Random(3))
        match.play(7, 2, 2)
        mine = next(
            (r, c)
            for r in range(match.board.rows)
            for c in range(match.board.cols)
            if match.board.cell(r, c).mine
        )
        match.play(8, *mine)
        match.check_timeout(match.last_activity + 600)
        self.assertEqual(match.reason, "timeout")
        assert_valid_html(self, ui.duel_text(match), "duel-timeout")

        # تایم‌اوتِ مساوی (بدون بمب)
        draw = DuelMatch(chat_id=-100, difficulty=DIFFICULTIES["easy"], players=players,
                         rng=random.Random(4))
        draw.play(7, 2, 2)
        draw.check_timeout(draw.last_activity + 600)
        self.assertIsNone(draw.winner)
        assert_valid_html(self, ui.duel_text(draw), "duel-draw")

    def test_group_table_escapes_dangerous_names(self):
        rows = [
            {"user_id": 7, "name": "<b>آرش</b>", "wins": 3, "losses": 1, "matches": 4},
            {"user_id": 8, "name": "سارا & co", "wins": 1, "losses": 2, "matches": 3},
        ]
        history = [
            {
                "winner": 7, "winner_name": "<b>آرش</b>", "loser": 8, "loser_name": "سارا & co",
                "level": "easy", "seconds": 42, "at": 1_700_000_000.0,
            }
        ]
        text = ui.group_table_text(rows, history, total=7, title="<گروه & تست>")
        assert_valid_html(self, text, "group-table")
        self.assertIn("&lt;b&gt;آرش&lt;/b&gt;", text)
        self.assertIn("&lt;گروه &amp; تست&gt;", text)
        self.assertIn("🥇", text)

    def test_stats_texts(self):
        self.storage.record(7, "<b>آرش</b>", "easy", True, 30)
        assert_valid_html(self, self.bot._solo_stats_text(7), "solo-stats")
        self.storage.record_duel(
            chat_id=-100, winner_id=7, winner_name="<b>آرش</b>", loser_id=8,
            loser_name="سارا", level="easy", seconds=30, group_title="گروه",
        )
        assert_valid_html(self, self.bot._duel_stats_text(7), "duel-stats")
        assert_valid_html(
            self,
            self.bot._stats_text(
                {"id": -100, "type": "supergroup"}, {"id": 7, "first_name": "<b>آرش</b>"}
            ),
            "combined-stats",
        )
        assert_valid_html(self, self.bot._top_text(), "top")
        assert_valid_html(self, self.bot._score_text(-100, "<گروه & تست>"), "score")


if __name__ == "__main__":
    unittest.main()
