import os
import asyncpg
from datetime import datetime, date, timedelta

# Получаем ключ от базы данных из Railway
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool = None

# Создаем скоростной пул подключений
async def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            telegram_id BIGINT,
            photo_file_id TEXT,
            is_admin INTEGER DEFAULT 0,
            is_owner INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS medals (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            medal_type TEXT NOT NULL,
            points INTEGER NOT NULL,
            comment TEXT,
            awarded_by TEXT NOT NULL,
            awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            month TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS weekly_limits (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            medal_type TEXT NOT NULL,
            week_start TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            UNIQUE(username, medal_type, week_start)
        );

        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            added_by TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS month_messages (
            id SERIAL PRIMARY KEY,
            month TEXT UNIQUE NOT NULL,
            congrats_text TEXT,
            congrats_author TEXT,
            sent INTEGER DEFAULT 0
        );
        """)

        # Добавляем владельца если ещё нет (ON CONFLICT DO NOTHING - аналог INSERT OR IGNORE)
        await conn.execute("""
            INSERT INTO users (username, full_name, is_admin, is_owner)
            VALUES ($1, $2, 1, 1)
            ON CONFLICT (username) DO NOTHING
        """, "studio_Slim_Line", "Организатор")

# ─── ПОЛЬЗОВАТЕЛИ ───────────────────────────────────────────

async def add_user(username: str, full_name: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Проверяем, есть ли уже такой пользователь в базе
        row = await conn.fetchrow("SELECT is_active FROM users WHERE username=$1", uname)
        
        if row:
            # Если пользователь есть и он активен - выдаем ошибку (False)
            if row["is_active"] == 1:
                return False
            else:
                # Если пользователь есть, но был удален - ВОСКРЕШАЕМ ЕГО
                await conn.execute(
                    "UPDATE users SET full_name=$1, is_active=1 WHERE username=$2",
                    full_name, uname
                )
                return True
        else:
            # Если пользователя вообще никогда не было - создаем нового
            await conn.execute(
                "INSERT INTO users (username, full_name) VALUES ($1, $2)",
                uname, full_name
            )
            return True

async def remove_user(username: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE users SET is_active=0 WHERE username=$1",
            username.lstrip("@")
        )
        return status != "UPDATE 0"

async def get_user(username: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE username=$1 AND is_active=1",
            username.lstrip("@")
        )
        return dict(row) if row else None

async def get_all_users() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM users WHERE is_active=1 ORDER BY full_name"
        )
        return [dict(r) for r in rows]

async def update_user_tg_id(username: str, tg_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET telegram_id=$1 WHERE username=$2",
            tg_id, username.lstrip("@")
        )

async def update_user_photo(username: str, file_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET photo_file_id=$1 WHERE username=$2",
            file_id, username.lstrip("@")
        )

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
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()

def get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")

async def check_weekly_limit(username: str, medal_type: str, points: int) -> dict:
    week_start = get_week_start()
    max_pts = MEDAL_LIMITS[medal_type]["max_points"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetch
