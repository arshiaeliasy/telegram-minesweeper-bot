"""ساخت متن‌ها و صفحه‌کلیدهای شیشه‌ای (لایهٔ نمایش).

هم حالت تک‌نفره و هم حالت دوئل دو نفره اینجا ساخته می‌شوند.
"""

from __future__ import annotations

from html import escape

from fa import duration, fa, when
from minesweeper import LOST, READY, WON, Board, DIFFICULTIES

# ---------------------------------------------------------------- نمادها
HIDDEN = "🟦"
EMPTY = "⬜"
FLAG = "🚩"
MINE = "💣"
BOOM = "💥"
WRONG_FLAG = "❌"

DIGITS = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
}

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# ---------------------------------------------------------- دادهٔ callback
CB_TAP = "t:"                 # تک‌نفره: t:3:4
CB_FLAG_MODE = "F"            # تک‌نفره: حالت پرچم
CB_MENU = "D"                 # منوی سطح تک‌نفره
CB_STATS = "S"
CB_HELP = "H"
CB_SOLO_DIFFICULTY = "d:"     # d:easy

CB_DUEL_NEW = "duel:new"
CB_DUEL_JOIN = "duel:join"              # duel:join[:<lobby_id>]
CB_DUEL_CANCEL = "duel:cancel"          # duel:cancel[:<lobby_id>]
CB_DUEL_REMATCH = "duel:rematch"        # duel:rematch[:<match_id>]
CB_DUEL_SURRENDER = "duel:surrender:"   # duel:surrender:<match_id>
CB_DUEL_TABLE = "duel:table"
CB_DUEL_LEVEL = "duel:level:"           # duel:level:[<lobby_id>:]<key>
CB_DUEL_TAP = "dt:"                     # dt:<match_id>:<r>:<c>

# ------------------------------------------------------------------ متن‌ها
WELCOME_TEXT = (
    "💣 <b>به ربات مین‌روب خوش آمدی!</b>\n\n"
    "🔹 <b>حالت دوئل (اصل بازی):</b> مرا به یک گروه اضافه کن، آنجا <code>/duel</code> را بزن "
    "و با یکی از اعضا دوئل کن — روی یک تختهٔ مشترک، نفرِ به نوبت.\n"
    "🔹 <b>حالت تک‌نفره:</b> همین‌جا در چت خصوصی.\n\n"
    "برای شروع تک‌نفره یک سطح انتخاب کن:"
)

MENU_TEXT = "🎮 <b>سطح بازی تک‌نفره را انتخاب کن</b>"

DUEL_INTRO_TEXT = (
    "⚔️ <b>دوئل مین‌روب، دو نفره!</b>\n\n"
    "روی یک تختهٔ مشترک، نفرِ به نوبت خانه‌ها را باز می‌کند:\n"
    "💣 اگر <b>مین (بمب)</b> پیدا کند یک امتیاز می‌گیرد و <b>دوباره نوبت خودش</b> است.\n"
    "🔢 اگر خانهٔ امن باز کند، عددِ مین‌های اطراف نمایش داده می‌شود و نوبت به حریف می‌رود.\n"
    "🏆 پایان بازی: هرکس <b>بمب بیشتری</b> پیدا کرده باشد برنده است.\n"
    "⏱ اگر ۱۰ دقیقه هیچ‌کس کلیک نکند، بازی خودکار تمام می‌شود.\n"
    "🛡 اولین کلیک هرگز مین نیست (مین‌ها بعد از آن کاشته می‌شوند).\n"
    "🎮 چند دوئل و چند دعوت را می‌شود همزمان در یک گروه داشت!\n"
    "🏆 نتیجهٔ هر دوئل در <b>جدول امتیازات همین گروه</b> ثبت می‌شود.\n\n"
    "برای شروع، دکمهٔ زیر را بزن یا <code>/duel</code> را بفرست.\n"
    "برای بازی تک‌نفره: <code>/solo</code>"
)

