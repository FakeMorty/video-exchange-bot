import re

with open("app/main.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('        async with async_session() as session:\n        video = await session.get(Video, int(video_id))', '        async with async_session() as session:\n            video = await session.get(Video, int(video_id))')

with open("app/main.py", "w", encoding="utf-8") as f:
    f.write(text)

with open("app/services.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo"', 'from app.config import PHOTO_UPLOAD_REWARD\n        reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo"')

with open("app/services.py", "w", encoding="utf-8") as f:
    f.write(text)

with open("app/user_handlers.py", "r", encoding="utf-8") as f:
    text = f.read()

old_ref = """
        user.agreed_to_rules = True
            from app.services import process_referral_reward
            if user.referred_by_user_id:
                await process_referral_reward(session, user.id)
"""
new_ref = """
        user.agreed_to_rules = True
        from app.services import process_referral_reward
        if user.referred_by_user_id:
            await process_referral_reward(session, user.id)
"""
text = text.replace(old_ref.strip('\n'), new_ref.strip('\n'))

with open("app/user_handlers.py", "w", encoding="utf-8") as f:
    f.write(text)

