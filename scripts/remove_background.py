import os
from PIL import Image

def remove_white_background(input_path: str, output_path: str):
    """
    Удаляет внешний белый фон у стикера с белой обводкой, делая его прозрачным.
    Использует алгоритм заливки (flood fill) из углов, чтобы не повредить белый контур внутри самого стикера!
    """
    try:
        img = Image.open(input_path).convert("RGBA")
        width, height = img.size
        visited = set()
        queue = []
        
        # Добавляем угловые и граничные точки (0, y), (width-1, y), (x, 0), (x, height-1)
        for y in range(height):
            queue.append((0, y))
            queue.append((width - 1, y))
            visited.add((0, y))
            visited.add((width - 1, y))
        for x in range(width):
            queue.append((x, 0))
            queue.append((x, height - 1))
            visited.add((x, 0))
            visited.add((x, height - 1))
            
        # Запускаем обход в ширину (BFS) для заливки прозрачностью
        while queue:
            cx, cy = queue.pop(0)
            
            # Получаем цвет пикселя
            r, g, b, a = img.getpixel((cx, cy))
            
            # Если цвет близок к чистому белому (R, G, B > 240), то убираем его (делаем прозрачным)
            if r > 240 and g > 240 and b > 240:
                img.putpixel((cx, cy), (0, 0, 0, 0)) # Делаем прозрачным
                
                # Добавляем соседей
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        if (nx, ny) not in visited:
                            visited.add((nx, ny))
                            queue.append((nx, ny))
                            
        img.save(output_path, "PNG")
        print(f"✅ Фон успешно удален для {input_path}!")
    except Exception as e:
        print(f"❌ Ошибка при обработке {input_path}: {e}")

# Пройдемся по всем сгенерированным стикерам в папках sanya/, sofa/ и katya/
for folder in ["video-exchange-bot/sanya", "video-exchange-bot/sofa", "video-exchange-bot/katya"]:
    if not os.path.exists(folder):
        folder = folder.replace("video-exchange-bot/", "")
        
    if os.path.exists(folder):
        print(f"Обработка папки {folder}...")
        for file in os.listdir(folder):
            if file.endswith(".png") and not file.endswith("_resized.png"):
                full_path = os.path.join(folder, file)
                # Перезаписываем тот же файл прозрачным!
                remove_white_background(full_path, full_path)