HELP_TEXT = (
    "❓ <b>راهنمای ربات مین‌روب</b>\n\n"
    "⚔️ <b>دوئل دو نفره (در گروه)</b>\n"
    "• <code>/duel</code> — باز کردن دعوت‌نامهٔ دوئل (یا <code>/duel متوسط</code>)\n"
    "• بازیکن دوم روی «🎯 پیوستن به دوئل» می‌زند و بازی شروع می‌شود\n"
    "• چند دعوت و چند دوئل همزمان در یک گروه مجاز است\n"
    "• 💣 مین پیدا کنی: یک امتیاز می‌گیری و <b>دوباره نوبت توست</b>\n"
    "• 🔢 خانهٔ امن باز کنی: عدد نمایش داده می‌شود و نوبت حریف می‌رود\n"
    "• 🏆 برنده کسی است که پایان بازی <b>بمب بیشتری</b> پیدا کرده باشد\n"
    "• ⏱ ۱۰ دقیقه بدون کلیک → بازی خودکار تمام و بمب‌ها مقایسه می‌شود\n"
    "• <code>/surrender</code> — تسلیم شدن در دوئل جاری\n"
    "• <code>/score</code> — جدول امتیازات و تاریخچهٔ همین گروه\n"
    "• 🛡 مین‌ها بعد از اولین کلیک کاشته می‌شوند؛ پس اولین کلیک هرگز مین نیست\n\n"
    "⚙️ <b>تاپیک گروه (سوپراگروه فروم)</b>\n"
    "• <code>/topic</code> — همین تاپیک، تاپیک ثابت ربات شود (فقط مدیر گروه)\n"
    "• <code>/topic off</code> — برگشت به حالت خودکار (پاسخ در تاپیکِ پیام)\n\n"
    "🎮 <b>تک‌نفره</b>\n"
    "• <code>/solo</code> — انتخاب سطح و شروع بازی\n"
    "• <code>/stats</code> — آمار شخصی (تک‌نفره + دوئل)\n"
    "• <code>/top</code> — برترین زمان‌های تک‌نفره\n\n"
    "🔢 <b>نمادها:</b> 🟦 پوشیده · ⬜ خالی · 1️⃣..8️⃣ تعداد مین اطراف · 🚩 پرچم · "
    "💣 مین پیداشده · 💥 مین منفجرشده · ❌ پرچم اشتباه"
)


def level_title(key: str) -> str:
    difficulty = DIFFICULTIES.get(key)
    return difficulty.title if difficulty else str(key)


def mention(user_id: int, name: str) -> str:
    """لینک منشن تلگرامی با نام امن‌شده."""
    return f'<a href="tg://user?id={int(user_id)}">{escape(str(name))}</a>'


def player_ref(player) -> str:
    return mention(player.user_id, player.name)


# ------------------------------------------------------------ تختهٔ مشترک
def cell_label(board: Board, r: int, c: int) -> str:
    """متن روی دکمهٔ یک خانه."""
    cell = board.cell(r, c)
    if cell.flagged:
        if board.status == LOST and not cell.mine:
            return WRONG_FLAG
        return FLAG
    if cell.revealed:
        if cell.mine:
            return BOOM if board.exploded == (r, c) else MINE
        if cell.adjacent:
            return DIGITS.get(cell.adjacent, str(cell.adjacent))
        return EMPTY
    return HIDDEN


def _board_rows(board: Board, prefix: str) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for r in range(board.rows):
        rows.append(
            [
                {"text": cell_label(board, r, c), "callback_data": f"{prefix}{r}:{c}"}
                for c in range(board.cols)
            ]
        )
    return rows


