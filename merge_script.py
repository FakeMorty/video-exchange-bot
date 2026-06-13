import re

with open("app/admin_handlers_backup.py", "r", encoding="utf-8") as f:
    admin_code = f.read()

with open("app/admin_events_handlers.py", "r", encoding="utf-8") as f:
    events_code = f.read()

# Add missing imports to admin_code
imports_to_add = "import asyncio\nfrom html import escape"
if "import asyncio" not in admin_code:
    admin_code = admin_code.replace("import os", "import os\nimport asyncio")
if "from html import escape" not in admin_code:
    admin_code = admin_code.replace("import os", "import os\nfrom html import escape")

# Add missing models to imports
admin_code = re.sub(r"TrustedUploader\s*\)", "TrustedUploader, Event, ActiveSale, OfferParticipation)", admin_code)
# Add missing services to imports
admin_code = re.sub(r"get_recent_feedback,\s*\)", "get_recent_feedback, get_active_sale, get_active_events)", admin_code)

# Extract EventCreationState and append it
event_state = """
class EventCreationState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_discount = State()
    waiting_duration = State()
    waiting_applies = State()
    waiting_image = State()      # опциональная картинка
    confirm = State()
"""
if "class EventCreationState" not in admin_code:
    admin_code = admin_code.replace("class TrustedUploaderState(StatesGroup):", event_state + "\n\nclass TrustedUploaderState(StatesGroup):")

# Extract handlers and helpers from events_code (skip imports)
# Keep only functions and decorated methods
events_handlers = []
lines = events_code.split("\n")
skip = True
for line in lines:
    if line.startswith("def ") or line.startswith("@router."):
        skip = False
    if not skip:
        events_handlers.append(line)

# Append to the end
admin_code += "\n\n" + "\n".join(events_handlers)

with open("app/admin_handlers.py", "w", encoding="utf-8") as f:
    f.write(admin_code)
