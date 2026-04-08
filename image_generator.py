import io
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot

# Пути к твоим картинкам
MEDAL_IMAGES = {
    "contact": {"color": "assets/contact_color.png", "bw": "assets/contact_bw.png"},
    "vklad": {"color": "assets/vklad_color.png", "bw": "assets/vklad_bw.png"},
    "proryv": {"color": "assets/proryv_color.png", "bw": "assets/proryv_bw.png"}
}

async def create_stat_image(bot: Bot, user: dict, by_month: dict, current_month: str) -> io.BytesIO:
    # 1. Создаем фон (например, темно-серый холст 800x600)
    img_width, img_height = 800, 600
    bg = Image.new('RGB', (img_width, img_height), color=(30, 30, 30))
    draw = ImageDraw.Draw(bg)

    # 2. Пытаемся скачать и вставить аватарку
    if user.get("photo_file_id"):
        try:
            file = await bot.get_file(user["photo_file_id"])
            avatar_bytes = io.BytesIO()
            await bot.download_file(file.file_path, avatar_bytes)
            
            avatar = Image.open(avatar_bytes).convert("RGBA")
            avatar = avatar.resize((150, 150)) # Размер аватарки
            bg.paste(avatar, (50, 50), mask=avatar if 'A' in avatar.getbands() else None)
        except Exception as e:
            print(f"Ошибка загрузки фото: {e}")
            
    # Рисуем имя пользователя рядом с аватаркой (простым текстом, так как шрифты нужно загружать отдельно)
    # По умолчанию PIL использует стандартный мелкий шрифт, но для тестов сойдет
    draw.text((220, 110), f"Статистика: {user['full_name']}", fill=(255, 255, 255))

    # 3. Отрисовка жетонов
    x_start = 50
    y_start = 250
    icon_size = 100 # Размер жетона на холсте
    
    current_x = x_start
    current_y = y_start

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
                    icon = icon.resize((icon_size, icon_size))
                    # Накладываем жетон на фон с учетом прозрачности
                    bg.paste(icon, (current_x, current_y), mask=icon)
                except FileNotFoundError:
                    print(f"Файл {img_path} не найден!")
            
            # Сдвигаем координаты для следующего жетона вправо
            current_x += icon_size + 20
            
            # Если вышли за край картинки, переходим на новую строку
            if current_x > img_width - icon_size - 50:
                current_x = x_start
                current_y += icon_size + 20

    # 4. Сохраняем результат в оперативную память и возвращаем
    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes
