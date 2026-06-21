"""
Промпты для генерации стикерпака Кати.

КАК ИСПОЛЬЗОВАТЬ:
1. Сгенерируй первый стикер (например #1 Привет) вручную с нужным стилем
2. Для каждого следующего — используй img2img с референсом первого,
   меняя только позу и эмоцию
3. Размер: 512x512, PNG с прозрачным фоном
4. Обрежь фон и добавь белую обводку 2-3px

ПЕРСОНАЖ (описание для всех промптов):
18yo anime girl, Katya, long light-brown hair, blue eyes, slim athletic figure,
school uniform (white blouse + navy skirt) for SFW / casual outfit for NSFW,
cheerful and flirty personality

СТИЛЬ (добавлять в каждый промпт):
anime sticker style, white outline, chibi proportions, simple clean shading,
transparent background, full body or upper body, expressive face, 512x512
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
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "02_joy": {
        "emotion": "Радость / восторг",
        "prompt": (
            "anime sticker, 18yo girl Katya jumping with joy, both arms raised up, "
            "huge sparkling smile, closed happy eyes, hair flying up, "
            "wearing school uniform, full body, dynamic pose, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "03_pout": {
        "emotion": "Обида / надула губки",
        "prompt": (
            "anime sticker, 18yo girl Katya pouting with puffed cheeks, "
            "looking up from below with big sad puppy eyes, arms crossed, "
            "slight blush, hurt expression, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, smile",
    },

    "04_thinking": {
        "emotion": "Задумчивость",
        "prompt": (
            "anime sticker, 18yo girl Katya thinking with index finger touching her lips, "
            "eyes looking to the side, slightly tilted head, curious expression, "
            "one hand on hip, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "05_wink": {
        "emotion": "Подмигивание / хитрость",
        "prompt": (
            "anime sticker, 18yo girl Katya winking one eye with a sly smile, "
            "peace sign near her face, playful flirty expression, "
            "leaning forward slightly, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "06_blush": {
        "emotion": "Стыд / застенчивость",
        "prompt": (
            "anime sticker, 18yo girl Katya hiding face behind both hands but peeking through fingers, "
            "deep red blush on cheeks, embarrassed shy expression, "
            "slightly hunched shoulders, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, confident",
    },

    "07_tired": {
        "emotion": "Усталость / ЕГЭ достало",
        "prompt": (
            "anime sticker, 18yo girl Katya lying face-down on desk with books, "
            "half-closed eyes, exhausted expression, one hand dangling off the desk, "
            "messy hair, school papers scattered around, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, energetic",
    },

    "08_angry": {
        "emotion": "Злость / обиделась",
        "prompt": (
            "anime sticker, 18yo girl Katya with angry puffed cheeks and furrowed brows, "
            "arms crossed tightly, glaring from below, small fang showing, "
            "anime anger vein on forehead, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, smiling",
    },

    # ══════════════════════════════════════════
    #  🟡 ВАЖНЫЕ (12 шт)
    # ══════════════════════════════════════════

    "09_flirt": {
        "emotion": "Флирт / соблазн",
        "prompt": (
            "anime sticker, 18yo girl Katya biting her lower lip with half-lidded eyes, "
            "one finger tracing her collar, hair tossed to one side, "
            "seductive knowing smile, slight blush, wearing slightly unbuttoned blouse, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, explicit nsfw, dark background, text, watermark",
    },

    "10_kiss": {
        "emotion": "Поцелуй",
        "prompt": (
            "anime sticker, 18yo girl Katya sending a kiss with pursed lips, "
            "eyes closed, making a heart shape with fingers, pink blush, "
            "small floating hearts around her, upper body, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "11_hug": {
        "emotion": "Объятия / обнимашки",
        "prompt": (
            "anime sticker, 18yo girl Katya hugging a big pillow tightly, "
            "cheek pressed against it, soft smile, closed eyes, content expression, "
            "legs curled up on a bed, wearing cozy oversized shirt, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "12_split": {
        "emotion": "Гимнастика — шпагат",
        "prompt": (
            "anime sticker, 18yo girl Katya doing a perfect full split on the floor, "
            "arms raised triumphantly, big proud smile, wearing gymnastics leotard, "
            "legs extended perfectly straight, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, broken pose",
    },

    "13_bridge": {
        "emotion": "Гимнастика — мостик",
        "prompt": (
            "anime sticker, 18yo girl Katya doing a backbend bridge, "
            "hands and feet on floor, arched back, face upside-down smiling playfully, "
            "wearing gymnastics leotard, impressive flexibility, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, broken pose",
    },

    "14_stretch": {
        "emotion": "Растяжка",
        "prompt": (
            "anime sticker, 18yo girl Katya sitting on floor stretching, "
            "one leg extended forward reaching toward toes, other leg bent, "
            "focused expression, slightly straining, wearing sports top and shorts, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "15_school": {
        "emotion": "В школе / скучает",
        "prompt": (
            "anime sticker, 18yo girl Katya sitting at school desk bored, "
            "head propped on hand, chin resting on palm, deadpan expression, "
            "blank stare, pencil in other hand, wearing school uniform, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, happy",
    },

    "16_reading": {
        "emotion": "Читает / учится",
        "prompt": (
            "anime sticker, 18yo girl Katya lying on stomach on bed reading a book, "
            "legs kicked up behind crossed at ankles, concentrating with slight frown, "
            "glasses on nose, wearing oversized t-shirt, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "17_cry": {
        "emotion": "Плачет / расстроена",
        "prompt": (
            "anime sticker, 18yo girl Katya crying with big teary eyes, "
            "rubbing eyes with small fists, tears streaming down, "
            "quivering lips, sad pitiful expression, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, happy",
    },

    "18_hearts": {
        "emotion": "Сердечки / влюблена",
        "prompt": (
            "anime sticker, 18yo girl Katya with heart-shaped eyes, "
            "hands clasped together at chest, huge dreamy smile, "
            "floating pink hearts around her, blushing intensely, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, sad",
    },

    "19_whisper": {
        "emotion": "Шёпот / секрет",
        "prompt": (
            "anime sticker, 18yo girl Katya leaning close with finger over lips, "
            "shushing expression, one eye closed in wink, conspiratorial smile, "
            "leaning forward as if sharing a secret, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark",
    },

    "20_intrigued": {
        "emotion": "Заинтригована / интересно",
        "prompt": (
            "anime sticker, 18yo girl Katya with one eyebrow raised, "
            "leaning forward with chin on hands, curious knowing smirk, "
            "eyes gleaming with interest, upper body over a table, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, nsfw, dark background, text, watermark, bored",
    },

    # ══════════════════════════════════════════
    #  🔴 ВИШЕНКА 18+ (8 шт)
    # ══════════════════════════════════════════

    "21_seduce": {
        "emotion": "Соблазн / раздевается",
        "prompt": (
            "anime sticker, 18yo girl Katya pulling her blouse up with teeth, "
            "showing toned stomach, half-lidded eyes looking directly at viewer, "
            "playful blush, slim athletic waist visible, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark",
    },

    "22_nocover": {
        "emotion": "Без одежды / смущённо-дерзкая",
        "prompt": (
            "anime sticker, 18yo girl Katya with arms crossed covering chest, "
            "embarrassed but cheeky smile, deep blush, looking slightly away, "
            "bare shoulders and collarbone visible, teasing expression, "
            "white outline, transparent background, chibi proportions, clean shading, SFW composition"
        ),
        "negative": "multiple girls, explicit nipples, dark background, text, watermark",
    },

    "23_bed_side": {
        "emotion": "В постели — на боку",
        "prompt": (
            "anime sticker, 18yo girl Katya lying on her side on a bed, "
            "head propped on hand, sheet loosely draped over hip, "
            "lazy satisfied smile, messy hair, bare shoulder, inviting gaze, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark",
    },

    "24_allfours": {
        "emotion": "В постели — на четвереньках",
        "prompt": (
            "anime sticker, 18yo girl Katya on all fours looking back over shoulder, "
            "flushed face, arched back, sheet tangled around legs, "
            "embarrassed but willing expression, athletic flexible body, "
            "white outline, transparent background, chibi proportions, clean shading, SFW composition"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark",
    },

    "25_orgasm": {
        "emotion": "Оргазм / кульминация",
        "prompt": (
            "anime sticker, 18yo girl Katya with eyes rolled back, mouth open, "
            "whole body arched, face completely flushed red, fingers gripping sheets, "
            "ecstasy expression, sweat drops, messy hair, "
            "white outline, transparent background, chibi proportions, clean shading, SFW composition"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark",
    },

    "26_afterglow": {
        "emotion": "После / блаженство",
        "prompt": (
            "anime sticker, 18yo girl Katya lying peacefully on pillow, "
            "lazy satisfied smile, half-closed dreamy eyes, messy hair everywhere, "
            "sheet pulled up to chest, one arm dangling off bed, relaxed pose, "
            "white outline, transparent background, chibi proportions, clean shading"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark",
    },

    "27_cowgirl": {
        "emotion": "Верхом / контроль",
        "prompt": (
            "anime sticker, 18yo girl Katya straddling position, "
            "both hands on hips, confident dominant smirk, looking down at viewer, "
            "hair flowing down, wearing just an unbuttoned shirt, athletic figure, "
            "white outline, transparent background, chibi proportions, clean shading, SFW composition"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark, submissive",
    },

    "28_flexible_bed": {
        "emotion": "Гибкость в постели",
        "prompt": (
            "anime sticker, 18yo girl Katya with one leg behind her head, "
            "guilty-proud smile, blushing intensely, surprised at her own flexibility, "
            "in bed with sheets, athletic gymnast body, "
            "white outline, transparent background, chibi proportions, clean shading, SFW composition"
        ),
        "negative": "multiple girls, explicit nudity, dark background, text, watermark, broken pose",
    },
}

# Список в порядке генерации
GENERATION_ORDER = [
    # 🟢 Обязательные
    "01_greet",
    "02_joy",
    "03_pout",
    "04_thinking",
    "05_wink",
    "06_blush",
    "07_tired",
    "08_angry",
    # 🟡 Важные
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
    # 🔴 Вишенка
    "21_seduce",
    "22_nocover",
    "23_bed_side",
    "24_allfours",
    "25_orgasm",
    "26_afterglow",
    "27_cowgirl",
    "28_flexible_bed",
]