# ------------------------------------------------------------- تک‌نفره
def build_text(board: Board, *, flag_mode: bool = False, elapsed: float | None = None) -> str:
    d = board.difficulty
    lines = [
        f"🎮 <b>مین‌روب تک‌نفره</b> | سطح: {d.title} ({fa(d.rows)}×{fa(d.cols)}، {fa(d.mines)} مین)",
        f"🚩 مین‌های باقی‌مانده: <b>{fa(board.remaining_mines)}</b> | ⏱ زمان: <b>{duration(elapsed)}</b>",
        f"حالت فعلی: {'🚩 پرچم‌گذاری' if flag_mode else '⛏ کندن'}",
    ]
    if board.status == READY:
        lines.append("👉 برای شروع، روی یک خانه بزن (اولین کلیک امن است).")
    elif board.status == WON:
        lines.append(f"🎉 <b>بردی!</b> زمان: {duration(elapsed)}")
    elif board.status == LOST:
        lines.append("💥 <b>باختی!</b> مین‌ها مشخص شدند.")
    else:
        lines.append("ادامه بده…")
    return "\n".join(lines)


def build_keyboard(board: Board, flag_mode: bool = False) -> dict:
    rows = _board_rows(board, CB_TAP)
    rows.append(
        [
            {
                "text": "🚩 حالت پرچم: روشن" if flag_mode else "🚩 حالت پرچم: خاموش",
                "callback_data": CB_FLAG_MODE,
            }
        ]
    )
    rows.append(
        [
            {"text": "🔄 بازی جدید", "callback_data": CB_MENU},
            {"text": "📊 آمار", "callback_data": CB_STATS},
            {"text": "❓ راهنما", "callback_data": CB_HELP},
        ]
    )
    return {"inline_keyboard": rows}


def difficulty_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "🙂 آسان ۶×۶ (۶ مین)", "callback_data": f"{CB_SOLO_DIFFICULTY}easy"}],
            [{"text": "😐 متوسط ۸×۸ (۱۲ مین)", "callback_data": f"{CB_SOLO_DIFFICULTY}medium"}],
            [{"text": "😈 سخت ۹×۹ (۲۰ مین)", "callback_data": f"{CB_SOLO_DIFFICULTY}hard"}],
        ]
    }


def finished_keyboard(board: Board | None = None) -> dict:
    """صفحه‌کلید پایان بازی؛ تخته باقی می‌ماند تا مین‌ها دیده شوند."""
    rows = _board_rows(board, CB_TAP) if board is not None else []
    rows.append(
        [
            {"text": "🔄 بازی جدید", "callback_data": CB_MENU},
            {"text": "📊 آمار", "callback_data": CB_STATS},
            {"text": "❓ راهنما", "callback_data": CB_HELP},
        ]
    )
    return {"inline_keyboard": rows}


# ---------------------------------------------------------------- دوئل
def duel_intro_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "⚔️ شروع دوئل جدید", "callback_data": CB_DUEL_NEW}],
            [
                {"text": "🏆 جدول امتیازات", "callback_data": CB_DUEL_TABLE},
                {"text": "❓ راهنما", "callback_data": CB_HELP},
            ],
        ]
    }


def duel_lobby_text(lobby) -> str:
    difficulty = DIFFICULTIES[lobby.difficulty_key]
    return "\n".join(
        [
            "⚔️ <b>دعوت‌نامهٔ دوئل مین‌روب</b>",
            f"{player_ref(lobby.host)} دنبال یک حریف است!",
            f"🎯 سطح: <b>{difficulty.title}</b> ({fa(difficulty.rows)}×{fa(difficulty.cols)}، {fa(difficulty.mines)} مین)",
            "",
            "👉 بازیکن دوم روی «🎯 پیوستن به دوئل» بزند تا بازی شروع شود.",
            "⏳ این دعوت ۱۵ دقیقه معتبر است. (تغییر سطح و لغو، فقط دستِ دعوت‌کننده است.)",
        ]
    )


