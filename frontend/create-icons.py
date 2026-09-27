"""
生成 SubAI Translator 应用图标
"""
from PIL import Image, ImageDraw, ImageFont
import os

# 创建图标目录
icon_dir = os.path.join(os.path.dirname(__file__), 'src-tauri', 'icons')
os.makedirs(icon_dir, exist_ok=True)

# 创建 256x256 图标
size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 绘制圆角矩形背景
corner_radius = 50
points = [
    (corner_radius, 0),
    (size - corner_radius, 0),
    (size, corner_radius),
    (size, size - corner_radius),
    (size - corner_radius, size),
    (corner_radius, size),
    (0, size - corner_radius),
    (0, corner_radius),
]

# 绘制渐变背景（使用蓝色）
for y in range(size):
    for x in range(size):
        # 检查点是否在圆角矩形内
        in_rect = corner_radius <= x <= size - corner_radius and corner_radius <= y <= size - corner_radius
        in_corner = False
        
        # 四个圆角
        corners = [
            ((corner_radius, corner_radius), (x - corner_radius)**2 + (y - corner_radius)**2 <= corner_radius**2),
            ((size - corner_radius, corner_radius), (x - (size - corner_radius))**2 + (y - corner_radius)**2 <= corner_radius**2),
            ((corner_radius, size - corner_radius), (x - corner_radius)**2 + (y - (size - corner_radius))**2 <= corner_radius**2),
            ((size - corner_radius, size - corner_radius), (x - (size - corner_radius))**2 + (y - (size - corner_radius))**2 <= corner_radius**2),
        ]
        in_corner = any(corners[i][1] for i in range(4))
        
        if in_rect or in_corner:
            # 简单的蓝色背景
            draw.point((x, y), fill=(59, 130, 246, 255))

# 绘制文字 "S"
try:
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 140)
except:
    font = ImageFont.load_default()

# 计算文字位置
bbox = draw.textbbox((0, 0), 'S', font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]
text_x = (size - text_width) // 2
text_y = (size - text_height) // 2 - bbox[1]

draw.text((text_x, text_y), 'S', fill=(255, 255, 255, 255), font=font)

# 保存不同尺寸的图标
icons = {
    '32x32.png': 32,
    '128x128.png': 128,
    '128x128@2x.png': 256,
    'icon.ico': None,  # 特殊处理
}

for filename, icon_size in icons.items():
    if filename == 'icon.ico':
        # 保存为 PNG，Windows 会自动转换
        img.save(os.path.join(icon_dir, 'icon.png'))
        print(f'✓ Created icon.png (256x256)')
    else:
        scaled_img = img.resize((icon_size, icon_size), Image.LANCZOS)
        scaled_img.save(os.path.join(icon_dir, filename))
        print(f'✓ Created {filename} ({icon_size}x{icon_size})')

print('\nIcons generated successfully!')
print(f'Icon directory: {icon_dir}')