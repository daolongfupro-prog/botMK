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
    get_monthly_stats, get_active_stats, get_user_history, get_current_month,
    add_admin, remove_admin, make_owner, revoke_owner, get_all_admins, is_admin, is_owner,
    save_congrats, close_current_month, undo_last_closure, 
    get_last_closure_info, get_closure_breakdown,
    MEDAL_NAMES, MEDAL_LIMITS
)

admin_router = Router()

# Твой неизменный цифровой ID
DEVELOPER_ID = 2103579364

# ─── СОСТОЯНИЯ (FSM) ──────────────────────────────────────────
class AddUser(StatesGroup):
    waiting_username = State()
    waiting_fullname = State()

class GiveMedal(StatesGroup):
    waiting_selection = State() 
    waiting_comment   = State()
    confirm_overlimit = State()

class AdminMgmt(StatesGroup):
    waiting_add    = State()
    waiting_remove = State()
    waiting_owner  = State() 
    waiting_revoke_owner = State()

class CongratsWrite(StatesGroup):
    waiting_text = State()

# ─── ВСПОМОГАТЕЛЬНЫЕ КЛАВИАТУРЫ ──────────────────────────────
def back_button_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="cancel_admin_action")]
    ])

def skip_comment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Без комментария", callback_data="skip_comment")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_admin_action")]
    ])

# ─── ПРОВЕРКИ ПРАВ ───────────────────────────────────────────
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
        await cb.answer("⛔ Только Разработчик может управлять Супер-админами.", show_alert=True)
        return False
    return True

# ─── ГЛАВНОЕ МЕНЮ АДМИНКИ ─────────────────────────────────────
def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Начислить жетоны",  callback_data="give_medal")],
        [InlineKeyboardButton(text="🗑 Снять жетон",      callback_data="revoke_medal")],
        [InlineKeyboardButton(text="👥 Карточки участников", callback_data="list_users")],
        [InlineKeyboardButton(text="➕ Добавить участника", callback_data="add_user")],
        [InlineKeyboardButton(text="➖ Удалить участника",  callback_data="remove_user")],
        [InlineKeyboardButton(text="📊 Итоги текущего периода", callback_data="month_stats")],
        [
            InlineKeyboardButton(text="🏁 Завершить период", callback_data="conf_close_m"),
            InlineKeyboardButton(text="↩️ Откат закрытия", callback_data="conf_undo_m")
        ],
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
        btn_text = f"{u['full_name']} (@{u['username']})"
        cb_data = f"{action_prefix}_{u['username']}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
        
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ─── ЛОГИКА НАЧИСЛЕНИЯ (КОРЗИНА) ─────────────────────────────
def multi_medal_kb(counts: dict) -> InlineKeyboardMarkup:
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
    
    counts = {"contact": 0, "vklad": 0, "proryv": 0}
    await state.update_data(target_username=uname, target_name=user["full_name"], counts=counts)
    await cb.message.edit_text(
        f"👤 Участник: <b>{user['full_name']}</b>\n\nВыберите жетоны для начисления:",
        parse_mode="HTML", reply_markup=multi_medal_kb(counts)
    )
    await cb.answer()

