"""
Автоматическая генерация стикерпака Кати.
Берёт референсное изображение, прогоняет все 28 промптов через API,
сохраняет результаты в папку stickers/.

Использование:
    python generate_stickers.py --reference путь/к/референсу.png --api replicate --key rk-xxx

Поддерживаемые API:
    --api replicate   → Replicate (лучшие аниме-модели, img2img)
    --api stability   → Stability AI (Stable Diffusion)
    --api prodia      → Prodia (бесплатный тир)
    --api local       → Локальный Stable Diffusion WebUI API

Если --key не указан, читается из переменной окружения:
    REPLICATE_API_TOKEN / STABILITY_API_KEY / PRODIA_API_KEY
"""

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

# Импортируем промпты из модуля бота
sys.path.insert(0, str(Path(__file__).parent))
from app.sticker_prompts import STICKER_PROMPTS, GENERATION_ORDER

# ──────────────────────────────────────────────
#  Настройки
# ──────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "stickers"
IMAGE_SIZE = 512
REQUEST_DELAY = 3  # секунд между запросами (чтоб не банили)
MAX_RETRIES = 3
RETRY_DELAY = 10

# Общий negative prompt для всех стикеров
NEGATIVE_PROMPT = (
    "multiple girls, nsfw, nudity, explicit, dark background, "
    "text, watermark, signature, blurry, low quality, deformed, "
    "bad anatomy, extra limbs, ugly, realistic photo"
)


# ──────────────────────────────────────────────
#  Replicate API
# ──────────────────────────────────────────────

async def generate_replicate(
    session: aiohttp.ClientSession,
    prompt: str,
    reference_path: str,
    api_key: str,
) -> bytes | None:
    """Replicate: img2img через аниме-модель."""
    # Кодируем референс в base64
    with open(reference_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode()

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }

    # Создаём предсказание
    # Модель: counterfeit-xl — отличный аниме-стиль для стикеров
    payload = {
        "version": "b8e554b5c6a14c9e8a665437c7e8c0c7d9e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5",
        "input": {
            "image": f"data:image/png;base64,{ref_b64}",
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
            "image_guidance_scale": 1.5,
            "width": IMAGE_SIZE,
            "height": IMAGE_SIZE,
        },
    }

    # Шаг 1: Создаём prediction
    async with session.post(
        "https://api.replicate.com/v1/predictions",
        headers=headers,
        json=payload,
    ) as resp:
        if resp.status != 201:
            error = await resp.text()
            print(f"  ❌ Ошибка создания prediction: {resp.status} — {error[:200]}")
            return None
        data = await resp.json()
        prediction_id = data["id"]
        status_url = data["urls"]["get"]

    # Шаг 2: Ждём результат (polling)
    for _ in range(120):  # максимум 2 минуты
        await asyncio.sleep(2)
        async with session.get(status_url, headers=headers) as resp:
            data = await resp.json()
            status = data.get("status")

            if status == "succeeded":
                output_url = data["output"]
                if isinstance(output_url, list):
                    output_url = output_url[0]
                # Скачиваем картинку
                async with session.get(output_url) as img_resp:
                    if img_resp.status == 200:
                        return await img_resp.read()
                    return None

            elif status == "failed":
                print(f"  ❌ Prediction failed: {data.get('error', 'unknown')}")
                return None

            # status in ("starting", "processing") — ждём дальше

    print("  ❌ Таймаут ожидания prediction")
    return None


# ──────────────────────────────────────────────
#  Stability AI API
# ──────────────────────────────────────────────

