#!/usr/bin/env python3
"""ربات تلگرامی مین‌روب.

دو حالت دارد:
* ⚔️ دوئل دو نفره در گروه — روی یک تختهٔ مشترک، نفرِ به نوبت.
  نتیجهٔ هر دوئل در جدول امتیازات همان گروه ثبت می‌شود.
* 🎮 تک‌نفره — در چت خصوصی یا گروه (هر کاربر بازی خودش را دارد).

اجرا:
    python bot.py --token 123456:ABC-DEF...
یا با گذاشتن توکن در فایل token.txt و اجرای run.bat

بدون هیچ وابستگی خارجی؛ فقط کتابخانهٔ استاندارد پایتون.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path

import ui
from duel import DuelMatch, DuelResult, Lobby, Player
from fa import duration as fa_duration
from fa import fa
from minesweeper import DEFAULT_DIFFICULTY, DIFFICULTIES, READY, WON, Board, MoveResult
from storage import StatsStorage
from telegram_api import TelegramAPI, TelegramError, TelegramNetworkError

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("minesweeper.bot")

DEFAULT_DUEL_LEVEL = "easy"
LEVEL_ALIASES = {
    "easy": "easy",
    "آسان": "easy",
    "اسان": "easy",
    "medium": "medium",
    "متوسط": "medium",
    "hard": "hard",
    "سخت": "hard",
    "دشوار": "hard",
}


@dataclass
class SoloGame:
    """بازی تک‌نفرهٔ یک کاربر در یک گفتگو."""

    chat_id: int
    user_id: int
    board: Board
    flag_mode: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    stats_recorded: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class MinesweeperBot:
    def __init__(self, api, storage: StatsStorage, clock=time.monotonic) -> None:
        self.api = api
        self.storage = storage
        self.clock = clock
        self.solo: dict[tuple[int, int], SoloGame] = {}
        self.duels: dict[str, DuelMatch] = {}
        self.lobbies: dict[str, Lobby] = {}
        # تاپیک (موضوع) آخرین پیام ورودی هر گروه؛ پاسخ‌ها در همان تاپیک بروند.
        self.threads: dict[int, int | None] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------- کمکی‌ها
    @staticmethod
    def _is_group(chat: dict | None) -> bool:
        return bool(chat) and chat.get("type") in ("group", "supergroup")

    @staticmethod
    def _display_name(user: dict) -> str:
        full = " ".join(
            part for part in (user.get("first_name"), user.get("last_name")) if part
        ).strip()
        return full or user.get("username") or str(user.get("id") or "بازیکن")

    def _player(self, user: dict) -> Player:
        return Player(int(user.get("id")), self._display_name(user))

    def _answer(self, cb_id, text: str | None = None, alert: bool = False) -> None:
        if cb_id is None:
            return
        try:
            self.api.answer_callback_query(cb_id, text=text, show_alert=alert)
        except TelegramError as exc:
            logger.debug("answerCallbackQuery ناموفق: %s", exc)

    def _tell(self, cb_id, chat_id: int, text: str, alert: bool = False) -> None:
        """اگر از دکمه آمده باشد توست می‌دهد، وگرنه پیام می‌فرستد."""
        if cb_id:
            self._answer(cb_id, text, alert=alert)
        elif text:
            self._send(chat_id, text)

    def _send(self, chat_id, text, **kwargs) -> dict | None:
        """ارسال پیام در تاپیکِ ثابت گروه یا همان تاپیک آخرین پیام ورودی.

        اگر مدیر گروه با <code>/topic</code> یک تاپیک ثابت تعیین کرده باشد، همهٔ
        پیام‌های ربات همان‌جا می‌روند. وگرنه ربات هرجا صدا زده شد همان‌جا جواب
        می‌دهد. (در گروه‌های فروم، پیام بدون message_thread_id در General می‌رود.)
        """
        if "message_thread_id" not in kwargs:
            home = self.storage.get_topic(chat_id)
            if home is not None:
                # ۰ و ۱ یعنی تاپیک General؛ برای ارسال باید thread حذف شود.
                if home not in (0, 1):
                    kwargs["message_thread_id"] = home
            else:
                thread = self.threads.get(chat_id)
                if thread:
                    kwargs["message_thread_id"] = thread
        return self.api.send_message(chat_id, text, **kwargs)

    # -------------------------------------------------------- پردازش آپدیت
    def handle_update(self, update: dict) -> None:
        try:
            if "message" in update:
                self._on_message(update["message"])
            elif "callback_query" in update:
                self._on_callback(update["callback_query"])
        except TelegramError as exc:
            if "not modified" in (exc.description or ""):
                return
            logger.warning("خطای تلگرام: %s", exc)
        except Exception:  # noqa: BLE001 - یک آپدیت خراب نباید حلقه را بخواباند
            logger.exception("خطای پیش‌بینی‌نشده در پردازش آپدیت")

    # ---------------------------------------------------------- پیام‌ها
    def _on_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        user = message.get("from") or {}
        if chat_id is None or user.get("is_bot"):
            return

        text = (message.get("text") or "").strip()
        # در گروه فروم، تاپیکی که فرمان از آنجا آمده را نگه می‌داریم تا جواب همان‌جا برود.
        if chat_id is not None:
            self.threads[chat_id] = message.get("message_thread_id")
        command, argument = "", ""
        if text.startswith("/"):
            head, _, argument = text.partition(" ")
            command = head.split("@")[0].lower()
        argument = argument.strip()

        if command == "/start":
            self._cmd_start(chat, user)
        elif command in ("/duel", "/دوئل"):
            self._cmd_duel(chat, user, argument)
        elif command in ("/join", "/پیوستن"):
            self._cmd_join(chat, user)
        elif command in ("/cancel", "/لغو"):
            self._cmd_cancel_lobby(chat, user)
        elif command in ("/surrender", "/resign", "/تسلیم"):
            self._cmd_surrender(chat, user)
        elif command in ("/score", "/table", "/جدول", "/امتیازات"):
            self._cmd_score(chat, user)
        elif command in ("/solo", "/new", "/تکنفره"):
            if self._is_group(chat):
                self._send(
                    chat_id, ui.DUEL_INTRO_TEXT, reply_markup=ui.duel_intro_keyboard()
                )
            else:
                self._cmd_solo(chat, user)
        elif command in ("/help", "/راهنما"):
            self._send(chat_id, ui.HELP_TEXT)
        elif command in ("/topic", "/تاپیک", "/موضوع"):
            self._cmd_topic(chat, user, argument, message.get("message_thread_id"))
        elif command in ("/stats", "/آمار"):
            self._send(chat_id, self._stats_text(chat, user))
        elif command in ("/top", "/برترین"):
            self._send(chat_id, self._top_text())
        elif text and not text.startswith("/") and not self._is_group(chat):
            self._send(
                chat_id,
                "برای دوئل دو نفره مرا به یک گروه اضافه کن و <code>/duel</code> بزن.\n"
                "برای بازی تک‌نفره همین‌جا: /solo\n"
                "راهنمای کامل: /help",
            )

    # ------------------------------------------------------------ دستورها
    def _cmd_start(self, chat: dict, user: dict) -> None:
        if self._is_group(chat):
            self._send(
                chat["id"], ui.DUEL_INTRO_TEXT, reply_markup=ui.duel_intro_keyboard()
            )
        else:
            self._send(chat["id"], ui.WELCOME_TEXT, reply_markup=ui.difficulty_keyboard())

    def _cmd_solo(self, chat: dict, user: dict) -> None:
        self._send(chat["id"], ui.MENU_TEXT, reply_markup=ui.difficulty_keyboard())

    def _is_admin(self, chat_id: int, user_id) -> bool:
        """آیا کاربر مدیر/سازندهٔ گروه است؟ اگر نتوانیم بپرسیم، مانع نمی‌شویم."""
        getter = getattr(self.api, "get_chat_member", None)
        if getter is None or user_id is None:
            return True
        try:
            member = getter(chat_id, user_id) or {}
        except (TelegramError, TelegramNetworkError) as exc:
            logger.debug("getChatMember ناموفق بود: %s", exc)
            return True
        return member.get("status") in ("creator", "administrator")

    def _cmd_topic(self, chat: dict, user: dict, argument: str, thread_id) -> None:
        """تاپیک ثابت گروه را تنظیم/حذف می‌کند تا پیام‌ها همیشه همان‌جا بروند."""
        chat_id = chat["id"]
        if not self._is_group(chat):
            self._send(chat_id, "⚙️ تنظیم تاپیک فقط برای گروه‌هاست.")
            return
        if not self._is_admin(chat_id, user.get("id")):
            self._send(chat_id, "فقط مدیران گروه می‌توانند تاپیک ربات را تنظیم کنند.")
            return

        if argument.lower() in ("off", "reset", "auto", "خاموش", "حذف", "خودکار"):
            self.storage.clear_topic(chat_id)
            self._send(
                chat_id,
                "✅ حالت خودکار روشن شد؛ از این به بعد ربات در همان تاپیکی جواب "
                "می‌دهد که پیام یا دکمه از آن آمده است.",
            )
            return
        if argument:
            self._send(
                chat_id,
                "دستور درست:\n"
                "• <code>/topic</code> — ثبت همین تاپیک به‌عنوان تاپیک ثابت ربات\n"
                "• <code>/topic off</code> — برگشت به حالت خودکار",
            )
            return

        thread = int(thread_id) if thread_id else 0
        self.storage.set_topic(chat_id, thread)
        if thread and thread != 1:
            self._send(
                chat_id,
                "✅ ثبت شد! از این به بعد همهٔ پیام‌های ربات در <b>همین تاپیک</b> "
                "فرستاده می‌شوند.\nبرای برگشت به حالت خودکار: <code>/topic off</code>",
            )
        else:
            self._send(
                chat_id,
                "✅ تاپیک ثابت روی <b>General</b> تنظیم شد.\n"
                "برای برگشت به حالت خودکار: <code>/topic off</code>",
            )

    def _cmd_duel(self, chat: dict, user: dict, argument: str = "") -> None:
        chat_id = chat["id"]
        if not self._is_group(chat):
            self._send(
                chat_id,
                "⚔️ دوئل دو نفره فقط در <b>گروه</b> کار می‌کند.\n"
                "مرا به یک گروه اضافه کن و آنجا <code>/duel</code> را بزن.\n"
                "همین‌جا می‌توانی تک‌نفره بازی کنی: /solo",
            )
            return
        # چند دعوت و چند دوئل همزمان در یک گروه مجاز است.
        key = LEVEL_ALIASES.get(argument.lower(), DEFAULT_DUEL_LEVEL) if argument else DEFAULT_DUEL_LEVEL
        self._open_lobby(chat, user, key)

    def _open_lobby(self, chat: dict, user: dict, level_key: str) -> None:
        chat_id = chat["id"]
        lobby = Lobby(
            chat_id=chat_id,
            host=self._player(user),
            difficulty_key=level_key if level_key in DIFFICULTIES else DEFAULT_DUEL_LEVEL,
            created_at=self.clock(),
            group_title=chat.get("title") or "",
        )
        with self._lock:
            self.lobbies[lobby.id] = lobby
        sent = self._send(
            chat_id, ui.duel_lobby_text(lobby), reply_markup=ui.duel_lobby_keyboard(lobby)
        )
        lobby.message_id = (sent or {}).get("message_id")

    # ------------------------------------------------------------- کمکی دوئل
    def _active_lobbies(self, chat_id: int) -> list[Lobby]:
        now = self.clock()
        with self._lock:
            return [
                lobby
                for lobby in self.lobbies.values()
                if lobby.chat_id == chat_id and not lobby.is_expired(now)
            ]

    def _active_matches(self, chat_id: int) -> list[DuelMatch]:
        with self._lock:
            return [
                match
                for match in self.duels.values()
                if match.chat_id == chat_id and not match.is_finished
            ]

    def _finished_matches(self, chat_id: int) -> list[DuelMatch]:
        with self._lock:
            return [
                match
                for match in self.duels.values()
                if match.chat_id == chat_id and match.is_finished
            ]

    def _resolve_lobby(self, chat_id: int, lobby_id: str | None) -> Lobby | None:
        """دعوتِ با شناسه، یا در حالت قدیمی تنها دعوتِ فعال گروه."""
        if lobby_id:
            with self._lock:
                lobby = self.lobbies.get(lobby_id)
            if lobby is None or lobby.chat_id != chat_id:
                return None
            return lobby
        candidates = self._active_lobbies(chat_id)
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_match(self, chat_id: int, match_id: str) -> DuelMatch | None:
        """دوئلِ با شناسه، فقط اگر متعلق به همین گروه باشد."""
        with self._lock:
            match = self.duels.get(match_id)
        if match is None or match.chat_id != chat_id:
            return None
        return match

    def _match_for_message(self, chat_id: int, message_id) -> DuelMatch | None:
        """دوئلی که پیامش همین message_id است (برای دکمه‌های نسخهٔ قدیمی)."""
        if message_id is None:
            return None
        with self._lock:
            candidates = [
                match
                for match in self.duels.values()
                if match.chat_id == chat_id and match.message_id == message_id
            ]
        active = [match for match in candidates if not match.is_finished]
        if len(active) == 1:
            return active[0]
        if len(active) > 1:
            return None
        return candidates[0] if len(candidates) == 1 else None

    def _cmd_join(self, chat: dict, user: dict) -> None:
        chat_id = chat["id"]
        lobbies = self._active_lobbies(chat_id)
        if not lobbies:
            self._send(chat_id, "دعوت فعالی نیست؛ با <code>/duel</code> یکی بساز.")
            return
        if len(lobbies) == 1:
            self._join_lobby(None, chat, user, None, lobbies[0].id)
            return
        self._send(
            chat_id,
            "چند دعوت دوئل باز است؛ یکی را انتخاب کن:",
            reply_markup=ui.lobby_pick_keyboard(lobbies),
        )

    def _cmd_cancel_lobby(self, chat: dict, user: dict) -> None:
        chat_id = chat["id"]
        lobbies = self._active_lobbies(chat_id)
        mine = [lobby for lobby in lobbies if lobby.host.user_id == user.get("id")]
        if not mine:
            if lobbies:
                msg = "فقط کسی که دوئل را ساخته می‌تواند آن را لغو کند."
            else:
                msg = "دعوت فعالی برای لغو کردن نیست."
            self._send(chat_id, msg)
            return
        if len(mine) == 1:
            with self._lock:
                self.lobbies.pop(mine[0].id, None)
            self._send(chat_id, "❌ دعوت دوئل لغو شد.")
            return
        self._send(
            chat_id,
            "کدام دعوت را لغو کنم؟",
            reply_markup=ui.cancel_pick_keyboard(mine),
        )

    def _cmd_surrender(self, chat: dict, user: dict) -> None:
        chat_id = chat["id"]
        mine = [
            match
            for match in self._active_matches(chat_id)
            if match.player_of(user.get("id")) is not None
        ]
        if not mine:
            self._send(chat_id, "دوئل فعالی در این گفتگو نیست.")
            return
        if len(mine) == 1:
            error = self._surrender_match(mine[0], user)
            if error:
                self._send(chat_id, error)
            return
        self._send(
            chat_id,
            "در چند دوئل هستی؛ کدام را تسلیم می‌شوی؟",
            reply_markup=ui.surrender_pick_keyboard(mine),
        )

    def _surrender_match(self, match: DuelMatch, user: dict) -> str | None:
        """تسلیم شدنِ کاربر در یک دوئل. خطا را برمی‌گرداند وگرنه None."""
        with match.lock:
            player = match.player_of(user.get("id"))
            if player is None:
                return "تو بازیکن این دوئل نیستی 😄"
            if match.is_finished:
                return "این دوئل تمام شده است."
            match.resign(player.user_id)
            self._record_duel(match)
            self._render_duel(match, edit_message_id=match.message_id)
            self._send(
                match.chat_id,
                f"🏳️ {html_escape(player.name)} تسلیم شد؛ "
                f"<b>{html_escape(match.winner.name)}</b> برد! "
                f"(💣 {fa(match.found[0])} — {fa(match.found[1])})",
            )
        return None

    def _cmd_score(self, chat: dict, user: dict) -> None:
        chat_id = chat["id"]
        if self._is_group(chat):
            self._send(chat_id, self._score_text(chat_id, chat.get("title")))
        else:
            self._send(chat_id, self._duel_stats_text(user.get("id")))

    # -------------------------------------------------------- دکمه‌های شیشه‌ای
    def _on_callback(self, callback: dict) -> None:
        cb_id = callback.get("id")
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        user = callback.get("from") or {}

        if chat_id is None:
            self._answer(cb_id)
            return

        # تاپیک پیام دکمه‌ای را هم ثبت می‌کنیم تا پیام‌های تازه در همان تاپیک بروند.
        # (پیامِ بدون message_thread_id یعنی تاپیک General؛ پس None ذخیره می‌شود.)
        self.threads[chat_id] = message.get("message_thread_id")

        # ---------------------------------------------------------- دوئل
        if data == ui.CB_DUEL_NEW:
            if not self._is_group(chat):
                self._answer(cb_id, "دوئل فقط در گروه ممکن است؛ مرا به یک گروه اضافه کن.", alert=True)
                return
            self._answer(cb_id)
            self._open_lobby(chat, user, DEFAULT_DUEL_LEVEL)
            return

        if data.startswith(ui.CB_DUEL_SURRENDER):
            match_id = data[len(ui.CB_DUEL_SURRENDER):]
            match = self.duels.get(match_id)
            if match is None or match.chat_id != chat_id:
                self._answer(cb_id, "این دوئل دیگر فعال نیست.", alert=True)
                return
            error = self._surrender_match(match, user)
            if error:
                self._answer(cb_id, error, alert=True)
            else:
                self._answer(cb_id)
            return

        if data == ui.CB_DUEL_JOIN or data.startswith(ui.CB_DUEL_JOIN + ":"):
            lobby_id = (
                data[len(ui.CB_DUEL_JOIN) + 1:]
                if len(data) > len(ui.CB_DUEL_JOIN)
                else None
            )
            self._join_lobby(cb_id, chat, user, message_id, lobby_id)
            return

        if data.startswith(ui.CB_DUEL_LEVEL):
            rest = data[len(ui.CB_DUEL_LEVEL):]
            parts = rest.split(":")
            lobby_id, key = (parts[0], parts[1]) if len(parts) == 2 else (None, rest)
            lobby = self._resolve_lobby(chat_id, lobby_id)
            if lobby is None or lobby.is_expired(self.clock()):
                self._answer(cb_id, "این دعوت منقضی شده است؛ /duel را بزن.", alert=True)
                return
            if lobby.host.user_id != user.get("id"):
                self._answer(cb_id, "فقط سازندهٔ دوئل می‌تواند سطح را عوض کند.", alert=True)
                return
            if key not in DIFFICULTIES:
                self._answer(cb_id, "سطح نامعتبر است.", alert=True)
                return
            lobby.difficulty_key = key
            self._answer(cb_id, f"سطح: {DIFFICULTIES[key].title}")
            self.api.edit_message_text(
                chat_id,
                message_id,
                ui.duel_lobby_text(lobby),
                reply_markup=ui.duel_lobby_keyboard(lobby),
            )
            return

        if data == ui.CB_DUEL_CANCEL or data.startswith(ui.CB_DUEL_CANCEL + ":"):
            lobby_id = (
                data[len(ui.CB_DUEL_CANCEL) + 1:]
                if len(data) > len(ui.CB_DUEL_CANCEL)
                else None
            )
            lobby = self._resolve_lobby(chat_id, lobby_id)
            if lobby is None:
                self._answer(cb_id, "دعوتی برای لغو کردن نیست.", alert=True)
                return
            if lobby.host.user_id != user.get("id"):
                self._answer(cb_id, "فقط سازندهٔ دوئل می‌تواند لغو کند.", alert=True)
                return
            with self._lock:
                self.lobbies.pop(lobby.id, None)
            self._answer(cb_id, "دعوت لغو شد.")
            self.api.edit_message_text(
                chat_id,
                message_id,
                "❌ <b>دعوت دوئل لغو شد.</b>\nبرای شروع دوباره /duel را بزن.",
            )
            return

        if data == ui.CB_DUEL_REMATCH or data.startswith(ui.CB_DUEL_REMATCH + ":"):
            match_id = (
                data[len(ui.CB_DUEL_REMATCH) + 1:]
                if len(data) > len(ui.CB_DUEL_REMATCH)
                else None
            )
            self._rematch(cb_id, chat_id, message_id, user, match_id)
            return

        if data == ui.CB_DUEL_TABLE:
            self._answer(cb_id)
            if self._is_group(chat):
                self._send(chat_id, self._score_text(chat_id, chat.get("title")))
            else:
                self._send(chat_id, self._duel_stats_text(user.get("id")))
            return

        if data.startswith(ui.CB_DUEL_TAP):
            parts = data.split(":")
            # قالب جدید: dt:<match_id>:<r>:<c> — قالب قدیمی: dt:<r>:<c>
            if len(parts) == 4 and parts[2].lstrip("-").isdigit() and parts[3].lstrip("-").isdigit():
                self._duel_tap(
                    cb_id, chat_id, message_id, user, parts[1], int(parts[2]), int(parts[3])
                )
                return
            if len(parts) == 3 and all(p.lstrip("-").isdigit() for p in parts[1:]):
                # دکمه‌های نسخهٔ قدیمی (بدون شناسهٔ دوئل): اول از روی همان پیام
                # تشخیص می‌دهیم مال کدام دوئل است؛ وگرنه فقط اگر یک دوئل فعال باشد.
                match = self._match_for_message(chat_id, message_id)
                if match is None:
                    active = self._active_matches(chat_id)
                    if len(active) == 1:
                        match = active[0]
                if match is not None:
                    self._duel_tap(
                        cb_id, chat_id, message_id, user, match.id, int(parts[1]), int(parts[2])
                    )
                else:
                    self._answer(
                        cb_id,
                        "این دکمه مال پیام/نسخهٔ قبلی ربات است و آن بازی دیگر در حافظه نیست.\n"
                        "یک دوئل تازه بساز: /duel",
                        alert=True,
                    )
                return
            self._answer(cb_id, "این دکمه دیگر معتبر نیست؛ /duel را بزن.", alert=True)
            return

        # -------------------------------------------------------- عمومی
        if data == ui.CB_HELP:
            self._answer(cb_id)
            self._send(chat_id, ui.HELP_TEXT)
            return

        if data == ui.CB_STATS:
            self._answer(cb_id)
            self._send(chat_id, self._stats_text(chat, user))
            return

        # ------------------------------------------------------- تک‌نفره
        if data == ui.CB_MENU:
            self._answer(cb_id)
            self.api.edit_message_text(
                chat_id, message_id, ui.MENU_TEXT, reply_markup=ui.difficulty_keyboard()
            )
            return

        if data.startswith(ui.CB_SOLO_DIFFICULTY):
            key = data[len(ui.CB_SOLO_DIFFICULTY):]
            if key not in DIFFICULTIES:
                self._answer(cb_id, "سطح نامعتبر است.")
                return
            game = SoloGame(
                chat_id=chat_id, user_id=int(user.get("id")), board=Board(DIFFICULTIES[key])
            )
            with self._lock:
                self.solo[(chat_id, game.user_id)] = game
            self._answer(cb_id, f"سطح: {DIFFICULTIES[key].title}")
            self._render_solo(game, edit_message_id=message_id)
            return

        if data == ui.CB_FLAG_MODE:
            game = self._solo_game(chat_id, user.get("id"))
            if game is None:
                self._answer(cb_id, "بازی فعالی برای تو نیست؛ /solo را بزن.", alert=True)
                return
            with game.lock:
                game.flag_mode = not game.flag_mode
                self._answer(
                    cb_id,
                    "🚩 حالت پرچم‌گذاری روشن شد" if game.flag_mode else "⛏ حالت کندن روشن شد",
                )
                self._render_solo(game, edit_message_id=message_id)
            return

        if data.startswith(ui.CB_TAP):
            parts = data.split(":")
            if len(parts) != 3 or not all(p.lstrip("-").isdigit() for p in parts[1:]):
                self._answer(cb_id, "این دکمه دیگر معتبر نیست؛ /solo را بزن.")
                return
            self._solo_tap(cb_id, chat_id, message_id, user, int(parts[1]), int(parts[2]))
            return

        if data.startswith("noop:"):
            self._answer(cb_id)
            return

        self._answer(cb_id)

    # ------------------------------------------------------------------ دوئل
    def _join_lobby(self, cb_id, chat: dict, user: dict, message_id, lobby_id: str | None = None) -> None:
        chat_id = chat.get("id") if chat else None
        if lobby_id:
            with self._lock:
                lobby = self.lobbies.get(lobby_id)
            if lobby is None or lobby.chat_id != chat_id:
                self._tell(cb_id, chat_id, "این دعوت منقضی شده است؛ با /duel یکی بساز.", alert=True)
                return
        else:
            candidates = self._active_lobbies(chat_id)
            if len(candidates) > 1:
                if cb_id:
                    self._answer(cb_id)
                self._send(
                    chat_id,
                    "چند دعوت دوئل باز است؛ یکی را انتخاب کن:",
                    reply_markup=ui.lobby_pick_keyboard(candidates),
                )
                return
            lobby = candidates[0] if candidates else None
            if lobby is None:
                self._tell(cb_id, chat_id, "این دعوت منقضی شده است؛ با /duel یکی بساز.", alert=True)
                return
        if lobby.is_expired(self.clock()):
            with self._lock:
                self.lobbies.pop(lobby.id, None)
            self._tell(cb_id, chat_id, "این دعوت منقضی شده است؛ با /duel یکی بساز.", alert=True)
            return

        player = self._player(user)
        if player.user_id == lobby.host.user_id:
            self._tell(cb_id, chat_id, "خودت که نمی‌توانی با خودت دوئل کنی! 😄", alert=True)
            return

        # چند دوئل همزمان در یک گروه مجاز است؛ بررسی «دوئل در جریان» حذف شد.
        match = DuelMatch(
            chat_id=chat_id,
            difficulty=DIFFICULTIES[lobby.difficulty_key],
            players=[lobby.host, player],
            clock=self.clock,
            group_title=lobby.group_title,
            message_id=lobby.message_id or message_id,
        )
        with self._lock:
            self.duels[match.id] = match
            self.lobbies.pop(lobby.id, None)

        self._answer(cb_id, f"دوئل شروع شد! اول {match.current.name} بازی می‌کند.")
        self._render_duel(match, edit_message_id=match.message_id)

    def _duel_tap(self, cb_id, chat_id: int, message_id, user: dict, match_id: str, r: int, c: int) -> None:
        match = self.duels.get(match_id)
        if match is None or match.chat_id != chat_id:
            self._answer(cb_id, "این دوئل دیگر فعال نیست؛ /duel را بزن.", alert=True)
            return
        with match.lock:
            result = match.play(user.get("id"), r, c)
            toast, alert = self._duel_toast(result, match)
            changed = result in (
                DuelResult.OPENED,
                DuelResult.MINE_FOUND,
                DuelResult.WON,
                DuelResult.LOST,
                DuelResult.DRAW,
            )
            if result in (DuelResult.WON, DuelResult.LOST, DuelResult.DRAW):
                self._record_duel(match)
            if changed:
                self._render_duel(match, edit_message_id=match.message_id or message_id)
            self._answer(cb_id, toast, alert=alert)

    def _duel_toast(self, result: str, match: DuelMatch) -> tuple[str | None, bool]:
        bombs = f"{fa(match.found[0])} — {fa(match.found[1])}"
        if result == DuelResult.OPENED:
            return f"✅ باز شد؛ عدد نمایش داده شد — نوبت {match.current.name}", False
        if result == DuelResult.MINE_FOUND:
            total = fa(match.board.total_mines)
            return (
                f"💣 بمب پیدا کردی! دوباره یک خانه انتخاب کن. "
                f"(مجموع: {fa(sum(match.found))} از {total})",
                False,
            )
        if result == DuelResult.WON:
            return f"🏆 بردی! بمب‌ها: {bombs}", True
        if result == DuelResult.LOST:
            return f"😔 باختی؛ بمب‌ها: {bombs}", True
        if result == DuelResult.DRAW:
            return f"🤝 مساوی شد! بمب‌ها: {bombs}", True
        if result == DuelResult.NOT_YOUR_TURN:
            return f"⏳ نوبت {match.current.name} است.", True
        if result == DuelResult.NOT_PLAYER:
            return "تو بازیکن این دوئل نیستی 😄", True
        if result == DuelResult.FINISHED:
            return "این دوئل تمام شده؛ «🔁 دوئل مجدد» را بزن.", True
        if result == DuelResult.NOOP:
            return "این خانه قبلاً باز شده؛ یک خانهٔ پوشیدهٔ دیگر را انتخاب کن.", False
        return None, False

    def _rematch(self, cb_id, chat_id: int, message_id, user: dict, match_id: str | None = None) -> None:
        if match_id:
            match = self._resolve_match(chat_id, match_id)
            if match is None:
                self._answer(cb_id, "این دوئل دیگر وجود ندارد؛ /duel را بزن.", alert=True)
                return
        else:
            # دکمهٔ قدیمی (بدون شناسه): اگر دقیقاً یک دوئل تمام‌شده باشد.
            done = self._finished_matches(chat_id)
            match = done[0] if len(done) == 1 else None
        if match is None or not match.is_finished:
            self._answer(cb_id, "دوئل تمام‌شده‌ای برای تکرار نیست؛ /duel را بزن.", alert=True)
            return
        if match.player_of(user.get("id")) is None:
            self._answer(cb_id, "فقط دو بازیکن همان دوئل می‌توانند مجدد بازی کنند.", alert=True)
            return
        new_match = match.next_match(message_id=match.message_id or message_id)
        with self._lock:
            self.duels[new_match.id] = new_match
        self._answer(cb_id, f"🔁 دوئل مجدد! اول {new_match.current.name} بازی می‌کند.")
        self._render_duel(new_match, edit_message_id=new_match.message_id)

    def _record_duel(self, match: DuelMatch) -> None:
        if match.recorded or match.winner is None or match.loser is None:
            return
        match.recorded = True
        match.summary = self.storage.record_duel(
            chat_id=match.chat_id,
            winner_id=match.winner.user_id,
            winner_name=match.winner.name,
            loser_id=match.loser.user_id,
            loser_name=match.loser.name,
            level=match.difficulty.key,
            seconds=int(round(match.elapsed())),
            group_title=match.group_title,
        )
        logger.info(
            "دوئل %s: %s برد %s (سطح %s، %s ثانیه)",
            match.chat_id,
            match.winner.name,
            match.loser.name,
            match.difficulty.key,
            match.summary.get("seconds"),
        )

    def _render_duel(self, match: DuelMatch, edit_message_id=None) -> None:
        text = ui.duel_text(match)
        markup = ui.duel_finished_keyboard(match) if match.is_finished else ui.duel_keyboard(match)
        if edit_message_id:
            try:
                self.api.edit_message_text(match.chat_id, edit_message_id, text, reply_markup=markup)
                match.message_id = edit_message_id
                return
            except TelegramError as exc:
                if "not modified" in (exc.description or ""):
                    return
                logger.warning("ویرایش پیام دوئل ناموفق بود: %s", exc)
        sent = self._send(match.chat_id, text, reply_markup=markup)
        match.message_id = (sent or {}).get("message_id") or match.message_id

    # ------------------------------------------------------------ تایم‌اوت
    def _timeout_notice(self, match: DuelMatch) -> str:
        counts = (
            f"💣 بمب‌ها: {html_escape(match.players[0].name)} {fa(match.found[0])} — "
            f"{fa(match.found[1])} {html_escape(match.players[1].name)}"
        )
        if match.winner is None:
            return f"⏰ <b>۱۰ دقیقه بدون حرکت؛ دوئل مساوی تمام شد.</b>\n{counts}"
        return (
            f"⏰ <b>۱۰ دقیقه بدون حرکت؛ دوئل خودکار تمام شد.</b>\n"
            f"🏆 {html_escape(match.winner.name)} برنده شد!\n{counts}"
        )

    def _sweep_idle(self) -> None:
        """دوئل‌های بی‌حرکتِ ۱۰ دقیقه‌ای را تمام و دعوت‌های منقضی را پاک می‌کند."""
        now = self.clock()
        with self._lock:
            expired = [
                lobby_id
                for lobby_id, lobby in self.lobbies.items()
                if lobby.is_expired(now)
            ]
            for lobby_id in expired:
                self.lobbies.pop(lobby_id, None)
            idle = [match for match in self.duels.values() if not match.is_finished]

        for match in idle:
            with match.lock:
                if not match.check_timeout(now):
                    continue
                self._record_duel(match)
                self._render_duel(match, edit_message_id=match.message_id)
                try:
                    self._send(match.chat_id, self._timeout_notice(match))
                except TelegramError as exc:  # pragma: no cover - شبکه
                    logger.warning("ارسال پیام تایم‌اوت ناموفق بود: %s", exc)
                logger.info(
                    "تایم‌اوت دوئل %s در گروه %s (بمب‌ها: %s — %s)",
                    match.id,
                    match.chat_id,
                    match.found[0],
                    match.found[1],
                )

    def _watchdog_loop(self, stop: threading.Event) -> None:
        while not stop.wait(15):
            try:
                self._sweep_idle()
            except Exception:  # noqa: BLE001 - نگهبان نباید بخوابد
                logger.exception("خطا در بررسی تایم‌اوت دوئل‌ها")

    # --------------------------------------------------------------- تک‌نفره
    def _solo_game(self, chat_id: int, user_id) -> SoloGame | None:
        if user_id is None:
            return None
        with self._lock:
            return self.solo.get((int(chat_id), int(user_id)))

    def _solo_tap(self, cb_id, chat_id: int, message_id, user: dict, r: int, c: int) -> None:
        game = self._solo_game(chat_id, user.get("id"))
        if game is None:
            self._answer(cb_id, "بازی فعالی برای تو نیست؛ /solo را بزن.", alert=True)
            return
        with game.lock:
            board = game.board
            result = board.toggle_flag(r, c) if game.flag_mode else board.tap(r, c)
            if game.started_at is None and board.status != READY:
                game.started_at = self.clock()
            if board.is_finished:
                if game.finished_at is None:
                    game.finished_at = self.clock()
                if not game.stats_recorded:
                    game.stats_recorded = True
                    self.storage.record(
                        user.get("id"),
                        self._display_name(user),
                        board.difficulty.key,
                        board.status == WON,
                        int(round(self._solo_elapsed(game))),
                    )
            self._answer(cb_id, self._solo_toast(result, game), alert=board.is_finished)
            self._render_solo(game, edit_message_id=message_id)

    def _solo_elapsed(self, game: SoloGame) -> float:
        if game.started_at is None:
            return 0.0
        end = game.finished_at if game.finished_at is not None else self.clock()
        return max(0.0, end - game.started_at)

    def _solo_toast(self, result: str, game: SoloGame) -> str | None:
        if result == MoveResult.WON:
            return f"🎉 بردی! زمان: {fa_duration(self._solo_elapsed(game))}"
        if result == MoveResult.BOOM:
            return "💥 بوم! روی مین رفتی."
        if result == MoveResult.FLAGGED:
            return "🚩 پرچم گذاشته شد."
        if result == MoveResult.UNFLAGGED:
            return "پرچم برداشته شد."
        if result == MoveResult.BLOCKED:
            return "این خانه پرچم دارد؛ اول پرچم را بردار."
        if result == MoveResult.FINISHED:
            return "این بازی تمام شده است. /solo را بزن."
        return None

    def _render_solo(self, game: SoloGame, edit_message_id=None) -> None:
        board = game.board
        text = ui.build_text(board, flag_mode=game.flag_mode, elapsed=self._solo_elapsed(game))
        markup = ui.finished_keyboard(board) if board.is_finished else ui.build_keyboard(board, game.flag_mode)
        if edit_message_id:
            try:
                self.api.edit_message_text(game.chat_id, edit_message_id, text, reply_markup=markup)
                return
            except TelegramError as exc:
                if "not modified" in (exc.description or ""):
                    return
                logger.warning("ویرایش پیام بازی ناموفق بود: %s", exc)
        self._send(game.chat_id, text, reply_markup=markup)

    # ------------------------------------------------------------------ آمار
    def _score_text(self, chat_id: int, title: str | None = None) -> str:
        rows = self.storage.group_table(chat_id)
        history = self.storage.group_history(chat_id, 5)
        info = self.storage.group_info(chat_id)
        return ui.group_table_text(rows, history, info["matches"], title or info["title"])

    def _solo_stats_text(self, user_id) -> str:
        data = self.storage.get(user_id)
        if not data or not data.get("played"):
            return "🎮 <b>تک‌نفره:</b> هنوز بازی‌ای ثبت نشده است. با /solo شروع کن!"
        played = int(data.get("played", 0))
        wins = int(data.get("wins", 0))
        rate = round(wins * 100 / played) if played else 0
        lines = [
            f"🎮 <b>تک‌نفرهٔ {html_escape(str(data.get('name', '')))}</b>",
            f"بازی‌ها: {fa(played)} | بردها: {fa(wins)} | نرخ برد: {fa(rate)}٪",
            "<b>بهترین زمان‌ها</b>",
        ]
        for key, diff in DIFFICULTIES.items():
            best = (data.get("best") or {}).get(key)
            lines.append(f"• {diff.title}: {fa_duration(best) if best is not None else '—'}")
        return "\n".join(lines)

    def _duel_stats_text(self, user_id) -> str:
        data = self.storage.duel_stats(user_id)
        if not data or not data.get("matches"):
            return (
                "⚔️ <b>دوئل:</b> هنوز دوئلی بازی نکرده‌ای.\n"
                "در یک گروه <code>/duel</code> را بزن تا شروع شود."
            )
        matches = int(data.get("matches", 0))
        wins = int(data.get("wins", 0))
        losses = int(data.get("losses", 0))
        rate = round(wins * 100 / matches) if matches else 0
        return "\n".join(
            [
                f"⚔️ <b>دوئل‌های {html_escape(str(data.get('name', '')))}</b>",
                f"🎮 دوئل‌ها: {fa(matches)} | 🏆 برد: {fa(wins)} | 💥 باخت: {fa(losses)} | 📈 {fa(rate)}٪",
                "<i>جدول هر گروه را همان‌جا با /score ببین.</i>",
            ]
        )

    def _stats_text(self, chat: dict, user: dict) -> str:
        parts = [self._solo_stats_text(user.get("id")), self._duel_stats_text(user.get("id"))]
        if self._is_group(chat):
            chat_id = chat["id"]
            rows = self.storage.group_table(chat_id)
            mine = next((row for row in rows if row["user_id"] == user.get("id")), None)
            if mine:
                parts.append(
                    f"🏆 <b>در این گروه:</b> {fa(mine['wins'])} برد / {fa(mine['losses'])} باخت"
                )
                rank = rows.index(mine) + 1
                parts.append(f"رتبهٔ تو در جدول گروه: {fa(rank)} از {fa(len(rows))}")
            else:
                parts.append("🏆 <b>در این گروه:</b> هنوز دوئلی ثبت نکرده‌ای.")
        return "\n\n".join(parts)

    def _top_text(self) -> str:
        lines = ["🏆 <b>برترین زمان‌های تک‌نفره</b>"]
        for key, diff in DIFFICULTIES.items():
            rows = self.storage.top(key, limit=5)
            lines.append("")
            lines.append(f"<b>{diff.title}</b>")
            if not rows:
                lines.append("— هنوز رکوردی ثبت نشده")
                continue
            for index, row in enumerate(rows, start=1):
                lines.append(
                    f"{fa(index)}. {html_escape(str(row['name']))} — {fa_duration(row['seconds'])}"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------ حلقه
    def run(self, poll_timeout: int = 25, workers: int = 8) -> None:
        # این متد مستقیم هم صدا زده می‌شود (نه فقط از main)، پس خودش کنسول را
        # UTF-8 می‌کند تا پیام‌های فارسی/اموجی روی ویندوز خطا ندهند.
        _force_utf8_console()
        try:
            me = self.api.get_me()
        except TelegramError as exc:
            # توکن اشتباه/باطل‌شده یا وبهوک نامعتبر: پیام واضح بده، نه traceback.
            logger.error("اتصال به تلگرام ممکن نشد: %s", exc)
            print(
                "❌ ربات روشن نشد؛ توکن پذیرفته نشد.\n"
                "   • توکن را از @BotFather دوباره بگیر (اگر لو رفته: /revoke).\n"
                "   • مطمئن شو توکن کامل کپی شده و فاصلهٔ اضافه ندارد.\n"
                f"   جزئیات: {exc}"
            )
            return
        except TelegramNetworkError as exc:
            logger.error("دسترسی به تلگرام ممکن نشد: %s", exc)
            print(
                "❌ ربات روشن نشد؛ به api.telegram.org دسترسی نداریم.\n"
                "   • اینترنت/پروکسی/فیلترشکن و DNS را بررسی کن.\n"
                f"   جزئیات: {exc}"
            )
            return

        logger.info("ربات @%s آماده است (شناسه: %s)", me.get("username"), me.get("id"))
        print(f"✅ ربات @{me.get('username')} روشن شد. برای توقف Ctrl+C را بزن.")

        stop = threading.Event()

        def _handle_signal(signum, frame):  # pragma: no cover - تعاملی
            logger.info("سیگنال توقف دریافت شد (%s)", signum)
            stop.set()

        for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _handle_signal)
                except (ValueError, OSError):  # pragma: no cover
                    pass

        offset: int | None = None
        watchdog = threading.Thread(
            target=self._watchdog_loop, args=(stop,), daemon=True, name="duel-timeout"
        )
        watchdog.start()
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="update") as pool:
            while not stop.is_set():
                try:
                    updates = self.api.get_updates(offset=offset, timeout=poll_timeout) or []
                except TelegramNetworkError as exc:
                    logger.warning("خطای شبکه: %s — تلاش دوباره در ۳ ثانیه", exc)
                    stop.wait(3)
                    continue
                except TelegramError as exc:
                    if exc.retry_after:
                        logger.warning("محدودیت نرخ: %s ثانیه صبر می‌کنیم", exc.retry_after)
                        stop.wait(exc.retry_after)
                    else:
                        logger.warning("خطای تلگرام: %s — تلاش دوباره در ۵ ثانیه", exc)
                        stop.wait(5)
                    continue

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id is not None:
                        offset = max(offset or 0, update_id + 1)
                    pool.submit(self.handle_update, update)

        logger.info("ربات خاموش شد.")


# --------------------------------------------------------------------- راه‌اندازی
def _force_utf8_console() -> None:
    """روی ویندوز کنسول به‌طور پیش‌فرض UTF-8 نیست و متن فارسی خطا می‌دهد."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):  # pragma: no cover
            pass