@admin_router.callback_query(F.data.startswith("add_item_"))
async def add_item_to_cart(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    counts = dict(data.get("counts", {"contact": 0, "vklad": 0, "proryv": 0}))
    medal_type = cb.data.replace("add_item_", "")
    counts[medal_type] = counts.get(medal_type, 0) + 1
    await state.update_data(counts=counts)
    try:
        await cb.message.edit_reply_markup(reply_markup=multi_medal_kb(counts))
    except: pass
    await cb.answer(f"+1 {MEDAL_NAMES.get(medal_type, '')}")

@admin_router.callback_query(F.data == "clear_items")
async def clear_cart(cb: CallbackQuery, state: FSMContext):
    counts = {"contact": 0, "vklad": 0, "proryv": 0}
    await state.update_data(counts=counts)
    try:
        await cb.message.edit_reply_markup(reply_markup=multi_medal_kb(counts))
    except: pass
    await cb.answer("🧹 Очищено")

@admin_router.callback_query(F.data == "confirm_items")
async def confirm_cart(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    counts, uname = data.get("counts", {}), data.get("target_username")
    overlimit_list = []
    for m_type, count in counts.items():
        if count > 0:
            pts = MEDAL_LIMITS[m_type]["points_per"] * count
            limit = await check_weekly_limit(uname, m_type, pts)
            if not limit["ok"]:
                overlimit_list.append(f"{MEDAL_NAMES[m_type]} (всего будет {limit['used'] + pts} из {limit['max']})")

    if overlimit_list:
        text = "⚠️ <b>Превышение лимита!</b>\n\n" + "\n".join(overlimit_list) + "\n\nВсё равно начислить?"
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=confirm_overlimit_kb())
        await state.set_state(GiveMedal.confirm_overlimit)
    else:
        await cb.message.edit_text("✏️ Напишите комментарий или нажмите кнопку:", reply_markup=skip_comment_kb())
        await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

def confirm_overlimit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, начислить", callback_data="overlimit_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin_action")],
    ])

