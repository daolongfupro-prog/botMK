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

# Размер аватарок в топ-листе (в пикселях)
AVATAR_SIZE = 80
# Цвет фона карточки (темно-серый)
BG_COLOR = (30, 33, 36)

async def download_avatar(bot: Bot, file_id: str) -> Image.Image | None:
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
        # Изменяем размер до нужного
        return avatar.resize((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
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

async def create_top_image(bot: Bot, stats: list, current_month: str) -> io.BytesIO:
    """Генерирует изображение карточки топ-листа."""
    
    # 1. Параметры карточки
    padding = 30
    header_height = 80
    row_height = AVATAR_SIZE + 20
    # Берем топ-10 (или меньше, если участников мало)
    display_count = min(len(stats), 10)
    
    card_width = 800
    # Рассчитываем высоту динамически
    card_height = header_height + (display_count * row_height) + (padding * 2)
    
    # Создаем холст
    bg = Image.new('RGB', (card_width, int(card_height)), color=BG_COLOR)
    draw = ImageDraw.Draw(bg)
    
    # Загружаем шрифт (укажи путь к .ttf файлу, если load_default() выглядит плохо)
    try:
        # Пример для Linux/Windows, если шрифт установлен:
        font_header = ImageFont.truetype("arial.ttf", 36)
        font_main = ImageFont.truetype("arial.ttf", 28)
    except IOError:
        # Если шрифт не найден, используем стандартный
        font_header = ImageFont.load_default()
        font_main = ImageFont.load_default()

    # 2. Отрисовка заголовка
    header_text = f"Топ-лидеров — {current_month}"
    draw.text((padding, padding), header_text, fill=(255, 255, 255), font=font_header)

    current_y = header_height + padding
    
    # 3. Подготовка аватарок (скачиваем асинхронно, чтобы не тормозить бота)
    avatar_futures = [download_avatar(bot, s.get("photo_file_id")) for s in stats[:display_count]]
    avatars = await asyncio.gather(*avatar_futures)

    # 4. Отрисовка участников
    for i, s in enumerate(stats[:display_count]):
        # Определяем, это «Я» или нет (для теста, можно убрать)
        is_me = (s.get('username') == 'твой_username_для_теста')
        
        # Координаты строки
        y_center = current_y + (row_height / 2)
        
        # Позиция (1., 2., 🥇, 🥈, 🥉)
        place_text = f"{i+1}."
        if i == 0: place_text = "🥇"
        elif i == 1: place_text = "🥈"
        elif i == 2: place_text = "🥉"
        draw.text((padding, y_center - 15), place_text, fill=(255, 215, 0), font=font_main)

        # Аватарка (в круге)
        avatar_x = padding + 60
        avatar = avatars[i]
        if avatar:
            # Обрезаем в круг
            avatar_circle = apply_circle_mask(avatar, AVATAR_SIZE)
            # Накладываем на фон
            bg.paste(avatar_circle, (int(avatar_x), int(current_y)), avatar_circle)
        else:
            # Заглушка, если нет аватара
            draw.ellipse((avatar_x, current_y, avatar_x + AVATAR_SIZE, current_y + AVATAR_SIZE), outline=(100, 100, 100))

        # Имя (или юзернейм)
        name_x = avatar_x + AVATAR_SIZE + 20
        user_name = s['full_name'] or f"@{s['username']}"
        name_color = (255, 255, 255) if not is_me else (100, 255, 100)
        draw.text((int(name_x), y_center - 15), user_name, fill=name_color, font=font_main)

        # Жетоны и баллы (ЦВЕТНЫЕ для текущего месяца)
        points_x = card_width - padding - 150
        draw.text((int(points_x), y_center - 15), f"{s['total_points']} балл(ов)", fill=(255, 255, 255), font=font_main)
        
        # Накладываем твои уникальные жетоны (ЦВЕТНЫЕ)
        icon_size = 40
        # Координата X для первой иконки (справа налево)
        current_icon_x = points_x - (icon_size * 3) - 10
        
        medal_types = ["contact", "vklad", "proryv"]
        for medal_type in medal_types:
            # В топе месяца мы всегда используем ЦВЕТНЫЕ жетоны
            img_path = MEDAL_IMAGES.get(medal_type, {}).get("color")
            if img_path:
                try:
                    # Открываем, изменяем размер и накладываем
                    icon = Image.open(img_path).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    # mask=icon обеспечивает прозрачность
                    bg.paste(icon, (int(current_icon_x), int(y_center - (icon_size/2))), mask=icon)
                except FileNotFoundError:
                    pass
            current_icon_x += icon_size + 5 # Сдвигаем X для следующей иконки

        # Обновляем Y для следующей строки
        current_y += row_height

    # 5. Сохранение результата в оперативную память
    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes
