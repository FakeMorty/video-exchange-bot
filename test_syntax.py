import ast

def check_syntax(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()
    try:
        ast.parse(source)
        print("Syntax OK!")
    except Exception as e:
        print(f"Syntax ERROR: {e}")

check_syntax("app/user_handlers.py")