@admin_router.callback_query(GiveMedal.confirm_overlimit, F.data == "overlimit_yes")
async def overlimit_yes_multi(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✏️ Напишите комментарий или нажмите кнопку:", reply_markup=skip_comment_kb())
    await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

async def execute_award_logic(message_obj: Message, state: FSMContext, awarded_by: str, comment: str):
    data = await state.get_data()
    uname, name, counts = data.get("target_username"), data.get("target_name"), data.get("counts", {})
    summary = []
    for m_type, count in counts.items():
        for _ in range(count):
            await award_medal(uname, m_type, comment, awarded_by)
        if count > 0: summary.append(f"{MEDAL_NAMES[m_type]}: {count} шт.")

    text = f"✅ <b>Успешно начислено {name}:</b>\n\n" + "\n".join(summary)
    if comment: text += f"\n\n💬 {comment}"
    await message_obj.answer(text, parse_mode="HTML", reply_markup=back_button_kb())
    
    user = await get_user(uname)
    if user and user.get("telegram_id"):
        try:
            notif = f"🎉 <b>Вам начислены жетоны!</b>\n\n" + "\n".join(summary)
            if comment: notif += f"\n\n💬 <i>{comment}</i>"
            await message_obj.bot.send_message(user["telegram_id"], notif, parse_mode="HTML")
        except: pass
    await state.clear()

@admin_router.callback_query(GiveMedal.waiting_comment, F.data == "skip_comment")
async def skip_comment_award(cb: CallbackQuery, state: FSMContext):
    await cb.message.delete()
    await execute_award_logic(cb.message, state, cb.from_user.username or "admin", "")
    await cb.answer()

@admin_router.message(GiveMedal.waiting_comment)
async def process_multi_award_with_comment(msg: Message, state: FSMContext):
    await execute_award_logic(msg, state, msg.from_user.username or "admin", msg.text.strip())

# ─── УПРАВЛЕНИЕ УЧАСТНИКАМИ ──────────────────────────────────
@admin_router.callback_query(F.data == "add_user")
async def cb_add_user(cb: CallbackQuery, state: FSMContext):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("➕ Введите @username (без @):", reply_markup=back_button_kb())
    await state.set_state(AddUser.waiting_username)
    await cb.answer()

@admin_router.message(AddUser.waiting_username)
async def add_user_username(msg: Message, state: FSMContext):
    await state.update_data(username=msg.text.strip().lstrip("@"))
    await msg.answer("Введите полное имя участника:", reply_markup=back_button_kb())
    await state.set_state(AddUser.waiting_fullname)

@admin_router.message(AddUser.waiting_fullname)
async def add_user_fullname(msg: Message, state: FSMContext):
    data = await state.get_data()
    ok = await add_user(data["username"], msg.text.strip())
    text = f"✅ Участник @{data['username']} добавлен!" if ok else "⚠️ Ошибка или уже есть."
    await msg.answer(text, reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "remove_user")
async def cb_remove_user(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("➖ <b>Выберите кого удалить:</b>", parse_mode="HTML", reply_markup=await users_list_kb("rm_user"))
    await cb.answer()

@admin_router.callback_query(F.data.startswith("rm_user_"))
async def process_remove_user(cb: CallbackQuery):
    uname = cb.data.replace("rm_user_", "")
    await remove_user(uname)
    await cb.message.edit_text(f"✅ @{uname} деактивирован.", reply_markup=back_button_kb())
    await cb.answer()

@admin_router.callback_query(F.data == "revoke_medal")
async def cb_revoke_medal(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("🗑 <b>У кого отменить последний жетон?</b>", parse_mode="HTML", reply_markup=await users_list_kb("rev_medal"))
    await cb.answer()

@admin_router.callback_query(F.data.startswith("rev_medal_"))
async def process_revoke_medal(cb: CallbackQuery):
    uname = cb.data.replace("rev_medal_", "")
    ok = await cancel_last_medal(uname)
    text = f"✅ Отменено для @{uname}." if ok else "❌ Нет активных жетонов."
    await cb.message.edit_text(text, reply_markup=back_button_kb())
    await cb.answer()

# ─── КАРТОЧКИ УЧАСТНИКОВ ─────────────────────────────────────
@admin_router.callback_query(F.data == "list_users")
async def cb_list_users(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    await cb.message.edit_text("👥 <b>Выберите участника:</b>", parse_mode="HTML", reply_markup=await users_list_kb("show_card"))
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
    
    await cb.answer("⏳ Генерирую карточку...")
    wait = await cb.message.answer("⏳ Формирую изображение...")
    image_bytes = await create_stat_image(bot, user, by_month, get_current_month())
    await wait.delete()
    await cb.message.delete()
    await cb.message.answer_photo(BufferedInputFile(image_bytes.read(), filename="card.png"), 
                                  caption=f"👤 Участник: {user['full_name']}", reply_markup=back_button_kb())

# ─── СТАТИСТИКА ПЕРИОДА ──────────────────────────────────────
@admin_router.callback_query(F.data == "month_stats")
async def cb_month_stats(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    stats = await get_active_stats()
    admins = [a["username"] for a in await get_all_admins()]
    filtered = [s for s in stats if s["username"] not in admins]
    
    if not filtered:
        await cb.message.edit_text("📈 В текущем периоде нет начислений.", reply_markup=back_button_kb())
        await cb.answer()
        return

    await cb.answer("⏳ Подготовка лидерборда...")
    wait = await cb.message.answer("⏳ Формирую лидерборд...")
    image_bytes = await create_top_image(bot, filtered, get_current_month())
    await wait.delete()
    await cb.message.delete()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Поздравление", callback_data="write_congrats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")]
    ])
    await cb.message.answer_photo(BufferedInputFile(image_bytes.read(), filename="top.png"), 
                                  caption="📊 Итоги активного периода", reply_markup=kb)

# ─── ЗАКРЫТИЕ И ОТКАТ ПЕРИОДА ────────────────────────────────
@admin_router.callback_query(F.data == "conf_close_m")
async def cb_conf_close_m(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    stats = await get_active_stats()
    count = sum(s['medal_count'] for s in stats)
    
    if count == 0:
        await cb.answer("⚠️ В текущем периоде еще нет жетонов для архивации.", show_alert=True)
        return

    text = (
        "⚠️ <b>ВНИМАНИЕ: ЗАВЕРШЕНИЕ ПЕРИОДА</b>\n\n"
        f"Сейчас накоплено жетонов: <b>{count}</b>.\n\n"
        "<b>Что произойдет после подтверждения:</b>\n"
        "1. Все текущие жетоны станут <b>неактивными</b> и уйдут в архив.\n"
        "2. Общий счет участников в лидерборде <b>обнулится</b>.\n"
        "3. Начнется отсчет нового периода.\n\n"
        "<b>Вы уверены, что хотите завершить этот период?</b>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, завершить период", callback_data="exec_close_m")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin_action")]
    ])
    
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "exec_close_m")
async def cb_exec_close_m(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    
    await cb.answer("⏳ Обработка архива...", show_alert=False)
    res = await close_current_month(cb.from_user.username or str(cb.from_user.id))
    
    text = (
        "🏁 <b>Период успешно завершен!</b>\n\n"
        f"Архивировано жетонов: <b>{res['count']}</b>.\n"
        "Все показатели сброшены. Можно начинать новый учет."
    )
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=back_button_kb())

@admin_router.callback_query(F.data == "conf_undo_m")
async def cb_conf_undo_m(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    
    info = await get_last_closure_info()
    if not info:
        await cb.answer("❌ Нет доступных закрытий для отката.", show_alert=True)
        return
    
    breakdown = await get_closure_breakdown(info['id'])
    
    current_activity = await get_active_stats()
    new_medals_count = sum(s['medal_count'] for s in current_activity)

    user_list = "\n".join([f"• {b['full_name']}: {b['medal_count']} шт." for b in breakdown[:10]])
    if len(breakdown) > 10:
        user_list += f"\n...и еще {len(breakdown)-10} участников"

    warning_text = ""
    if new_medals_count > 0:
        warning_text = (
            f"\n\n⚠️ <b>ВНИМАНИЕ:</b> В текущем периоде уже начислено <b>{new_medals_count}</b> новых жетонов. "
            "При откате они будут <b>БЕЗВОЗВРАТНО УДАЛЕНЫ</b>, так как система вернется к состоянию архива!"
        )

    text = (
        "🔄 <b>ОТКАТ ЗАКРЫТИЯ ПЕРИОДА</b>\n\n"
        f"Вы собираетесь отменить закрытие от: <code>{info['closed_at'].strftime('%d.%m %H:%M')}</code>\n\n"
        f"<b>Будет восстановлено из архива:</b>\n{user_list}"
        f"{warning_text}\n\n"
        "Восстановить данные и вернуться в прошлый период?"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Да, выполнить откат", callback_data="exec_undo_m")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin_action")]
    ])
    
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "exec_undo_m")
async def cb_exec_undo_m(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    
    await cb.answer("⏳ Восстановление данных...", show_alert=False)
    res = await undo_last_closure()
    
    if res["success"]:
        text = (
            "✅ <b>Откат успешно выполнен!</b>\n\n"
            f"Восстановлено из архива: <b>{res['count']}</b> жетонов.\n"
            "Текущий период снова активен."
        )
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=back_button_kb())
    else:
        await cb.message.edit_text("❌ <b>Ошибка отката.</b>\nВозможно, архив уже был изменен или пуст.", 
                                  parse_mode="HTML", reply_markup=back_button_kb())
    await cb.answer()

