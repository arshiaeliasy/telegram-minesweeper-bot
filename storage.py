"""ذخیرهٔ آمار در یک فایل JSON (نوشتن اتمیک + قفل تردی).

ساختار فایل:
{
  "users":  { "<user_id>": {"name", "played", "wins", "best": {...}} },   # بازی تک‌نفره
  "duel":   { "<user_id>": {"name", "matches", "wins", "losses"} },       # دوئل، در همهٔ گروه‌ها
  "topics": { "<chat_id>": <thread_id> },   # تاپیک پیش‌فرض هر گروه (۰ = General)
  "groups": {
     "<chat_id>": {
        "title": "...",
        "players": {"<user_id>": {"name", "wins", "losses", "matches", "last_at"}},
        "pairs":   {"<id1>:<id2>": {"<id1>": 3, "<id2>": 2}},
        "matches": [ {"winner", "winner_name", "loser", "loser_name",
                      "level", "seconds", "at"} ]                       # آخرین ۳۰ دوئل
     }
  }
}
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

MAX_HISTORY = 30


class StatsStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    # ------------------------------------------------------------------ فایل
    def _load(self) -> dict:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("users", {})
        data.setdefault("duel", {})
        data.setdefault("topics", {})
        data.setdefault("groups", {})
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # --------------------------------------------------- تاپیک پیش‌فرض گروه
    def set_topic(self, chat_id: int, thread_id: int) -> None:
        """تاپیک ثابت گروه را ذخیره می‌کند؛ ۰ یعنی تاپیک General."""
        with self._lock:
            topics = self._data.setdefault("topics", {})
            topics[str(int(chat_id))] = int(thread_id)
            self._save()

    def get_topic(self, chat_id: int) -> int | None:
        """تاپیک ثابت گروه؛ None یعنی تنظیم نشده (حالت خودکار)."""
        with self._lock:
            value = (self._data.get("topics") or {}).get(str(int(chat_id)))
        return int(value) if value is not None else None

    def clear_topic(self, chat_id: int) -> None:
        """حذف تاپیک ثابت و برگشت به حالت خودکار."""
        with self._lock:
            topics = self._data.setdefault("topics", {})
            if topics.pop(str(int(chat_id)), None) is not None:
                self._save()

    # ------------------------------------------------------- بازی تک‌نفره
    def record(
        self,
        user_id: int | None,
        name: str | None,
        difficulty: str,
        won: bool,
        seconds: int,
    ) -> dict | None:
        if user_id is None:
            return None
        with self._lock:
            users = self._data.setdefault("users", {})
            user = users.setdefault(
                str(user_id),
                {"name": name or str(user_id), "played": 0, "wins": 0, "best": {}},
            )
            if name:
                user["name"] = name
            user["played"] = int(user.get("played", 0)) + 1
            if won:
                user["wins"] = int(user.get("wins", 0)) + 1
                best = user.setdefault("best", {})
                current = best.get(difficulty)
                seconds = max(1, int(seconds))
                if current is None or seconds < int(current):
                    best[difficulty] = seconds
            user.setdefault("best", {})
            self._save()
            return json.loads(json.dumps(user))

    def get(self, user_id: int | None) -> dict | None:
        if user_id is None:
            return None
        with self._lock:
            user = self._data.get("users", {}).get(str(user_id))
            return json.loads(json.dumps(user)) if user else None

    def top(self, difficulty: str, limit: int = 5) -> list[dict]:
        """بهترین زمان‌های تک‌نفره در یک سطح."""
        with self._lock:
            rows = []
            for user in self._data.get("users", {}).values():
                best = (user.get("best") or {}).get(difficulty)
                if best is None:
                    continue
                rows.append({"name": user.get("name") or "?", "seconds": int(best)})
        rows.sort(key=lambda item: (item["seconds"], item["name"]))
        return rows[:limit]

    # -------------------------------------------------------------- دوئل‌ها
    def record_duel(
        self,
        chat_id: int,
        winner_id: int,
        winner_name: str,
        loser_id: int,
        loser_name: str,
        level: str,
        seconds: int,
        group_title: str = "",
        at: float | None = None,
    ) -> dict:
        """ثبت نتیجهٔ یک دوئل در تاریخچهٔ گروه + آمار کلی دو بازیکن."""
        seconds = max(1, int(seconds))
        moment = float(at if at is not None else time.time())
        with self._lock:
            group = self._group(chat_id)
            if group_title:
                group["title"] = group_title

            for user_id, name, field_name in (
                (winner_id, winner_name, "wins"),
                (loser_id, loser_name, "losses"),
            ):
                row = group["players"].setdefault(
                    str(user_id),
                    {"name": name, "wins": 0, "losses": 0, "matches": 0, "last_at": moment},
                )
                if name:
                    row["name"] = name
                row[field_name] = int(row.get(field_name, 0)) + 1
                row["matches"] = int(row.get("matches", 0)) + 1
                row["last_at"] = moment
                self._bump_duel_totals(user_id, name, won=field_name == "wins")

            key = self._pair_key(winner_id, loser_id)
            pair = group["pairs"].setdefault(key, {})
            pair[str(winner_id)] = int(pair.get(str(winner_id), 0)) + 1

            group["matches"].append(
                {
                    "winner": winner_id,
                    "winner_name": winner_name,
                    "loser": loser_id,
                    "loser_name": loser_name,
                    "level": level,
                    "seconds": seconds,
                    "at": moment,
                }
            )
            group["total"] = int(group.get("total", 0)) + 1
            del group["matches"][:-MAX_HISTORY]
            self._save()

            row_winner = json.loads(json.dumps(group["players"][str(winner_id)]))
            row_loser = json.loads(json.dumps(group["players"][str(loser_id)]))
            pair_copy = json.loads(json.dumps(pair))
        return {
            "winner": row_winner,
            "loser": row_loser,
            "head_to_head": pair_copy,
            "seconds": seconds,
        }

    def _bump_duel_totals(self, user_id: int, name: str, won: bool) -> None:
        totals = self._data.setdefault("duel", {}).setdefault(
            str(user_id), {"name": name, "matches": 0, "wins": 0, "losses": 0}
        )
        if name:
            totals["name"] = name
        totals["matches"] = int(totals.get("matches", 0)) + 1
        key = "wins" if won else "losses"
        totals[key] = int(totals.get(key, 0)) + 1

    @staticmethod
    def _pair_key(first: int, second: int) -> str:
        a, b = sorted((int(first), int(second)))
        return f"{a}:{b}"

    def _group(self, chat_id: int) -> dict:
        groups = self._data.setdefault("groups", {})
        return groups.setdefault(
            str(chat_id),
            {"title": "", "players": {}, "pairs": {}, "matches": [], "total": 0},
        )

    def group_table(self, chat_id: int) -> list[dict]:
        """جدول امتیازات یک گروه، مرتب‌شده با برد و سپس کمترین باخت."""
        with self._lock:
            group = self._data.get("groups", {}).get(str(chat_id)) or {}
            rows = []
            for user_id, row in (group.get("players") or {}).items():
                rows.append(
                    {
                        "user_id": int(user_id),
                        "name": row.get("name") or "?",
                        "wins": int(row.get("wins", 0)),
                        "losses": int(row.get("losses", 0)),
                        "matches": int(row.get("matches", 0)),
                    }
                )
        rows.sort(key=lambda item: (-item["wins"], item["losses"], item["name"]))
        return rows

    def group_history(self, chat_id: int, limit: int = 5) -> list[dict]:
        with self._lock:
            group = self._data.get("groups", {}).get(str(chat_id)) or {}
            matches = list(group.get("matches") or [])
        return list(reversed(matches))[:limit]

    def group_info(self, chat_id: int) -> dict:
        with self._lock:
            group = self._data.get("groups", {}).get(str(chat_id)) or {}
            return {
                "title": group.get("title") or "",
                "matches": int(group.get("total", len(group.get("matches") or []))),
                "players": len(group.get("players") or {}),
            }

    def duel_stats(self, user_id: int | None) -> dict | None:
        if user_id is None:
            return None
        with self._lock:
            row = self._data.get("duel", {}).get(str(user_id))
            return json.loads(json.dumps(row)) if row else None

    def head_to_head(self, chat_id: int, first: int, second: int) -> dict:
        with self._lock:
            group = self._data.get("groups", {}).get(str(chat_id)) or {}
            pair = (group.get("pairs") or {}).get(self._pair_key(first, second)) or {}
            return {str(first): int(pair.get(str(first), 0)), str(second): int(pair.get(str(second), 0))}
