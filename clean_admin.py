import sys

# Define all needed handlers
with open("app/admin_handlers.py", "r") as f:
    lines = f.readlines()

output = []
seen_functions = set()
skip_mode = False

for line in lines:
    # Detect function start
    if line.startswith("async def ") or line.startswith("def "):
        name = line.split("(")[0].split()[-1]
        if name in seen_functions:
            skip_mode = True
        else:
            seen_functions.add(name)
            skip_mode = False
    
    if not skip_mode:
        output.append(line)

with open("app/admin_handlers_clean.py", "w") as f:
    f.writelines(output)