# ─── EXCEL БЭКАП ─────────────────────────────────────────────
async def send_backup(bot: Bot, chat_id: int):
    month = get_current_month()
    stats = await get_monthly_stats(month)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Statistics"
    ws.append(["Имя", "Username", "Контакт", "Вклад", "Прорыв", "Всего баллов"])
    for s in stats:
        ws.append([s['full_name'], s['username'], s['contact_count'], s['vklad_count'], s['proryv_count'], s['total_points']])
    
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    await bot.send_document(chat_id, BufferedInputFile(out.read(), filename=f"backup_{month}.xlsx"), caption=f"📊 Бэкап за {month}")

@admin_router.callback_query(F.data == "backup")
async def cb_backup(cb: CallbackQuery, bot: Bot):
    if not await check_admin_cb(cb): return
    await send_backup(bot, cb.from_user.id)
    await cb.answer("Файл отправлен в ЛС", show_alert=True)

# ─── ПОЗДРАВЛЕНИЯ ────────────────────────────────────────────
@admin_router.callback_query(F.data == "write_congrats")
async def cb_write_congrats(cb: CallbackQuery, state: FSMContext):
    if not await check_admin_cb(cb): return
    await cb.message.answer("✍️ Введите текст поздравления для канала:", reply_markup=back_button_kb())
    await state.set_state(CongratsWrite.waiting_text)
    await cb.answer()

