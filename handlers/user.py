from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime

from image_generator import create_top_image, create_stat_image
from database import (
    get_user, update_user_tg_id, update_user_photo, update_user_business_info,
    get_monthly_stats, get_current_month,
    MEDAL_NAMES, is_admin, get_all_admins, get_user_history, get_all_users
)

user_router = Router()
COMMUNITY = "Метод Контакта"

# ─── СОСТОЯНИЯ ДЛЯ ЗАПОЛНЕНИЯ ПРОФИЛЯ ───
class UserProfile(StatesGroup):
    waiting_for_photo = State()
    waiting_for_bio = State()

# ─── КЛАВИАТУРЫ ───
def user_main_kb(is_adm: bool) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🏅 Мои жетоны", callback_data="user_my_stats"),
         InlineKeyboardButton(text="📊 Лидерборд", callback_data="user_top")],
        [InlineKeyboardButton(text="🤝 Нетворкинг (Участники)", callback_data="networking_list")],
        [InlineKeyboardButton(text="💼 Заполнить визитку", callback_data="edit_bio"),
         InlineKeyboardButton(text="📸 Обновить фото", callback_data="edit_photo")]
    ]
    if is_adm:
        kb.append([InlineKeyboardButton(text="👑 Панель Администратора", callback_data="go_to_admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_user_main")]
    ])

async def generate_networking_kb() -> InlineKeyboardMarkup:
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    
    # Исключаем админов из списка нетворкинга (по аналогии с топом)
    pure_users = [u for u in users if u["username"] not in admin_usernames]
    
    keyboard = []
    for u in pure_users:
        keyboard.append([InlineKeyboardButton(text=f"👤 {u['full_name']}", callback_data=f"net_user_{u['username']}")])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_user_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ─── ГЛАВНОЕ МЕНЮ ───
@user_router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uname = msg.from_user.username
    if not uname:
        await msg.answer("❌ У вас не установлен username в Telegram. Пожалуйста, задайте его в настройках.")
        return

    user = await get_user(uname)
    if not user:
        await msg.answer(f"👋 Добро пожаловать!\n\nВы не найдены в системе сообщества <b>{COMMUNITY}</b>.\nОбратитесь к организатору для добавления.", parse_mode="HTML")
        return

    await update_user_tg_id(uname, msg.from_user.id)
    adm = await is_admin(uname)
    month = get_current_month()
    all_stats = await get_monthly_stats(month)

    if adm:
        admins = await get_all_admins()
        admin_unames = [a["username"] for a in admins]
        pts = sum(s.get("total_points", 0) for s in all_stats if s.get("username") not in admin_unames)
        pts_text = f"💎 Выдано баллов участникам за месяц: <b>{pts}</b>"
    else:
        user_stat = next((s for s in all_stats if s.get("username") == uname), None)
        pts = user_stat.get("total_points", 0) if user_stat else 0
        pts_text = f"💎 Баллов в этом месяце: <b>{pts}</b>"

    text = (
        f"👋 Привет, <b>{user['full_name']}</b>!\n\n"
        f"🏅 Сообщество: <b>{COMMUNITY}</b>\n"
        f"{pts_text}\n\n"
        f"Выберите действие в меню ниже 👇"
    )

    kb = user_main_kb(adm)
    if user.get("photo_file_id"):
        await msg.answer_photo(user["photo_file_id"], caption=text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@user_router.callback_query(F.data == "back_to_user_main")
async def cb_back_to_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    uname = cb.from_user.username
    user = await get_user(uname)
    if not user: return
    
    adm = await is_admin(uname)
    month = get_current_month()
    all_stats = await get_monthly_stats(month)

    if adm:
        admins = await get_all_admins()
        pts = sum(s.get("total_points", 0) for s in all_stats if s.get("username") not in [a["username"] for a in admins])
        pts_text = f"💎 Выдано баллов участникам за месяц: <b>{pts}</b>"
    else:
        user_stat = next((s for s in all_stats if s.get("username") == uname), None)
        pts = user_stat.get("total_points", 0) if user_stat else 0
        pts_text = f"💎 Баллов в этом месяце: <b>{pts}</b>"

    text = f"👋 Привет, <b>{user['full_name']}</b>!\n\n🏅 Сообщество: <b>{COMMUNITY}</b>\n{pts_text}\n\nВыберите действие в меню ниже 👇"
    
    try: await cb.message.delete()
    except: pass

    if user.get("photo_file_id"):
        await cb.message.answer_photo(user["photo_file_id"], caption=text, parse_mode="HTML", reply_markup=user_main_kb(adm))
    else:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=user_main_kb(adm))
    await cb.answer()

# Переход в админку для удобства
@user_router.callback_query(F.data == "go_to_admin")
async def cb_go_to_admin(cb: CallbackQuery):
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("Введите команду /admin для входа в панель управления.")
    await cb.answer()

# ─── КНОПКИ ГЛАВНОГО МЕНЮ ───

@user_router.callback_query(F.data == "user_my_stats")
async def cb_my_stats(cb: CallbackQuery, bot: Bot):
    uname = cb.from_user.username
    user = await get_user(uname)
    medals = await get_user_history(uname, limit=1000)
    current_month = get_current_month()

    by_month: dict[str, list] = {}
    for m in medals:
        by_month.setdefault(m["month"], []).append(m)

    try: await cb.message.delete()
    except: pass

    if not medals:
        await cb.message.answer("🏅 У вас пока нет жетонов. Вперёд — к первому! 💪", reply_markup=back_to_main_kb())
        return

    wait_msg = await cb.message.answer("⏳ Собираем вашу статистику...")
    image_bytes = await create_stat_image(bot, user, by_month, current_month)
    photo = BufferedInputFile(image_bytes.read(), filename="stats.png")
    
    await wait_msg.delete()
    await cb.message.answer_photo(photo=photo, caption=f"👤 Карточка участника: {user['full_name']}", parse_mode="HTML", reply_markup=back_to_main_kb())
    await cb.answer()

