import os
import asyncpg
from datetime import datetime, date, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")
db_pool = None

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

        # Задел на будущее для визиток (чтобы потом не ломать базу)
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN business_info TEXT;")
        except asyncpg.exceptions.DuplicateColumnError:
            pass 

        await conn.execute("""
            INSERT INTO users (username, full_name, is_admin, is_owner)
            VALUES ($1, $2, 1, 1)
            ON CONFLICT (username) 
            DO UPDATE SET full_name = $2, is_admin = 1, is_owner = 1
        """, "studio_Slim_Line", "Разработчик")

# ─── ПОЛЬЗОВАТЕЛИ ───────────────────────────────────────────

async def add_user(username: str, full_name: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_active FROM users WHERE username=$1", uname)
        if row:
            if row["is_active"] == 1:
                return False
            else:
                await conn.execute("UPDATE users SET full_name=$1, is_active=1 WHERE username=$2", full_name, uname)
                return True
        else:
            await conn.execute("INSERT INTO users (username, full_name) VALUES ($1, $2)", uname, full_name)
            return True

async def remove_user(username: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute("UPDATE users SET is_active=0 WHERE username=$1", username.lstrip("@"))
        return status != "UPDATE 0"

async def get_user(username: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE username=$1 AND is_active=1", username.lstrip("@"))
        return dict(row) if row else None

async def get_all_users() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users WHERE is_active=1 ORDER BY full_name")
        return [dict(r) for r in rows]

async def update_user_tg_id(username: str, tg_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET telegram_id=$1 WHERE username=$2", tg_id, username.lstrip("@"))

async def update_user_photo(username: str, file_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET photo_file_id=$1 WHERE username=$2", file_id, username.lstrip("@"))

async def update_user_business_info(username: str, info: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET business_info=$1 WHERE username=$2", info, username.lstrip("@"))

# ─── МЕДАЛИ И СТАТИСТИКА ────────────────────────────────────
MEDAL_LIMITS = {
    "contact": {"points_per": 1, "max_points": 3},
    "vklad":   {"points_per": 1, "max_points": 4},
    "proryv":  {"points_per": 2, "max_points": 6},
}
MEDAL_NAMES = {"contact": "⭐ Контакт", "vklad": "💛 Вклад", "proryv": "🔥 Прорыв"}

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
        row = await conn.fetchrow("SELECT points FROM weekly_limits WHERE username=$1 AND medal_type=$2 AND week_start=$3", username.lstrip("@"), medal_type, week_start)
        used = row["points"] if row else 0
    return {"ok": used + points <= max_pts, "used": used, "max": max_pts}

async def award_medal(username: str, medal_type: str, comment: str, awarded_by: str) -> dict:
    uname = username.lstrip("@")
    pts = MEDAL_LIMITS[medal_type]["points_per"]
    month = get_current_month()
    week_start = get_week_start()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("INSERT INTO medals (username, medal_type, points, comment, awarded_by, month) VALUES ($1,$2,$3,$4,$5,$6)", uname, medal_type, pts, comment, awarded_by.lstrip("@"), month)
            await conn.execute("""
                INSERT INTO weekly_limits (username, medal_type, week_start, count, points)
                VALUES ($1, $2, $3, 1, $4)
                ON CONFLICT(username, medal_type, week_start)
                DO UPDATE SET count=weekly_limits.count+1, points=weekly_limits.points+$5
            """, uname, medal_type, week_start, pts, pts)
    return {"success": True, "points": pts, "medal_name": MEDAL_NAMES[medal_type]}

async def cancel_last_medal(username: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, medal_type, points FROM medals WHERE username=$1 ORDER BY id DESC LIMIT 1", uname)
        if not row: return False
        medal_id, medal_type, pts = row["id"], row["medal_type"], row["points"]
        week_start = get_week_start()
        async with conn.transaction():
            await conn.execute("DELETE FROM medals WHERE id=$1", medal_id)
            await conn.execute("""
                UPDATE weekly_limits SET count=GREATEST(0,count-1), points=GREATEST(0,points-$1)
                WHERE username=$2 AND medal_type=$3 AND week_start=$4
            """, pts, uname, medal_type, week_start)
    return True

async def get_monthly_stats(month: str = None) -> list[dict]:
    if not month: month = get_current_month()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.username, u.full_name, u.photo_file_id,
                   COALESCE(SUM(m.points), 0) as total_points,
                   COALESCE(SUM(CASE WHEN m.medal_type='contact' THEN 1 ELSE 0 END), 0) as contact_count,
                   COALESCE(SUM(CASE WHEN m.medal_type='vklad'   THEN 1 ELSE 0 END), 0) as vklad_count,
                   COALESCE(SUM(CASE WHEN m.medal_type='proryv'  THEN 1 ELSE 0 END), 0) as proryv_count
            FROM users u
            LEFT JOIN medals m ON u.username=m.username AND m.month=$1
            WHERE u.is_active=1
            GROUP BY u.username, u.full_name, u.photo_file_id
            ORDER BY total_points DESC
        """, month)
        return [dict(r) for r in rows]

async def get_user_history(username: str, limit: int = 1000) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM medals WHERE username=$1 ORDER BY awarded_at DESC LIMIT $2", username.lstrip("@"), limit)
        return [dict(r) for r in rows]

# ─── ИСПРАВЛЕННОЕ УПРАВЛЕНИЕ АДМИНАМИ ────────────────────────

async def add_admin(username: str, added_by: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Проверяем, может он уже админ в главной таблице
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE username=$1", uname)
        if row and row["is_admin"] == 1:
            return False # Точно уже админ
            
        try:
            async with conn.transaction():
                # УМНЫЙ ХОД: Если юзера нет, бот сам его создаст с именем = username
                await conn.execute("""
                    INSERT INTO users (username, full_name, is_admin, is_active)
                    VALUES ($1, $1, 1, 1)
                    ON CONFLICT (username)
                    DO UPDATE SET is_admin=1, is_active=1
                """, uname)
                
                # Записываем в логи админов, игнорируем ошибку, если он там застрял призраком
                await conn.execute("""
                    INSERT INTO admins (username, added_by) 
                    VALUES ($1,$2)
                    ON CONFLICT (username) DO NOTHING
                """, uname, added_by.lstrip("@"))
            return True
        except Exception as e:
            print(f"Ошибка при добавлении админа: {e}")
            return False

async def remove_admin(username: str) -> bool:
    uname = username.lstrip("@")
    if uname.lower() == "studio_slim_line": return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM admins WHERE username=$1", uname)
            await conn.execute("UPDATE users SET is_admin=0, is_owner=0 WHERE username=$1", uname)
    return True

async def make_owner(username: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_owner FROM users WHERE username=$1", uname)
        if row and row["is_owner"] == 1:
            return False 

        async with conn.transaction():
            await conn.execute("""
                INSERT INTO users (username, full_name, is_admin, is_owner, is_active)
                VALUES ($1, $1, 1, 1, 1)
                ON CONFLICT (username)
                DO UPDATE SET is_owner=1, is_admin=1, is_active=1
            """, uname)
            
            await conn.execute("""
                INSERT INTO admins (username, added_by) 
                VALUES ($1, 'system')
                ON CONFLICT (username) DO NOTHING
            """, uname)
        return True

async def revoke_owner(username: str) -> bool:
    uname = username.lstrip("@")
    if uname.lower() == "studio_slim_line": return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute("UPDATE users SET is_owner=0 WHERE username=$1", uname)
        return status != "UPDATE 0"

async def is_admin(username: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin, is_owner FROM users WHERE username=$1 AND is_active=1", uname)
        return bool(row and (row["is_admin"] or row["is_owner"]))

async def is_owner(username: str) -> bool:
    uname = username.lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_owner FROM users WHERE username=$1", uname)
        return bool(row and row["is_owner"])

async def get_all_admins() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users WHERE is_admin=1 OR is_owner=1")
        return [dict(r) for r in rows]

# ─── ПОЗДРАВЛЕНИЯ ────────────────────────────────────────────
async def save_congrats(month: str, text: str, author: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO month_messages (month, congrats_text, congrats_author) 
            VALUES ($1,$2,$3) ON CONFLICT (month) DO UPDATE SET congrats_text=$2, congrats_author=$3
        """, month, text, author)

async def get_congrats(month: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM month_messages WHERE month=$1", month)
        return dict(row) if row else None

async def mark_congrats_sent(month: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE month_messages SET sent=1 WHERE month=$1", month)
