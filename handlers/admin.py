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

# Твой неизменный цифровой ID
DEVELOPER_ID = 2103579364

class AddUser(StatesGroup):
    waiting_username = State()
    waiting_fullname = State()

class GiveMedal(StatesGroup):
    waiting_selection = State() # Теперь тут выбираем количество
    waiting_comment   = State()
    confirm_overlimit = State()

class AdminMgmt(StatesGroup):
    waiting_add    = State()
    waiting_remove = State()
    waiting_owner  = State() 
    waiting_revoke_owner = State()

class CongratsWrite(StatesGroup):
    waiting_text = State()

# ─── Вспомогательные функции ──────────────────────────────────
def back_button_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="cancel_admin_action")]
    ])

async def check_admin_cb(cb: CallbackQuery) -> bool:
    if cb.from_user.id == DEVELOPER_ID: return True
    uname = cb.from_user.username
    if not uname or not await is_admin(uname):
        await cb.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return False
    return True

async def check_owner_cb(cb: CallbackQuery) -> bool:
    if cb.from_user.id == DEVELOPER_ID: return True
    uname = cb.from_user.username
    if not uname or not await is_owner(uname):
        await cb.answer("⛔ Только Супер-админ может это сделать.", show_alert=True)
        return False
    return True

async def check_creator_cb(cb: CallbackQuery) -> bool:
    if cb.from_user.id != DEVELOPER_ID:
        await cb.answer("⛔ Только Разработчик системы может управлять правами владельцев.", show_alert=True)
        return False
    return True

# ─── ГЛАВНОЕ МЕНЮ ─────────────────────────────────────────────
def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Начислить жетоны",  callback_data="give_medal")],
        [InlineKeyboardButton(text="🗑 Снять жетон",      callback_data="revoke_medal")],
        [InlineKeyboardButton(text="👥 Карточки участников", callback_data="list_users")],
        [InlineKeyboardButton(text="➕ Добавить участника", callback_data="add_user")],
        [InlineKeyboardButton(text="➖ Удалить участника",  callback_data="remove_user")],
        [InlineKeyboardButton(text="📊 Итоги месяца",     callback_data="month_stats")],
        [InlineKeyboardButton(text="📤 Excel Бэкап",      callback_data="backup")],
        [InlineKeyboardButton(text="👑 Управление админами", callback_data="manage_admins")],
    ])

@admin_router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    await state.clear()
    uname = msg.from_user.username
    if msg.from_user.id != DEVELOPER_ID and (not uname or not await is_admin(uname)):
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

