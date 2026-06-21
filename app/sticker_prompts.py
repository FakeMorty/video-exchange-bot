"""
Промпты для генерации стикерпака Кати.

КАК ИСПОЛЬЗОВАТЬ:
1. Сгенерируй первый стикер вручную с нужным стилем
2. Для каждого следующего — используй img2img с референсом первого
3. Размер: 512x512, PNG
4. Удали зелёный фон (хромакей) и добавь белую обводку 2-3px

ПРАВИЛА:
- Фон: сплошной хромакей зелёный #00FF00 (для точного удаления)
- Только Катя: никаких предметов, мебели, декораций
- Эмоции через позу и мимику, не через реквизит
"""

STICKER_PROMPTS = {

    # ══════════════════════════════════════════
    #  🟢 ОБЯЗАТЕЛЬНЫЕ (8 шт)
    # ══════════════════════════════════════════

    "01_greet": {
        "emotion": "Привет / рада видеть",
        "prompt": (
            "anime sticker, 18yo girl Katya waving hello with one hand raised, "
            "warm happy smile, slightly tilted head, long light-brown hair swaying, "
            "wearing white school blouse and navy skirt, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, desk, books, objects, props",
    },

    "02_joy": {
        "emotion": "Радость / восторг",
        "prompt": (
            "anime sticker, 18yo girl Katya jumping with joy, both arms raised up, "
            "huge sparkling smile, closed happy eyes, hair flying up, "
            "wearing white school blouse and navy skirt, full body, dynamic pose, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "03_pout": {
        "emotion": "Обида / надула губки",
        "prompt": (
            "anime sticker, 18yo girl Katya pouting with puffed cheeks, "
            "looking up from below with big sad puppy eyes, arms crossed, "
            "slight blush, hurt expression, wearing white school blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, smile, furniture, objects, props",
    },

    "04_thinking": {
        "emotion": "Задумчивость",
        "prompt": (
            "anime sticker, 18yo girl Katya thinking with index finger touching her lips, "
            "eyes looking to the side, slightly tilted head, curious expression, "
            "one hand on hip, wearing white school blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "05_wink": {
        "emotion": "Подмигивание / хитрость",
        "prompt": (
            "anime sticker, 18yo girl Katya winking one eye with a sly smile, "
            "peace sign near her face, playful flirty expression, "
            "leaning forward slightly, wearing white school blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "06_blush": {
        "emotion": "Стыд / застенчивость",
        "prompt": (
            "anime sticker, 18yo girl Katya hiding face behind both hands but peeking through fingers, "
            "deep red blush on cheeks, embarrassed shy expression, "
            "slightly hunched shoulders, wearing white school blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, confident, furniture, objects, props",
    },

    "07_tired": {
        "emotion": "Усталость / выдохлась",
        "prompt": (
            "anime sticker, 18yo girl Katya standing slumped with droopy half-closed eyes, "
            "one hand wiping forehead, other arm hanging limply at side, "
            "exhausted expression, messy hair, wearing rumpled white school blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, energetic, desk, books, furniture, objects, props",
    },

    "08_angry": {
        "emotion": "Злость / обиделась",
        "prompt": (
            "anime sticker, 18yo girl Katya with angry puffed cheeks and furrowed brows, "
            "arms crossed tightly, glaring from below, small fang showing, "
            "anime anger vein on forehead, wearing white school blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, smiling, furniture, objects, props",
    },

    # ══════════════════════════════════════════
    #  🟡 ВАЖНЫЕ (12 шт)
    # ══════════════════════════════════════════

    "09_flirt": {
        "emotion": "Флирт / соблазн",
        "prompt": (
            "anime sticker, 18yo girl Katya biting her lower lip with half-lidded eyes, "
            "one finger tracing her collar, hair tossed to one side, "
            "seductive knowing smile, slight blush, wearing slightly unbuttoned white blouse and navy skirt, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, explicit nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "10_kiss": {
        "emotion": "Поцелуй",
        "prompt": (
            "anime sticker, 18yo girl Katya sending a kiss with pursed lips, "
            "eyes closed, making a heart shape with fingers, pink blush, "
            "small floating hearts around her, wearing white school blouse and navy skirt, upper body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "11_hug": {
        "emotion": "Обнимашки / хочу обнять",
        "prompt": (
            "anime sticker, 18yo girl Katya hugging herself tightly with both arms wrapped around own body, "
            "eyes closed, soft dreamy smile, cheek pressed to her own shoulder, "
            "wearing cozy oversized shirt, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, pillow, bed, furniture, objects, props",
    },

    "12_split": {
        "emotion": "Гимнастика — шпагат",
        "prompt": (
            "anime sticker, 18yo girl Katya doing a perfect full split, "
            "arms raised triumphantly, big proud smile, wearing gymnastics leotard, "
            "legs extended perfectly straight, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, broken pose, furniture, objects, props",
    },

    "13_bridge": {
        "emotion": "Гимнастика — мостик",
        "prompt": (
            "anime sticker, 18yo girl Katya doing a backbend bridge, "
            "hands and feet on ground, arched back, face upside-down smiling playfully, "
            "wearing gymnastics leotard, impressive flexibility, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, broken pose, furniture, objects, props",
    },

    "14_stretch": {
        "emotion": "Растяжка",
        "prompt": (
            "anime sticker, 18yo girl Katya sitting stretching, "
            "one leg extended forward reaching toward toes, other leg bent, "
            "focused expression, slightly straining, wearing sports top and shorts, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "15_school": {
        "emotion": "Скучает / тоска",
        "prompt": (
            "anime sticker, 18yo girl Katya standing with chin resting on palm, "
            "head tilted, deadpan bored expression, blank stare, "
            "other hand on hip, wearing white school blouse and navy skirt, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, happy, desk, pencil, furniture, objects, props",
    },

    "16_reading": {
        "emotion": "Задумалась / витает в облаках",
        "prompt": (
            "anime sticker, 18yo girl Katya standing with both hands behind head, "
            "looking up dreamily, glasses on nose, soft absent-minded smile, "
            "one knee slightly bent, wearing oversized t-shirt and shorts, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, book, bed, furniture, objects, props",
    },

    "17_cry": {
        "emotion": "Плачет / расстроена",
        "prompt": (
            "anime sticker, 18yo girl Katya crying with big teary eyes, "
            "rubbing eyes with small fists, tears streaming down, "
            "quivering lips, sad pitiful expression, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, happy, furniture, objects, props",
    },

    "18_hearts": {
        "emotion": "Влюблена / сердечки",
        "prompt": (
            "anime sticker, 18yo girl Katya with heart-shaped eyes, "
            "hands clasped together at chest, huge dreamy smile, "
            "floating pink hearts around her, blushing intensely, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, sad, furniture, objects, props",
    },

    "19_whisper": {
        "emotion": "Шёпот / секрет",
        "prompt": (
            "anime sticker, 18yo girl Katya leaning close with finger over lips, "
            "shushing expression, one eye closed in wink, conspiratorial smile, "
            "leaning forward as if sharing a secret, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "20_intrigued": {
        "emotion": "Заинтригована / интересно",
        "prompt": (
            "anime sticker, 18yo girl Katya with one eyebrow raised, "
            "leaning forward slightly, chin resting on one hand, "
            "curious knowing smirk, eyes gleaming with interest, upper body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nsfw, dark background, transparent background, text, watermark, bored, table, furniture, objects, props",
    },

    # ══════════════════════════════════════════
    #  🔴 ВИШЕНКА — горячо, но SFW (8 шт)
    # ══════════════════════════════════════════

    "21_shirt_pull": {
        "emotion": "Дёргает край футболки / «а дальше?»",
        "prompt": (
            "anime sticker, 18yo girl Katya playfully pulling up the hem of her "
            "oversized t-shirt with both hands, showing just a sliver of her toned "
            "stomach, half-lidded eyes looking directly at viewer, mischievous smile, "
            "deep blush, standing pose, wearing short shorts underneath, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "22_towel": {
        "emotion": "В одном полотенце / растерянно-смелая",
        "prompt": (
            "anime sticker, 18yo girl Katya wrapped in a white fluffy towel tucked under arms, "
            "one hand holding towel closed at chest, wet hair clinging to shoulders, "
            "embarrassed but cheeky smile, deep blush, looking slightly away, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, wardrobe malfunction, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "23_sleepy_bed": {
        "emotion": "Сонная / «иди ко мне»",
        "prompt": (
            "anime sticker, 18yo girl Katya lying on her side in mid-air, "
            "head propped on hand, wearing a thin strapped camisole top and pajama "
            "shorts, lazy satisfied smile, messy bedhead hair, beckoning with other hand, "
            "inviting gaze, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, bed, pillow, furniture, objects, props",
    },

    "24_peek_shoulder": {
        "emotion": "Смотрит через плечо / «нравится вид?»",
        "prompt": (
            "anime sticker, 18yo girl Katya looking back over her shoulder at viewer, "
            "back turned, wearing a backless tank top, one hand pulling hair to the "
            "side revealing neck and shoulder, flirty half-smile, slight blush, "
            "standing with weight on one hip, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "25_overwhelmed": {
        "emotion": "Перегрев / «я сейчас сгорю»",
        "prompt": (
            "anime sticker, 18yo girl Katya clutching both hands to her chest, "
            "entire face bright red, steam coming off her head, eyes spiraling, "
            "mouth open in overwhelmed gasp, knees buckling together, "
            "wearing casual crop top and skirt, exaggerated embarrassed expression, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, furniture, objects, props",
    },

    "26_afterglow": {
        "emotion": "Блаженство / нега",
        "prompt": (
            "anime sticker, 18yo girl Katya lying relaxed on her back in mid-air, "
            "lazy satisfied smile, half-closed dreamy eyes, messy hair spread out, "
            "wearing an oversized button-up shirt with rolled-up sleeves, "
            "one arm stretched out, totally relaxed content pose, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, bed, pillow, furniture, objects, props",
    },

    "27_straddle": {
        "emotion": "Доминирует / «я сверху»",
        "prompt": (
            "anime sticker, 18yo girl Katya in a confident kneeling straddle pose, "
            "both hands on her own hips, looking down at viewer with dominant smirk, "
            "one eyebrow raised, wearing fitted tank top and shorts, "
            "hair flowing down, athletic confident pose, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, chair, furniture, objects, props",
    },

    "28_flexible_boast": {
        "emotion": "Стоячий шпагат / «впечатлён?»",
        "prompt": (
            "anime sticker, 18yo girl Katya standing with one leg kicked straight up "
            "next to her head in a standing split, hands on hips, proud smug grin, "
            "wearing sports bra and athletic shorts, looking at viewer challengingly, "
            "impressive gymnast flexibility, full body, "
            "solid bright green chroma key background #00FF00, "
            "chibi proportions, clean shading, no objects"
        ),
        "negative": "multiple girls, nudity, explicit, dark background, transparent background, text, watermark, broken pose, furniture, objects, props",
    },
}

GENERATION_ORDER = [
    "01_greet",
    "02_joy",
    "03_pout",
    "04_thinking",
    "05_wink",
    "06_blush",
    "07_tired",
    "08_angry",
    "09_flirt",
    "10_kiss",
    "11_hug",
    "12_split",
    "13_bridge",
    "14_stretch",
    "15_school",
    "16_reading",
    "17_cry",
    "18_hearts",
    "19_whisper",
    "20_intrigued",
    "21_shirt_pull",
    "22_towel",
    "23_sleepy_bed",
    "24_peek_shoulder",
    "25_overwhelmed",
    "26_afterglow",
    "27_straddle",
    "28_flexible_boast",
]
