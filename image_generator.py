import io
from PIL import Image
from aiogram import Bot

# Пути к твоим картинкам (цветные и ЧБ)
MEDAL_IMAGES = {
    "contact": {"color": "assets/contact_color.png", "bw": "assets/contact_bw.png"},
    "vklad": {"color": "assets/vklad_color.png", "bw": "assets/vklad_bw.png"},
    "proryv": {"color": "assets/proryv_color.png", "bw": "assets/proryv_bw.png"}
}

async def create_stat_image(bot: Bot, user: dict, by_month: dict, current_month: str) -> io.BytesIO:
    # 1. Загрузка Аватарки (если она есть)
    if user.get("photo_file_id"):
        try:
            file = await bot.get_file(user["photo_file_id"])
            avatar_bytes = io.BytesIO()
            await bot.download_file(file.file_path, avatar_bytes)
            
            avatar = Image.open(avatar_bytes).convert("RGBA")
            # LANCZOS делает картинку гладкой при изменении размера
            avatar = avatar.resize((150, 150), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"Ошибка загрузки фото: {e}")
            avatar = None
    else:
        avatar = None

    # 2. Создаем фон
    # Берем с запасом по высоте, потом обрежем
    bg_width, bg_height = 800, 1000 
    bg = Image.new('RGB', (bg_width, bg_height), color=(30, 30, 30))
    
    current_x = 50
    current_y = 50

    # 3. Вставляем аватарку
    if avatar:
        bg.paste(avatar, (current_x, current_y), avatar if 'A' in avatar.getbands() else None)
        current_y += 180 # Сдвигаем координаты для жетонов ниже аватарки
    
    # Мы убрали отрисовку мелкого текста здесь, чтобы картинка была чище.
    # Имя мы пишем в подписи к фото в Телеграме.

    # 4. Отрисовка жетонов
    icon_size = 120 # Размер жетона (чуть покрупнее)
    
    for month, items in sorted(by_month.items(), reverse=True):
        is_current = (month == current_month)
        
        for item in items:
            medal_type = item["medal_type"]
            # Выбираем цветной или ЧБ вариант в зависимости от месяца
            state = "color" if is_current else "bw"
            img_path = MEDAL_IMAGES.get(medal_type, {}).get(state)
            
            if img_path:
                try:
                    icon = Image.open(img_path).convert("RGBA")
                    # LANCZOS - секрет качественного масштабирования без пикселей
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    
                    # Накладываем жетон. Параметр icon в конце (mask=icon) - ЭТО КЛЮЧ к прозрачности!
                    bg.paste(icon, (current_x, current_y), mask=icon)
                except FileNotFoundError:
                    print(f"Файл {img_path} не найден!")
            
            # Сдвигаем координаты для следующего жетона вправо
            current_x += icon_size + 20
            
            # Если вышли за край картинки, переходим на новую строку
            if current_x > bg_width - icon_size - 50:
                current_x = 50
                current_y += icon_size + 20

    # 5. Умная обрезка холста (убираем лишнюю черноту снизу)
    # Определяем, где закончился последний элемент
    final_height = current_y + icon_size + 50
    # Если картинка получилась меньше, чем мы зарезервировали, обрезаем её
    if final_height < bg_height:
        bg = bg.crop((0, 0, bg_width, final_height))

    # 6. Сохранение результата
    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes
