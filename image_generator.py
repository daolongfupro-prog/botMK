import io
import asyncio
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot

# Настройки ресурсов
MEDAL_IMAGES = {
    "contact": {"color": "assets/contact_color.png", "bw": "assets/contact_bw.png"},
    "vklad":   {"color": "assets/vklad_color.png", "bw": "assets/vklad_bw.png"},
    "proryv":  {"color": "assets/proryv_color.png", "bw": "assets/proryv_bw.png"}
}

AVATAR_SIZE = 80
BG_COLOR = (30, 33, 36)

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (общие для обеих команд) ─────────

async def download_avatar(bot: Bot, file_id: str, size: int = AVATAR_SIZE) -> Image.Image | None:
    if not file_id:
        return None
    try:
        file = await bot.get_file(file_id)
        avatar_bytes = io.BytesIO()
        await bot.download_file(file.file_path, avatar_bytes)
        avatar = Image.open(avatar_bytes).convert("RGBA")
        return avatar.resize((size, size), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"Ошибка загрузки аватара {file_id}: {e}")
        return None

def apply_circle_mask(image: Image.Image, size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(image, (0, 0), mask=mask)
    return output

# ─── 1. ГЕНЕРАТОР ДЛЯ /my (ЛИЧНАЯ КАРТОЧКА) ────────────────────

async def create_stat_image(bot: Bot, user: dict, by_month: dict, current_month: str) -> io.BytesIO:
    bg_width, bg_height = 800, 1000 
    bg = Image.new('RGB', (bg_width, bg_height), color=BG_COLOR)
    
    current_x = 50
    current_y = 50

    my_avatar_size = 150
    avatar = await download_avatar(bot, user.get("photo_file_id"), size=my_avatar_size)
    if avatar:
        avatar_circle = apply_circle_mask(avatar, my_avatar_size)
        bg.paste(avatar_circle, (current_x, current_y), avatar_circle)
        current_y += my_avatar_size + 30
    
    icon_size = 120 
    
    for month, items in sorted(by_month.items(), reverse=True):
        is_current = (month == current_month)
        
        for item in items:
            medal_type = item["medal_type"]
            state = "color" if is_current else "bw"
            img_path = MEDAL_IMAGES.get(medal_type, {}).get(state)
            
            if img_path:
                try:
                    icon = Image.open(img_path).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    bg.paste(icon, (current_x, current_y), mask=icon)
                except FileNotFoundError:
                    pass
            
            current_x += icon_size + 20
            if current_x > bg_width - icon_size - 50:
                current_x = 50
                current_y += icon_size + 20

    final_height = current_y + icon_size + 50
    if final_height < bg_height:
        bg = bg.crop((0, 0, bg_width, final_height))

    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes

# ─── 2. ГЕНЕРАТОР ДЛЯ /top (ЛИДЕРБОРД) ─────────────────────────

async def create_top_image(bot: Bot, stats: list, current_month: str) -> io.BytesIO:
    padding = 30
    header_height = 80
    row_height = AVATAR_SIZE + 20
    display_count = min(len(stats), 10)
    
    card_width = 800
    card_height = header_height + (display_count * row_height) + (padding * 2)
    
    bg = Image.new('RGB', (card_width, int(card_height)), color=BG_COLOR)
    draw = ImageDraw.Draw(bg)
    
    try:
        font_header = ImageFont.truetype("arial.ttf", 36)
        font_main = ImageFont.truetype("arial.ttf", 28)
        font_bold = ImageFont.truetype("arial.ttf", 28, encoding="unic")
    except IOError:
        font_header = ImageFont.load_default()
        font_main = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    header_text = f"Топ-лидеров — {current_month}"
    draw.text((padding, padding), header_text, fill=(255, 255, 255), font=font_header)

    current_y = header_height + padding
    
    avatar_futures = [download_avatar(bot, s.get("photo_file_id"), size=AVATAR_SIZE) for s in stats[:display_count]]
    avatars = await asyncio.gather(*avatar_futures)

    for i, s in enumerate(stats[:display_count]):
        y_center = current_y + (row_height / 2)
        
        place_text = f"{i+1}."
        if i == 0: place_text = "🥇"
        elif i == 1: place_text = "🥈"
        elif i == 2: place_text = "🥉"
        draw.text((padding, y_center - 15), place_text, fill=(255, 215, 0), font=font_main)

        avatar_x = padding + 60
        avatar = avatars[i]
        if avatar:
            avatar_circle = apply_circle_mask(avatar, AVATAR_SIZE)
            bg.paste(avatar_circle, (int(avatar_x), int(current_y)), avatar_circle)
        else:
            draw.ellipse((avatar_x, current_y, avatar_x + AVATAR_SIZE, current_y + AVATAR_SIZE), outline=(100, 100, 100))

        name_x = avatar_x + AVATAR_SIZE + 20
        user_name = s['full_name'] or f"@{s['username']}"
        draw.text((int(name_x), y_center - 15), user_name, fill=(255, 255, 255), font=font_main)

        points_x = card_width - padding - 150
        draw.text((int(points_x), y_center - 15), f"{s['total_points']} балл(ов)", fill=(255, 255, 255), font=font_bold)
        
        icon_size = 40
        current_icon_x = points_x - (icon_size * 3) - 10
        
        medal_types = ["contact", "vklad", "proryv"]
        for medal_type in medal_types:
            img_path = MEDAL_IMAGES.get(medal_type, {}).get("color")
            if img_path:
                try:
                    icon = Image.open(img_path).convert("RGBA")
                    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
                    bg.paste(icon, (int(current_icon_x), int(y_center - (icon_size/2))), mask=icon)
                except FileNotFoundError:
                    pass
            current_icon_x += icon_size + 5

        current_y += row_height

    result_bytes = io.BytesIO()
    bg.save(result_bytes, format='PNG')
    result_bytes.seek(0)
    
    return result_bytes
