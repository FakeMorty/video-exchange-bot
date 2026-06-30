import asyncio
import os
import sys

# Добавляем текущую директорию в путь импорта
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aiogram import Bot
from aiogram.types import FSInputFile, InputSticker

# Список смайликов для 20 эмоций Софы
EMOJIS_MAP = [
    "😉",  # sofa_01_wink
    "💋",  # sofa_02_kiss
    "😍",  # sofa_03_love
    "🖤",  # sofa_04_harness
    "💤",  # sofa_05_sleepy
    "😡",  # sofa_06_angry
    "🤔",  # sofa_07_thinking
    "😨",  # sofa_08_shock
    "😊",  # sofa_09_smile
    "😢",  # sofa_10_sad
    "😏",  # sofa_11_smirk
    "😊",  # sofa_12_blush
    "😚",  # sofa_13_flirt
    "🥵",  # sofa_14_hot
    "🤑",  # sofa_15_rich
    "🎮",  # sofa_16_gamer
    "💪",  # sofa_17_strong
    "❓",  # sofa_18_confused
    "🏆",  # sofa_19_victory
    "🤫"   # sofa_20_muted
]

async def update_sofa_sticker_pack(bot_token: str, user_id: int, pack_link_name: str, pack_title: str):
    bot = Bot(token=bot_token)
    
    # Название пака должно оканчиваться на _by_<bot_username>
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    full_pack_name = f"{pack_link_name}_by_{bot_username}"
    
    print(f"📦 Попытка обновить стикерпак Софы: {full_pack_name}...")
    
    # Шаг 1: Проверяем, существует ли пак
    try:
        old_set = await bot.get_sticker_set(full_pack_name)
        print(f"  [+] Пак найден! В нем сейчас {len(old_set.stickers)} старых стикеров.")
        old_stickers = [s.file_id for s in old_set.stickers]
    except Exception as e:
        # Если пак не найден — мы создадим его с нуля!
        old_set = None
        print(f"  ℹ️ Пак {full_pack_name} пока не создан в Telegram. Будет создана чистая новая версия!")
        
    folder = "video-exchange-bot/sofa"
    if not os.path.exists(folder):
        folder = "sofa"
        
    files = sorted([f for f in os.listdir(folder) if f.startswith("sofa_") and f.endswith(".png")])
    if not files:
        print("❌ Ошибка: В папке sofa/ нет картинок!")
        return
        
    print(f"🖼 Подготовка {len(files[:20])} прозрачных картинок Софы...")
    
    stickers = []
    # Загружаем новые прозрачные файлы в Telegram
    for i, file in enumerate(files[:20]):
        path = os.path.join(folder, file)
        emoji = EMOJIS_MAP[i] if i < len(EMOJIS_MAP) else "🖤"
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
                print(f"\n🎉 УСПЕХ! Прозрачный стикерпак Софы успешно опубликован!")
                print(f"🔗 Ссылка на добавление: https://t.me/addstickers/{full_pack_name}")
            else:
                print("❌ Ошибка: Не удалось создать прозрачный стикерпак Софы.")
        else:
            raise Exception("Пак уже существует, переходим к бесшовному обновлению.")
    except Exception as e:
        # Если пак уже существовал, create_new_sticker_set вернет ошибку или мы подняли исключение.
        # В таком случае мы поочередно добавляем новые стикеры и удаляем старые!
        print(f"  ℹ️ Пак уже существует. Запуск процедуры бесшовного обновления стикеров Софы...")
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
                
            print(f"\n🎉 УСПЕХ! Существующий стикерпак Софы «{full_pack_name}» бесшовно обновлен на версию БЕЗ ФОНА!")
            print(f"🔗 Ссылка осталась прежней: https://t.me/addstickers/{full_pack_name}")
        except Exception as ex:
            print(f"❌ Сбой обновления существующего пака Софы: {ex}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python3 update_sofa_pack_transparent.py <BOT_TOKEN> <USER_ID>")
        sys.exit(1)
        
    token = sys.argv[1]
    uid = int(sys.argv[2])
    
    asyncio.run(update_sofa_sticker_pack(
        bot_token=token,
        user_id=uid,
        pack_link_name="sofa_pack",
        pack_title="Милая Готка Софа 🖤"
    ))