@admin_router.message(CongratsWrite.waiting_text)
async def process_congrats_text(msg: Message, state: FSMContext):
    await save_congrats(get_current_month(), msg.text, msg.from_user.username or "Admin")
    await msg.answer("✅ Текст сохранен! Он будет отправлен при публикации итогов.", reply_markup=back_button_kb())
    await state.clear()

# ─── УПРАВЛЕНИЕ АДМИНАМИ ─────────────────────────────────────
@admin_router.callback_query(F.data == "manage_admins")
async def cb_manage_admins(cb: CallbackQuery):
    if not await check_admin_cb(cb): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Назначить админа", callback_data="adm_add")],
        [InlineKeyboardButton(text="➖ Разжаловать админа", callback_data="adm_rem")],
        [InlineKeyboardButton(text="👑 Назначить Супер-админа", callback_data="adm_make_owner")],
        [InlineKeyboardButton(text="🚫 Убрать Супер-админа", callback_data="adm_rev_owner")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="cancel_admin_action")]
    ])
    await cb.message.edit_text("👑 <b>Управление доступом</b>", parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "adm_add")
async def cb_adm_add(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    await cb.message.edit_text("Введите @username нового админа:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_add)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_add)
async def process_adm_add(msg: Message, state: FSMContext):
    ok = await add_admin(msg.text.strip().lstrip("@"), msg.from_user.username or "system")
    await msg.answer("✅ Готово!" if ok else "⚠️ Ошибка или уже админ.", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "adm_rem")
async def cb_adm_rem(cb: CallbackQuery, state: FSMContext):
    if not await check_owner_cb(cb): return
    await cb.message.edit_text("Введите @username для разжалования:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_remove)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_remove)
async def process_adm_rem(msg: Message, state: FSMContext):
    ok = await remove_admin(msg.text.strip().lstrip("@"))
    await msg.answer("✅ Права отозваны." if ok else "❌ Не найден.", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "adm_make_owner")
async def cb_adm_owner(cb: CallbackQuery, state: FSMContext):
    if not await check_creator_cb(cb): return
    await cb.message.edit_text("Введите @username для назначения Супер-админом:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_owner)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_owner)
async def process_adm_owner(msg: Message, state: FSMContext):
    ok = await make_owner(msg.text.strip().lstrip("@"))
    await msg.answer("👑 Супер-админ назначен!" if ok else "⚠️ Ошибка.", reply_markup=back_button_kb())
    await state.clear()

@admin_router.callback_query(F.data == "adm_rev_owner")
async def cb_adm_rev_owner(cb: CallbackQuery, state: FSMContext):
    if not await check_creator_cb(cb): return
    await cb.message.edit_text("Введите @username для снятия полномочий Супер-админа:", reply_markup=back_button_kb())
    await state.set_state(AdminMgmt.waiting_revoke_owner)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_revoke_owner)
async def process_adm_rev_owner(msg: Message, state: FSMContext):
    ok = await revoke_owner(msg.text.strip().lstrip("@"))
    await msg.answer("✅ Полномочия сняты." if ok else "❌ Ошибка.", reply_markup=back_button_kb())
    await state.clear()
