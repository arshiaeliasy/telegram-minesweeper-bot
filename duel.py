"""منطق دوئل دو نفره روی یک تختهٔ مشترک (بدون وابستگی به تلگرام).

قواعد دوئل (هدف: پیدا کردن بمب):
* دو بازیکن به نوبت یک خانهٔ پوشیده را باز می‌کنند.
* باز کردن مین → یک بمب پیدا شد؛ امتیاز +۱ و همان بازیکن دوباره انتخاب می‌کند.
* باز کردن خانهٔ امن → عددِ مین‌های اطراف نمایش داده می‌شود و نوبت به حریف می‌رود.
* بازی وقتی همهٔ مین‌ها پیدا شوند تمام می‌شود؛ بیشترین بمب برنده است (مساوی = مساوی).
* تایم‌اوت: ۱۰ دقیقه بدون هیچ کلیک → بازی خودکار تمام و بمب‌ها مقایسه می‌شوند.
* اولین کلیک هرگز مین نیست؛ مین‌ها بعد از اولین کلیک کاشته می‌شوند.
* تسلیم: هر بازیکن هر زمان بخواهد می‌تواند تسلیم شود و می‌بازد.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from minesweeper import READY as BOARD_READY
from minesweeper import Board, Difficulty, MoveResult

# وضعیت‌های دوئل
LOBBY = "lobby"
PLAYING = "playing"
FINISHED = "finished"

# علت پایان
REASON_SCORE = "score"       # همهٔ مین‌ها پیدا شدند
REASON_TIMEOUT = "timeout"   # ۱۰ دقیقه بدون حرکت
REASON_RESIGN = "resign"

# مهلت دعوت‌نامه (ثانیه)
LOBBY_TTL = 15 * 60
# مهلت بی‌حرکتی در جریان بازی (ثانیه)
DUEL_TIMEOUT = 10 * 60


def new_id() -> str:
    """شناسهٔ کوتاه و یکتا برای دکمه‌های callback (≤۶۴ بایت)."""
    return uuid.uuid4().hex[:8]


class DuelResult:
    OPENED = "opened"          # خانهٔ امن باز شد؛ عدد نمایش داده شد و نوبت عوض شد
    MINE_FOUND = "mine_found"  # بمب پیدا شد؛ همان بازیکن دوباره انتخاب می‌کند
    WON = "won"                # بازی تمام شد؛ این بازیکن برد
    LOST = "lost"              # بازی تمام شد؛ این بازیکن باخت
    DRAW = "draw"              # بازی تمام شد؛ مساوی
    NOT_YOUR_TURN = "not_your_turn"
    NOT_PLAYER = "not_player"
    FINISHED = "finished"
    NOOP = "noop"


@dataclass(frozen=True)
class Player:
    user_id: int
    name: str


@dataclass
class Lobby:
    """دعوت‌نامهٔ دوئل که منتظر بازیکن دوم است."""

    chat_id: int
    host: Player
    difficulty_key: str
    created_at: float
    group_title: str = ""
    message_id: int | None = None
    id: str = field(default_factory=new_id)

    def is_expired(self, now: float) -> bool:
        return now - self.created_at > LOBBY_TTL


@dataclass
class DuelMatch:
    chat_id: int
    difficulty: Difficulty
    players: list[Player]
    clock: Callable[[], float] = time.monotonic
    rng: random.Random | None = None
    starting_index: int = 0
    group_title: str = ""
    message_id: int | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        self.board = Board(self.difficulty, rng=self.rng, collect=True)
        self.status = BOARD_READY
        self.turn_index = self.starting_index % len(self.players)
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.winner: Player | None = None
        self.loser: Player | None = None
        self.reason: str | None = None
        self.moves = 0
        self.found: list[int] = [0 for _ in self.players]  # بمب‌های پیداشدهٔ هر بازیکن
        self.last_move: str | None = None
        self.last_activity: float = self.clock()
        self.recorded = False
        self.summary: dict | None = None
        self.lock = threading.RLock()

    # ------------------------------------------------------------- بازیکنان
    @property
    def current(self) -> Player:
        return self.players[self.turn_index]

    @property
    def opponent(self) -> Player:
        return self.players[(self.turn_index + 1) % len(self.players)]

    @property
    def is_finished(self) -> bool:
        return self.status == FINISHED

    def player_of(self, user_id: int | None) -> Player | None:
        for player in self.players:
            if player.user_id == user_id:
                return player
        return None

    def bombs_of(self, player: Player) -> int:
        try:
            return self.found[self.players.index(player)]
        except ValueError:  # pragma: no cover - بازیکنِ خارج از بازی
            return 0

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else self.clock()
        return max(0.0, end - self.started_at)

    # --------------------------------------------------------------- حرکت‌ها
    def play(self, user_id: int | None, r: int, c: int) -> str:
        """کندن یک خانه. نتیجه یکی از مقادیر DuelResult است."""
        player = self.player_of(user_id)
        if player is None:
            return DuelResult.NOT_PLAYER
        if self.status == FINISHED:
            return DuelResult.FINISHED
        if player is not self.current:
            return DuelResult.NOT_YOUR_TURN

        # هر کلیکِ معتبرِ بازیکنِ نوبت، تایم‌اوت را جلو می‌اندازد.
        self.last_activity = self.clock()

        if self.status == BOARD_READY:
            self.started_at = self.clock()
            self.status = PLAYING

        result = self.board.tap(r, c)

        if result == MoveResult.MINE_FOUND:
            self.found[self.players.index(player)] += 1
            self.moves += 1
            self.last_move = f"💣 {player.name} بمب پیدا کرد!"
            if self.board.is_finished:
                return self._finish_by_score(REASON_SCORE, player)
            return DuelResult.MINE_FOUND  # نوبت همان بازیکن می‌ماند

        if result == MoveResult.REVEALED:
            self.moves += 1
            self.turn_index = (self.turn_index + 1) % len(self.players)
            self.last_move = f"👆 {player.name} خانهٔ امن باز کرد؛ عدد نمایش داده شد."
            if self.board.is_finished:
                return self._finish_by_score(REASON_SCORE, player)
            return DuelResult.OPENED

        return DuelResult.NOOP

    def resign(self, user_id: int | None) -> str:
        player = self.player_of(user_id)
        if player is None:
            return DuelResult.NOT_PLAYER
        if self.status == FINISHED:
            return DuelResult.FINISHED
        self.last_move = f"🏳️ {player.name} تسلیم شد."
        self._finish(
            winner=self.players[(self.players.index(player) + 1) % len(self.players)],
            loser=player,
            reason=REASON_RESIGN,
        )
        return DuelResult.LOST

    def check_timeout(self, now: float | None = None) -> bool:
        """اگر DUEL_TIMEOUT ثانیه از آخرین کلیک گذشته باشد، بازی تمام می‌شود."""
        if self.is_finished:
            return False
        moment = self.clock() if now is None else now
        if moment - self.last_activity < DUEL_TIMEOUT:
            return False
        self._finish_by_score(REASON_TIMEOUT)
        return True

    def _finish_by_score(self, reason: str, player: Player | None = None) -> str:
        """پایان بازی با مقایسهٔ تعداد بمب‌های پیداشده (بیشترین بمب برنده است)."""
        best = max(self.found)
        if self.found.count(best) > 1:
            winner = loser = None
        else:
            winner_index = self.found.index(best)
            winner = self.players[winner_index]
            loser = self.players[(winner_index + 1) % len(self.players)]
        self._finish(winner, loser, reason)
        if winner is None or player is None:
            return DuelResult.DRAW
        return DuelResult.WON if winner is player else DuelResult.LOST

    def _finish(self, winner: Player | None, loser: Player | None, reason: str) -> None:
        self.status = FINISHED
        self.winner = winner
        self.loser = loser
        self.reason = reason
        self.finished_at = self.clock()
        if self.started_at is None:
            self.started_at = self.finished_at

    def next_match(self, message_id: int | None = None) -> "DuelMatch":
        """دوئل مجدد با همان بازیکنان؛ نفر شروع‌کننده عوض می‌شود."""
        return DuelMatch(
            chat_id=self.chat_id,
            difficulty=self.difficulty,
            players=list(self.players),
            clock=self.clock,
            starting_index=(self.starting_index + 1) % len(self.players),
            group_title=self.group_title,
            message_id=message_id if message_id is not None else self.message_id,
        )

    def to_lines(self) -> list[str]:
        return self.board.to_lines()
