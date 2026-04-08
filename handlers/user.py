from aiogram.types import BufferedInputFile
from image_generator import create_stat_image
from aiogram import Router, F
from aiogram.types import Message, PhotoSize
from aiogram.filters import Command
from database import (
    get_user, update_user_tg_id, update_user_photo,
    get_user_medals, get_monthly_stats, get_current_month,
    MEDAL_NAMES, is_admin
)
from datetime import datetime

user_router = Router()

COMMUNITY = "Метод Контакта"

def get_status(points: int) -> str:
    if points >= 50:  return "🏆 Мастер"
    if points >= 25:  return "🔵 Проводник"
    if points >= 10:  return "🟢 Практик"
    return "⚪ Искатель"

def get_next_status(points: int) -> tuple[str, int]:
    if points >= 50:  return ("Мастер — высший уровень!", 0)
    if points >= 25:  return ("🏆 Мастер", 50 - points)
    if points >= 10:  return ("🔵 Проводник", 25 - points)
    return ("🟢 Практик", 10 - points)

def progress_bar(current: int, target: int, length: int = 10) -> str:
    if target == 0:
        return "█" * length
    filled = min(int((current / target) * length), length)
    return "█" * filled + "░" * (length - filled)

@user_router.message(Command("start"))
async def cmd_start(msg: Message):
    uname = msg.from_user.username
    if not uname:
        await msg.answer("❌ У вас не установлен username в Telegram. Пожалуйста, задайте его в настройках.")
        return

    user = await get_user(uname)
    if not user:
        await msg.answer(
            f"👋 Добро пожаловать!\n\n"
            f"Вы не найдены в системе сообщества <b>{COMMUNITY}</b>.\n"
            f"Обратитесь к организатору для добавления.",
            parse_mode="HTML"
        )
        return

    await update_user_tg_id(uname, msg.from_user.id)

    month = get_current_month()
    stats = await get_monthly_stats(month)
    user_stat = next((s for s in stats if s["username"] == uname), None)
    pts = user_stat["total_points"] if user_stat else 0
    status = get_status(pts)
    next_s, need = get_next_status(pts)
    bar = progress_bar(pts, pts + need)

    text = (
        f"👋 Привет, <b>{user['full_name']}</b>!\n\n"
        f"🏅 Сообщество: <b>{COMMUNITY}</b>\n\n"
        f"📊 Текущий статус: {status}\n"
        f"💎 Баллов в этом месяце: <b>{pts}</b>\n"
    )
    if need > 0:
        text += f"⬆️ До {next_s}: ещё <b>{need}</b> балл(ов)\n{bar}\n"
    else:
        text += f"🎯 {next_s}\n"

    text += (
        f"\n📋 Мои команды:\n"
        f"/my — мои жетоны\n"
        f"/top — лидерборд\n"
        f"/setphoto — загрузить фото\n"
        f"/help — помощь"
    )

    if user.get("photo_file_id"):
        await msg.answer_photo(user["photo_file_id"], caption=text, parse_mode="HTML")
    else:
        await msg.answer(text, parse_mode="HTML")


