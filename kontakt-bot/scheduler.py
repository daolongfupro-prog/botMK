import os
import logging
from datetime import datetime, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from database import (
    get_monthly_stats, get_current_month, get_all_users,
    get_congrats, mark_congrats_sent, save_congrats,
    MEDAL_NAMES
)

logger = logging.getLogger(__name__)

OWNER_USERNAME = "studio_Slim_Line"
GROUP_ID = os.getenv("GROUP_ID")  # добавишь позже

MOTIVATING_TEXT = (
    "💪 Каждый из вас делает важный шаг — в контакте с собой и другими.\n"
    "Новый месяц — новые возможности для роста. Вперёд, Метод Контакта! 🌟"
)

def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot):
    # Последний день месяца — сводка владельцу
    scheduler.add_job(
        send_month_summary,
        trigger="cron",
        day="last",
        hour=19,
        minute=0,
        args=[bot],
        id="month_summary"
    )

    # 1-е число — отправка поздравлений
    scheduler.add_job(
        send_congrats,
        trigger="cron",
        day=1,
        hour=10,
        minute=0,
        args=[bot],
        id="send_congrats"
    )

    # Воскресенье — автобэкап владельцу
    scheduler.add_job(
        send_weekly_backup,
        trigger="cron",
        day_of_week="sun",
        hour=20,
        minute=0,
        args=[bot],
        id="weekly_backup"
    )

    logger.info("Планировщик настроен ✅")


# ─── СВОДКА В КОНЦЕ МЕСЯЦА ───────────────────────────────────

async def send_month_summary(bot: Bot):
    try:
        month = get_current_month()
        stats = await get_monthly_stats(month)
        dt = datetime.strptime(month, "%Y-%m")
        month_name = dt.strftime("%B %Y")

        text = (
            f"📊 <b>Итоги месяца — {month_name}</b>\n"
            f"Метод Контакта\n\n"
        )

        medals_top = ["🥇", "🥈", "🥉"]
        for i, s in enumerate(stats):
            prefix = medals_top[i] if i < 3 else f"{i+1}."
            text += (
                f"{prefix} <b>{s['full_name']}</b> (@{s['username']})\n"
                f"   ⭐×{s['contact_count']} 💛×{s['vklad_count']} 🔥×{s['proryv_count']} "
                f"│ <b>{s['total_points']} балл(ов)</b>\n\n"
            )

        text += (
            "─────────────────\n"
            "Выберите кто поздравит участников:\n\n"
            "✍️ Напишите /write_congrats — чтобы написать своё поздравление\n"
            "🤖 Напишите /bot_congrats — чтобы бот поздравил сам\n\n"
            "Поздравление будет отправлено завтра (1-го числа) в 10:00"
        )

        # Находим telegram_id владельца
        users = await get_all_users()
        owner = next((u for u in users if u["username"] == OWNER_USERNAME), None)
        if owner and owner.get("telegram_id"):
            await bot.send_message(owner["telegram_id"], text, parse_mode="HTML")
            logger.info("Сводка месяца отправлена владельцу")

    except Exception as e:
        logger.error(f"Ошибка при отправке сводки: {e}")


# ─── ПОЗДРАВЛЕНИЕ 1-ГО ЧИСЛА ─────────────────────────────────

async def send_congrats(bot: Bot):
    try:
        # Берём прошлый месяц (сейчас уже новый)
        now = datetime.now()
        if now.month == 1:
            prev_month = f"{now.year - 1}-12"
        else:
            prev_month = f"{now.year}-{now.month - 1:02d}"

        congrats = await get_congrats(prev_month)
        if not congrats or congrats.get("sent"):
            logger.info("Поздравление уже отправлено или не найдено")
            return

        stats = await get_monthly_stats(prev_month)
        dt = datetime.strptime(prev_month, "%Y-%m")
        month_name = dt.strftime("%B %Y")

        # Топ-3
        top3 = stats[:3]
        rest = stats[3:]

        # Текст поздравления
        if congrats.get("congrats_author") == "bot" or not congrats.get("congrats_text"):
            congrats_text = _generate_bot_congrats(top3, month_name)
        else:
            congrats_text = congrats["congrats_text"]

        # ── Личные сообщения топ-3 ──
        medals_emoji = ["🥇", "🥈", "🥉"]
        personal_texts = [
            f"🎉 <b>Поздравляем!</b>\n\nВы заняли {medals_emoji[i]} место в {month_name}!\n\n"
            f"⭐×{s['contact_count']} 💛×{s['vklad_count']} 🔥×{s['proryv_count']} "
            f"│ <b>{s['total_points']} балл(ов)</b>\n\n"
            f"{congrats_text}"
            for i, s in enumerate(top3)
        ]

        users = await get_all_users()
        user_map = {u["username"]: u for u in users}

        for i, s in enumerate(top3):
            u = user_map.get(s["username"])
            if u and u.get("telegram_id"):
                try:
                    await bot.send_message(
                        u["telegram_id"],
                        personal_texts[i],
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки топ-3 @{s['username']}: {e}")

        # ── Сообщение в группу ──
        if GROUP_ID:
            group_text = (
                f"🏆 <b>Итоги {month_name} — Метод Контакта</b>\n\n"
            )
            for i, s in enumerate(top3):
                group_text += (
                    f"{medals_emoji[i]} <b>{s['full_name']}</b>\n"
                    f"   ⭐×{s['contact_count']} 💛×{s['vklad_count']} 🔥×{s['proryv_count']} "
                    f"│ <b>{s['total_points']} балл(ов)</b>\n\n"
                )

            if rest:
                group_text += "─────────────────\n"
                for i, s in enumerate(rest, 4):
                    group_text += (
                        f"{i}. {s['full_name']} — {s['total_points']} балл(ов)\n"
                    )
                group_text += "\n"

            group_text += f"─────────────────\n{congrats_text}\n\n{MOTIVATING_TEXT}"

            try:
                await bot.send_message(GROUP_ID, group_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка отправки в группу: {e}")

        await mark_congrats_sent(prev_month)
        logger.info(f"Поздравления за {prev_month} отправлены ✅")

    except Exception as e:
        logger.error(f"Ошибка при отправке поздравлений: {e}")


def _generate_bot_congrats(top3: list, month_name: str) -> str:
    if not top3:
        return "Отличная работа всем участникам! 🌟"
    leader = top3[0]
    return (
        f"🌟 <b>Лидер {month_name} — {leader['full_name']}!</b>\n\n"
        f"Этот месяц показал настоящую силу контакта с собой и другими. "
        f"Каждый жетон — это реальный шаг, реальное действие, реальное изменение. "
        f"Гордимся каждым участником клуба! 💪"
    )


# ─── ЕЖЕНЕДЕЛЬНЫЙ БЭКАП ──────────────────────────────────────

async def send_weekly_backup(bot: Bot):
    try:
        from handlers.admin import send_backup
        users = await get_all_users()
        owner = next((u for u in users if u["username"] == OWNER_USERNAME), None)
        if owner and owner.get("telegram_id"):
            await send_backup(bot, owner["telegram_id"])
            logger.info("Еженедельный бэкап отправлен ✅")
    except Exception as e:
        logger.error(f"Ошибка бэкапа: {e}")
