import asyncio
import os
import sys

# Добавляем текущую директорию в путь импорта
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aiogram import Bot
from aiogram.types import FSInputFile, InputSticker

# Список смайликов для первых 20 эмоций Сани
EMOJIS_MAP = [
    "👍", "👋", "😡", "🤔", "😨", "😍", "💋", "💤", "😆", "😢",
    "😉", "😊", "😚", "🥵", "🤑", "🎮", "💪", "❓", "🏆", "🤫"
]

async def create_sanya_sticker_pack(bot_token: str, user_id: int, pack_link_name: str, pack_title: str):
    bot = Bot(token=bot_token)
    
    folder = "sanya"
    if not os.path.exists(folder):
        folder = "video-exchange-bot/sanya"
        
    if not os.path.exists(folder):
        print(f"❌ Ошибка: Папка sanya не найдена!")
        return
        
    files = sorted([f for f in os.listdir(folder) if f.startswith("sanya_") and f.endswith(".png")])
    if not files:
        print("❌ Ошибка: В папке sanya/ нет сгенерированных картинок!")
        return
        
    print(f"📦 Найдено {len(files)} картинок Сани. Подготовка к загрузке в Telegram...")
    
    stickers = []
    # Лимитируем первыми 20 стикерами
    for i, file in enumerate(files[:20]):
        path = os.path.join(folder, file)
        emoji = EMOJIS_MAP[i] if i < len(EMOJIS_MAP) else "💪"
        print(f"  [+] Подготовка и загрузка {file} со смайликом {emoji}...")
        
        try:
            # Изменяем размер до 512x512 для лимитов стикерпаков Telegram
            from PIL import Image
            img = Image.open(path)
            img = img.resize((512, 512), Image.Resampling.LANCZOS)
            temp_path = path.replace(".png", "_resized.png")
            img.save(temp_path, "PNG")
            
            # Шаг 1: Загружаем файл на сервера Telegram
            uploaded_file = await bot.upload_sticker_file(
                user_id=user_id,
                sticker=FSInputFile(temp_path),
                sticker_format="static"
            )
            
            try:
                os.remove(temp_path)
            except Exception:
                pass
                
            # Шаг 2: Создаем объект стикера
            stickers.append(InputSticker(
                sticker=uploaded_file.file_id,
                emoji_list=[emoji],
                format="static"
            ))
            await asyncio.sleep(0.5) # защита от лимитов
        except Exception as e:
            print(f"  ❌ Ошибка подготовки/загрузки файла {file}: {e}")
            return
            
    # Название пака должно оканчиваться на _by_<bot_username>
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    
    # Формируем системное имя пака
    full_pack_name = f"{pack_link_name}_by_{bot_username}"
    print(f"🚀 Создание стикерпака в Telegram под именем «{full_pack_name}»...")
    
    try:
        success = await bot.create_new_sticker_set(
            user_id=user_id,
            name=full_pack_name,
            title=pack_title,
            stickers=stickers,
            sticker_format="static"
        )
        if success:
            print(f"\n🎉 УСПЕХ! Стикерпак Сани создан и опубликован!")
            print(f"🔗 Ссылка на добавление: https://t.me/addstickers/{full_pack_name}")
        else:
            print("❌ Ошибка: Telegram отклонил создание стикерпака.")
    except Exception as e:
        print(f"❌ Критический сбой при создании стикерпака: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python3 create_sanya_pack.py <BOT_TOKEN> <USER_ID>")
        sys.exit(1)
        
    token = sys.argv[1]
    uid = int(sys.argv[2])
    
    # Запускаем создание пака
    asyncio.run(create_sanya_sticker_pack(
        bot_token=token,
        user_id=uid,
        pack_link_name="sanya_pack",
        pack_title="Брутальный Саня 🏋️‍♂️"
    ))
