import os
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from database import get_active_stats, get_all_users

logger = logging.getLogger(__name__)

# Тот же ID владельца для уведомлений
OWNER_USERNAME = "studio_Slim_Line"

def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot):
    # 1-е число месяца — напоминание владельцу закрыть период вручную
    scheduler.add_job(
        send_closure_reminder,
        trigger="cron",
        day=1,
        hour=10,
        minute=0,
        args=[bot],
        id="closure_reminder"
    )

    # Воскресенье — автобэкап владельцу (оставляем, это полезно)
    scheduler.add_job(
        send_weekly_backup,
        trigger="cron",
        day_of_week="sun",
        hour=20,
        minute=0,
        args=[bot],
        id="weekly_backup"
    )

    logger.info("Планировщик настроен (ручной режим) ✅")


# ─── НАПОМИНАНИЕ О ЗАКРЫТИИ ─────────────────────────────────

async def send_closure_reminder(bot: Bot):
    """
    Вместо автоматической отправки итогов, просто пишем админу,
    что наступило 1-е число и пора бы нажать кнопку в панели.
    """
    try:
        stats = await get_active_stats()
        if not stats:
            return

        text = (
            "🔔 <b>Напоминание: Начало нового периода!</b>\n\n"
            "В системе остались незакрытые итоги прошлого месяца.\n"
            "Пожалуйста, зайдите в <code>/admin</code> и нажмите <b>'Завершить период'</b>, "
            "чтобы перевести жетоны в архив и начать отсчет с чистого листа."
        )

        users = await get_all_users()
        # Ищем владельца без учета регистра букв (для надежности)
        owner = next((u for u in users if u["username"].lower() == OWNER_USERNAME.lower()), None)
        
        if owner and owner.get("telegram_id"):
            await bot.send_message(owner["telegram_id"], text, parse_mode="HTML")
            logger.info("Напоминание о закрытии отправлено владельцу")

    except Exception as e:
        logger.error(f"Ошибка в напоминании: {e}")


# ─── ЕЖЕНЕДЕЛЬНЫЙ БЭКАП ──────────────────────────────────────

async def send_weekly_backup(bot: Bot):
    try:
        # Импорт внутри, чтобы избежать циклической зависимости
        from handlers.admin import send_backup
        users = await get_all_users()
        owner = next((u for u in users if u["username"].lower() == OWNER_USERNAME.lower()), None)
        
        if owner and owner.get("telegram_id"):
            # Отправляем актуальный бэкап в личку
            await send_backup(bot, owner["telegram_id"])
            logger.info("Еженедельный бэкап отправлен ✅")
    except Exception as e:
        logger.error(f"Ошибка бэкапа: {e}")
