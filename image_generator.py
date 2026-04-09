import io
import asyncio
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot

# Настройки ресурсов: пути к твоим уникальным картинкам жетонов
# Убедись, что файлы с такими именами лежат в папке assets/
MEDAL_IMAGES = {
    "contact": {"color": "assets/contact_color.png", "bw": "assets/contact_bw.png"},
    "vklad":   {"color": "assets/vklad_color.png", "bw": "assets/vklad_bw.png"},
    "proryv":  {"color": "assets/proryv_color.png", "bw": "assets/proryv_bw.png"}
}

# Цвет фона карточки (темно-серый)
BG_COLOR = (30, 33, 36)

async def download_avatar(bot: Bot, file_id: str, size: int) -> Image.Image | None:
    """Вспомогательная функция для скачивания и подготовки аватарки."""
    if not file_id:
        return None
    try:
        # Получаем информацию о файле через API Телеграма
        file = await bot.get_file(file_id)
        # Скачиваем файл в память
        avatar_bytes = io.BytesIO()
        await bot.download_file(file.file_path, avatar_bytes)
        # Открываем изображение и конвертируем в RGBA (с прозрачностью)
        avatar = Image.open(avatar_bytes).convert("RGBA")
        return avatar.resize((size, size), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"Ошибка загрузки аватара {file_id}: {e}")
        return None

def apply_circle_mask(image: Image.Image, size: int) -> Image.Image:
    """Вспомогательная функция для обрезки картинки в круг."""
    # Создаем маску: белый круг на черном фоне
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    
    # Накладываем маску на прозрачный фон
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(image, (0, 0), mask=mask)
    return output

# ─── 1. ГЕНЕРАТОР ДЛЯ /my (ЛИЧНАЯ КАРТОЧКА) ────────────────────

async def create_stat_image(bot: Bot, user: dict, by_month: dict, current_month: str) -> io.BytesIO:
    """Генерирует изображение личной карточки жетонов без искажений и черной области."""
    
    # 1. Параметры карточки
    padding = 50
    gap = 20
    img_width = 800
    icon_size = 120 # Размер жетона (чуть покрупнее)
    my_avatar_size = 150 # Размер аватарки в личной карточке
    
    # Считаем количество жетонов и необходимых строк
    total_medals = sum(len(items) for items in by_month.values())
    
    # Считаем, сколько жетонов влезает в одну строку
    icons_per_row = (img_width - padding * 2) // (icon_size + gap)
    # Считаем количество необходимых строк для жетонов
    medal_rows = (total_medals + icons_per_row - 1) // icons_per_row if total_medals > 0 else 0
    
    # 2. Скачиваем аватарку (если есть)
    avatar = await download_avatar(bot, user.get("photo_file_id"), size=my_avatar_size)

    # 3. Расчет высоты холста до его создания
    # Базовая высота: верхний отступ + аватарка (если есть) + отступ
    base_height = padding + gap
    if avatar:
        base_height += my_avatar_size + gap

    # Высота жетонов
    medals_height = medal_rows * (icon_size + gap)
    
    # Итоговая высота
    final_height = base_height + medals_height + padding
    
    # Минимальная высота, если жетонов нет, но есть аватарка
    if avatar and final_height < (padding + my_avatar_size + padding):
         final_height = padding + my_avatar_size + padding
         
    # Минимальная высота, если вообще ничего нет (для пустой карточки)
    if final_height < padding * 2:
         final_height = padding * 2

    # 4. Создаем фон ПРАВИЛЬНОГО РАЗМЕРА
    bg = Image.new('RGB', (img_width, final_height), color=BG_COLOR)
    
    current_x = padding
    current_y = padding

    # 5. Вставляем аватарку (БЕЗ ИСКАЖЕНИЙ, в круг)
    if avatar:
        avatar_circle = apply_circle_mask(avatar, my_avatar_size)
        bg.paste(avatar_circle, (current_x, current_y), avatar_circle)
        current_y += my_avatar_size + gap

    # 6. Отрисовка жетонов
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
                    # mask=icon обеспечивает прозрачность
                    bg.paste(icon, (int(current_x), int(current_y)), mask=icon)
                except FileNotFoundError:
                    pass
            
            # Сдвигаем координаты для следующего жетона вправо
            current_x += icon_size + gap
            
            # Если вышли за край картинки, переходим на новую строку
            if current_x > img_width - icon_size - padding:
                current_x = padding
                current_y += icon_size + gap

    # 7. Сохранение результата в оперативную память
    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes

# ─── 2. ГЕНЕРАТОР ДЛЯ /top (ЛИДЕРБОРД) ─────────────────────────
async def create_top_image(bot: Bot, stats: list, current_month: str) -> io.BytesIO:
    avatar_size_top = 80
    padding = 30
    header_height = 80
    row_height = avatar_size_top + 20
    display_count = min(len(stats), 10)
    
    card_width = 800
    card_height = header_height + (display_count * row_height) + (padding * 2)
    
    bg = Image.new('RGB', (card_width, int(card_height)), color=BG_COLOR)
    draw = ImageDraw.Draw(bg)
    
    # Загружаем шрифт из папки assets
    try:
        font_main = ImageFont.truetype("assets/font.ttf", 28)
        font_bold = ImageFont.truetype("assets/font.ttf", 32)
    except:
        font_main = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    current_y = header_height + padding
    
    # Скачиваем аватарки
    avatar_futures = [download_avatar(bot, s.get("photo_file_id"), size=avatar_size_top) for s in stats[:display_count]]
    avatars = await asyncio.gather(*avatar_futures)

    for i, s in enumerate(stats[:display_count]):
        y_center = current_y + (row_height / 2)
        
        # --- РИСУЕМ МЕДАЛИ ДЛЯ ТОП-3 ---
        place_x = padding
        if i < 3:
            # Цвета: Золото, Серебро, Бронза
            colors = [(255, 215, 0), (192, 192, 192), (205, 127, 50)]
            # Рисуем круг-медаль
            circle_r = 20
            draw.ellipse([place_x, y_center-circle_r, place_x+circle_r*2, y_center+circle_r], fill=colors[i])
            # Пишем цифру внутри круга (черным цветом для контраста)
            draw.text((place_x + 13, y_center - 15), str(i+1), fill=(0,0,0), font=font_bold)
        else:
            # Для остальных просто белая цифра
            draw.text((place_x + 5, y_center - 15), f"{i+1}.", fill=(255, 255, 255), font=font_main)

        # Аватарка
        avatar_x = padding + 60
        if avatars[i]:
            avatar_circle = apply_circle_mask(avatars[i], avatar_size_top)
            bg.paste(avatar_circle, (int(avatar_x), int(current_y)), avatar_circle)
        
        # Имя
        name_x = avatar_x + avatar_size_top + 20
        draw.text((int(name_x), y_center - 15), s['full_name'], fill=(255, 255, 255), font=font_main)

        # Баллы и жетоны (логика жетонов остается из прошлого шага)
        points_x = card_width - padding - 150
        draw.text((int(points_x), y_center - 15), f"{s['total_points']} б.", fill=(255, 255, 255), font=font_bold)
        
        current_y += row_height

    res = io.BytesIO()
    bg.save(res, format='PNG')
    res.seek(0)
    return res
