import re

with open("app/admin_handlers.py", "r", encoding="utf-8") as f:
    code = f.read()

# Restore from backup first to be clean
import subprocess
subprocess.run(["git", "checkout", "6a865cd", "app/admin_handlers.py"])

with open("app/admin_handlers.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix imports only at the top of the file
# Look for the first occurrence of import os
code = code.replace("import os", "import os\nimport asyncio\nfrom html import escape", 1)

code = re.sub(r"TrustedUploader\s*\)", "TrustedUploader, Event, ActiveSale, OfferParticipation)", code)
code = re.sub(r"get_recent_feedback,\s*\)", "get_recent_feedback, get_active_sale, get_active_events)", code)

# Fix helpers
helper_pattern = r"def is_super_admin.*?async def _safe_edit.*?await callback\.message\.answer\(text, \*\*kwargs\)"
code = re.sub(helper_pattern, "from app.utils.admin import check_admin, is_super_admin, _safe_edit", code, flags=re.DOTALL)

# Add state
event_state = """
class EventCreationState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_discount = State()
    waiting_duration = State()
    waiting_applies = State()
    waiting_image = State()
    confirm = State()
"""
if "class EventCreationState" not in code:
    code = code.replace("class TrustedUploaderState(StatesGroup):", event_state + "\n\nclass TrustedUploaderState(StatesGroup):")

# Re-read Events code
with open("app/admin_events_handlers.py", "r", encoding="utf-8") as f:
    events_code = f.read()

events_handlers = []
lines = events_code.split("\n")
skip = True
for line in lines:
    if line.startswith("def ") or line.startswith("@router."):
        skip = False
    if not skip:
        events_handlers.append(line)

code += "\n\n" + "\n".join(events_handlers)

with open("app/admin_handlers.py", "w", encoding="utf-8") as f:
    f.write(code)