def resolve_token(args) -> str:
    if args.token:
        return args.token.strip()
    env = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if env:
        return env.strip()
    token_file = Path(args.token_file)
    if token_file.is_file():
        content = token_file.read_text(encoding="utf-8").strip()
        if content and not content.startswith("#"):
            return content
    raise SystemExit(
        "توکن ربات پیدا نشد!\n"
        "۱) از @BotFather در تلگرام یک ربات بساز و توکن بگیر.\n"
        "۲) توکن را یکی از این سه راه بده:\n"
        "   • python bot.py --token 123456:ABC-DEF...\n"
        "   • set BOT_TOKEN=123456:ABC-DEF...  سپس python bot.py\n"
        f"   • توکن را در فایل {token_file} بگذار.\n"
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ربات تلگرامی مین‌روب (دوئل دو نفره + تک‌نفره)")
    parser.add_argument("--token", "-t", help="توکن ربات از BotFather")
    parser.add_argument(
        "--token-file",
        default=str(BASE_DIR / "token.txt"),
        help="مسیر فایلی که توکن در آن است (پیش‌فرض: token.txt)",
    )
    parser.add_argument(
        "--stats-file",
        default=str(BASE_DIR / "stats.json"),
        help="مسیر فایل ذخیرهٔ آمار (پیش‌فرض: stats.json)",
    )
    parser.add_argument("--poll-timeout", type=int, default=25, help="زمان انتظار long-polling (ثانیه)")
    parser.add_argument("--workers", type=int, default=8, help="تعداد تردهای پردازش آپدیت")
    parser.add_argument("--verbose", "-v", action="store_true", help="نمایش لاگ کامل")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _force_utf8_console()
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    token = resolve_token(args)
    api = TelegramAPI(token)
    try:
        api.delete_webhook()
    except (TelegramError, TelegramNetworkError) as exc:
        logger.warning("deleteWebhook ناموفق بود (%s)؛ ادامه می‌دهیم.", exc)

    bot = MinesweeperBot(api, StatsStorage(args.stats_file))
    try:
        bot.run(poll_timeout=args.poll_timeout, workers=args.workers)
    except KeyboardInterrupt:  # pragma: no cover
        print("\n👋 خاموش شد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