@user_router.message(Command("my"))
async def cmd_my(msg: Message):
    uname = msg.from_user.username
    if not uname:
        await msg.answer("❌ Установите username в настройках Telegram.")
        return

    user = await get_user(uname)
    if not user:
        await msg.answer("❌ Вы не найдены в системе. Обратитесь к организатору.")
        return

    medals = await get_user_medals(uname)
    current_month = get_current_month()

    # Разделяем по месяцам
    by_month: dict[str, list] = {}
    for m in medals:
        by_month.setdefault(m["month"], []).append(m)

    if not medals:
        await msg.answer(
            f"🏅 <b>{user['full_name']}</b>\n\n"
            f"У вас пока нет жетонов. Вперёд — к первому! 💪",
            parse_mode="HTML"
        )
        return

    text = f"🏅 <b>Жетоны {user['full_name']}</b>\n\n"

    for month, items in sorted(by_month.items(), reverse=True):
        dt = datetime.strptime(month, "%Y-%m")
        month_name = dt.strftime("%B %Y")
        is_current = month == current_month

        contact = sum(1 for i in items if i["medal_type"] == "contact")
        vklad   = sum(1 for i in items if i["medal_type"] == "vklad")
        proryv  = sum(1 for i in items if i["medal_type"] == "proryv")
        total   = sum(i["points"] for i in items)

        if is_current:
            text += f"📅 <b>{month_name}</b> (текущий)\n"
            text += f"⭐ Контакт × {contact}  💛 Вклад × {vklad}  🔥 Прорыв × {proryv}\n"
            text += f"💎 Итого: <b>{total} балл(ов)</b>\n\n"
            # Детали текущего месяца
            for i in items:
                date_str = i["awarded_at"][:10]
                cmt = f" — {i['comment']}" if i.get("comment") else ""
                text += f"  {MEDAL_NAMES[i['medal_type']]} {date_str}{cmt}\n"
            text += "\n"
        else:
            # Прошлые месяцы — ЧБ, только сводка
            text += f"◻️ <i>{month_name}</i>\n"
            text += f"★ ×{contact}  ♡ ×{vklad}  ✦ ×{proryv}  │  {total} балл(ов)\n\n"

    await msg.answer(text, parse_mode="HTML")


@user_router.message(Command("top"))
async def cmd_top(msg: Message):
    uname = msg.from_user.username
    month = get_current_month()
    stats = await get_monthly_stats(month)

    dt = datetime.strptime(month, "%Y-%m")
    month_name = dt.strftime("%B %Y")

    text = f"🏆 <b>Лидерборд — {month_name}</b>\n\n"
    medals_top = ["🥇", "🥈", "🥉"]

    for i, s in enumerate(stats):
        prefix = medals_top[i] if i < 3 else f"{i+1}."
        is_me = s["username"] == uname
        name = f"<b>{s['full_name']}</b>" if is_me else s["full_name"]
        you = " ← вы" if is_me else ""
        text += (
            f"{prefix} {name}{you}\n"
            f"   ⭐×{s['contact_count']} 💛×{s['vklad_count']} 🔥×{s['proryv_count']} │ "
            f"<b>{s['total_points']} балл(ов)</b>\n\n"
        )

    if not stats:
        text += "Пока нет данных за этот месяц."

    await msg.answer(text, parse_mode="HTML")


@user_router.message(Command("setphoto"))
async def cmd_setphoto(msg: Message):
    uname = msg.from_user.username
    if not uname:
        await msg.answer("❌ Установите username в настройках Telegram.")
        return
    user = await get_user(uname)
    if not user:
        await msg.answer("❌ Вы не найдены в системе.")
        return
    await msg.answer(
        "📸 Отправьте фото, которое будет вашим аватаром в системе.\n"
        "Это фото будут видеть другие участники в статистике."
    )


@user_router.message(F.photo)
async def handle_photo(msg: Message):
    uname = msg.from_user.username
    if not uname:
        return
    user = await get_user(uname)
    if not user:
        return
    photo: PhotoSize = msg.photo[-1]
    await update_user_photo(uname, photo.file_id)
    await msg.answer("✅ Фото профиля обновлено!")


@user_router.message(Command("help"))
async def cmd_help(msg: Message):
    uname = msg.from_user.username
    adm = await is_admin(uname) if uname else False
    text = (
        f"📖 <b>Команды участника — {COMMUNITY}</b>\n\n"
        f"/start — главная страница профиля\n"
        f"/my — все мои жетоны по месяцам\n"
        f"/top — лидерборд текущего месяца\n"
        f"/setphoto — загрузить фото профиля\n"
        f"/help — эта справка\n"
    )
    if adm:
        text += (
            f"\n👑 <b>Команды администратора</b>\n"
            f"/admin — панель управления\n"
        )
    await msg.answer(text, parse_mode="HTML")
