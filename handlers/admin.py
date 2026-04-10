from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import openpyxl, io

# Импортируем генераторы картинок для админки
from image_generator import create_top_image, create_stat_image
from database import (
    get_user, get_all_users, add_user, remove_user,
    award_medal, cancel_last_medal, check_weekly_limit,
    get_monthly_stats, get_user_history, get_current_month,
    add_admin, remove_admin, get_all_admins, is_admin, is_owner,
    save_congrats, MEDAL_NAMES, MEDAL_LIMITS
)

admin_router = Router()

# ─── FSM состояния ───────────────────────────────────────────
class AddUser(StatesGroup):
    waiting_username = State()
    waiting_fullname = State()

class GiveMedal(StatesGroup):
    waiting_medal   = State()
    waiting_comment = State()
    confirm_overlimit = State()

class AdminMgmt(StatesGroup):
    waiting_add    = State()
    waiting_remove = State()

class CongratsWrite(StatesGroup):
    waiting_text = State()

# ─── Вспомогательные функции и проверки ──────────────────────
def back_button_kb() -> InlineKeyboardMarkup:
    """Универсальная кнопка Назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="cancel_admin_action")]
    ])

async def check_admin_cb(cb: CallbackQuery) -> bool:
    uname = cb.from_user.username
    if not uname or not await is_admin(uname):
        await cb.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return False
    return True

async def check_owner_cb(cb: CallbackQuery) -> bool:
    uname = cb.from_user.username
    if not uname or not await is_owner(uname):
        await cb.answer("⛔ Только владелец может это сделать.", show_alert=True)
        return False
    return True

# ─── ГЛАВНОЕ МЕНЮ ────────────────────────────────────────────
def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Начислить жетон",  callback_data="give_medal")],
        [InlineKeyboardButton(text="🗑 Снять жетон",      callback_data="revoke_medal")],
        [InlineKeyboardButton(text="👥 Участники (Карточки)", callback_data="list_users")],
        [InlineKeyboardButton(text="➕ Добавить участника", callback_data="add_user")],
        [InlineKeyboardButton(text="➖ Удалить участника",  callback_data="remove_user")],
        [InlineKeyboardButton(text="📊 Итоги месяца", callback_data="month_stats")],
        [InlineKeyboardButton(text="📤 Excel Бэкап",       callback_data="backup")],
        [InlineKeyboardButton(text="👑 Управление админами", callback_data="manage_admins")],
    ])

@admin_router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    await state.clear()
    uname = msg.from_user.username
    if not uname or not await is_admin(uname):
        await msg.answer("⛔ У вас нет прав администратора.")
        return
    await msg.answer("👑 <b>Панель управления Метод Контакта</b>", 
                     parse_mode="HTML", reply_markup=admin_menu_kb())

@admin_router.callback_query(F.data == "cancel_admin_action")
async def cb_cancel_admin_action(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("👑 <b>Панель управления Метод Контакта</b>", 
                               parse_mode="HTML", reply_markup=admin_menu_kb())
    await cb.answer()

# ─── ГЕНЕРАТОР СПИСКА УЧАСТНИКОВ (ФИЛЬТРАЦИЯ АДМИНОВ) ────────
async def users_list_kb(action_prefix: str) -> InlineKeyboardMarkup:
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    
    # Оставляем только обычных участников (чистим от админов и организатора)
    pure_users = [u for u in users if u["username"] not in admin_usernames]

    keyboard = []
    for u in pure_users:
        btn_text = f"{u['full_name']} (@{u['username']})"
        cb_data = f"{action_prefix}_{u['username']}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
        
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ─── ДОБАВИТЬ УЧАСТНИКА ──────────────────────────────────────
@admin_router.callback_query(F.data == "add_user")
async def cb_add_user(cb: CallbackQuery, state: FSMContext):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("➕ Введите @username нового участника (без @):", reply_markup=back_button_kb())
    await state.set_state(AddUser.waiting_username)
    await cb.answer()

@admin_router.message(AddUser.waiting_username)
async def add_user_username(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    await state.update_data(username=uname)
    await msg.answer(f"Введите полное имя для @{uname}:", reply_markup=back_button_kb())
    await state.set_state(AddUser.waiting_fullname)

@admin_router.message(AddUser.waiting_fullname)
async def add_user_fullname(msg: Message, state: FSMContext):
    data = await state.get_data()
    uname = data["username"]
    full_name = msg.text.strip()
    ok = await add_user(uname, full_name)
    if ok:
        await msg.answer(f"✅ Участник @{uname} ({full_name}) добавлен!", reply_markup=back_button_kb())
    else:
        await msg.answer(f"⚠️ Участник @{uname} уже существует.", reply_markup=back_button_kb())
    await state.clear()

# ─── УДАЛИТЬ УЧАСТНИКА ───────────────────────────────────────
@admin_router.callback_query(F.data == "remove_user")
async def cb_remove_user(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("rm_user")
    await cb.message.edit_text("➖ <b>Выберите участника для удаления:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("rm_user_"))
async def process_remove_user(cb: CallbackQuery):
    uname = cb.data.replace("rm_user_", "")
    ok = await remove_user(uname)
    text = f"✅ Участник @{uname} деактивирован." if ok else f"❌ Участник @{uname} не найден."
    await cb.message.edit_text(text, reply_markup=back_button_kb())
    await cb.answer()

# ─── СНЯТЬ ЖЕТОН (ОТКАТ) ─────────────────────────────────────
@admin_router.callback_query(F.data == "revoke_medal")
async def cb_revoke_medal(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("rev_medal")
    await cb.message.edit_text("🗑 <b>Выберите участника для отмены последнего жетона:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("rev_medal_"))
async def process_revoke_medal(cb: CallbackQuery):
    uname = cb.data.replace("rev_medal_", "")
    ok = await cancel_last_medal(uname)
    text = f"✅ Последнее начисление для @{uname} успешно отменено." if ok else f"❌ У пользователя @{uname} нет жетонов для отмены."
    await cb.message.edit_text(text, reply_markup=back_button_kb())
    await cb.answer()

# ─── НАЧИСЛИТЬ ЖЕТОН ─────────────────────────────────────────
def medal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Контакт (1 балл)",  callback_data="medal_contact")],
        [InlineKeyboardButton(text="💛 Вклад (1 балл)",    callback_data="medal_vklad")],
        [InlineKeyboardButton(text="🔥 Прорыв (2 балла)",  callback_data="medal_proryv")],
        [InlineKeyboardButton(text="◀️ Назад",             callback_data="cancel_admin_action")],
    ])

def confirm_overlimit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начислить (превысить лимит)", callback_data="overlimit_yes")],
        [InlineKeyboardButton(text="❌ Отменить",                      callback_data="cancel_admin_action")],
    ])

@admin_router.callback_query(F.data == "give_medal")
async def cb_give_medal(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("give_medal")
    await cb.message.edit_text("🏅 <b>Выберите участника для начисления жетона:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("give_medal_"))
async def process_user_for_medal(cb: CallbackQuery, state: FSMContext):
    uname = cb.data.replace("give_medal_", "")
    user = await get_user(uname)
    if not user:
        await cb.answer("❌ Пользователь не найден", show_alert=True); return
        
    await state.update_data(target_username=uname, target_name=user["full_name"])
    await cb.message.edit_text(f"👤 Участник: <b>{user['full_name']}</b>\n\nВыберите тип жетона:", parse_mode="HTML", reply_markup=medal_kb())
    await state.set_state(GiveMedal.waiting_medal)
    await cb.answer()

@admin_router.callback_query(GiveMedal.waiting_medal, F.data.startswith("medal_"))
async def give_medal_type(cb: CallbackQuery, state: FSMContext):
    medal_type = cb.data.replace("medal_", "")
    await state.update_data(medal_type=medal_type)
    
    data = await state.get_data()
    uname = data["target_username"]
    pts = MEDAL_LIMITS[medal_type]["points_per"]
    limit = await check_weekly_limit(uname, medal_type, pts)

    if not limit["ok"]:
        await cb.message.edit_text(
            f"⚠️ <b>Превышение недельного лимита!</b>\n\n"
            f"Участник: @{uname}\n"
            f"Жетон: {MEDAL_NAMES[medal_type]}\n"
            f"Использовано: <b>{limit['used']}</b> из <b>{limit['max']}</b>\n\n"
            f"Продолжить или отменить?",
            parse_mode="HTML", reply_markup=confirm_overlimit_kb()
        )
        await state.set_state(GiveMedal.confirm_overlimit)
    else:
        await cb.message.edit_text(
            f"✏️ Напишите комментарий к жетону {MEDAL_NAMES[medal_type]}\n(или отправьте <i>-</i> чтобы пропустить):",
            parse_mode="HTML", reply_markup=back_button_kb()
        )
        await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.callback_query(GiveMedal.confirm_overlimit, F.data == "overlimit_yes")
async def overlimit_yes(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "✏️ Напишите комментарий к жетону (или отправьте - чтобы пропустить):",
        reply_markup=back_button_kb()
    )
    await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.message(GiveMedal.waiting_comment)
async def give_medal_comment(msg: Message, state: FSMContext):
    comment = msg.text.strip()
    if comment == "-": comment = ""
    
    data = await state.get_data()
    uname, name, medal_type = data["target_username"], data["target_name"], data["medal_type"]
    awarded_by = msg.from_user.username or "admin"

    result = await award_medal(uname, medal_type, comment, awarded_by)

    await msg.answer(
        f"✅ Жетон начислен!\n\n👤 {name} (@{uname})\n{MEDAL_NAMES[medal_type]} +{result['points']} балл(ов)\n{'💬 ' + comment if comment else ''}",
        parse_mode="HTML", reply_markup=back_button_kb()
    )

    user = await get_user(uname)
    if user and user.get("telegram_id"):
        try:
            cmt_text = f"\n💬 <i>{comment}</i>" if comment else ""
            await msg.bot.send_message(
                user["telegram_id"],
                f"🎉 <b>Вы получили жетон!</b>\n\n{MEDAL_NAMES[medal_type]} +{result['points']} балл(ов){cmt_text}\n\nот Метод Контакта",
                parse_mode="HTML"
            )
        except Exception: pass
    await state.clear()

# ─── КАРТОЧКИ УЧАСТНИКОВ ─────────────────────────────────────
@admin_router.callback_query(F.data == "list_users")
async def cb_list_users(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("show_card")
    await cb.message.edit_text("👥 <b>Выберите участника для просмотра карточки:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("show_card_"))
async def show_user_card(cb: CallbackQuery, bot: Bot):
    uname = cb.data.replace("show_card_", "")
    user = await get_user(uname)
    medals = await get_user_history(uname, 1000)
    
    # Группируем по месяцам для графики
    by_month = {}
    for m in medals: 
        m_month = m.get("month", m["awarded_at"][:7])
        by_month.setdefault(m_month, []).append(m)
        
    await cb.message.edit_text("⏳ Генерирую карточку участника...")
    image_bytes = await create_stat_image(bot, user, by_month, get_current_month())
    photo = BufferedInputFile(image_bytes.read(), filename="card.png")
    
    await cb.message.answer_photo(photo=photo, caption=f"👤 Карточка участника: {user['full_name']}", reply_markup=back_button_kb())
    await cb.message.delete()
    await cb.answer()

# ─── СТАТИСТИКА МЕСЯЦА (СВЕТЛАЯ ТЕМА) ────────────────────────
@admin_router.callback_query(F.data == "month_stats")
async def cb_month_stats(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    
    month = get_current_month()
    all_stats = await get_monthly_stats(month)
    
    # Чистим от админов
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    await cb.message.edit_text("⏳ Генерирую лидерборд...")
    image_bytes = await create_top_image(bot, stats, month)
    photo = BufferedInputFile(image_bytes.read(), filename="top.png")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать поздравление", callback_data="write_congrats")],
        [InlineKeyboardButton(text="🤖 Бот поздравит сам",       callback_data="bot_congrats")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="cancel_admin_action")]
    ])
    
    await cb.message.answer_photo(photo=photo, caption=f"📊 Итоги месяца — {month}", reply_markup=kb)
    await cb.message.delete()
    await cb.answer()

@admin_router.callback_query(F.data == "write_congrats")
async def cb_write_congrats(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✍️ Напишите текст поздравления:", reply_markup=back_button_kb())
    await state.set_state(CongratsWrite.waiting_text)
    await cb.answer()

@admin_router.message(CongratsWrite.waiting_text)
async def save_congrats_handler(msg: Message, state: FSMContext):
    await save_congrats(get_current_month(), msg.text.strip(), msg.from_user.username or "admin")
    await msg.answer("✅ Поздравление сохранено!", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "bot_congrats")
async def cb_bot_congrats(cb: CallbackQuery):
    await save_congrats(get_current_month(), "", "bot")
    await cb.message.edit_text(
        "✅ Понял! Бот сам составит поздравление и отправит 1-го числа.",
        reply_markup=back_button_kb()
    )
    await cb.answer()

# ─── EXCEL БЭКАП ─────────────────────────────────────────────
@admin_router.callback_query(F.data == "backup")
async def cb_backup(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("📤 Формирую Excel файл...")
    await send_backup(bot, cb.from_user.id)
    await cb.message.edit_text("✅ Бэкап успешно отправлен.", reply_markup=back_button_kb())
    await cb.answer()

@admin_router.message(Command("backup"))
async def cmd_backup(msg: Message, bot: Bot):
    uname = msg.from_user.username
    if not uname or not await is_admin(uname): return
    await msg.answer("📤 Формирую Excel файл...")
    await send_backup(bot, msg.from_user.id)

async def send_backup(bot: Bot, chat_id: int):
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    
    # Исключаем админов из бэкапа
    pure_users = [u for u in users if u["username"] not in admin_usernames]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Жетоны"
    ws.append(["Дата", "Месяц", "Участник", "Тип жетона", "Баллы", "Комментарий"])
    
    for u in pure_users:
        history = await get_user_history(u["username"], 500)
        for h in history:
            month_str = h.get("month", h["awarded_at"][:7])
            ws.append([
                h["awarded_at"][:10], month_str, u["full_name"],
                MEDAL_NAMES.get(h["medal_type"], h["medal_type"]),
                h["points"], h.get("comment", "")
            ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    
    dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    await bot.send_document(
        chat_id,
        BufferedInputFile(buf.read(), filename=f"Backup_Kontakt_{dt_str}.xlsx"),
        caption=f"📊 Полная выгрузка базы данных"
    )

# ─── УПРАВЛЕНИЕ АДМИНАМИ ─────────────────────────────────────
@admin_router.callback_query(F.data == "manage_admins")
async def cb_manage_admins(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    admins = await get_all_admins()
    text = "👑 <b>Администраторы</b>\n\n"
    for a in admins:
        role = "👑 Владелец" if a["is_owner"] else "🔧 Админ"
        text += f"{role}: @{a['username']} — {a['full_name']}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа",  callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Убрать админа",    callback_data="remove_admin")],
        [InlineKeyboardButton(text="◀️ Назад в меню",    callback_data="cancel_admin_action")]
    ])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "add_admin")
async def cb_add_admin(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    await cb.message.edit_text("Введите @username нового администратора (без @):", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_add)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_add)
async def do_add_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    ok = await add_admin(uname, msg.from_user.username)
    text = f"✅ @{uname} назначен администратором." if ok else f"⚠️ @{uname} уже администратор."
    await msg.answer(text, reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "remove_admin")
async def cb_remove_admin(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    await cb.message.edit_text("Введите @username администратора для снятия прав (без @):", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_remove)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_remove)
async def do_remove_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    await remove_admin(uname)
    await msg.answer(f"✅ Права администратора сняты с @{uname}.", reply_markup=back_button_kb())
    await state.clear()
