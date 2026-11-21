"""تست‌های جریان ربات با یک API جعلی (بدون نیاز به توکن و شبکه).

هم حالت تک‌نفره و هم دوئل دو نفره در گروه پوشش داده می‌شود.
"""

from __future__ import annotations

import random
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ui  # noqa: E402
from bot import MinesweeperBot  # noqa: E402
from storage import StatsStorage  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent

ARASH = (7, "آرش")
SARA = (8, "سارا")
NAVID = (9, "نوید")
GROUP = -1001234567890
PRIVATE = 7


class FakeAPI:
    """جایگزین TelegramAPI که فراخوانی‌ها را ثبت می‌کند."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.answered: list[dict] = []
        self._message_id = 100
        self.member_status = "administrator"

    def get_chat_member(self, chat_id, user_id):
        return {"status": self.member_status, "user": {"id": user_id}}

    def send_message(self, chat_id, text, **kwargs):
        self._message_id += 1
        self.sent.append(
            {"chat_id": chat_id, "text": text, "message_id": self._message_id, **kwargs}
        )
        return {"message_id": self._message_id}

    def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "text": text, **kwargs})
        return {"message_id": message_id}

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        self.answered.append({"id": callback_query_id, "text": text, "alert": show_alert})
        return True

    # ------------------------------------------------------------- کمکی
    @property
    def last_text(self) -> str:
        if self.edited:
            return self.edited[-1]["text"]
        return self.sent[-1]["text"] if self.sent else ""

    @property
    def last_buttons(self) -> int:
        source = self.edited[-1] if self.edited else self.sent[-1]
        markup = source.get("reply_markup") or {}
        return sum(len(row) for row in markup.get("inline_keyboard", []))

    @property
    def last_toast(self) -> str | None:
        return self.answered[-1]["text"] if self.answered else None


def message(update_id: int, text: str, chat_id: int = PRIVATE, user=ARASH, chat_type="private",
            title=None, thread_id: int | None = None) -> dict:
    chat = {"id": chat_id, "type": chat_type}
    if title:
        chat["title"] = title
    body = {
        "message_id": update_id,
        "chat": chat,
        "from": {"id": user[0], "first_name": user[1]},
        "text": text,
    }
    if thread_id is not None:
        body["message_thread_id"] = thread_id
    return {"update_id": update_id, "message": body}


def callback(update_id: int, data: str, chat_id: int = PRIVATE, user=ARASH, message_id: int = 55,
             chat_type="private", title=None, thread_id: int | None = None) -> dict:
    chat = {"id": chat_id, "type": chat_type}
    if title:
        chat["title"] = title
    msg = {"message_id": message_id, "chat": chat}
    if thread_id is not None:
        msg["message_thread_id"] = thread_id
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": user[0], "first_name": user[1]},
            "data": data,
            "message": msg,
        },
    }


def group_message(update_id: int, text: str, user=ARASH, thread_id: int | None = None) -> dict:
    return message(update_id, text, chat_id=GROUP, user=user, chat_type="supergroup",
                   title="گروه تست", thread_id=thread_id)


def group_callback(update_id: int, data: str, user=ARASH, message_id: int = 55,
                   thread_id: int | None = None) -> dict:
    return callback(update_id, data, chat_id=GROUP, user=user, message_id=message_id,
                    chat_type="supergroup", title="گروه تست", thread_id=thread_id)


class BotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._stats_path = TMP_ROOT / f"stats-{uuid.uuid4().hex}.json"
        self.api = FakeAPI()
        self.storage = StatsStorage(self._stats_path)
        self.now = [1000.0]
        self.bot = MinesweeperBot(self.api, self.storage, clock=lambda: self.now[0])
        self._update_id = 0

    def tearDown(self) -> None:
        for candidate in (self._stats_path, Path(str(self._stats_path) + ".tmp")):
            candidate.unlink(missing_ok=True)

    def next_id(self) -> int:
        self._update_id += 1
        return self._update_id


# ============================================================ حالت تک‌نفره
class SoloFlowTest(BotTestCase):
    def solo(self):
        return self.bot.solo.get((PRIVATE, ARASH[0]))

    def test_start_shows_difficulty_menu(self):
        self.bot.handle_update(message(1, "/start"))
        markup = self.api.sent[0]["reply_markup"]["inline_keyboard"]
        datas = [button["callback_data"] for row in markup for button in row]
        self.assertIn("d:easy", datas)
        self.assertIn("d:hard", datas)

    def test_choosing_difficulty_starts_board(self):
        self.bot.handle_update(message(1, "/solo"))
        self.bot.handle_update(callback(2, "d:medium"))
        board = self.solo().board
        self.assertEqual((board.rows, board.cols, board.total_mines), (8, 8, 12))
        self.assertEqual(self.api.last_buttons, 64 + 4)

    def test_flag_mode_and_tap(self):
        self.bot.handle_update(message(1, "/solo"))
        self.bot.handle_update(callback(2, "d:easy"))
        self.bot.handle_update(callback(3, ui.CB_FLAG_MODE))
        self.assertTrue(self.solo().flag_mode)
        self.bot.handle_update(callback(4, "t:0:0"))
        self.assertTrue(self.solo().board.cell(0, 0).flagged)

    def test_losing_records_stats(self):
        self.bot.handle_update(message(1, "/solo"))
        self.bot.handle_update(callback(2, "d:easy"))
        board = self.solo().board
        self.bot.handle_update(callback(3, "t:0:0"))
        mine = next((r, c) for r in range(board.rows) for c in range(board.cols) if board.cell(r, c).mine)
        self.bot.handle_update(callback(4, f"t:{mine[0]}:{mine[1]}"))
        stats = self.storage.get(ARASH[0])
        self.assertEqual(stats["played"], 1)
        self.assertEqual(stats["wins"], 0)
        self.assertIn("باختی", self.api.last_text)

    def test_winning_records_best_time(self):
        self.bot.handle_update(message(1, "/solo"))
        self.bot.handle_update(callback(2, "d:easy"))
        board = self.solo().board
        self.bot.handle_update(callback(3, "t:0:0"))
        self.now[0] = 1042.0
        for r in range(board.rows):
            for c in range(board.cols):
                cell = board.cell(r, c)
                if cell.mine or cell.revealed or board.is_finished:
                    continue
                self.bot.handle_update(callback(self.next_id() + 100, f"t:{r}:{c}"))
        self.assertEqual(board.status, "won")
        self.assertEqual(self.storage.get(ARASH[0])["best"]["easy"], 42)

    def test_other_user_cannot_tap_my_board(self):
        self.bot.handle_update(message(1, "/solo"))
        self.bot.handle_update(callback(2, "d:easy"))
        self.bot.handle_update(callback(3, "t:0:0", user=SARA))
        self.assertTrue(self.api.answered[-1]["alert"])
        self.assertEqual(self.solo().board.revealed, 0)


# ============================================================== دوئل گروهی
class DuelFlowTest(BotTestCase):
    # -------------------------------------------------------------- کمکی‌ها
    def lobbies(self):
        return [lobby for lobby in self.bot.lobbies.values() if lobby.chat_id == GROUP]

    def matches(self, finished: bool = False):
        return [
            match
            for match in self.bot.duels.values()
            if match.chat_id == GROUP and match.is_finished == finished
        ]

    def the_match(self, finished: bool = False):
        found = self.matches(finished=finished)
        self.assertEqual(len(found), 1, f"تعداد دوئل: {len(found)}")
        return found[0]

    def open_lobby(self, level: str = "easy", host=ARASH) -> None:
        self.bot.handle_update(group_message(self.next_id(), f"/duel {level}", user=host))

    def buttons_of_last(self) -> list[str]:
        source = self.api.edited[-1] if self.api.edited else self.api.sent[-1]
        markup = source.get("reply_markup") or {}
        return [
            button["callback_data"]
            for row in markup.get("inline_keyboard", [])
            for button in row
        ]

    def join(self, guest=SARA, message_id: int = 55) -> None:
        # حالت قدیمیِ دکمه (بدون شناسه) وقتی فقط یک دعوت باز باشد کار می‌کند.
        self.bot.handle_update(group_callback(self.next_id(), ui.CB_DUEL_JOIN, user=guest,
                                              message_id=message_id))

    def start_duel(self, level: str = "easy", seed: int = 5):
        self.open_lobby(level)
        lobby_message = self.api.sent[-1]["message_id"]
        self.join(message_id=lobby_message)
        match = self.the_match()
        match.board.rng = random.Random(seed)  # چیدمان قطعی برای تست
        return match

    def tap(self, user, r: int, c: int, match=None) -> None:
        match = match or self.the_match()
        self.bot.handle_update(
            group_callback(self.next_id(), f"dt:{match.id}:{r}:{c}", user=user)
        )

    def hidden_mine(self, match):
        return next(
            (r, c)
            for r in range(match.board.rows)
            for c in range(match.board.cols)
            if match.board.cell(r, c).mine and not match.board.cell(r, c).revealed
        )

    def finish_by_mines(self, match, guard: int = 100) -> None:
        """تا پیدا شدن همهٔ مین‌ها بازی می‌کند (نوبت طبق قانون نزد بازیکن فعلی می‌ماند)."""
        if match.board.status == "ready":
            player = match.current
            self.tap((player.user_id, player.name), 0, 0, match=match)
        for _ in range(guard):
            if match.is_finished:
                break
            mine = self.hidden_mine(match)
            if mine is None:
                break
            player = match.current
            self.tap((player.user_id, player.name), *mine, match=match)
        self.assertTrue(match.is_finished, "بازی باید با پیدا شدن همهٔ مین‌ها تمام شود")

    # ----------------------------------------------------------- لابی
    def test_duel_command_opens_lobby(self):
        self.open_lobby("medium")
        lobby = self.lobbies()[0]
        self.assertEqual(lobby.host.user_id, ARASH[0])
        self.assertEqual(lobby.difficulty_key, "medium")
        text = self.api.sent[-1]["text"]
        self.assertIn("دعوت‌نامهٔ دوئل", text)
        self.assertIn("متوسط", text)
        datas = [
            button["callback_data"]
            for row in self.api.sent[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertIn(f"{ui.CB_DUEL_JOIN}:{lobby.id}", datas)
        self.assertIn(f"duel:level:{lobby.id}:hard", datas)
        self.assertIn(f"{ui.CB_DUEL_CANCEL}:{lobby.id}", datas)

    def test_duel_needs_a_group(self):
        self.bot.handle_update(message(self.next_id(), "/duel"))
        self.assertIn("گروه", self.api.sent[-1]["text"])
        self.assertEqual(self.lobbies(), [])

    def test_host_cannot_join_his_own_lobby(self):
        self.open_lobby()
        self.join(guest=ARASH)
        self.assertTrue(self.api.answered[-1]["alert"])
        self.assertEqual(self.matches(), [])

    def test_level_change_only_by_host(self):
        self.open_lobby()
        lobby = self.lobbies()[0]
        message_id = self.api.sent[-1]["message_id"]
        data = f"duel:level:{lobby.id}:hard"
        self.bot.handle_update(group_callback(self.next_id(), data, user=SARA,
                                              message_id=message_id))
        self.assertEqual(self.lobbies()[0].difficulty_key, "easy")
        self.assertIn("سازنده", self.api.answered[-1]["text"])
        self.bot.handle_update(group_callback(self.next_id(), data, user=ARASH,
                                              message_id=message_id))
        self.assertEqual(self.lobbies()[0].difficulty_key, "hard")
        self.assertIn("سخت", self.api.edited[-1]["text"])

    def test_cancel_lobby(self):
        self.open_lobby()
        lobby = self.lobbies()[0]
        message_id = self.api.sent[-1]["message_id"]
        data = f"{ui.CB_DUEL_CANCEL}:{lobby.id}"
        self.bot.handle_update(group_callback(self.next_id(), data, user=SARA,
                                              message_id=message_id))
        self.assertEqual(len(self.lobbies()), 1)
        self.bot.handle_update(group_callback(self.next_id(), data, user=ARASH,
                                              message_id=message_id))
        self.assertEqual(self.lobbies(), [])
        self.assertIn("لغو", self.api.edited[-1]["text"])

    def test_expired_lobby_cannot_be_joined(self):
        self.open_lobby()
        message_id = self.api.sent[-1]["message_id"]
        self.now[0] += 20 * 60
        self.join(message_id=message_id)
        self.assertTrue(self.api.answered[-1]["alert"])
        self.assertEqual(self.matches(), [])

    def test_sweep_cleans_expired_lobbies(self):
        self.open_lobby()
        self.assertEqual(len(self.lobbies()), 1)
        self.now[0] += 16 * 60
        self.bot._sweep_idle()
        self.assertEqual(self.lobbies(), [])

    def test_multiple_lobbies_can_open_and_are_picked_from_a_list(self):
        self.open_lobby("easy", host=ARASH)
        self.open_lobby("hard", host=SARA)
        self.assertEqual(len(self.lobbies()), 2)
        self.bot.handle_update(group_message(self.next_id(), "/join", user=NAVID))
        # به‌جای پیوستن کور، فهرست دعوت‌ها نمایش داده می‌شود
        self.assertEqual(self.matches(), [])
        text = self.api.sent[-1]["text"]
        self.assertIn("چند دعوت", text)
        datas = [
            button["callback_data"]
            for row in self.api.sent[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertEqual(len([d for d in datas if d.startswith("duel:join")]), 2)
        # پیوستن با شناسهٔ یکی از آن‌ها
        self.bot.handle_update(group_callback(self.next_id(), datas[0], user=NAVID))
        self.assertEqual(len(self.matches()), 1)
        self.assertEqual(len(self.lobbies()), 1)

    # ---------------------------------------------------------- شروع دوئل
    def test_joining_starts_the_duel(self):
        match = self.start_duel("medium")
        self.assertEqual(match.players[0].user_id, ARASH[0])
        self.assertEqual(match.players[1].user_id, SARA[0])
        self.assertEqual(match.current.user_id, ARASH[0])
        self.assertEqual(self.lobbies(), [])
        text = self.api.last_text
        self.assertIn("دوئل مین‌روب", text)
        self.assertIn("نوبت", text)
        self.assertIn("بمب‌ها", text)
        self.assertEqual(self.api.last_buttons, 64 + 2, "تخته + جدول + راهنما (بدون دکمهٔ پرچم)")

    def test_duel_board_has_no_flag_button(self):
        self.start_duel()
        self.assertNotIn("df", self.buttons_of_last())

    def test_non_player_cannot_tap(self):
        self.start_duel()
        before = self.the_match().board.revealed
        self.tap(NAVID, 0, 0)
        self.assertTrue(self.api.answered[-1]["alert"])
        self.assertEqual(self.the_match().board.revealed, before)

    def test_wrong_turn_is_rejected(self):
        match = self.start_duel()
        self.tap(SARA, 0, 0)  # نوبت آرش است
        self.assertIn("نوبت", self.api.answered[-1]["text"])
        self.assertEqual(match.board.revealed, 0)
        self.assertEqual(match.current.user_id, ARASH[0])

    def test_turns_alternate_on_safe_cells(self):
        match = self.start_duel()
        self.tap(ARASH, 0, 0)
        self.assertEqual(match.current.user_id, SARA[0])
        self.assertEqual(match.moves, 1)
        self.tap(SARA, 5, 5)
        self.assertEqual(match.current.user_id, ARASH[0])
        self.assertEqual(match.moves, 2)

    def test_mine_found_scores_and_keeps_turn(self):
        match = self.start_duel()
        self.tap(ARASH, 0, 0)  # مین‌ها کاشته می‌شوند؛ نوبت سارا
        self.tap(SARA, *self.hidden_mine(match))
        self.assertEqual(match.found, [0, 1])
        self.assertEqual(match.current.user_id, SARA[0], "بمب پیدا کردن یعنی دوباره نوبت خودش")
        self.assertFalse(match.is_finished)
        self.assertIn("بمب پیدا کردی", self.api.last_toast)
        self.assertIn("💣", self.api.last_text)

    def test_game_ends_when_all_mines_found_and_records_table(self):
        match = self.start_duel()
        self.finish_by_mines(match)
        self.assertEqual(match.reason, "score")
        self.assertEqual(sum(match.found), match.board.total_mines)
        self.assertIn("برندهٔ دوئل", self.api.last_text)
        self.assertIn("بمب‌ها", self.api.last_text)
        self.assertIn("رودررو", self.api.last_text)

        rows = self.storage.group_table(GROUP)
        self.assertEqual(
            [(row["name"], row["wins"], row["losses"]) for row in rows],
            [("سارا", 1, 0), ("آرش", 0, 1)],
        )
        info = self.storage.group_info(GROUP)
        self.assertEqual(info["matches"], 1)
        self.assertEqual(info["title"], "گروه تست")

    def test_post_match_keyboard_and_rematch(self):
        match = self.start_duel()
        self.finish_by_mines(match)
        self.assertEqual(self.api.last_buttons, 36 + 3, "تخته + دکمه‌های کنترل")

        self.bot.handle_update(
            group_callback(self.next_id(), f"{ui.CB_DUEL_REMATCH}:{match.id}", user=SARA)
        )
        again = self.the_match()
        self.assertIsNot(again, match)
        self.assertFalse(again.is_finished)
        self.assertEqual(again.current.user_id, SARA[0], "نفر شروع‌کننده باید عوض شود")
        self.assertEqual(again.board.revealed, 0)
        self.assertEqual(again.found, [0, 0])

    def test_non_player_cannot_rematch(self):
        match = self.start_duel()
        self.finish_by_mines(match)
        self.bot.handle_update(
            group_callback(self.next_id(), f"{ui.CB_DUEL_REMATCH}:{match.id}", user=NAVID)
        )
        self.assertTrue(self.api.answered[-1]["alert"])
        self.assertTrue(match.is_finished)

    def test_surrender_command(self):
        match = self.start_duel()
        self.tap(ARASH, 0, 0)
        self.bot.handle_update(group_message(self.next_id(), "/surrender", user=SARA))
        self.assertTrue(match.is_finished)
        self.assertEqual(match.winner.user_id, ARASH[0])
        self.assertEqual(self.storage.group_info(GROUP)["matches"], 1)
        self.assertIn("تسلیم", self.api.sent[-1]["text"])

    def test_surrender_button_when_multiple_duels(self):
        first = self.start_duel()
        # دعوت و دوئل دوم همزمان
        self.open_lobby("medium", host=NAVID)
        lobby2 = self.lobbies()[0]
        join2 = next(
            d for d in (
                button["callback_data"]
                for row in self.api.sent[-1]["reply_markup"]["inline_keyboard"]
                for button in row
            )
            if d.startswith("duel:join")
        )
        self.bot.handle_update(group_callback(self.next_id(), join2, user=ARASH))
        active = self.matches()
        self.assertEqual(len(active), 2)
        second = next(m for m in active if m is not first)
        self.assertEqual(second.players[0].user_id, NAVID[0])

        # آرش در هر دو دوئل است؛ /surrender باید فهرست بدهد
        self.bot.handle_update(group_message(self.next_id(), "/surrender", user=ARASH))
        self.assertEqual(len(self.matches()), 2, "هنوز چیزی تمام نشده")
        text = self.api.sent[-1]["text"]
        self.assertIn("چند دوئل", text)
        datas = [
            button["callback_data"]
            for row in self.api.sent[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertEqual(len([d for d in datas if d.startswith("duel:surrender")]), 2)
        # تسلیم در دوئل اول
        self.bot.handle_update(group_callback(self.next_id(), datas[0], user=ARASH))
        self.assertTrue(first.is_finished)
        self.assertFalse(second.is_finished)

    def test_no_flag_button_in_finished_keyboard(self):
        match = self.start_duel()
        self.finish_by_mines(match)
        self.assertNotIn("df", self.buttons_of_last())

    # ------------------------------------------------------ چند بازی همزمان
    def test_multiple_duels_run_in_parallel(self):
        first = self.start_duel()
        self.open_lobby("medium", host=NAVID)
        lobby2 = self.lobbies()[0]
        join2 = next(
            d for d in (
                button["callback_data"]
                for row in self.api.sent[-1]["reply_markup"]["inline_keyboard"]
                for button in row
            )
            if d.startswith("duel:join")
        )
        self.bot.handle_update(group_callback(self.next_id(), join2, user=ARASH))
        active = self.matches()
        self.assertEqual(len(active), 2, "باید دو دوئل همزمان در یک گروه فعال شود")
        second = next(m for m in active if m is not first)

        # هر دو دوئل همزمان بازی می‌شوند
        self.tap(ARASH, 0, 0, match=first)
        self.assertEqual(first.moves, 1)
        self.assertEqual(second.moves, 0)
        self.tap(NAVID, 1, 1, match=second)
        self.assertEqual(second.moves, 1)
        self.assertEqual(first.current.user_id, SARA[0])
        self.assertEqual(second.current.user_id, ARASH[0])
        self.assertEqual(len(self.matches()), 2)

    def test_second_lobby_does_not_block_anything(self):
        self.start_duel()
        self.open_lobby()  # دعوت دوم در همان گروهِ در جریان
        self.assertEqual(len(self.lobbies()), 1)
        self.assertEqual(len(self.matches()), 1)

    # ------------------------------------------------------------ تایم‌اوت
    def test_timeout_sweep_finishes_idle_duel_with_score(self):
        match = self.start_duel()
        self.tap(ARASH, 0, 0, match=match)
        self.tap(SARA, *self.hidden_mine(match), match=match)  # سارا ۱ بمب
        self.now[0] += 601
        self.bot._sweep_idle()
        self.assertTrue(match.is_finished)
        self.assertEqual(match.reason, "timeout")
        self.assertEqual(match.winner.user_id, SARA[0])
        self.assertIn("۱۰ دقیقه", self.api.sent[-1]["text"])
        self.assertEqual(self.storage.group_info(GROUP)["matches"], 1)

    def test_timeout_sweep_without_bombs_is_a_draw(self):
        match = self.start_duel()
        self.tap(ARASH, 0, 0, match=match)
        self.now[0] += 601
        self.bot._sweep_idle()
        self.assertTrue(match.is_finished)
        self.assertIsNone(match.winner)
        self.assertIn("مساوی", self.api.last_text)
        self.assertEqual(self.storage.group_info(GROUP)["matches"], 0, "مساوی ثبت نمی‌شود")

    def test_no_timeout_before_10_minutes(self):
        match = self.start_duel()
        self.tap(ARASH, 0, 0, match=match)
        self.now[0] += 599
        self.bot._sweep_idle()
        self.assertFalse(match.is_finished)

    # -------------------------------------------------------- جدول و متون
    def test_score_table_lists_group_history(self):
        match = self.start_duel()
        self.finish_by_mines(match)
        self.bot.handle_update(group_message(self.next_id(), "/score", user=NAVID))
        text = self.api.sent[-1]["text"]
        self.assertIn("جدول امتیازات این گروه", text)
        self.assertIn("🥇", text)
        self.assertIn("آخرین دوئل‌ها", text)
        self.assertIn("گروه تست", text)

    def test_score_in_private_shows_personal_duel_stats(self):
        self.bot.handle_update(message(self.next_id(), "/score"))
        self.assertIn("دوئل", self.api.sent[-1]["text"])

    def test_group_start_shows_duel_intro(self):
        self.bot.handle_update(group_message(self.next_id(), "/start"))
        self.assertIn("دوئل", self.api.sent[-1]["text"])
        datas = [
            button["callback_data"]
            for row in self.api.sent[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertIn(ui.CB_DUEL_NEW, datas)

    def test_duel_new_button_opens_lobby(self):
        self.start_duel()  # حتی با وجود یک دوئل فعال
        self.bot.handle_update(group_callback(self.next_id(), ui.CB_DUEL_NEW, user=SARA))
        lobbies = self.lobbies()
        self.assertEqual(len(lobbies), 1)
        self.assertEqual(lobbies[0].host.user_id, SARA[0])

    def test_help_and_stats_commands(self):
        self.bot.handle_update(group_message(self.next_id(), "/help"))
        self.assertIn("دوئل", self.api.sent[-1]["text"])
        self.bot.handle_update(group_message(self.next_id(), "/stats"))
        self.assertIn("تک‌نفره", self.api.sent[-1]["text"])

    def test_legacy_tap_without_match_id(self):
        # پیام‌های قدیمیِ بدون شناسه وقتی یک دوئل فعال باشد هنوز کار می‌کنند
        match = self.start_duel()
        self.bot.handle_update(group_callback(self.next_id(), "dt:0:0", user=ARASH))
        self.assertEqual(match.moves, 1)
        self.assertEqual(match.current.user_id, SARA[0])

    def test_broken_callback_does_not_crash(self):
        self.bot.handle_update(group_callback(self.next_id(), "dt:banana"))
        self.bot.handle_update(group_callback(self.next_id(), "dt:1:2:3:4:5"))
        self.bot.handle_update({"update_id": 9991, "message": {"chat": {"id": GROUP}}})
        self.bot.handle_update({"update_id": 9992})
        self.assertTrue(self.api.answered[-1]["text"])

    # ------------------------------------------------ بازگشتی: شناسه در کلیدها
    def test_duel_keyboard_carries_match_id(self):
        match = self.start_duel()
        taps = [d for d in self.buttons_of_last() if d.startswith(ui.CB_DUEL_TAP)]
        self.assertTrue(taps, "کلید تخته پیدا نشد")
        for data in taps:
            self.assertTrue(
                data.startswith(f"{ui.CB_DUEL_TAP}{match.id}:"),
                f"کلید بدون شناسهٔ بازی است: {data}",
            )

    def test_finished_keyboard_carries_match_id(self):
        match = self.start_duel()
        self.finish_by_mines(match)
        taps = [d for d in self.buttons_of_last() if d.startswith(ui.CB_DUEL_TAP)]
        self.assertTrue(taps, "کلید تختهٔ پایان‌یافته پیدا نشد")
        for data in taps:
            self.assertTrue(data.startswith(f"{ui.CB_DUEL_TAP}{match.id}:"), data)

    def test_tap_from_rendered_keyboard_works_with_two_matches(self):
        """تاپ با همان callback_data که راستی‌روی صفحه است، حتی با چند دوئل همزمان."""
        first = self.start_duel(seed=5)
        # دوئل دوم همزمان در همان گروه
        self.open_lobby()
        lobby_msg = self.api.sent[-1]["message_id"]
        self.join(message_id=lobby_msg)
        second = next(m for m in self.matches() if m.id != first.id)
        second.board.rng = random.Random(7)
        self.assertEqual(len(self.matches()), 2)

        # کلیدها را از همان صفحه‌ای که ربات فرستاده برمی‌داریم
        datas = [
            d for d in self.buttons_of_last()
            if d.startswith(f"{ui.CB_DUEL_TAP}{second.id}:")
        ]
        self.assertTrue(datas, "کلید دوئل دوم در صفحه نیست")
        data = datas[0]
        self.assertLessEqual(len(data.encode()), 64, "callback_data از ۶۴ بایت بیشتر شد")

        mover = second.current
        self.bot.handle_update(
            group_callback(self.next_id(), data, user=(mover.user_id, mover.name))
        )
        self.assertEqual(second.moves, 1, "تاپ با دکمهٔ واقعی صفحه اعمال نشد")
        self.assertEqual(first.moves, 0, "تاپ به دوئل اشتباه رفت")

    def test_legacy_tap_still_works_after_new_format(self):
        # پیام‌های قدیمیِ بدون شناسه فقط وقتی دقیقاً یک دوئل فعال باشد
        match = self.start_duel()
        self.bot.handle_update(group_callback(self.next_id(), "dt:0:0", user=ARASH))
        self.assertEqual(match.moves, 1)


    def test_legacy_tap_resolves_its_own_message_with_two_duels(self):
        first = self.start_duel(seed=5)
        self.open_lobby()
        lobby_msg = self.api.sent[-1]["message_id"]
        self.join(message_id=lobby_msg)
        active = self.matches()
        self.assertEqual(len(active), 2)
        second = next(m for m in active if m.id != first.id)
        self.assertEqual(second.moves, 0)
        mover = first.current
        self.bot.handle_update(
            group_callback(
                self.next_id(), "dt:0:0", user=(mover.user_id, mover.name),
                message_id=first.message_id,
            )
        )
        self.assertEqual(first.moves, 1, "دکمهٔ قدیمی باید به دوئل خودش نسبت داده شود")
        self.assertEqual(second.moves, 0)

    def test_unknown_legacy_tap_explains_stale_message(self):
        self.start_duel()
        self.open_lobby()
        lobby_msg = self.api.sent[-1]["message_id"]
        self.join(message_id=lobby_msg)
        self.assertEqual(len(self.matches()), 2)
        self.bot.handle_update(
            group_callback(self.next_id(), "dt:0:0", message_id=999999)
        )
        self.assertTrue(self.api.answered[-1]["alert"])
        self.assertIn("/duel", self.api.answered[-1]["text"])


# ============================================================ تاپیک‌های فروم
class TopicRoutingTest(BotTestCase):
    """پیام‌های ربات باید در همان تاپیکی بروند که کاربر از آنجا فرمان داده."""

    def sent_thread(self) -> dict:
        return self.api.sent[-1]

    def test_reply_stays_in_command_topic(self):
        self.bot.handle_update(group_message(self.next_id(), "/duel", thread_id=777))
        self.assertEqual(self.sent_thread().get("message_thread_id"), 777)

    def test_goes_to_general_when_command_is_in_general(self):
        # در تاپیک General معمولاً message_thread_id نیست → بدون آن ارسال شود
        self.bot.handle_update(group_message(self.next_id(), "/duel"))
        self.assertIsNone(self.sent_thread().get("message_thread_id"))
        self.assertEqual(self.bot.threads.get(GROUP), None)

    def test_follows_latest_topic(self):
        self.bot.handle_update(group_message(self.next_id(), "/help", thread_id=111))
        self.assertEqual(self.sent_thread().get("message_thread_id"), 111)
        self.bot.handle_update(group_message(self.next_id(), "/help", thread_id=222))
        self.assertEqual(self.sent_thread().get("message_thread_id"), 222)

    def test_button_reply_keeps_topic(self):
        # دکمه‌ای که در تاپیک ۳۳۳ لمس شود، پاسخ تازه را همان‌جا می‌فرستد
        self.bot.handle_update(group_message(self.next_id(), "/duel", thread_id=333))
        self.bot.handle_update(
            group_callback(self.next_id(), ui.CB_DUEL_TABLE, thread_id=333)
        )
        self.assertEqual(self.sent_thread().get("message_thread_id"), 333)

    def test_game_messages_follow_topic(self):
        self.bot.handle_update(group_message(self.next_id(), "/duel", thread_id=555))
        lobby_msg = self.api.sent[-1]["message_id"]
        self.bot.handle_update(
            group_callback(self.next_id(), ui.CB_DUEL_JOIN, user=SARA,
                           message_id=lobby_msg, thread_id=555)
        )
        match = next(m for m in self.bot.duels.values() if m.chat_id == GROUP)
        self.assertEqual(match.message_id, lobby_msg)
        # پس از شروع بازی، ویرایش‌ها روی همان پیام انجام می‌شوند (نیازی به تاپیک ندارند)
        self.assertTrue(self.api.edited)
        self.assertEqual(self.bot.threads.get(GROUP), 555)

    def test_topic_command_pins_home_topic(self):
        self.bot.handle_update(group_message(self.next_id(), "/topic", thread_id=444))
        self.assertEqual(self.storage.get_topic(GROUP), 444)
        self.assertEqual(self.sent_thread().get("message_thread_id"), 444)
        # فرمان از تاپیک دیگری هم بیاید، پاسخ در تاپیک ثابت می‌رود
        self.bot.handle_update(group_message(self.next_id(), "/help", thread_id=999))
        self.assertEqual(self.sent_thread().get("message_thread_id"), 444)

    def test_game_messages_use_pinned_topic(self):
        self.bot.handle_update(group_message(self.next_id(), "/topic", thread_id=444))
        self.bot.handle_update(group_message(self.next_id(), "/duel", thread_id=999))
        self.assertEqual(self.sent_thread().get("message_thread_id"), 444)

    def test_topic_command_requires_admin(self):
        self.api.member_status = "member"
        self.bot.handle_update(group_message(self.next_id(), "/topic", thread_id=444))
        self.assertIsNone(self.storage.get_topic(GROUP))
        self.assertIn("مدیر", self.sent_thread()["text"])

    def test_topic_off_returns_to_following_mode(self):
        self.bot.handle_update(group_message(self.next_id(), "/topic", thread_id=444))
        self.bot.handle_update(group_message(self.next_id(), "/topic off", thread_id=888))
        self.assertIsNone(self.storage.get_topic(GROUP))
        self.bot.handle_update(group_message(self.next_id(), "/help", thread_id=777))
        self.assertEqual(self.sent_thread().get("message_thread_id"), 777)

    def test_topic_command_only_for_groups(self):
        self.bot.handle_update(message(self.next_id(), "/topic"))
        self.assertIn("گروه", self.api.sent[-1]["text"])
        self.assertIsNone(self.storage.get_topic(PRIVATE))


class GroupIsolationTest(BotTestCase):
    def test_groups_keep_separate_tables(self):
        self.storage.record_duel(
            chat_id=-111, winner_id=1, winner_name="الف", loser_id=2, loser_name="ب",
            level="easy", seconds=30, group_title="گروه یک",
        )
        self.storage.record_duel(
            chat_id=-222, winner_id=2, winner_name="ب", loser_id=1, loser_name="الف",
            level="hard", seconds=50, group_title="گروه دو",
        )
        first = self.storage.group_table(-111)
        second = self.storage.group_table(-222)
        self.assertEqual(first[0]["name"], "الف")
        self.assertEqual(second[0]["name"], "ب")
        self.assertEqual(self.storage.group_info(-111)["matches"], 1)
        self.assertEqual(self.storage.group_info(-222)["matches"], 1)


if __name__ == "__main__":
    unittest.main()
