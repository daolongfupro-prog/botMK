from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import (
    get_user, get_all_users, add_user, remove_user,
    award_medal, cancel_last_medal, check_weekly_limit,
    get_monthly_stats, get_user_history, get_current_month,
    add_admin, remove_admin, get_all_admins, is_admin, is_owner,
    save_congrats, MEDAL_NAMES, MEDAL_LIMITS
)
from datetime import datetime
import openpyxl, io

admin_router = Router()

# ─── FSM состояния ───────────────────────────────────────────

class AddUser(StatesGroup):
    waiting_username = State()
    waiting_fullname = State()

class RemoveUser(StatesGroup):
    waiting_username = State()

class GiveMedal(StatesGroup):
    waiting_user    = State()
    waiting_medal   = State()
    waiting_comment = State()
    confirm_overlimit = State()

class AdminMgmt(StatesGroup):
    waiting_add    = State()
    waiting_remove = State()

class CongratsWrite(StatesGroup):
    waiting_text = State()

# ─── Проверка прав ───────────────────────────────────────────

async def check_admin(msg: Message) -> bool:
    uname = msg.from_user.username
    if not uname or not await is_admin(uname):
        await msg.answer("⛔ У вас нет прав администратора.")
        return False
    return True

async def check_owner(msg: Message) -> bool:
    uname = msg.from_user.username
    if not uname or not await is_owner(uname):
        await msg.answer("⛔ Только владелец может выполнить это действие.")
        return False
    return True

# ─── ГЛАВНОЕ МЕНЮ ────────────────────────────────────────────

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Начислить жетон",    callback_data="give_medal")],
        [InlineKeyboardButton(text="👥 Список участников",  callback_data="list_users")],
        [InlineKeyboardButton(text="➕ Добавить участника", callback_data="add_user")],
        [InlineKeyboardButton(text="➖ Удалить участника",  callback_data="remove_user")],
        [InlineKeyboardButton(text="📊 Статистика месяца",  callback_data="month_stats")],
        [InlineKeyboardButton(text="📤 Бэкап данных",       callback_data="backup")],
        [InlineKeyboardButton(text="👑 Управление админами",callback_data="manage_admins")],
    ])

@admin_router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if not await check_admin(msg): return
    await msg.answer("👑 <b>Панель администратора — Метод Контакта</b>", 
                     parse_mode="HTML", reply_markup=admin_menu_kb())

# ─── СПИСОК УЧАСТНИКОВ ───────────────────────────────────────

@admin_router.callback_query(F.data == "list_users")
async def cb_list_users(cb: CallbackQuery):
    if not await is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True); return

    month = get_current_month()
    stats = await get_monthly_stats(month)
    dt = datetime.strptime(month, "%Y-%m")

    text = f"👥 <b>Участники — {dt.strftime('%B %Y')}</b>\n\n"
    for i, s in enumerate(stats, 1):
        text += (
            f"{i}. @{s['username']} — {s['full_name']}\n"
            f"   ⭐×{s['contact_count']} 💛×{s['vklad_count']} 🔥×{s['proryv_count']} "
            f"│ <b>{s['total_points']} балл(ов)</b>\n"
        )
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()

# ─── ДОБАВИТЬ УЧАСТНИКА ──────────────────────────────────────

@admin_router.callback_query(F.data == "add_user")
async def cb_add_user(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True); return
    await cb.message.answer("➕ Введите @username нового участника:")
    await state.set_state(AddUser.waiting_username)
    await cb.answer()

@admin_router.message(AddUser.waiting_username)
async def add_user_username(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    await state.update_data(username=uname)
    await msg.answer(f"Введите полное имя для @{uname}:")
    await state.set_state(AddUser.waiting_fullname)

@admin_router.message(AddUser.waiting_fullname)
async def add_user_fullname(msg: Message, state: FSMContext):
    data = await state.get_data()
    uname = data["username"]
    full_name = msg.text.strip()
    ok = await add_user(uname, full_name)
    if ok:
        await msg.answer(f"✅ Участник @{uname} ({full_name}) добавлен!")
    else:
        await msg.answer(f"⚠️ Участник @{uname} уже существует.")
    await state.clear()

# ─── УДАЛИТЬ УЧАСТНИКА ───────────────────────────────────────

@admin_router.callback_query(F.data == "remove_user")
async def cb_remove_user(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True); return
    await cb.message.answer("➖ Введите @username участника для удаления:")
    await state.set_state(RemoveUser.waiting_username)
    await cb.answer()

@admin_router.message(RemoveUser.waiting_username)
async def remove_user_handler(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    ok = await remove_user(uname)
    if ok:
        await msg.answer(f"✅ Участник @{uname} деактивирован. Данные сохранены.")
    else:
        await msg.answer(f"❌ Участник @{uname} не найден.")
    await state.clear()

# ─── НАЧИСЛИТЬ ЖЕТОН ─────────────────────────────────────────

def medal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Контакт (1 балл)",  callback_data="medal_contact")],
        [InlineKeyboardButton(text="💛 Вклад (1 балл)",    callback_data="medal_vklad")],
        [InlineKeyboardButton(text="🔥 Прорыв (2 балла)",  callback_data="medal_proryv")],
        [InlineKeyboardButton(text="❌ Отмена",             callback_data="cancel")],
    ])