async def users_list_kb(action_prefix: str) -> InlineKeyboardMarkup:
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    pure_users = [u for u in users if u["username"] not in admin_usernames]
    keyboard = []
    for u in pure_users:
        keyboard.append([InlineKeyboardButton(text=f"{u['full_name']} (@{u['username']})", callback_data=f"{action_prefix}_{u['username']}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ─── НОВАЯ ЛОГИКА: МУЛЬТИ-НАЧИСЛЕНИЕ ──────────────────────────

def multi_medal_kb(counts: dict) -> InlineKeyboardMarkup:
    """Генерирует меню выбора количества жетонов."""
    c_contact = counts.get("contact", 0)
    c_vklad   = counts.get("vklad", 0)
    c_proryv  = counts.get("proryv", 0)
    total = c_contact + c_vklad + c_proryv

    kb = [
        [InlineKeyboardButton(text=f"⭐ Контакт: {c_contact}", callback_data="add_item_contact")],
        [InlineKeyboardButton(text=f"💛 Вклад: {c_vklad}",   callback_data="add_item_vklad")],
        [InlineKeyboardButton(text=f"🔥 Прорыв: {c_proryv}",  callback_data="add_item_proryv")],
        [InlineKeyboardButton(text="🧹 Очистить", callback_data="clear_items")]
    ]
    if total > 0:
        kb.append([InlineKeyboardButton(text=f"✅ Подтвердить ({total} шт.)", callback_data="confirm_items")])
    
    kb.append([InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_admin_action")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@admin_router.callback_query(F.data == "give_medal")
async def cb_give_medal(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("multi_give")
    await cb.message.edit_text("🏅 <b>Выберите участника для начисления:</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data.startswith("multi_give_"))
async def process_user_multi(cb: CallbackQuery, state: FSMContext):
    uname = cb.data.replace("multi_give_", "")
    user = await get_user(uname)
    if not user:
        await cb.answer("❌ Участник не найден", show_alert=True); return
    
    # Инициализируем пустую корзину
    counts = {"contact": 0, "vklad": 0, "proryv": 0}
    await state.update_data(target_username=uname, target_name=user["full_name"], counts=counts)
    
    await cb.message.edit_text(
        f"👤 Участник: <b>{user['full_name']}</b>\n\nНажимайте на кнопки, чтобы добавить жетоны:",
        parse_mode="HTML", reply_markup=multi_medal_kb(counts)
    )
    await state.set_state(GiveMedal.waiting_selection)
    await cb.answer()

@admin_router.callback_query(GiveMedal.waiting_selection, F.data.startswith("add_item_"))
async def add_item_to_cart(cb: CallbackQuery, state: FSMContext):
    medal_type = cb.data.replace("add_item_", "")
    data = await state.get_data()
    counts = data["counts"]
    
    # Увеличиваем счетчик в корзине
    counts[medal_type] += 1
    await state.update_data(counts=counts)
    
    # Обновляем клавиатуру
    await cb.message.edit_reply_markup(reply_markup=multi_medal_kb(counts))
    await cb.answer(f"+1 {MEDAL_NAMES[medal_type]}")

@admin_router.callback_query(GiveMedal.waiting_selection, F.data == "clear_items")
async def clear_cart(cb: CallbackQuery, state: FSMContext):
    counts = {"contact": 0, "vklad": 0, "proryv": 0}
    await state.update_data(counts=counts)
    await cb.message.edit_reply_markup(reply_markup=multi_medal_kb(counts))
    await cb.answer("Корзина очищена")

@admin_router.callback_query(GiveMedal.waiting_selection, F.data == "confirm_items")
async def confirm_cart(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    counts = data["counts"]
    uname = data["target_username"]
    
    # Проверка лимитов для всего пакета сразу
    overlimit_list = []
    for m_type, count in counts.items():
        if count > 0:
            pts = MEDAL_LIMITS[m_type]["points_per"] * count
            limit = await check_weekly_limit(uname, m_type, pts)
            if not limit["ok"]:
                overlimit_list.append(f"{MEDAL_NAMES[m_type]} (набрано {count} шт.)")

    if overlimit_list:
        text = "⚠️ <b>Превышение недельного лимита!</b>\n\n" + "\n".join(overlimit_list)
        text += "\n\nВсё равно начислить?"
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=confirm_overlimit_kb())
        await state.set_state(GiveMedal.confirm_overlimit)
    else:
        await cb.message.edit_text(
            "✏️ Напишите общий комментарий для всех жетонов\n(или отправьте <i>-</i> чтобы пропустить):",
            parse_mode="HTML", reply_markup=back_button_kb()
        )
        await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.callback_query(GiveMedal.confirm_overlimit, F.data == "overlimit_yes")
async def overlimit_yes_multi(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✏️ Напишите комментарий (или отправьте - чтобы пропустить):", reply_markup=back_button_kb())
    await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.message(GiveMedal.waiting_comment)
async def process_multi_award(msg: Message, state: FSMContext):
    comment = msg.text.strip()
    if comment == "-": comment = ""
    
    data = await state.get_data()
    uname, name, counts = data["target_username"], data["target_name"], data["counts"]
    awarded_by = msg.from_user.username or "admin"
    
    # Начисляем все жетоны из корзины
    summary = []
    for m_type, count in counts.items():
        for _ in range(count):
            await award_medal(uname, m_type, comment, awarded_by)
        if count > 0:
            summary.append(f"{MEDAL_NAMES[m_type]}: {count} шт.")

    text = f"✅ <b>Успешно начислено для {name}:</b>\n\n" + "\n".join(summary)
    if comment: text += f"\n\n💬 {comment}"
    
    await msg.answer(text, parse_mode="HTML", reply_markup=back_button_kb())
    
    # Уведомление участнику (одним сообщением)
    user = await get_user(uname)
    if user and user.get("telegram_id"):
        try:
            notif = f"🎉 <b>Вы получили жетоны!</b>\n\n" + "\n".join(summary)
            if comment: notif += f"\n\n💬 <i>{comment}</i>"
            await msg.bot.send_message(user["telegram_id"], notif, parse_mode="HTML")
        except: pass
        
    await state.clear()

# ─── ОСТАЛЬНЫЕ ФУНКЦИИ (БЕЗ ИЗМЕНЕНИЙ В ЛОГИКЕ) ───────────────

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
    uname, full_name = data["username"], msg.text.strip()
    ok = await add_user(uname, full_name)
    text = f"✅ Участник @{uname} ({full_name}) добавлен!" if ok else f"⚠️ Участник @{uname} уже активен."
    await msg.answer(text, reply_markup=back_button_kb())
    await state.clear()

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
    text = f"✅ Участник @{uname} деактивирован." if ok else "❌ Ошибка"
    await cb.message.edit_text(text, reply_markup=back_button_kb())
    await cb.answer()

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
    text = f"✅ Последнее начисление для @{uname} отменено." if ok else "❌ Нет жетонов"
    await cb.message.edit_text(text, reply_markup=back_button_kb())
    await cb.answer()

@admin_router.callback_query(F.data == "list_users")
async def cb_list_users(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = await users_list_kb("show_card")
    await cb.message.edit_text("👥 <b>Карточки участников:</b>", parse_mode="HTML", reply_markup=kb)
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
    
    await cb.message.delete()
    wait = await cb.message.answer("⏳ Генерирую карточку...")
    image_bytes = await create_stat_image(bot, user, by_month, get_current_month())
    await wait.delete()
    await cb.message.answer_photo(photo=BufferedInputFile(image_bytes.read(), filename="card.png"), caption=f"👤 {user['full_name']}", reply_markup=back_button_kb())

@admin_router.callback_query(F.data == "month_stats")
async def cb_month_stats(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    month = get_current_month()
    all_stats = await get_monthly_stats(month)
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    await cb.message.delete()
    wait = await cb.message.answer("⏳ Генерирую лидерборд...")
    image_bytes = await create_top_image(bot, stats, month)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Поздравление", callback_data="write_congrats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")]
    ])
    await wait.delete()
    await cb.message.answer_photo(photo=BufferedInputFile(image_bytes.read(), filename="top.png"), caption=f"📊 Итоги — {month}", reply_markup=kb)

@admin_router.callback_query(F.data == "backup")
async def cb_backup(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("📤 Формирую Excel...")
    await send_backup(bot, cb.from_user.id)
    await cb.message.answer("✅ Бэкап отправлен.", reply_markup=back_button_kb())

async def send_backup(bot: Bot, chat_id: int):
    month = get_current_month()
    all_stats = await get_monthly_stats(month)
    users = await get_all_users()
    admins = await get_all_admins()
    admin_usernames = [a["username"] for a in admins]
    pure_users = [u for u in users if u["username"] not in admin_usernames]
    pure_stats = [s for s in all_stats if s.get("username") not in admin_usernames]

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Статистика"
    ws1.append(["Место", "Username", "Имя", "Контакт", "Вклад", "Прорыв", "Итого"])
    for i, s in enumerate(pure_stats, 1):
        ws1.append([i, s["username"], s["full_name"], s["contact_count"], s["vklad_count"], s["proryv_count"], s["total_points"]])

    ws2 = wb.create_sheet("История")
    ws2.append(["Дата", "Username", "Имя", "Жетон", "Баллы", "Комментарий", "Админ"])
    for u in pure_users:
        history = await get_user_history(u["username"], 500)
        for h in history:
            ws2.append([str(h["awarded_at"])[:10], h["username"], u["full_name"], MEDAL_NAMES.get(h["medal_type"]), h["points"], h.get("comment"), h.get("awarded_by")])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    await bot.send_document(chat_id, BufferedInputFile(buf.read(), filename=f"Backup_{month}.xlsx"))

@admin_router.callback_query(F.data == "manage_admins")
async def cb_manage_admins(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    admins = await get_all_admins()
    text = "👑 <b>Команда управления</b>\n\n"
    for a in admins:
        role = "👨‍💻 Разработчик" if a.get("telegram_id") == DEVELOPER_ID or a['username'].lower() == "studio_slim_line" else ("⭐ Супер-админ" if a["is_owner"] else "🔧 Админ")
        text += f"{role}: @{a['username']} — {a['full_name']}\n"

    kb = [[InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_admin")], [InlineKeyboardButton(text="➖ Убрать админа", callback_data="remove_admin")]]
    if cb.from_user.id == DEVELOPER_ID:
        kb.append([InlineKeyboardButton(text="👑 Сделать Супер-админом", callback_data="make_owner")])
        kb.append([InlineKeyboardButton(text="⬇️ Снять Супер-админа", callback_data="revoke_owner")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(F.data == "add_admin")
async def cb_add_admin(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    await cb.message.edit_text("Введите @username нового админа (без @):", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_add)

@admin_router.message(AdminMgmt.waiting_add)
async def do_add_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    ok = await add_admin(uname, msg.from_user.username)
    await msg.answer(f"✅ @{uname} назначен админом." if ok else "⚠️ Уже админ", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "remove_admin")
async def cb_remove_admin(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    await cb.message.edit_text("Введите @username для снятия ВСЕХ прав:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_remove)

@admin_router.message(AdminMgmt.waiting_remove)
async def do_remove_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    if uname.lower() == "studio_slim_line":
        await msg.answer("⛔ Нельзя удалить Разработчика!"); await state.clear(); return
    await remove_admin(uname)
    await msg.answer(f"✅ Права сняты с @{uname}.", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "make_owner")
async def cb_make_owner(cb: CallbackQuery, state: FSMContext):
    if not await check_creator_cb(cb): return
    await cb.message.edit_text("Введите @username для прав Супер-админа:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_owner)

@admin_router.message(AdminMgmt.waiting_owner)
async def do_make_owner(msg: Message, state: FSMContext):
    if msg.from_user.id != DEVELOPER_ID: return
    uname = msg.text.strip().lstrip("@")
    ok = await make_owner(uname)
    await msg.answer(f"✅ @{uname} теперь Супер-админ!" if ok else "❌ Ошибка", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "revoke_owner")
async def cb_revoke_owner(cb: CallbackQuery, state: FSMContext):
    if not await check_creator_cb(cb): return
    await cb.message.edit_text("Введите @username для снятия прав Супер-админа:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_revoke_owner)

@admin_router.message(AdminMgmt.waiting_revoke_owner)
async def do_revoke_owner(msg: Message, state: FSMContext):
    if msg.from_user.id != DEVELOPER_ID: return
    uname = msg.text.strip().lstrip("@")
    if uname.lower() == "studio_slim_line":
        await msg.answer("⛔ Нельзя!"); await state.clear(); return
    ok = await revoke_owner(uname)
    await msg.answer(f"✅ Статус Супер-админа снят с @{uname}." if ok else "❌ Ошибка", reply_markup=back_button_kb())
    await state.clear()
