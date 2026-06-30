import asyncio
import os
import sys

# Добавляем текущую директорию в путь импорта
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aiogram import Bot
from aiogram.types import FSInputFile, InputSticker

# Список смайликов для первых 5 эмоций Кати
EMOJIS_MAP = [
    "👋",  # katya_01_greet
    "😆",  # katya_02_joy
    "😡",  # katya_03_pout
    "🤔",  # katya_04_thinking
    "😉"   # katya_05_wink
]

async def update_katya_sticker_pack(bot_token: str, user_id: int, pack_link_name: str, pack_title: str):
    bot = Bot(token=bot_token)
    
    # Название пака должно оканчиваться на _by_<bot_username>
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    full_pack_name = f"{pack_link_name}_by_{bot_username}"
    
    print(f"📦 Попытка обновить стикерпак Кати: {full_pack_name}...")
    
    # Шаг 1: Проверяем, существует ли пак
    try:
        old_set = await bot.get_sticker_set(full_pack_name)
        print(f"  [+] Пак найден! В нем сейчас {len(old_set.stickers)} старых стикеров.")
        old_stickers = [s.file_id for s in old_set.stickers]
    except Exception as e:
        # Если пак не найден — мы создадим его с нуля!
        old_set = None
        print(f"  ℹ️ Пак {full_pack_name} пока не создан в Telegram. Будет создана чистая новая версия!")
        
    folder = "video-exchange-bot/katya"
    if not os.path.exists(folder):
        folder = "katya"
        
    files = sorted([f for f in os.listdir(folder) if f.startswith("katya_") and f.endswith(".png")])
    if not files:
        print("❌ Ошибка: В папке katya/ нет картинок!")
        return
        
    print(f"🖼 Подготовка {len(files[:5])} прозрачных картинок Кати...")
    
    stickers = []
    # Загружаем новые прозрачные файлы в Telegram
    for i, file in enumerate(files[:5]):
        path = os.path.join(folder, file)
        emoji = EMOJIS_MAP[i] if i < len(EMOJIS_MAP) else "💋"
        print(f"  [+] Подготовка и загрузка без фона: {file} ({emoji})...")
        
        try:
            # Масштабируем до 512x512
            from PIL import Image
            img = Image.open(path)
            img = img.resize((512, 512), Image.Resampling.LANCZOS)
            temp_path = path.replace(".png", "_temp_trans.png")
            img.save(temp_path, "PNG")
            
            uploaded_file = await bot.upload_sticker_file(
                user_id=user_id,
                sticker=FSInputFile(temp_path),
                sticker_format="static"
            )
            
            try:
                os.remove(temp_path)
            except Exception:
                pass
                
            new_sticker = InputSticker(
                sticker=uploaded_file.file_id,
                emoji_list=[emoji],
                format="static"
            )
            
            stickers.append(new_sticker)
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"  ❌ Ошибка загрузки {file}: {e}")
            return

    try:
        # Если пака нет — создаем с нуля
        if not old_set:
            success = await bot.create_new_sticker_set(
                user_id=user_id,
                name=full_pack_name,
                title=pack_title,
                stickers=stickers,
                sticker_format="static"
            )
            if success:
                print(f"\n🎉 УСПЕХ! Прозрачный стикерпак Кати успешно опубликован!")
                print(f"🔗 Ссылка на добавление: https://t.me/addstickers/{full_pack_name}")
            else:
                print("❌ Ошибка: Не удалось создать прозрачный стикерпак Кати.")
        else:
            raise Exception("Пак уже существует, переходим к бесшовному обновлению.")
    except Exception as e:
        # Процедура горячего бесшовного обновления существующего пака
        print(f"  ℹ️ Пак уже существует. Запуск процедуры бесшовного обновления стикеров Кати...")
        try:
            old_sticker_set = await bot.get_sticker_set(full_pack_name)
            
            # 1. Добавляем все новые прозрачные стикеры в пак
            for ns in stickers:
                await bot.add_sticker_to_set(
                    user_id=user_id,
                    name=full_pack_name,
                    sticker=ns
                )
                print(f"  [+] Добавлен прозрачный стикер с эмодзи {ns.emoji_list[0]}")
                await asyncio.sleep(0.3)
                
            # 2. Удаляем все старые непрозрачные стикеры из пака
            for os_sticker in old_sticker_set.stickers:
                await bot.delete_sticker_from_set(sticker=os_sticker.file_id)
                print(f"  [-] Удален старый непрозрачный стикер: {os_sticker.file_id[:15]}...")
                await asyncio.sleep(0.3)
                
            print(f"\n🎉 УСПЕХ! Существующий стикерпак Кати «{full_pack_name}» бесшовно обновлен на версию БЕЗ ФОНА!")
            print(f"🔗 Ссылка осталась прежней: https://t.me/addstickers/{full_pack_name}")
        except Exception as ex:
            print(f"❌ Сбой обновления существующего пака Кати: {ex}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python3 update_katya_pack_transparent.py <BOT_TOKEN> <USER_ID>")
        sys.exit(1)
        
    token = sys.argv[1]
    uid = int(sys.argv[2])
    
    asyncio.run(update_katya_sticker_pack(
        bot_token=token,
        user_id=uid,
        pack_link_name="katya_pack",
        pack_title="Милая Катя 💋"
    ))