def confirm_overlimit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начислить (превысить лимит)", callback_data="overlimit_yes")],
        [InlineKeyboardButton(text="❌ Отменить",                     callback_data="overlimit_no")],
    ])

@admin_router.callback_query(F.data == "give_medal")
async def cb_give_medal(cb: CallbackQuery, state: FSMContext):
    if not await is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True); return
    await cb.message.answer("🏅 Введите @username участника для начисления жетона:")
    await state.set_state(GiveMedal.waiting_user)
    await cb.answer()

@admin_router.message(GiveMedal.waiting_user)
async def give_medal_user(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    user = await get_user(uname)
    if not user:
        await msg.answer(f"❌ Участник @{uname} не найден. Попробуйте снова:")
        return
    await state.update_data(target_username=uname, target_name=user["full_name"])
    await msg.answer(
        f"👤 Участник: <b>{user['full_name']}</b> (@{uname})\n\nВыберите тип жетона:",
        parse_mode="HTML", reply_markup=medal_kb()
    )
    await state.set_state(GiveMedal.waiting_medal)

@admin_router.callback_query(GiveMedal.waiting_medal, F.data.startswith("medal_"))
async def give_medal_type(cb: CallbackQuery, state: FSMContext):
    medal_type = cb.data.replace("medal_", "")
    await state.update_data(medal_type=medal_type)

    data = await state.get_data()
    uname = data["target_username"]
    pts = MEDAL_LIMITS[medal_type]["points_per"]
    limit = await check_weekly_limit(uname, medal_type, pts)

    if not limit["ok"]:
        await cb.message.answer(
            f"⚠️ <b>Превышение недельного лимита!</b>\n\n"
            f"Участник: @{uname}\n"
            f"Жетон: {MEDAL_NAMES[medal_type]}\n"
            f"Использовано баллов: <b>{limit['used']}</b> из <b>{limit['max']}</b>\n\n"
            f"Продолжить или отменить?",
            parse_mode="HTML", reply_markup=confirm_overlimit_kb()
        )
        await state.set_state(GiveMedal.confirm_overlimit)
    else:
        await cb.message.answer(
            f"✏️ Напишите комментарий к жетону {MEDAL_NAMES[medal_type]}\n"
            f"(или отправьте <i>-</i> чтобы пропустить):",
            parse_mode="HTML"
        )
        await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.callback_query(GiveMedal.confirm_overlimit, F.data == "overlimit_yes")
async def overlimit_yes(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer(
        "✏️ Напишите комментарий к жетону (или отправьте - чтобы пропустить):"
    )
    await state.set_state(GiveMedal.waiting_comment)
    await cb.answer()

@admin_router.callback_query(GiveMedal.confirm_overlimit, F.data == "overlimit_no")
async def overlimit_no(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("❌ Начисление отменено.")
    await state.clear()
    await cb.answer()

@admin_router.message(GiveMedal.waiting_comment)
async def give_medal_comment(msg: Message, state: FSMContext):
    comment = msg.text.strip()
    if comment == "-":
        comment = ""
    data = await state.get_data()
    uname = data["target_username"]
    name  = data["target_name"]
    medal_type = data["medal_type"]
    awarded_by = msg.from_user.username or "admin"

    result = await award_medal(uname, medal_type, comment, awarded_by)

    await msg.answer(
        f"✅ Жетон начислен!\n\n"
        f"👤 {name} (@{uname})\n"
        f"{MEDAL_NAMES[medal_type]} +{result['points']} балл(ов)\n"
        f"{'💬 ' + comment if comment else ''}",
        parse_mode="HTML"
    )

    # Уведомляем участника
    user = await get_user(uname)
    if user and user.get("telegram_id"):
        try:
            cmt_text = f"\n💬 <i>{comment}</i>" if comment else ""
            await msg.bot.send_message(
                user["telegram_id"],
                f"🎉 <b>Вы получили жетон!</b>\n\n"
                f"{MEDAL_NAMES[medal_type]} +{result['points']} балл(ов){cmt_text}\n\n"
                f"от Александр Ложкин │ Метод Контакта",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await state.clear()

@admin_router.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("❌ Действие отменено.")
    await cb.answer()

# ─── ОТМЕНА ПОСЛЕДНЕГО НАЧИСЛЕНИЯ ───────────────────────────

@admin_router.message(Command("cancel_last"))
async def cmd_cancel_last(msg: Message):
    if not await check_admin(msg): return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Использование: /cancel_last @username")
        return
    uname = parts[1].lstrip("@")
    ok = await cancel_last_medal(uname)
    if ok:
        await msg.answer(f"✅ Последнее начисление для @{uname} отменено.")
    else:
        await msg.answer(f"❌ Нет начислений для @{uname}.")

# ─── ИСТОРИЯ УЧАСТНИКА ───────────────────────────────────────

@admin_router.message(Command("history"))
async def cmd_history(msg: Message):
    if not await check_admin(msg): return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Использование: /history @username")
        return
    uname = parts[1].lstrip("@")
    history = await get_user_history(uname, 20)
    if not history:
        await msg.answer(f"📭 Нет истории для @{uname}.")
        return
    text = f"📋 <b>История @{uname}</b>\n\n"
    for h in history:
        date_str = h["awarded_at"][:10]
        cmt = f" — {h['comment']}" if h.get("comment") else ""
        text += f"{date_str} {MEDAL_NAMES[h['medal_type']]} +{h['points']}{cmt}\n"
    await msg.answer(text, parse_mode="HTML")

# ─── СТАТИСТИКА МЕСЯЦА ───────────────────────────────────────

@admin_router.callback_query(F.data == "month_stats")
async def cb_month_stats(cb: CallbackQuery):
    if not await is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True); return

    month = get_current_month()
    stats = await get_monthly_stats(month)
    dt = datetime.strptime(month, "%Y-%m")
    text = f"📊 <b>Итоги — {dt.strftime('%B %Y')}</b>\n\n"

    medals_top = ["🥇", "🥈", "🥉"]
    for i, s in enumerate(stats):
        prefix = medals_top[i] if i < 3 else f"{i+1}."
        text += (
            f"{prefix} <b>{s['full_name']}</b> (@{s['username']})\n"
            f"   ⭐×{s['contact_count']} 💛×{s['vklad_count']} 🔥×{s['proryv_count']} "
            f"│ <b>{s['total_points']} балл(ов)</b>\n\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать поздравление", callback_data="write_congrats")],
        [InlineKeyboardButton(text="🤖 Бот поздравит сам",     callback_data="bot_congrats")],
    ])
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()

