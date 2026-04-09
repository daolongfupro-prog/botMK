from aiogram.types import BufferedInputFile
from image_generator import create_top_image # Импортируем нашу функцию
from image_generator import create_stat_image

from aiogram import Router, F, Bot
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
async def cmd_my(msg: Message, bot: Bot): # <-- ОБРАТИ ВНИМАНИЕ: добавили параметр bot: Bot
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

    by_month: dict[str, list] = {}
    for m in medals:
        by_month.setdefault(m["month"], []).append(m)

    if not medals:
        await msg.answer("🏅 У вас пока нет жетонов. Вперёд — к первому! 💪")
        return

    # Генерируем картинку!
    await msg.answer("⏳ Собираем вашу статистику...") # Пишем, чтобы пользователь не скучал, пока грузится
    
    image_bytes = await create_stat_image(bot, user, by_month, current_month)
    photo = BufferedInputFile(image_bytes.read(), filename="stats.png")
    
    # Отправляем готовую картинку с короткой подписью
    await msg.answer_photo(
        photo=photo, 
        caption=f"🏅 <b>Жетоны {user['full_name']}</b>", 
        parse_mode="HTML"
    )

@user_router.message(Command("top"))
async def cmd_top(msg: Message, bot: Bot): 
    month = get_current_month()
    # Получаем вообще всех из базы
    all_stats = await get_monthly_stats(month)

    # --- УМНАЯ ФИЛЬТРАЦИЯ ---
    # 1. Запрашиваем из базы список всех админов и владельца
    admins = await get_all_admins()
    # 2. Создаем список только из их юзернеймов
    admin_usernames = [a["username"] for a in admins]
    # 3. Формируем новый топ: берем человека, только если его нет в списке админов
    stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    # Уведомляем пользователя, что картинка рисуется
    await msg.answer("⏳ Собираю топ участников...")
    
    try:
        # Генерируем изображение карточки Топ-листа (передаем уже очищенный stats)
        image_bytes = await create_top_image(bot, stats, month)
        
        # Создаем файл для отправки
        photo = BufferedInputFile(image_bytes.read(), filename=f"top_{month}.png")
        
        # Отправляем готовую картинку с короткой подписью
        await msg.answer_photo(
            photo=photo,
            caption=f"🏆 <b>Топ участников — {month}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await msg.answer(f"❌ Ошибка генерации картинки: {e}")
        print(f"Ошибка в cmd_top: {e}")
        
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
