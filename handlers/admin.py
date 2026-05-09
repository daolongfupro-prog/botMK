# ─── ОТКАТ ПЕРИОДА (С ПРЕДУПРЕЖДЕНИЕМ) ───────────────────────

@admin_router.callback_query(F.data == "conf_undo_m")
async def cb_conf_undo_m(cb: CallbackQuery):
    if not await check_owner_cb(cb): return
    
    # Получаем инфо о последнем закрытии
    info = await get_last_closure_info()
    if not info:
        await cb.answer("❌ Нет доступных закрытий для отката.", show_alert=True)
        return
    
    # Получаем список того, что будем восстанавливать
    breakdown = await get_closure_breakdown(info['id'])
    
    # Проверяем, есть ли уже новые жетоны в текущем (пустом) периоде
    current_activity = await get_active_stats()
    new_medals_count = sum(s['medal_count'] for s in current_activity)

    # Формируем список участников для наглядности (топ-10)
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
