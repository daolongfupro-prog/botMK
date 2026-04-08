
import aiosqlite
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "kontakt.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            telegram_id INTEGER,
            photo_file_id TEXT,
            is_admin INTEGER DEFAULT 0,
            is_owner INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS medals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            medal_type TEXT NOT NULL,       -- 'contact', 'vklad', 'proryv'
            points INTEGER NOT NULL,
            comment TEXT,
            awarded_by TEXT NOT NULL,
            awarded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            month TEXT NOT NULL             -- формат: '2026-04'
        );

        CREATE TABLE IF NOT EXISTS weekly_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            medal_type TEXT NOT NULL,
            week_start TEXT NOT NULL,       -- понедельник недели
            count INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            UNIQUE(username, medal_type, week_start)
        );

        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            added_by TEXT NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS month_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            congrats_text TEXT,
            congrats_author TEXT,           -- 'bot' или username админа
            sent INTEGER DEFAULT 0
        );
        """)
        await db.commit()

        # Добавляем владельца если ещё нет
        await db.execute("""
            INSERT OR IGNORE INTO users (username, full_name, is_admin, is_owner)
            VALUES (?, ?, 1, 1)
        """, ("studio_Slim_Line", "Организатор"))
        await db.commit()

# ─── ПОЛЬЗОВАТЕЛИ ───────────────────────────────────────────

async def add_user(username: str, full_name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO users (username, full_name) VALUES (?, ?)",
                (username.lstrip("@"), full_name)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def remove_user(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET is_active=0 WHERE username=?",
            (username.lstrip("@"),)
        )
        await db.commit()
        return cur.rowcount > 0

async def get_user(username: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1",
            (username.lstrip("@"),)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE is_active=1 ORDER BY full_name"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def update_user_tg_id(username: str, tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET telegram_id=? WHERE username=?",
            (tg_id, username.lstrip("@"))
        )
        await db.commit()

async def update_user_photo(username: str, file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET photo_file_id=? WHERE username=?",
            (file_id, username.lstrip("@"))
        )
        await db.commit()

# ─── МЕДАЛИ ─────────────────────────────────────────────────

MEDAL_LIMITS = {
    "contact": {"points_per": 1, "max_points": 3},
    "vklad":   {"points_per": 1, "max_points": 4},
    "proryv":  {"points_per": 2, "max_points": 6},
}

MEDAL_NAMES = {
    "contact": "⭐ Контакт",
    "vklad":   "💛 Вклад",
    "proryv":  "🔥 Прорыв",
}

def get_week_start() -> str:
    from datetime import date, timedelta
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()

def get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")

async def check_weekly_limit(username: str, medal_type: str, points: int) -> dict:
    """Возвращает {'ok': bool, 'used': int, 'max': int}"""
    week_start = get_week_start()
    max_pts = MEDAL_LIMITS[medal_type]["max_points"]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT points FROM weekly_limits WHERE username=? AND medal_type=? AND week_start=?",
            (username.lstrip("@"), medal_type, week_start)
        )
        row = await cur.fetchone()
        used = row[0] if row else 0
    return {"ok": used + points <= max_pts, "used": used, "max": max_pts}

async def award_medal(username: str, medal_type: str, comment: str, awarded_by: str) -> dict:
    """Начисляет медаль. Возвращает результат."""
    uname = username.lstrip("@")
    pts = MEDAL_LIMITS[medal_type]["points_per"]
    month = get_current_month()
    week_start = get_week_start()

    async with aiosqlite.connect(DB_PATH) as db:
        # Сохраняем медаль
        await db.execute(
            "INSERT INTO medals (username, medal_type, points, comment, awarded_by, month) VALUES (?,?,?,?,?,?)",
            (uname, medal_type, pts, comment, awarded_by.lstrip("@"), month)
        )
        # Обновляем недельный счётчик
        await db.execute("""
            INSERT INTO weekly_limits (username, medal_type, week_start, count, points)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(username, medal_type, week_start)
            DO UPDATE SET count=count+1, points=points+?
        """, (uname, medal_type, week_start, pts, pts))
        await db.commit()

    return {"success": True, "points": pts, "medal_name": MEDAL_NAMES[medal_type]}

async def cancel_last_medal(username: str) -> bool:
    """Отменяет последнее начисление."""
    uname = username.lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, medal_type, points FROM medals WHERE username=? ORDER BY id DESC LIMIT 1",
            (uname,)
        )
        row = await cur.fetchone()
        if not row:
            return False
        medal_id, medal_type, pts = row
        week_start = get_week_start()
        await db.execute("DELETE FROM medals WHERE id=?", (medal_id,))
        await db.execute("""
            UPDATE weekly_limits SET count=MAX(0,count-1), points=MAX(0,points-?)
            WHERE username=? AND medal_type=? AND week_start=?
        """, (pts, uname, medal_type, week_start))
        await db.commit()
    return True

async def get_user_medals(username: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM medals WHERE username=? ORDER BY awarded_at DESC",
            (username.lstrip("@"),)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_monthly_stats(month: str = None) -> list[dict]:
    if not month:
        month = get_current_month()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT u.username, u.full_name, u.photo_file_id,
                   COALESCE(SUM(m.points), 0) as total_points,
                   COALESCE(SUM(CASE WHEN m.medal_type='contact' THEN 1 ELSE 0 END), 0) as contact_count,
                   COALESCE(SUM(CASE WHEN m.medal_type='vklad'   THEN 1 ELSE 0 END), 0) as vklad_count,
                   COALESCE(SUM(CASE WHEN m.medal_type='proryv'  THEN 1 ELSE 0 END), 0) as proryv_count
            FROM users u
            LEFT JOIN medals m ON u.username=m.username AND m.month=?
            WHERE u.is_active=1
            GROUP BY u.username
            ORDER BY total_points DESC
        """, (month,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_user_history(username: str, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM medals WHERE username=? ORDER BY awarded_at DESC LIMIT ?",
            (username.lstrip("@"), limit)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

# ─── АДМИНИСТРАТОРЫ ──────────────────────────────────────────

async def add_admin(username: str, added_by: str) -> bool:
    uname = username.lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO admins (username, added_by) VALUES (?,?)",
                (uname, added_by.lstrip("@"))
            )
            await db.execute(
                "UPDATE users SET is_admin=1 WHERE username=?", (uname,)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def remove_admin(username: str) -> bool:
    uname = username.lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE username=?", (uname,))
        await db.execute("UPDATE users SET is_admin=0 WHERE username=?", (uname,))
        await db.commit()
    return True

async def is_admin(username: str) -> bool:
    uname = username.lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT is_admin, is_owner FROM users WHERE username=? AND is_active=1",
            (uname,)
        )
        row = await cur.fetchone()
        return bool(row and (row[0] or row[1]))

async def is_owner(username: str) -> bool:
    uname = username.lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT is_owner FROM users WHERE username=?", (uname,)
        )
        row = await cur.fetchone()
        return bool(row and row[0])

async def get_all_admins() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE is_admin=1 OR is_owner=1"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

# ─── ПОЗДРАВЛЕНИЯ ────────────────────────────────────────────

async def save_congrats(month: str, text: str, author: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO month_messages (month, congrats_text, congrats_author) VALUES (?,?,?)",
            (month, text, author)
        )
        await db.commit()

async def get_congrats(month: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM month_messages WHERE month=?", (month,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

async def mark_congrats_sent(month: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE month_messages SET sent=1 WHERE month=?", (month,)
        )
        await db.commit(