# ─── ПОЗДРАВЛЕНИЕ ────────────────────────────────────────────

@admin_router.callback_query(F.data == "write_congrats")
async def cb_write_congrats(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer(
        "✍️ Напишите текст поздравления.\n"
        "Бот отправит его 1-го числа в группу и топ-3 лично:"
    )
    await state.set_state(CongratsWrite.waiting_text)
    await cb.answer()

@admin_router.message(CongratsWrite.waiting_text)
async def save_congrats_handler(msg: Message, state: FSMContext):
    month = get_current_month()
    author = msg.from_user.username or "admin"
    await save_congrats(month, msg.text.strip(), author)
    await msg.answer(
        "✅ Поздравление сохранено! Будет отправлено 1-го числа следующего месяца."
    )
    await state.clear()

@admin_router.callback_query(F.data == "bot_congrats")
async def cb_bot_congrats(cb: CallbackQuery):
    month = get_current_month()
    await save_congrats(month, "", "bot")
    await cb.message.answer(
        "✅ Понял! Бот сам составит поздравление и отправит 1-го числа."
    )
    await cb.answer()

# ─── БЭКАП ───────────────────────────────────────────────────

@admin_router.callback_query(F.data == "backup")
async def cb_backup(cb: CallbackQuery):
    if not await is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True); return
    await cb.message.answer("📤 Формирую бэкап...")
    await send_backup(cb.message.bot, cb.from_user.id)
    await cb.answer()