@user_router.callback_query(F.data == "user_top")
async def cb_user_top(cb: CallbackQuery, bot: Bot): 
    month = get_current_month()
    all_stats = await get_monthly_stats(month)
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    try: await cb.message.delete()
    except: pass

    wait_msg = await cb.message.answer("⏳ Собираю топ участников...")
    try:
        image_bytes = await create_top_image(bot, stats, month)
        photo = BufferedInputFile(image_bytes.read(), filename=f"top_{month}.png")
        await wait_msg.delete()
        await cb.message.answer_photo(photo=photo, caption=f"🏆 <b>Итоги месяца — {month}</b>", parse_mode="HTML", reply_markup=back_to_main_kb())
    except Exception as e:
        await wait_msg.delete()
        await cb.message.answer(f"❌ Ошибка генерации: {e}", reply_markup=back_to_main_kb())
    await cb.answer()

# ─── РЕДАКТИРОВАНИЕ ПРОФИЛЯ (ФОТО И БИО) ───

@user_router.callback_query(F.data == "edit_photo")
async def cb_edit_photo(cb: CallbackQuery, state: FSMContext):
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("📸 Отправьте фото, которое будет вашим аватаром и визиткой в системе:", reply_markup=back_to_main_kb())
    await state.set_state(UserProfile.waiting_for_photo)
    await cb.answer()

@user_router.message(UserProfile.waiting_for_photo, F.photo)
async def process_photo(msg: Message, state: FSMContext):
    uname = msg.from_user.username
    if not uname: return
    photo: PhotoSize = msg.photo[-1]
    await update_user_photo(uname, photo.file_id)
    await msg.answer("✅ Фото профиля успешно обновлено!", reply_markup=back_to_main_kb())
    await state.clear()

@user_router.callback_query(F.data == "edit_bio")
async def cb_edit_bio(cb: CallbackQuery, state: FSMContext):
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(
        "💼 <b>Расскажите о себе и своем бизнесе!</b>\n\n"
        "Напишите текст, который увидят другие участники в разделе Нетворкинг.\n"
        "<i>(Чем вы занимаетесь, чем можете быть полезны, ваши контакты)</i>", 
        parse_mode="HTML", reply_markup=back_to_main_kb()
    )
    await state.set_state(UserProfile.waiting_for_bio)
    await cb.answer()

@user_router.message(UserProfile.waiting_for_bio, F.text)
async def process_bio(msg: Message, state: FSMContext):
    uname = msg.from_user.username
    if not uname: return
    
    bio_text = msg.text
    await update_user_business_info(uname, bio_text)
    
    await msg.answer("✅ Ваша бизнес-визитка успешно сохранена! Теперь её увидят другие участники.", reply_markup=back_to_main_kb())
    await state.clear()

# ─── НЕТВОРКИНГ (КАТАЛОГ УЧАСТНИКОВ) ───

@user_router.callback_query(F.data == "networking_list")
async def cb_networking_list(cb: CallbackQuery):
    kb = await generate_networking_kb()
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(
        "🤝 <b>Нетворкинг клуба</b>\n\n"
        "Выберите участника, чтобы посмотреть его бизнес-визитку:",
        parse_mode="HTML", reply_markup=kb
    )
    await cb.answer()

@user_router.callback_query(F.data.startswith("net_user_"))
async def cb_show_net_user(cb: CallbackQuery):
    target_uname = cb.data.replace("net_user_", "")
    target_user = await get_user(target_uname)
    
    if not target_user:
        await cb.answer("❌ Пользователь не найден.", show_alert=True)
        return

    # Собираем красивую визитку
    bio = target_user.get("business_info")
    if not bio:
        bio = "<i>Участник пока не заполнил информацию о себе.</i>"
    
    card_text = (
        f"📇 <b>Визитка: {target_user['full_name']}</b>\n"
        f"🔗 Telegram: @{target_user['username']}\n\n"
        f"💼 <b>О бизнесе:</b>\n{bio}"
    )

    try: await cb.message.delete()
    except: pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="networking_list")]
    ])

    if target_user.get("photo_file_id"):
        # Отправляем оригинальное фото без кругов и обрезок
        await cb.message.answer_photo(
            photo=target_user["photo_file_id"], 
            caption=card_text, 
            parse_mode="HTML", 
            reply_markup=kb
        )
    else:
        # Если фото нет, отправляем просто текст
        await cb.message.answer(
            card_text, 
            parse_mode="HTML", 
            reply_markup=kb
        )
    await cb.answer()

# ─── ОСТАВЛЯЕМ СТАРЫЕ КОМАНДЫ ДЛЯ СОВМЕСТИМОСТИ ───
@user_router.message(Command("my"))
async def cmd_my(msg: Message, bot: Bot):
    await cb_my_stats(msg, bot) # Перенаправляем на новую логику

@user_router.message(Command("top"))
async def cmd_top(msg: Message, bot: Bot): 
    await cb_user_top(msg, bot)

@user_router.message(Command("setphoto"))
async def cmd_setphoto(msg: Message):
    await msg.answer("Нажмите кнопку /start и выберите «📸 Обновить фото» в меню.")

@user_router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("Просто отправьте /start, чтобы открыть удобное кнопочное меню!")
