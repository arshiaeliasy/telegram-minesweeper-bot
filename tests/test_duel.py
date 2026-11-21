"""تست‌های منطق دوئل دو نفره (هدف: پیدا کردن بمب)."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from duel import (  # noqa: E402
    DUEL_TIMEOUT,
    FINISHED,
    REASON_RESIGN,
    REASON_SCORE,
    REASON_TIMEOUT,
    DuelMatch,
    DuelResult,
    Lobby,
    Player,
)
from minesweeper import DIFFICULTIES  # noqa: E402

ARASH = Player(7, "آرش")
SARA = Player(8, "سارا")


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_match(level="easy", seed=5, clock=None) -> DuelMatch:
    clock = clock or FakeClock()
    match = DuelMatch(
        chat_id=-100,
        difficulty=DIFFICULTIES[level],
        players=[ARASH, SARA],
        clock=clock,
        rng=random.Random(seed),
    )
    return match


def hidden_mine(match: DuelMatch):
    return next(
        (r, c)
        for r in range(match.board.rows)
        for c in range(match.board.cols)
        if match.board.cell(r, c).mine and not match.board.cell(r, c).revealed
    )


class LobbyTest(unittest.TestCase):
    def test_expiry(self):
        clock = FakeClock()
        lobby = Lobby(chat_id=-100, host=ARASH, difficulty_key="easy", created_at=clock())
        self.assertFalse(lobby.is_expired(clock()))
        clock.now += 16 * 60
        self.assertTrue(lobby.is_expired(clock()))

    def test_lobby_ids_are_unique(self):
        first = Lobby(chat_id=-100, host=ARASH, difficulty_key="easy", created_at=0.0)
        second = Lobby(chat_id=-100, host=SARA, difficulty_key="easy", created_at=0.0)
        self.assertNotEqual(first.id, second.id)


class TurnOrderTest(unittest.TestCase):
    def test_first_player_starts(self):
        match = make_match()
        self.assertEqual(match.current, ARASH)
        self.assertEqual(match.opponent, SARA)
        self.assertEqual(match.status, "ready")

    def test_only_participants_can_move(self):
        match = make_match()
        self.assertEqual(match.play(999, 0, 0), DuelResult.NOT_PLAYER)
        self.assertEqual(match.play(SARA.user_id, 0, 0), DuelResult.NOT_YOUR_TURN)
        self.assertEqual(match.board.revealed, 0)

    def test_turn_switches_after_safe_reveal(self):
        match = make_match()
        self.assertEqual(match.play(ARASH.user_id, 2, 2), DuelResult.OPENED)
        self.assertEqual(match.current, SARA)
        self.assertEqual(match.moves, 1)
        self.assertEqual(match.play(SARA.user_id, 5, 5), DuelResult.OPENED)
        self.assertEqual(match.current, ARASH)
        self.assertEqual(match.moves, 2)

    def test_timer_starts_with_first_move(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        self.assertEqual(match.elapsed(), 0.0)
        match.play(ARASH.user_id, 2, 2)
        clock.now += 12
        self.assertAlmostEqual(match.elapsed(), 12.0)

    def test_first_click_is_never_a_mine(self):
        for seed in range(20):
            match = make_match(seed=seed)
            match.play(ARASH.user_id, 2, 2)
            self.assertFalse(match.board.cell(2, 2).mine)
            for r, c in match.board.neighbors(2, 2):
                self.assertFalse(match.board.cell(r, c).mine, f"seed={seed}")

    def test_clicking_a_revealed_cell_is_noop(self):
        match = make_match()
        match.play(ARASH.user_id, 2, 2)  # خانهٔ (2,2) باز شد؛ نوبت سارا
        self.assertEqual(match.play(SARA.user_id, 2, 2), DuelResult.NOOP)
        self.assertEqual(match.current, SARA, "کلیک بی‌اثر نباید نوبت را عوض کند")


class BombScoringTest(unittest.TestCase):
    def test_finding_a_mine_scores_and_keeps_turn(self):
        match = make_match()
        match.play(ARASH.user_id, 2, 2)  # اولین کلیک امن؛ نوبت سارا
        mine = hidden_mine(match)
        self.assertEqual(match.play(SARA.user_id, *mine), DuelResult.MINE_FOUND)
        self.assertEqual(match.found, [0, 1])
        self.assertEqual(match.board.mines_found, 1)
        self.assertTrue(match.board.cell(*mine).revealed)
        self.assertEqual(match.current, SARA, "پیدا کردن بمب باید نوبت را نگه دارد")
        self.assertFalse(match.is_finished)
        self.assertEqual(match.moves, 2)

    def test_mine_found_does_not_lose_the_game(self):
        match = make_match()
        match.play(ARASH.user_id, 2, 2)
        match.play(SARA.user_id, *hidden_mine(match))
        self.assertNotEqual(match.status, FINISHED)
        self.assertIsNone(match.winner)

    def test_game_ends_when_all_mines_found(self):
        match = make_match()
        match.play(ARASH.user_id, 2, 2)  # نوبت سارا
        guard = 0
        while not match.is_finished and guard < 100:
            guard += 1
            mine = hidden_mine(match)
            self.assertIsNotNone(mine, "مین پیدانشده‌ای باقی نمانده")
            result = match.play(match.current.user_id, *mine)
            if not match.is_finished:
                self.assertEqual(result, DuelResult.MINE_FOUND)
        self.assertTrue(match.is_finished)
        self.assertEqual(match.reason, REASON_SCORE)
        self.assertEqual(sum(match.found), match.board.total_mines)
        self.assertIsNotNone(match.winner)
        self.assertEqual(match.winner, SARA, "سارا اولین بمب را پیدا کرد و همه را جمع زد")

    def test_equal_bombs_is_a_draw(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        match.play(ARASH.user_id, 2, 2)
        # هیچ بمبی پیدا نشده؛ تایم‌اوت → مساوی
        self.assertTrue(match.check_timeout(clock.now + DUEL_TIMEOUT))
        self.assertTrue(match.is_finished)
        self.assertIsNone(match.winner)
        self.assertIsNone(match.loser)
        self.assertEqual(match.reason, REASON_TIMEOUT)

    def test_timeout_winner_is_the_player_with_more_bombs(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        match.play(ARASH.user_id, 2, 2)      # نوبت سارا
        match.play(SARA.user_id, *hidden_mine(match))  # سارا ۱ بمب
        self.assertFalse(match.check_timeout(clock.now + DUEL_TIMEOUT - 1))
        self.assertFalse(match.is_finished)
        self.assertTrue(match.check_timeout(clock.now + DUEL_TIMEOUT))
        self.assertTrue(match.is_finished)
        self.assertEqual(match.reason, REASON_TIMEOUT)
        self.assertEqual(match.winner, SARA)
        self.assertEqual(match.loser, ARASH)

    def test_last_activity_refreshes_on_any_valid_click(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        match.play(ARASH.user_id, 2, 2)
        clock.now += 500
        match.play(SARA.user_id, 5, 5)
        clock.now += 500
        # ۵۰۰ ثانیه از آخرین کلیک گذشته → هنوز تایم‌اوت نشده
        self.assertFalse(match.check_timeout(clock.now))
        clock.now += DUEL_TIMEOUT
        self.assertTrue(match.check_timeout(clock.now))


class FinishTest(unittest.TestCase):
    def test_moves_after_finish_are_ignored(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        match.play(ARASH.user_id, 2, 2)
        match.check_timeout(clock.now + DUEL_TIMEOUT)
        self.assertTrue(match.is_finished)
        self.assertEqual(match.play(ARASH.user_id, 1, 1), DuelResult.FINISHED)
        self.assertEqual(match.status, FINISHED)

    def test_resign(self):
        match = make_match()
        match.play(ARASH.user_id, 2, 2)
        self.assertEqual(match.resign(SARA.user_id), DuelResult.LOST)
        self.assertEqual(match.winner, ARASH)
        self.assertEqual(match.reason, REASON_RESIGN)
        self.assertEqual(match.resign(999), DuelResult.NOT_PLAYER)

    def test_resign_after_finish_is_ignored(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        match.play(ARASH.user_id, 2, 2)
        match.check_timeout(clock.now + DUEL_TIMEOUT)
        self.assertEqual(match.resign(SARA.user_id), DuelResult.FINISHED)

    def test_rematch_swaps_starting_player(self):
        match = make_match()
        match.play(ARASH.user_id, 2, 2)
        match.resign(ARASH.user_id)
        again = match.next_match(message_id=77)
        self.assertEqual(again.current, SARA)
        self.assertEqual(again.players, match.players)
        self.assertEqual(again.difficulty, match.difficulty)
        self.assertEqual(again.message_id, 77)
        self.assertFalse(again.is_finished)
        self.assertEqual(again.board.revealed, 0)
        self.assertEqual(again.found, [0, 0])
        self.assertNotEqual(again.id, match.id)

    def test_finished_match_reports_timeout_as_noop(self):
        clock = FakeClock()
        match = make_match(clock=clock)
        match.play(ARASH.user_id, 2, 2)
        match.check_timeout(clock.now + DUEL_TIMEOUT)
        self.assertFalse(match.check_timeout(clock.now + 2 * DUEL_TIMEOUT))


if __name__ == "__main__":
    unittest.main()