def duel_lobby_keyboard(lobby) -> dict:
    level_row = []
    for key, difficulty in DIFFICULTIES.items():
        mark = "✅ " if key == lobby.difficulty_key else ""
        level_row.append(
            {"text": f"{mark}{difficulty.title} {fa(difficulty.rows)}×{fa(difficulty.cols)}",
             "callback_data": f"{CB_DUEL_LEVEL}{lobby.id}:{key}"}
        )
    return {
        "inline_keyboard": [
            level_row,
            [{"text": "🎯 پیوستن به دوئل", "callback_data": f"{CB_DUEL_JOIN}:{lobby.id}"}],
            [
                {"text": "❌ لغو دعوت", "callback_data": f"{CB_DUEL_CANCEL}:{lobby.id}"},
                {"text": "🏆 جدول امتیازات", "callback_data": CB_DUEL_TABLE},
                {"text": "❓ راهنما", "callback_data": CB_HELP},
            ],
        ]
    }


def lobby_pick_keyboard(lobbies: list) -> dict:
    """انتخاب یکی از چند دعوتِ فعال همزمان در یک گروه."""
    rows = []
    for lobby in lobbies:
        rows.append(
            [
                {
                    "text": f"🎯 پیوستن: {lobby.host.name[:16]} ({level_title(lobby.difficulty_key)})",
                    "callback_data": f"{CB_DUEL_JOIN}:{lobby.id}",
                }
            ]
        )
    return {"inline_keyboard": rows}


def cancel_pick_keyboard(lobbies: list) -> dict:
    """انتخاب دعوتی که باید لغو شود وقتی چند دعوتِ خودِ کاربر باز است."""
    rows = []
    for lobby in lobbies:
        rows.append(
            [
                {
                    "text": f"❌ لغو دعوت {lobby.host.name[:16]} ({level_title(lobby.difficulty_key)})",
                    "callback_data": f"{CB_DUEL_CANCEL}:{lobby.id}",
                }
            ]
        )
    return {"inline_keyboard": rows}


def surrender_pick_keyboard(matches: list) -> dict:
    """انتخاب دوئلی که باید در آن تسلیم شد وقتی چند دوئل همزمان جریان دارد."""
    rows = []
    for match in matches:
        first = match.players[0].name[:12]
        second = match.players[1].name[:12]
        rows.append(
            [
                {
                    "text": f"🏳️ تسلیم در دوئل {first} 🆚 {second}",
                    "callback_data": f"{CB_DUEL_SURRENDER}{match.id}",
                }
            ]
        )
    return {"inline_keyboard": rows}


def score_line(match) -> str:
    """تعداد بمب‌های پیداشدهٔ هر بازیکن."""
    first, second = match.players[0], match.players[1]
    return (
        f"💣 بمب‌ها: {player_ref(first)} <b>{fa(match.found[0])}</b> — "
        f"<b>{fa(match.found[1])}</b> {player_ref(second)}"
    )


def _finish_line(match) -> str:
    if match.winner is None:
        if match.reason == "timeout":
            return "⏰ <b>۱۰ دقیقه بدون حرکت؛ بازی مساوی تمام شد.</b>"
        return "🤝 <b>بازی مساوی تمام شد!</b>"
    head = f"🏆 <b>{escape(match.winner.name)}</b> برندهٔ دوئل شد!"
    if match.reason == "score":
        detail = "💣 همهٔ مین‌ها پیدا شدند؛ بیشترین بمب برنده است."
    elif match.reason == "timeout":
        detail = "⏰ ۱۰ دقیقه بدون حرکت؛ بازی خودکار تمام شد."
    elif match.reason == "resign":
        detail = f"🏳️ {escape(match.loser.name)} تسلیم شد."
    else:
        detail = ""
    return f"{head}\n{detail}"