async def generate_stability(
    session: aiohttp.ClientSession,
    prompt: str,
    reference_path: str,
    api_key: str,
) -> bytes | None:
    """Stability AI: img2img через Stable Diffusion."""
    with open(reference_path, "rb") as f:
        ref_bytes = f.read()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    data = aiohttp.FormData()
    data.add_field("init_image", ref_bytes, filename="ref.png", content_type="image/png")
    data.add_field("init_image_mode", "IMAGE_STRENGTH")
    data.add_field("image_strength", "0.45")  # 0.45 = сильное влияние референса
    data.add_field("text_prompts[0]", prompt)
    data.add_field("text_prompts[1]", NEGATIVE_PROMPT)
    data.add_field("cfg_scale", "7")
    data.add_field("samples", "1")
    data.add_field("steps", "30")
    data.add_field("width", str(IMAGE_SIZE))
    data.add_field("height", str(IMAGE_SIZE))
    data.add_field("style_preset", "anime")

    async with session.post(
        "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024/v1/image-to-image",
        headers=headers,
        data=data,
    ) as resp:
        if resp.status == 200:
            result = await resp.json()
            if result.get("artifacts"):
                img_b64 = result["artifacts"][0]["base64"]
                return base64.b64decode(img_b64)
        error = await resp.text()
        print(f"  ❌ Stability error: {resp.status} — {error[:200]}")
        return None


# ──────────────────────────────────────────────
#  Prodia API (бесплатный тир)
# ──────────────────────────────────────────────

