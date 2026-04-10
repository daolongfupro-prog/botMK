import io
import asyncio
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot

# Настройки ресурсов: пути к картинкам жетонов
MEDAL_IMAGES = {
    "contact": {"color": "assets/contact_color.png", "bw": "assets/contact_bw.png"},
    "vklad":   {"color": "assets/vklad_color.png", "bw": "assets/vklad_bw.png"},
    "proryv":  {"color": "assets/proryv_color.png", "bw": "assets/proryv_bw.png"}
}

# Цвет фона (теперь единая светлая тема для всего)
BG_COLOR_LIGHT = (245, 248, 250)

async def download_avatar(bot: Bot, file_id: str, size: int) -> Image.Image | None:
    """Скачивает аватарку и делает умную обрезку (crop), чтобы не было искажений пропорций."""
    if not file_id:
        return None
    try:
        file = await bot.get_file(file_id)
        avatar_bytes = io.BytesIO()
        await bot.download_file(file.file_path, avatar_bytes)
        avatar = Image.open(avatar_bytes).convert("RGBA")
        
        # Умная обрезка по центру (делаем идеальный квадрат из любого прямоугольника)
        w, h = avatar.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        avatar = avatar.crop((left, top, left + min_dim, top + min_dim))
        
        return avatar.resize((size, size), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"Ошибка загрузки аватара {file_id}: {e}")
        return None