def duel_text(match) -> str:
    board = match.board
    d = board.difficulty
    lines = [
        f"⚔️ <b>دوئل مین‌روب</b> — سطح {d.title} ({fa(d.rows)}×{fa(d.cols)}، {fa(d.mines)} مین)",
        f"{player_ref(match.players[0])} 🆚 {player_ref(match.players[1])}",
        score_line(match),
    ]

    if match.is_finished:
        lines.append(_finish_line(match))
    else:
        lines.append(f"🟢 نوبت: {player_ref(match.current)}")

    lines.append(
        f"⏱ <b>{duration(match.elapsed())}</b> | 👆 {fa(match.moves)} حرکت"
    )
    if match.last_move and not match.is_finished:
        lines.append(match.last_move)

    if match.is_finished:
        lines.append(_h2h_line(match))
        lines.append("برای بازی مجدد دکمهٔ «🔁 دوئل مجدد» را بزن.")
    elif board.status == READY:
        lines.append("👉 بازیکن اول روی یک خانه بزند (اولین کلیک امن است).")
    else:
        lines.append("💣 هر بمبی بیشتر پیدا کنی به نفعت است؛ بمب که پیدا کنی دوباره نوبت توست!")

    return "\n".join(line for line in lines if line)


def _h2h_line(match) -> str:
    summary = match.summary or {}
    h2h = summary.get("head_to_head") or {}
    if not h2h:
        return ""
    first, second = match.players
    wins_first = fa(h2h.get(str(first.user_id), 0))
    wins_second = fa(h2h.get(str(second.user_id), 0))
    return f"🤝 رودررو در این گروه: {escape(first.name)} {wins_first} — {wins_second} {escape(second.name)}"


def duel_keyboard(match) -> dict:
    rows = _board_rows(match.board, f"{CB_DUEL_TAP}{match.id}:")
    rows.append(
        [
            {"text": "🏆 جدول امتیازات", "callback_data": CB_DUEL_TABLE},
            {"text": "❓ راهنما", "callback_data": CB_HELP},
        ]
    )
    return {"inline_keyboard": rows}


def duel_finished_keyboard(match=None) -> dict:
    """صفحه‌کلید پایان دوئل؛ تخته می‌ماند تا مین‌ها دیده شوند."""
    rows = (
        _board_rows(match.board, f"{CB_DUEL_TAP}{match.id}:")
        if match is not None
        else []
    )
    rematch = f"{CB_DUEL_REMATCH}:{match.id}" if match is not None else CB_DUEL_REMATCH
    rows.append(
        [
            {"text": "🔁 دوئل مجدد", "callback_data": rematch},
            {"text": "🏆 جدول امتیازات", "callback_data": CB_DUEL_TABLE},
            {"text": "❓ راهنما", "callback_data": CB_HELP},
        ]
    )
    return {"inline_keyboard": rows}


# ------------------------------------------------------- جدول امتیازات
def group_table_text(rows: list[dict], history: list[dict], total: int, title: str = "") -> str:
    lines = ["🏆 <b>جدول امتیازات این گروه</b>"]
    if title:
        lines.append(f"👥 {escape(title)}")
    lines.append(
        f"🎮 دوئل‌های انجام‌شده: <b>{fa(total)}</b> | 👤 بازیکن‌ها: <b>{fa(len(rows))}</b>"
    )
    lines.append("")

    if not rows:
        lines.append("هنوز دوئلی ثبت نشده است. با <code>/duel</code> شروع کن!")
    for index, row in enumerate(rows, start=1):
        played = row["wins"] + row["losses"]
        rate = round(row["wins"] * 100 / played) if played else 0
        medal = MEDALS.get(index, f"{fa(index)}.")
        lines.append(
            f"{medal} {mention(row['user_id'], row['name'])} — "
            f"<b>{fa(row['wins'])}</b> برد / {fa(row['losses'])} باخت ({fa(rate)}٪)"
        )

    if history:
        lines.append("")
        lines.append("📜 <b>آخرین دوئل‌ها</b>")
        for match in history:
            lines.append(
                f"• {when(match['at'])} — {escape(match['winner_name'])} 🏆 "
                f"{escape(match['loser_name'])} "
                f"({level_title(match['level'])}، {duration(match['seconds'])})"
            )
    return "\n".join(lines)