async def generate_prodia(
    session: aiohttp.ClientSession,
    prompt: str,
    reference_path: str,
    api_key: str,
) -> bytes | None:
    """Prodia: img2img через аниме-модель (бесплатный тир)."""
    with open(reference_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode()

    headers = {
        "X-Prodia-Key": api_key,
        "Content-Type": "application/json",
    }

    # Шаг 1: Отправляем job
    payload = {
        "imageUrl": f"data:image/png;base64,{ref_b64}",
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "model": "anything-v5.safetensors",  # аниме-модель
        "steps": 30,
        "cfg_scale": 7.5,
        "strength": 0.55,
        "seed": -1,
        "width": IMAGE_SIZE,
        "height": IMAGE_SIZE,
    }

    async with session.post(
        "https://api.prodia.com/v1/sd/img2img",
        headers=headers,
        json=payload,
    ) as resp:
        if resp.status != 200:
            error = await resp.text()
            print(f"  ❌ Prodia error: {resp.status} — {error[:200]}")
            return None
        data = await resp.json()
        job_id = data["job"]

    # Шаг 2: Ждём результат
    for _ in range(120):
        await asyncio.sleep(2)
        async with session.get(
            f"https://api.prodia.com/v1/job/{job_id}",
            headers=headers,
        ) as resp:
            data = await resp.json()
            if data.get("status") == "succeeded":
                img_url = data["imageUrl"]
                async with session.get(img_url) as img_resp:
                    if img_resp.status == 200:
                        return await img_resp.read()
            elif data.get("status") == "failed":
                print(f"  ❌ Prodia job failed")
                return None

    print("  ❌ Prodia timeout")
    return None


# ──────────────────────────────────────────────
#  Local Stable Diffusion WebUI API
# ──────────────────────────────────────────────

async def generate_local(
    session: aiohttp.ClientSession,
    prompt: str,
    reference_path: str,
    api_key: str,  # не используется для локального
    base_url: str = "http://127.0.0.1:7860",
) -> bytes | None:
    """Локальный Stable Diffusion WebUI (AUTOMATIC1111) — img2img."""
    with open(reference_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "init_images": [f"data:image/png;base64,{ref_b64}"],
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "denoising_strength": 0.55,
        "steps": 30,
        "cfg_scale": 7.5,
        "width": IMAGE_SIZE,
        "height": IMAGE_SIZE,
        "sampler_name": "Euler a",
        "override_settings": {"sd_model_checkpoint": "counterfeitXL_v10"},
    }

    async with session.post(
        f"{base_url}/sdapi/v1/img2img",
        json=payload,
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            if data.get("images"):
                return base64.b64decode(data["images"][0])
        error = await resp.text()
        print(f"  ❌ Local SD error: {resp.status} — {error[:200]}")
        return None


# ──────────────────────────────────────────────
#  Основной цикл
# ──────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Генерация стикерпака Кати")
    parser.add_argument("--reference", required=True, help="Путь к референсному изображению")
    parser.add_argument("--api", choices=["replicate", "stability", "prodia", "local"],
                        default="prodia", help="API для генерации (по умолчанию: prodia)")
    parser.add_argument("--key", default=None, help="API-ключ (или из переменной окружения)")
    parser.add_argument("--only", default=None, help="Только определённые стикеры, например: 01,02,05")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Пропускать уже сгенерированные")
    args = parser.parse_args()

    # Проверяем референс
    if not os.path.isfile(args.reference):
        print(f"❌ Референс не найден: {args.reference}")
        sys.exit(1)

    # API-ключ
    env_key_map = {
        "replicate": "REPLICATE_API_TOKEN",
        "stability": "STABILITY_API_KEY",
        "prodia": "PRODIA_API_KEY",
    }
    api_key = args.key or os.environ.get(env_key_map.get(args.api, ""), "")
    if args.api != "local" and not api_key:
        print(f"❌ Укажите --key или установите {env_key_map.get(args.api, '')}")
        sys.exit(1)

    # Создаём папку
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Фильтруем стикеры
    only_ids = None
    if args.only:
        only_ids = set(args.only.split(","))

    generator_map = {
        "replicate": generate_replicate,
        "stability": generate_stability,
        "prodia": generate_prodia,
        "local": generate_local,
    }
    generator = generator_map[args.api]

    total = len(GENERATION_ORDER)
    success = 0
    failed = 0
    skipped = 0

    print(f"🎨 Генерация стикерпака Кати")
    print(f"   API: {args.api}")
    print(f"   Референс: {args.reference}")
    print(f"   Стикеров: {total}")
    print(f"   Папка: {OUTPUT_DIR}")
    print()

    async with aiohttp.ClientSession() as session:
        for i, key in enumerate(GENERATION_ORDER, 1):
            sticker = STICKER_PROMPTS[key]
            num = key.split("_")[0]
            emotion = sticker["emotion"]

            # Фильтр --only
            if only_ids and num not in only_ids:
                continue

            # Пропуск существующих
            out_path = OUTPUT_DIR / f"{key}.png"
            if args.skip_existing and out_path.exists():
                print(f"  ⏭️  [{i}/{total}] {key}: уже есть, пропуск")
                skipped += 1
                continue

            print(f"  🖌️  [{i}/{total}] {key}: {emotion}...")

            # Пробуем с ретраями
            result = None
            for attempt in range(1, MAX_RETRIES + 1):
                result = await generator(session, sticker["prompt"], args.reference, api_key)
                if result:
                    break
                if attempt < MAX_RETRIES:
                    print(f"     ↻ Попытка {attempt + 1}/{MAX_RETRIES} через {RETRY_DELAY}с...")
                    await asyncio.sleep(RETRY_DELAY)

            if result:
                with open(out_path, "wb") as f:
                    f.write(result)
                print(f"     ✅ Сохранено: {out_path.name} ({len(result) // 1024} KB)")
                success += 1
            else:
                # Fallback: сохраняем промпт в txt для ручной генерации
                fallback_path = OUTPUT_DIR / f"{key}_prompt.txt"
                with open(fallback_path, "w", encoding="utf-8") as f:
                    f.write(f"Emotion: {emotion}\n")
                    f.write(f"Prompt: {sticker['prompt']}\n")
                    f.write(f"Negative: {NEGATIVE_PROMPT}\n")
                print(f"     ❌ Не сгенерировано. Промпт сохранён: {fallback_path.name}")
                failed += 1

            # Задержка между запросами
            if i < total:
                await asyncio.sleep(REQUEST_DELAY)

    print()
    print(f"{'='*50}")
    print(f"📊 Итого: ✅ {success}  ❌ {failed}  ⏭️ {skipped}")
    print(f"📁 Папка: {OUTPUT_DIR}")

    if failed > 0:
        print(f"\n💡 Неудавшиеся стикеры можно сгенерировать вручную")
        print(f"   или повторить: python generate_stickers.py --reference {args.reference} --api {args.api}")


if __name__ == "__main__":
    asyncio.run(main())