def apply_circle_mask(image: Image.Image, size: int) -> Image.Image:
    """Обрезает квадратную картинку в идеальный круг."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(image, (0, 0), mask=mask)
    return output

# ─── 1. ГЕНЕРАТОР ДЛЯ /my (ЛИЧНАЯ КАРТОЧКА С МЕСЯЦАМИ) ─────────

async def create_stat_image(bot: Bot, user: dict, by_month: dict, current_month: str) -> io.BytesIO:
    """Генерирует личную карточку (светлая тема)."""
    padding = 50
    gap = 20
    img_width = 800
    icon_size = 120
    my_avatar_size = 150
    
    # Пытаемся загрузить шрифты
    try:
        font_month = ImageFont.truetype("assets/font.ttf", 32)
    except:
        font_month = ImageFont.load_default()

    avatar = await download_avatar(bot, user.get("photo_file_id"), size=my_avatar_size)

    # ДИНАМИЧЕСКИЙ РАСЧЕТ ВЫСОТЫ ХОЛСТА
    current_y = padding
    if avatar:
        current_y += my_avatar_size + gap

    icons_per_row = (img_width - padding * 2) // (icon_size + gap)
    
    # Просчитываем, сколько места займут все месяцы
    for month, items in by_month.items():
        current_y += 50  # Место под текстовый заголовок месяца
        medal_rows = (len(items) + icons_per_row - 1) // icons_per_row
        current_y += medal_rows * (icon_size + gap) + gap

    final_height = max(current_y + padding, padding * 2)

    # СОЗДАЕМ ХОЛСТ (СВЕТЛЫЙ ФОН)
    bg = Image.new('RGB', (img_width, final_height), color=BG_COLOR_LIGHT)
    draw = ImageDraw.Draw(bg)
    
    current_x = padding
    current_y = padding

    # Вставляем аватарку
    if avatar:
        avatar_circle = apply_circle_mask(avatar, my_avatar_size)
        bg.paste(avatar_circle, (current_x, current_y), avatar_circle)
        current_y += my_avatar_size + gap

    # Отрисовка жетонов с заголовками месяцев
    for month, items in sorted(by_month.items(), reverse=True):
        is_current = (month == current_month)
        
        # Рисуем заголовок месяца (ТЕМНЫЙ ТЕКСТ, БЕЗ ЭМОДЗИ)
        draw.text((padding, current_y), f"Месяц: {month}", fill=(40, 40, 40), font=font_month)
        current_y += 50
        current_x = padding
        
        for item in items:
            medal_type = item["medal_type"]
            state = "color" if is_current else "bw"
            img_path = MEDAL_IMAGES.get(medal_type, {}).get(state)
            
            if img_path:
                try:
                    icon = Image.open(img_path).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    bg.paste(icon, (int(current_x), int(current_y)), mask=icon)
                except FileNotFoundError:
                    pass
            
            current_x += icon_size + gap
            
            # Перенос на новую строку внутри одного месяца
            if current_x > img_width - icon_size - padding:
                current_x = padding
                current_y += icon_size + gap
                
        # Сдвиг вниз перед следующим месяцем
        if current_x != padding:
            current_y += icon_size + gap
        current_y += gap

    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes

# ─── 2. ГЕНЕРАТОР ДЛЯ /top (ЛИДЕРБОРД - СВЕТЛАЯ ТЕМА) ──────────

async def create_top_image(bot: Bot, stats: list, current_month: str) -> io.BytesIO:
    """Генерирует светлый лидерборд с вашими кастомными PNG-медалями."""
    avatar_size_top = 80
    padding = 30
    header_height = 80
    row_height = avatar_size_top + 20
    display_count = min(len(stats), 10)
    
    card_width = 800
    card_height = header_height + (display_count * row_height) + (padding * 2)
    
    # Светлый фон
    bg = Image.new('RGB', (card_width, int(card_height)), color=BG_COLOR_LIGHT)
    draw = ImageDraw.Draw(bg)
    
    # Загружаем шрифты
    try:
        font_main = ImageFont.truetype("assets/font.ttf", 28)
        font_bold = ImageFont.truetype("assets/font.ttf", 32)
    except:
        font_main = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    # Темный заголовок на светлом фоне (БЕЗ ЭМОДЗИ)
    header_text = f"Топ лидеров — {current_month}"
    draw.text((padding, padding), header_text, fill=(30, 30, 30), font=font_bold)

    current_y = header_height + padding
    
    # Скачиваем аватарки
    avatar_futures = [download_avatar(bot, s.get("photo_file_id"), size=avatar_size_top) for s in stats[:display_count]]
    avatars = await asyncio.gather(*avatar_futures)

    # Пути к твоим кастомным медалям для ТОП-3
    top_medals = ["assets/gold.png", "assets/silver.png", "assets/bronze.png"]

    for i, s in enumerate(stats[:display_count]):
        y_center = current_y + (row_height / 2)
        place_x = padding
        
        # --- РИСУЕМ МЕСТА (PNG ДЛЯ ТОП-3 И ЦИФРЫ ДЛЯ ОСТАЛЬНЫХ) ---
        if i < 3:
            try:
                # Вставляем твою загруженную PNG картинку
                medal_icon = Image.open(top_medals[i]).convert("RGBA")
                # Подгоняем размер под дизайн (50x50)
                medal_icon = medal_icon.resize((50, 50), Image.Resampling.LANCZOS)
                bg.paste(medal_icon, (int(place_x), int(y_center - 25)), mask=medal_icon)
            except FileNotFoundError:
                # Подстраховка, если файл вдруг пропадет
                draw.text((place_x + 10, y_center - 20), f"{i+1}.", fill=(30, 30, 30), font=font_bold)
        else:
            # Для 4 места и ниже рисуем обычную серую цифру
            draw.text((place_x + 10, y_center - 20), f"{i+1}.", fill=(80, 80, 80), font=font_bold)

        # Аватарка
        avatar_x = padding + 70
        if avatars[i]:
            avatar_circle = apply_circle_mask(avatars[i], avatar_size_top)
            bg.paste(avatar_circle, (int(avatar_x), int(current_y)), avatar_circle)
        else:
            # Серая заглушка, если нет аватарки
            draw.ellipse((avatar_x, current_y, avatar_x + avatar_size_top, current_y + avatar_size_top), fill=(220, 220, 220))
        
        # Имя (Темное)
        name_x = avatar_x + avatar_size_top + 20
        draw.text((int(name_x), y_center - 15), s['full_name'], fill=(40, 40, 40), font=font_main)

        # Баллы (Темные)
        points_x = card_width - padding - 150
        draw.text((int(points_x), y_center - 15), f"{s['total_points']} балл(ов)", fill=(20, 20, 20), font=font_bold)
        
        # Жетоны
        user_medals = []
        user_medals.extend(["contact"] * int(s.get('contact_count', 0)))
        user_medals.extend(["vklad"] * int(s.get('vklad_count', 0)))
        user_medals.extend(["proryv"] * int(s.get('proryv_count', 0)))
        
        icon_size = 40
        current_icon_x = points_x - 10 
        
        for medal_type in reversed(user_medals):
            img_path = MEDAL_IMAGES.get(medal_type, {}).get("color")
            if img_path:
                try:
                    icon = Image.open(img_path).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    current_icon_x -= (icon_size + 5) 
                    bg.paste(icon, (int(current_icon_x), int(y_center - (icon_size/2))), mask=icon)
                except FileNotFoundError:
                    pass

        current_y += row_height

    res = io.BytesIO()
    bg.save(res, format='PNG')
    res.seek(0)
    return res
