"""منطق خالص بازی مین‌روب (Minesweeper).

این ماژول هیچ وابستگی‌ای به تلگرام ندارد تا کاملاً قابل تست باشد.
همهٔ مختصات‌ها صفر-پایه هستند: (سطر، ستون).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# وضعیت‌های بازی
READY = "ready"      # مین‌ها هنوز کاشته نشده‌اند
PLAYING = "playing"
WON = "won"
LOST = "lost"

NEIGHBOR_OFFSETS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


class MoveResult:
    """نتیجهٔ یک حرکت بازیکن."""

    REVEALED = "revealed"    # خانه(ها) باز شد
    FLAGGED = "flagged"
    UNFLAGGED = "unflagged"
    BOOM = "boom"            # روی مین رفت (کلاسیک)
    MINE_FOUND = "mine_found"  # حالت بمب‌گیری: مین پیدا شد (بازی ادامه دارد)
    WON = "won"
    NOOP = "noop"            # حرکت بی‌اثر (خارج از زمین، chord نامعتبر، خانهٔ بازشده)
    BLOCKED = "blocked"      # خانه پرچم دارد
    FINISHED = "finished"    # بازی تمام شده است


@dataclass(frozen=True)
class Difficulty:
    key: str
    title: str
    rows: int
    cols: int
    mines: int

    @property
    def cells(self) -> int:
        return self.rows * self.cols


# تعداد دکمه‌ها زیر سقف ۱۰۰ دکمه‌ای تلگرام بماند.
DIFFICULTIES: dict[str, Difficulty] = {
    "easy": Difficulty("easy", "آسان", 6, 6, 6),
    "medium": Difficulty("medium", "متوسط", 8, 8, 12),
    "hard": Difficulty("hard", "سخت", 9, 9, 20),
}

DEFAULT_DIFFICULTY = "easy"


class Cell:
    __slots__ = ("mine", "revealed", "flagged", "adjacent")

    def __init__(self) -> None:
        self.mine = False
        self.revealed = False
        self.flagged = False
        self.adjacent = 0

    def __repr__(self) -> str:  # pragma: no cover - فقط برای دیباگ
        if self.revealed and self.mine:
            return "*"
        if self.flagged:
            return "F"
        if not self.revealed:
            return "#"
        return str(self.adjacent) if self.adjacent else "."


class Board:
    """یک صفحهٔ مین‌روب."""

    def __init__(
        self,
        difficulty: Difficulty,
        rng: random.Random | None = None,
        collect: bool = False,
    ) -> None:
        self.difficulty = difficulty
        self.rng = rng if rng is not None else random.Random()
        self.rows = difficulty.rows
        self.cols = difficulty.cols
        self.total_mines = difficulty.mines
        self.status = READY
        self.grid: list[list[Cell]] = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]
        self.flags = 0
        self.revealed = 0
        self.exploded: tuple[int, int] | None = None
        # حالت بمب‌گیری (دوئل): روی مین رفتن = پیدا کردن بمب، نه باخت.
        self.collect = collect
        self.mines_found = 0

    # ---------------------------------------------------------------- کمکی‌ها
    def inside(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def cell(self, r: int, c: int) -> Cell:
        return self.grid[r][c]

    def neighbors(self, r: int, c: int):
        for dr, dc in NEIGHBOR_OFFSETS:
            nr, nc = r + dr, c + dc
            if self.inside(nr, nc):
                yield nr, nc

    @property
    def remaining_mines(self) -> int:
        return max(0, self.total_mines - self.flags)

    @property
    def is_finished(self) -> bool:
        return self.status in (WON, LOST)

    @property
    def safe_cells(self) -> int:
        return self.rows * self.cols - self.total_mines

    # ------------------------------------------------------------ کاشت مین‌ها
    def _place_mines(self, safe_r: int, safe_c: int) -> None:
        """مین‌ها را طوری می‌کارد که اولین کلیک هرگز مین نباشد."""
        forbidden = {(safe_r, safe_c)}
        forbidden.update(self.neighbors(safe_r, safe_c))
        candidates = [
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if (r, c) not in forbidden
        ]
        if len(candidates) < self.total_mines:  # صفحهٔ کوچک: فقط خودِ خانه را امن کن
            candidates = [
                (r, c)
                for r in range(self.rows)
                for c in range(self.cols)
                if (r, c) != (safe_r, safe_c)
            ]
        for r, c in self.rng.sample(candidates, self.total_mines):
            self.grid[r][c].mine = True
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.grid[r][c].mine:
                    self.grid[r][c].adjacent = sum(
                        1 for nr, nc in self.neighbors(r, c) if self.grid[nr][nc].mine
                    )

    # -------------------------------------------------------------- حرکت‌ها
    def tap(self, r: int, c: int) -> str:
        """کندن خانه؛ اگر خانه باز باشد، chord انجام می‌شود."""
        if self.is_finished:
            return MoveResult.FINISHED
        if not self.inside(r, c):
            return MoveResult.NOOP
        if self.status == READY:
            self._place_mines(r, c)
            self.status = PLAYING

        cell = self.grid[r][c]
        if cell.flagged:
            return MoveResult.BLOCKED
        if cell.revealed:
            # در حالت بمب‌گیری کلیک روی خانهٔ بازشده بی‌اثر است (chord وجود ندارد).
            return MoveResult.NOOP if self.collect else self._chord(r, c)
        if cell.mine:
            if self.collect:
                cell.revealed = True
                self.mines_found += 1
                self._check_win()
                return MoveResult.MINE_FOUND
            cell.revealed = True
            self.exploded = (r, c)
            self.status = LOST
            self._reveal_mines()
            return MoveResult.BOOM

        self._flood(r, c)
        if self._check_win():
            return MoveResult.WON
        return MoveResult.REVEALED

    def toggle_flag(self, r: int, c: int) -> str:
        if self.is_finished:
            return MoveResult.FINISHED
        if not self.inside(r, c):
            return MoveResult.NOOP
        cell = self.grid[r][c]
        if cell.revealed:
            return MoveResult.NOOP
        cell.flagged = not cell.flagged
        self.flags += 1 if cell.flagged else -1
        return MoveResult.FLAGGED if cell.flagged else MoveResult.UNFLAGGED

    def _chord(self, r: int, c: int) -> str:
        """کلیک روی عددِ بازشده: اگر تعداد پرچم‌ها با عدد یکی بود، بقیه باز می‌شوند."""
        cell = self.grid[r][c]
        if cell.adjacent <= 0:
            return MoveResult.NOOP
        flagged = sum(1 for nr, nc in self.neighbors(r, c) if self.grid[nr][nc].flagged)
        if flagged != cell.adjacent:
            return MoveResult.NOOP

        hit_mine = False
        for nr, nc in self.neighbors(r, c):
            n = self.grid[nr][nc]
            if n.flagged or n.revealed:
                continue
            if n.mine:
                n.revealed = True
                self.exploded = (nr, nc)
                hit_mine = True
            else:
                self._flood(nr, nc)

        if hit_mine:
            self.status = LOST
            self._reveal_mines()
            return MoveResult.BOOM
        if self._check_win():
            return MoveResult.WON
        return MoveResult.REVEALED

    def _flood(self, r: int, c: int) -> None:
        """باز کردن آبشاری خانه‌های خالی."""
        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            cell = self.grid[cr][cc]
            if cell.revealed or cell.flagged or cell.mine:
                continue
            cell.revealed = True
            self.revealed += 1
            if cell.adjacent == 0:
                for nr, nc in self.neighbors(cr, cc):
                    n = self.grid[nr][nc]
                    if not n.revealed and not n.flagged and not n.mine:
                        stack.append((nr, nc))

    def _check_win(self) -> bool:
        if self.collect:
            # در حالت بمب‌گیری بازی با پیدا شدن همهٔ مین‌ها تمام می‌شود.
            if self.mines_found >= self.total_mines:
                self.status = WON
                self._reveal_remaining_safe()
                return True
            return False
        if self.revealed >= self.safe_cells:
            self.status = WON
            self._auto_flag_mines()
            return True
        return False

    def _reveal_remaining_safe(self) -> None:
        """نمایش بقیهٔ خانه‌های امن وقتی همهٔ مین‌ها پیدا شدند."""
        for row in self.grid:
            for cell in row:
                if not cell.mine:
                    cell.revealed = True

    def _auto_flag_mines(self) -> None:
        for row in self.grid:
            for cell in row:
                if cell.mine and not cell.flagged:
                    cell.flagged = True
                    self.flags += 1

    def _reveal_mines(self) -> None:
        """نمایش همهٔ مین‌ها هنگام باخت (پرچم‌های درست دست‌نخورده می‌مانند)."""
        for row in self.grid:
            for cell in row:
                if cell.mine and not cell.flagged:
                    cell.revealed = True

    # ---------------------------------------------------------------- نمایش
    def to_lines(self) -> list[str]:
        """نمای متنی ساده (برای لاگ و تست)."""
        return [" ".join(repr(cell) for cell in row) for row in self.grid]
