from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import openpyxl, io

from image_generator import create_top_image, create_stat_image
from database import (
    get_user, get_all_users, add_user, remove_user,
    award_medal, cancel_last_medal, check_weekly_limit,
    get_monthly_stats, get_user_history, get_current_month,
    add_admin, remove_admin, make_owner, revoke_owner, get_all_admins, is_admin, is_owner,
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
    waiting_owner  = State() 
    waiting_revoke_owner = State()

class CongratsWrite(StatesGroup):
    waiting_text = State()

# ─── Вспомогательные функции и проверки ──────────────────────
def back_button_kb() -> InlineKeyboardMarkup:
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
        await cb.answer("⛔ Только Супер-админ может это сделать.", show_alert=True)
        return False
    return True

# НОВАЯ ПРОВЕРКА ТОЛЬКО ДЛЯ ТЕБЯ (СОЗДАТЕЛЯ)
async def check_creator_cb(cb: CallbackQuery) -> bool:
    uname = cb.from_user.username
    if not uname or uname.lower() != "studio_slim_line":
        await cb.answer("⛔ Только Создатель сообщества может назначать Супер-админов.", show_alert=True)
        return False
    return True

# ─── ГЛАВНОЕ МЕНЮ И УМНАЯ ОТМЕНА ─────────────────────────────
def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Начислить жетон",  callback_data="give_medal")],
        [InlineKeyboardButton(text="🗑 Снять жетон",      callback_data="revoke_medal")],
        [InlineKeyboardButton(text="👥 Карточки участников", callback_data="list_users")],
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
    if cb.message.content_type == 'photo':
        await cb.message.delete()
        await cb.message.answer("👑 <b>Панель управления Метод Контакта</b>", parse_mode="HTML", reply_markup=admin_menu_kb())
    else:
        await cb.message.edit_text("👑 <b>Панель управления Метод Контакта</b>", parse_mode="HTML", reply_markup=admin_menu_kb())
    await cb.answer()

# ─── ГЕНЕРАТОР СПИСКА УЧАСТНИКОВ (ФИЛЬТРАЦИЯ АДМИНОВ) ────────
async def users_list_kb(action_prefix: str) -> InlineKeyboardMarkup:
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
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
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("➕ Введите @username нового участника (без @):", reply_markup=back_button_kb())
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
        await msg.answer(f"✅ Участник @{uname} ({full_name}) добавлен/восстановлен!", reply_markup=back_button_kb())
    else:
        await msg.answer(f"⚠️ Участник @{uname} уже существует и активен.", reply_markup=back_button_kb())
    await state.clear()

# ─── УДАЛИТЬ УЧАСТНИКА ───────────────────────────────────────
@admin_router.callback_query(F.data == "remove_user")
async def cb_remove_user(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("rm_user")
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("➖ <b>Выберите участника для удаления:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("rm_user_"))
async def process_remove_user(cb: CallbackQuery):
    uname = cb.data.replace("rm_user_", "")
    ok = await remove_user(uname)
    text = f"✅ Участник @{uname} деактивирован." if ok else f"❌ Участник @{uname} не найден."
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(text, reply_markup=back_button_kb())
    await cb.answer()

# ─── СНЯТЬ ЖЕТОН (ОТКАТ) ─────────────────────────────────────
@admin_router.callback_query(F.data == "revoke_medal")
async def cb_revoke_medal(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("rev_medal")
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("🗑 <b>Выберите участника для отмены последнего жетона:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("rev_medal_"))
async def process_revoke_medal(cb: CallbackQuery):
    uname = cb.data.replace("rev_medal_", "")
    ok = await cancel_last_medal(uname)
    text = f"✅ Последнее начисление для @{uname} успешно отменено." if ok else f"❌ У пользователя @{uname} нет жетонов для отмены."
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(text, reply_markup=back_button_kb())
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
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("🏅 <b>Выберите участника для начисления жетона:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("give_medal_"))
async def process_user_for_medal(cb: CallbackQuery, state: FSMContext):
    uname = cb.data.replace("give_medal_", "")
    user = await get_user(uname)
    if not user:
        await cb.answer("❌ Пользователь не найден", show_alert=True); return
        
    await state.update_data(target_username=uname, target_name=user["full_name"])
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(f"👤 Участник: <b>{user['full_name']}</b>\n\nВыберите тип жетона:", parse_mode="HTML", reply_markup=medal_kb())
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

    try: await cb.message.delete()
    except: pass

    if not limit["ok"]:
        await cb.message.answer(
            f"⚠️ <b>Превышение недельного лимита!</b>\n\n"
            f"Участник: @{uname}\n"
            f"Жетон: {MEDAL_NAMES[medal_type]}\n"
            f"Использовано: <b>{limit['used']}</b> из <b>{limit['max']}</b>\n\n"
            f"Продолжить или отменить?",
            parse_mode="HTML", reply_markup=confirm_overlimit_kb()
        )
        await state.set_state(GiveMedal.confirm_overlimit)
    else:
        await cb.message.answer(
            f"✏️ Напишите комментарий к жетону {MEDAL_NAMES[medal_type]}\n(или отправьте <i>-</i> чтобы пропустить):",
            parse_mode="HTML", reply_markup=back_button_kb()
        )
        await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.callback_query(GiveMedal.confirm_overlimit, F.data == "overlimit_yes")
async def overlimit_yes(cb: CallbackQuery, state: FSMContext):
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(
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
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("👥 <b>Выберите участника для просмотра карточки:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("show_card_"))
async def show_user_card(cb: CallbackQuery, bot: Bot):
    uname = cb.data.replace("show_card_", "")
    user = await get_user(uname)
    medals = await get_user_history(uname, 1000)
    
    by_month = {}
    for m in medals: 
        m_month = m.get("month", str(m["awarded_at"])[:7])
        by_month.setdefault(m_month, []).append(m)
        
    try: await cb.message.delete()
    except: pass
    
    wait_msg = await cb.message.answer("⏳ Генерирую карточку участника...")
    image_bytes = await create_stat_image(bot, user, by_month, get_current_month())
    photo = BufferedInputFile(image_bytes.read(), filename="card.png")
    
    await wait_msg.delete()
    await cb.message.answer_photo(photo=photo, caption=f"👤 Карточка участника: {user['full_name']}", reply_markup=back_button_kb())
    await cb.answer()

# ─── СТАТИСТИКА МЕСЯЦА (СВЕТЛАЯ ТЕМА) ────────────────────────
@admin_router.callback_query(F.data == "month_stats")
async def cb_month_stats(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    
    month = get_current_month()
    all_stats = await get_monthly_stats(month)
    
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    try: await cb.message.delete()
    except: pass
    
    wait_msg = await cb.message.answer("⏳ Генерирую лидерборд...")
    image_bytes = await create_top_image(bot, stats, month)
    photo = BufferedInputFile(image_bytes.read(), filename="top.png")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать поздравление", callback_data="write_congrats")],
        [InlineKeyboardButton(text="🤖 Бот поздравит сам",       callback_data="bot_congrats")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="cancel_admin_action")]
    ])
    
    await wait_msg.delete()
    await cb.message.answer_photo(photo=photo, caption=f"📊 Итоги месяца — {month}", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "write_congrats")
async def cb_write_congrats(cb: CallbackQuery, state: FSMContext):
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("✍️ Напишите текст поздравления:", reply_markup=back_button_kb())
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
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("✅ Понял! Бот сам составит поздравление и отправит 1-го числа.", reply_markup=back_button_kb())
    await cb.answer()

# ─── EXCEL БЭКАП ─────────────────────────────────────────────
@admin_router.callback_query(F.data == "backup")
async def cb_backup(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    try: await cb.message.delete()
    except: pass
    
    msg = await cb.message.answer("📤 Формирую Excel файл...")
    try:
        await send_backup(bot, cb.from_user.id)
        await msg.delete()
        await cb.message.answer("✅ Excel файл успешно отправлен.", reply_markup=back_button_kb())
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка генерации: {e}", reply_markup=back_button_kb())
    await cb.answer()

@admin_router.message(Command("backup"))
async def cmd_backup(msg: Message, bot: Bot):
    uname = msg.from_user.username
    if not uname or not await is_admin(uname): return
    await msg.answer("📤 Формирую Excel файл...")
    await send_backup(bot, msg.from_user.id)

async def send_backup(bot: Bot, chat_id: int):
    month = get_current_month()
    all_stats = await get_monthly_stats(month)
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    
    # Фильтруем админов
    pure_users = [u for u in users if u["username"] not in admin_usernames]
    pure_stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    wb = openpyxl.Workbook()

    # Лист 1: Статистика месяца
    ws1 = wb.active
    ws1.title = f"Статистика {month}"
    ws1.append(["Место", "Username", "Имя", "Контакт", "Вклад", "Прорыв", "Итого баллов"])
    for i, s in enumerate(pure_stats, 1):
        ws1.append([i, s["username"], s["full_name"],
                    s["contact_count"], s["vklad_count"], s["proryv_count"], s["total_points"]])

    # Лист 2: Полная история
    ws2 = wb.create_sheet("История начислений")
    ws2.append(["Дата", "Username", "Имя", "Жетон", "Баллы", "Комментарий", "Начислил"])
    for u in pure_users:
        history = await get_user_history(u["username"], 500)
        for h in history:
            raw_date = h["awarded_at"]
            if isinstance(raw_date, datetime):
                date_str = raw_date.strftime("%Y-%m-%d")
            else:
                date_str = str(raw_date)[:10]

            ws2.append([
                date_str, h["username"], u["full_name"],
                MEDAL_NAMES.get(h["medal_type"], h["medal_type"]),
                h["points"], h.get("comment", ""), h.get("awarded_by", "")
            ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    
    dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    from aiogram.types import BufferedInputFile
    await bot.send_document(
        chat_id,
        BufferedInputFile(buf.read(), filename=f"Backup_Kontakt_{dt_str}.xlsx"),
        caption=f"📊 Полная выгрузка базы данных"
    )

# ─── УПРАВЛЕНИЕ АДМИНАМИ (ИНТЕЛЛЕКТУАЛЬНОЕ МЕНЮ) ──────────────
@admin_router.callback_query(F.data == "manage_admins")
async def cb_manage_admins(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    admins = await get_all_admins()
    
    text = "👑 <b>Команда управления</b>\n\n"
    for a in admins:
        # Красиво подписываем роли
        if a['username'].lower() == "studio_slim_line":
            role = "👑 Создатель"
        elif a["is_owner"]:
            role = "⭐ Супер-админ"
        else:
            role = "🔧 Админ"
        text += f"{role}: @{a['username']} — {a['full_name']}\n"

    # Базовые кнопки для Супер-админов
    kb_buttons = [
        [InlineKeyboardButton(text="➕ Добавить админа",  callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Убрать админа",    callback_data="remove_admin")],
    ]
    
    # ДОПОЛНИТЕЛЬНЫЕ КНОПКИ ТОЛЬКО ДЛЯ ТЕБЯ (СОЗДАТЕЛЯ)
    current_uname = cb.from_user.username
    if current_uname and current_uname.lower() == "studio_slim_line":
        kb_buttons.append([InlineKeyboardButton(text="👑 Сделать Супер-админом", callback_data="make_owner")])
        kb_buttons.append([InlineKeyboardButton(text="⬇️ Снять Супер-админа",   callback_data="revoke_owner")])

    kb_buttons.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="cancel_admin_action")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    try: await cb.message.delete()
    except: pass
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "add_admin")
async def cb_add_admin(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("Введите @username нового администратора (без @):", reply_markup=back_button_kb())
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
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("Введите @username администратора для снятия ВСЕХ прав (без @):", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_remove)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_remove)
async def do_remove_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    if uname.lower() == "studio_slim_line":
        await msg.answer("⛔ Нельзя удалить главного создателя системы!", reply_markup=back_button_kb())
        await state.clear()
        return

    await remove_admin(uname)
    await msg.answer(f"✅ Права администратора полностью сняты с @{uname}.", reply_markup=back_button_kb())
    await state.clear()

# ─── ФУНКЦИИ ТОЛЬКО ДЛЯ СОЗДАТЕЛЯ ────────────────────────────

@admin_router.callback_query(F.data == "make_owner")
async def cb_make_owner(cb: CallbackQuery, state: FSMContext):
    if not await check_creator_cb(cb): return
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("Введите @username участника или админа, чтобы дать ему права Супер-админа (без @):", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_owner)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_owner)
async def do_make_owner(msg: Message, state: FSMContext):
    if msg.from_user.username.lower() != "studio_slim_line": return
    
    uname = msg.text.strip().lstrip("@")
    ok = await make_owner(uname)
    if ok:
        await msg.answer(f"✅ @{uname} теперь Супер-админ!", reply_markup=back_button_kb())
    else:
        await msg.answer(f"❌ Не удалось найти @{uname} или он деактивирован.", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "revoke_owner")
async def cb_revoke_owner(cb: CallbackQuery, state: FSMContext):
    if not await check_creator_cb(cb): return
    try: await cb.message.delete()
    except: pass
    await cb.message.answer("Введите @username для снятия прав Супер-админа (он останется обычным админом):", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_revoke_owner)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_revoke_owner)
async def do_revoke_owner(msg: Message, state: FSMContext):
    if msg.from_user.username.lower() != "studio_slim_line": return

    uname = msg.text.strip().lstrip("@")
    if uname.lower() == "studio_slim_line":
        await msg.answer("⛔ Нельзя снять права с самого себя!", reply_markup=back_button_kb())
        await state.clear()
        return

    ok = await revoke_owner(uname)
    if ok:
        await msg.answer(f"✅ У @{uname} забрали статус Супер-админа (он стал обычным админом).", reply_markup=back_button_kb())
    else:
        await msg.answer(f"❌ Не удалось изменить права @{uname}.", reply_markup=back_button_kb())
    await state.clear()