@admin_router.message(Command("backup"))
async def cmd_backup(msg: Message):
    if not await check_admin(msg): return
    await msg.answer("📤 Формирую бэкап...")
    await send_backup(msg.bot, msg.from_user.id)

async def send_backup(bot, chat_id: int):
    from database import get_all_users, get_user_history
    month = get_current_month()
    stats = await get_monthly_stats(month)
    users = await get_all_users()

    wb = openpyxl.Workbook()

    # Лист 1: Статистика месяца
    ws1 = wb.active
    ws1.title = f"Статистика {month}"
    ws1.append(["Место", "Username", "Имя", "Контакт", "Вклад", "Прорыв", "Итого баллов"])
    for i, s in enumerate(stats, 1):
        ws1.append([i, s["username"], s["full_name"],
                    s["contact_count"], s["vklad_count"], s["proryv_count"], s["total_points"]])

    # Лист 2: Полная история
    ws2 = wb.create_sheet("История начислений")
    ws2.append(["Дата", "Username", "Имя", "Жетон", "Баллы", "Комментарий", "Начислил"])
    for u in users:
        history = await get_user_history(u["username"], 100)
        for h in history:
            ws2.append([
                h["awarded_at"][:10], h["username"], u["full_name"],
                MEDAL_NAMES.get(h["medal_type"], h["medal_type"]),
                h["points"], h.get("comment", ""), h.get("awarded_by", "")
            ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from aiogram.types import BufferedInputFile
    dt_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    await bot.send_document(
        chat_id,
        BufferedInputFile(buf.read(), filename=f"backup_kontakt_{dt_str}.xlsx"),
        caption=f"📊 Бэкап данных — {dt_str}"
    )

# ─── ВОССТАНОВЛЕНИЕ ──────────────────────────────────────────

@admin_router.message(Command("restore"))
async def cmd_restore(msg: Message):
    if not await check_owner(msg): return
    await msg.answer(
        "🔄 Отправьте Excel-файл бэкапа для восстановления данных.\n"
        "⚠️ Внимание: текущие данные будут перезаписаны!"
    )

# ─── УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ ─────────────────────────────

@admin_router.callback_query(F.data == "manage_admins")
async def cb_manage_admins(cb: CallbackQuery):
    if not await is_owner(cb.from_user.username):
        await cb.answer("⛔ Только владелец", show_alert=True); return

    admins = await get_all_admins()
    text = "👑 <b>Администраторы</b>\n\n"
    for a in admins:
        role = "👑 Владелец" if a["is_owner"] else "🔧 Админ"
        text += f"{role}: @{a['username']} — {a['full_name']}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа",  callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Убрать админа",    callback_data="remove_admin")],
    ])
    await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@admin_router.callback_query(F.data == "add_admin")
async def cb_add_admin(cb: CallbackQuery, state: FSMContext):
    if not await is_owner(cb.from_user.username):
        await cb.answer("⛔ Только владелец", show_alert=True); return
    await cb.message.answer("Введите @username нового администратора:")
    await state.set_state(AdminMgmt.waiting_add)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_add)
async def do_add_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    ok = await add_admin(uname, msg.from_user.username)
    if ok:
        await msg.answer(f"✅ @{uname} назначен администратором.")
    else:
        await msg.answer(f"⚠️ @{uname} уже является администратором.")
    await state.clear()

@admin_router.callback_query(F.data == "remove_admin")
async def cb_remove_admin(cb: CallbackQuery, state: FSMContext):
    if not await is_owner(cb.from_user.username):
        await cb.answer("⛔ Только владелец", show_alert=True); return
    await cb.message.answer("Введите @username администратора для снятия прав:")
    await state.set_state(AdminMgmt.waiting_remove)
    await cb.answer()

@admin_router.message(AdminMgmt.waiting_remove)
async def do_remove_admin(msg: Message, state: FSMContext):
    uname = msg.text.strip().lstrip("@")
    await remove_admin(uname)
    await msg.answer(f"✅ Права администратора сняты с @{uname}.")
    await state.clear()

@admin_router.message(Command("admins"))
async def cmd_admins(msg: Message):
    if not await check_owner(msg): return
    admins = await get_all_admins()
    text = "👑 <b>Список администраторов</b>\n\n"
    for a in admins:
        role = "👑 Владелец" if a["is_owner"] else "🔧 Админ"
        text += f"{role}: @{a['username']} — {a['full_name']}\n"
    await msg.answer(text, parse_mode="HTML")
