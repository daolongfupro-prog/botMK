from aiogram import Router, F, Bot
from aiogram.types import Message, PhotoSize, BufferedInputFile
from aiogram.filters import Command
from datetime import datetime

# Аккуратно сгруппированные импорты наших функций
from image_generator import create_top_image, create_stat_image
from database import (
    get_user, update_user_tg_id, update_user_photo,
    get_user_medals, get_monthly_stats, get_current_month,
    MEDAL_NAMES, is_admin, get_all_admins
)

user_router = Router()

COMMUNITY = "Метод Контакта"

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

    # Сохраняем ID пользователя для будущих рассылок
    await update_user_tg_id(uname, msg.from_user.id)

    # Получаем статистику только для того, чтобы показать баллы
    month = get_current_month()
    stats = await get_monthly_stats(month)
    user_stat = next((s for s in stats if s["username"] == uname), None)
    pts = user_stat["total_points"] if user_stat else 0

    # Проверяем, админ ли это
    adm = await is_admin(uname)

    # Формируем динамическое приветствие
    text = (
        f"👋 Привет, <b>{user['full_name']}</b>!\n\n"
        f"🏅 Сообщество: <b>{COMMUNITY}</b>\n"
        f"💎 Баллов в этом месяце: <b>{pts}</b>\n\n"
        f"📋 Доступные команды:\n"
    )

    # Если админ - показываем админку, скрываем личное
    if adm:
        text += f"/admin — панель управления\n"
    else:
        text += f"/my — мои жетоны\n"
        text += f"/setphoto — загрузить фото\n"
        
    text += f"/top — лидерборд\n"
    text += f"/help — помощь"

    if user.get("photo_file_id"):
        await msg.answer_photo(user["photo_file_id"], caption=text, parse_mode="HTML")
    else:
        await msg.answer(text, parse_mode="HTML")


@user_router.message(Command("my"))
async def cmd_my(msg: Message, bot: Bot):
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

    await msg.answer("⏳ Собираем вашу статистику...")
    
    image_bytes = await create_stat_image(bot, user, by_month, current_month)
    photo = BufferedInputFile(image_bytes.read(), filename="stats.png")
    
    await msg.answer_photo(
        photo=photo, 
        caption=f"🏅 <b>Жетоны {user['full_name']}</b>", 
        parse_mode="HTML"
    )


@user_router.message(Command("top"))
async def cmd_top(msg: Message, bot: Bot): 
    month = get_current_month()
    all_stats = await get_monthly_stats(month)

    # --- УМНАЯ ФИЛЬТРАЦИЯ ---
    # Запрашиваем из базы список всех админов и владельца
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    # Формируем новый топ: берем человека, только если его нет в списке админов
    stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    await msg.answer("⏳ Собираю топ участников...")
    
    try:
        image_bytes = await create_top_image(bot, stats, month)
        photo = BufferedInputFile(image_bytes.read(), filename=f"top_{month}.png")
        
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
    
    text = f"📖 <b>Помощь — {COMMUNITY}</b>\n\n"
    text += f"/start — главная страница профиля\n"
    text += f"/top — лидерборд текущего месяца\n"
    text += f"/help — эта справка\n"
    
    if adm:
        text += f"\n👑 <b>Команды администратора</b>\n"
        text += f"/admin — панель управления\n"
    else:
        text += f"\n🏅 <b>Команды участника</b>\n"
        text += f"/my — все мои жетоны по месяцам\n"
        text += f"/setphoto — загрузить фото профиля\n"

    await msg.answer(text, parse_mode="HTML")
