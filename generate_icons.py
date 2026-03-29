from PIL import Image, ImageDraw
import os

SIZES = [72, 96, 128, 144, 152, 180, 192, 512]
OUTPUT_DIR = "static/icons"

os.makedirs(OUTPUT_DIR, exist_ok=True)

for size in SIZES:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size, size], radius=size//5, fill=(79, 70, 229, 255))
    path = os.path.join(OUTPUT_DIR, f"icon-{size}.png")
    img.save(path)
    print(f"✅ icon-{size}.png")

print("Done!")