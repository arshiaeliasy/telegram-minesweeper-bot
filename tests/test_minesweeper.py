"""تست‌های منطق بازی مین‌روب."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minesweeper import (  # noqa: E402
    DIFFICULTIES,
    LOST,
    PLAYING,
    READY,
    WON,
    Board,
    Difficulty,
    MoveResult,
)


def make_board(rows=5, cols=5, mines=5, seed=1234) -> Board:
    board = Board(Difficulty("test", "تست", rows, cols, mines), rng=random.Random(seed))
    return board


class TestBoardSetup(unittest.TestCase):
    def test_starts_ready_without_mines(self):
        board = make_board()
        self.assertEqual(board.status, READY)
        self.assertFalse(any(cell.mine for row in board.grid for cell in row))
        self.assertEqual(board.remaining_mines, 5)

    def test_first_click_is_safe(self):
        for seed in range(25):
            board = make_board(6, 6, 8, seed=seed)
            result = board.tap(3, 2)
            self.assertIn(result, (MoveResult.REVEALED, MoveResult.WON))
            self.assertEqual(board.status, PLAYING)
            self.assertFalse(board.cell(3, 2).mine)
            # خانه‌های اطراف اولین کلیک هم امن هستند
            for nr, nc in board.neighbors(3, 2):
                self.assertFalse(board.cell(nr, nc).mine, f"seed={seed}")

    def test_exact_mine_count(self):
        board = make_board(8, 8, 12)
        board.tap(0, 0)
        self.assertEqual(sum(1 for row in board.grid for cell in row if cell.mine), 12)

    def test_adjacent_counts_are_correct(self):
        board = make_board(7, 7, 10, seed=7)
        board.tap(3, 3)
        for r in range(board.rows):
            for c in range(board.cols):
                cell = board.cell(r, c)
                if cell.mine:
                    continue
                expected = sum(1 for nr, nc in board.neighbors(r, c) if board.cell(nr, nc).mine)
                self.assertEqual(cell.adjacent, expected, f"({r},{c})")

    def test_small_board_keeps_first_click_safe(self):
        board = make_board(2, 2, 3, seed=5)
        board.tap(0, 0)
        self.assertFalse(board.cell(0, 0).mine)


class TestMoves(unittest.TestCase):
    def test_flood_fill_reveals_more_than_one_cell(self):
        board = make_board(6, 6, 4, seed=99)
        board.tap(0, 0)
        self.assertGreater(board.revealed, 1)

    def test_flag_toggle(self):
        board = make_board()
        board.tap(2, 2)
        target = next(
            (r, c)
            for r in range(board.rows)
            for c in range(board.cols)
            if not board.cell(r, c).revealed
        )
        self.assertEqual(board.toggle_flag(*target), MoveResult.FLAGGED)
        self.assertTrue(board.cell(*target).flagged)
        self.assertEqual(board.remaining_mines, 4)
        self.assertEqual(board.toggle_flag(*target), MoveResult.UNFLAGGED)
        self.assertFalse(board.cell(*target).flagged)

    def test_tapping_flagged_cell_is_blocked(self):
        board = make_board()
        board.tap(0, 0)
        hidden = next(
            (r, c)
            for r in range(board.rows)
            for c in range(board.cols)
            if not board.cell(r, c).revealed
        )
        board.toggle_flag(*hidden)
        self.assertEqual(board.tap(*hidden), MoveResult.BLOCKED)
        self.assertFalse(board.cell(*hidden).revealed)

    def test_stepping_on_mine_loses_and_reveals_mines(self):
        board = make_board(6, 6, 5, seed=3)
        board.tap(0, 0)
        mine = next(
            (r, c)
            for r in range(board.rows)
            for c in range(board.cols)
            if board.cell(r, c).mine
        )
        self.assertEqual(board.tap(*mine), MoveResult.BOOM)
        self.assertEqual(board.status, LOST)
        self.assertEqual(board.exploded, mine)
        self.assertTrue(all(cell.revealed for row in board.grid for cell in row if cell.mine))

    def test_finished_game_ignores_taps(self):
        board = make_board(4, 4, 3, seed=11)
        board.tap(0, 0)
        mine = next((r, c) for r in range(4) for c in range(4) if board.cell(r, c).mine)
        board.tap(*mine)
        self.assertEqual(board.tap(1, 1), MoveResult.FINISHED)

    def test_win_when_all_safe_cells_revealed(self):
        board = make_board(5, 5, 4, seed=21)
        board.tap(0, 0)
        for r in range(board.rows):
            for c in range(board.cols):
                cell = board.cell(r, c)
                if cell.mine or cell.revealed:
                    continue
                board.tap(r, c)
        self.assertEqual(board.status, WON)
        self.assertEqual(board.revealed, board.safe_cells)
        self.assertEqual(board.remaining_mines, 0)
        self.assertTrue(all(cell.flagged for row in board.grid for cell in row if cell.mine))

    def test_chord_opens_neighbors_when_flags_match(self):
        board = make_board(6, 6, 6, seed=42)
        board.tap(2, 2)
        target = None
        for r in range(board.rows):
            for c in range(board.cols):
                cell = board.cell(r, c)
                if cell.revealed and cell.adjacent > 0:
                    hidden = [
                        (nr, nc)
                        for nr, nc in board.neighbors(r, c)
                        if not board.cell(nr, nc).revealed
                    ]
                    if len(hidden) == cell.adjacent and all(
                        board.cell(nr, nc).mine for nr, nc in hidden
                    ):
                        target = (r, c, hidden)
                        break
            if target:
                break
        self.assertIsNotNone(target, "چیدمان مناسبی برای تست chord پیدا نشد")
        r, c, hidden = target
        for nr, nc in hidden:
            board.toggle_flag(nr, nc)
        result = board.tap(r, c)
        self.assertIn(result, (MoveResult.REVEALED, MoveResult.WON))
        for nr, nc in hidden:
            self.assertTrue(board.cell(nr, nc).flagged)

    def test_chord_with_wrong_flag_count_does_nothing(self):
        board = make_board(6, 6, 6, seed=42)
        board.tap(2, 2)
        target = next(
            (r, c)
            for r in range(board.rows)
            for c in range(board.cols)
            if board.cell(r, c).revealed and board.cell(r, c).adjacent > 1
        )
        revealed_before = board.revealed
        self.assertEqual(board.tap(*target), MoveResult.NOOP)
        self.assertEqual(board.revealed, revealed_before)

    def test_out_of_range_tap_is_noop(self):
        board = make_board(5, 5, 3)
        self.assertEqual(board.tap(-1, 0), MoveResult.NOOP)
        self.assertEqual(board.tap(0, 99), MoveResult.NOOP)


class TestCollectMode(unittest.TestCase):
    """حالت بمب‌گیری (دوئل): روی مین رفتن = پیدا کردن بمب، نه باخت."""

    def make_collect(self, rows=6, cols=6, mines=6, seed=7) -> Board:
        return Board(
            Difficulty("test", "تست", rows, cols, mines),
            rng=random.Random(seed),
            collect=True,
        )

    def test_mine_tap_scores_instead_of_losing(self):
        board = self.make_collect()
        board.tap(2, 2)
        mine = next(
            (r, c) for r in range(board.rows) for c in range(board.cols) if board.cell(r, c).mine
        )
        self.assertEqual(board.tap(*mine), MoveResult.MINE_FOUND)
        self.assertEqual(board.status, PLAYING)
        self.assertEqual(board.mines_found, 1)
        self.assertTrue(board.cell(*mine).revealed)
        self.assertIsNone(board.exploded)

    def test_all_mines_found_wins_and_reveals_rest(self):
        board = self.make_collect(mines=5)
        board.tap(2, 2)
        for _ in range(5):
            mine = next(
                (r, c)
                for r in range(board.rows)
                for c in range(board.cols)
                if board.cell(r, c).mine and not board.cell(r, c).revealed
            )
            board.tap(*mine)
        self.assertEqual(board.status, WON)
        self.assertEqual(board.mines_found, 5)
        self.assertTrue(all(cell.revealed for row in board.grid for cell in row))

    def test_safe_tap_passes_and_keeps_playing(self):
        board = self.make_collect()
        board.tap(2, 2)
        hidden_safe = next(
            (r, c)
            for r in range(board.rows)
            for c in range(board.cols)
            if not board.cell(r, c).revealed and not board.cell(r, c).mine
        )
        self.assertEqual(board.tap(*hidden_safe), MoveResult.REVEALED)
        self.assertEqual(board.status, PLAYING)
        self.assertEqual(board.mines_found, 0)

    def test_first_click_is_safe_in_collect_mode(self):
        for seed in range(15):
            board = self.make_collect(seed=seed)
            board.tap(3, 3)
            self.assertFalse(board.cell(3, 3).mine, f"seed={seed}")

    def test_finished_collect_board_ignores_taps(self):
        board = self.make_collect(mines=3)
        board.tap(2, 2)
        for _ in range(3):
            mine = next(
                (r, c)
                for r in range(board.rows)
                for c in range(board.cols)
                if board.cell(r, c).mine and not board.cell(r, c).revealed
            )
            board.tap(*mine)
        self.assertEqual(board.status, WON)
        self.assertEqual(board.tap(0, 0), MoveResult.FINISHED)

    def test_tapping_revealed_cell_is_noop_in_collect_mode(self):
        board = self.make_collect()
        board.tap(2, 2)
        self.assertEqual(board.tap(2, 2), MoveResult.NOOP)


class TestDifficulties(unittest.TestCase):
    def test_all_difficulties_fit_telegram_button_limit(self):
        for key, diff in DIFFICULTIES.items():
            with self.subTest(difficulty=key):
                self.assertLessEqual(diff.cells + 4, 100, "سقف ۱۰۰ دکمه‌ای تلگرام")
                self.assertLess(diff.mines, diff.cells - 8)

    def test_to_lines_shape(self):
        board = make_board(4, 4, 2)
        board.tap(0, 0)
        lines = board.to_lines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(len(line.split(" ")) == 4 for line in lines))


if __name__ == "__main__":
    unittest.main()
