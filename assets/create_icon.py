#!/usr/bin/env python3
"""
Generate application icon for KVM Serial application.
Creates a simple icon representing KVM (keyboard/video/mouse) over serial connection.
"""

from PIL import Image, ImageDraw, ImageFont
import os


def create_icon():
    """Create a simple KVM icon with serial port representation"""

    # Create base image (1024x1024 for high quality)
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Color scheme: Custom palette
    # 6b0f1f - deep red/burgundy
    # 41658a - steel blue
    # eef5db - off-white/cream

    burgundy = (107, 15, 31)  # Deep red/burgundy
    steel_blue = (65, 101, 138)  # Steel blue
    cream = (238, 245, 219)  # Off-white/cream

    # Draw monitor/screen (upper portion - represents Video)
    # Monitor extends beyond the circle bounds at the top
    screen_top = size * 0.08
    screen_height = size * 0.6
    screen_width = size * 0.9
    screen_left = (size - screen_width) // 2

    # Monitor bezel/frame
    bezel_thickness = 2
    draw.rounded_rectangle(
        [
            screen_left - bezel_thickness,
            screen_top,
            screen_left + screen_width + bezel_thickness,
            screen_top + screen_height + bezel_thickness,
        ],
        radius=60,
        fill=burgundy,
        outline=None,
        width=8,
    )

    # Screen center
    glow_margin = 25
    draw.rounded_rectangle(
        [
            screen_left + glow_margin,
            screen_top + glow_margin,
            screen_left + screen_width - glow_margin,
            screen_top + screen_height - glow_margin,
        ],
        radius=45,
        fill=cream,
    )

    # Add "K V M" text to the monitor
    try:
        # Try to use a nice font if available
        font_size = int(size * 0.25)  # 1/4 of canvas size
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size, index=1)  # bold
    except:
        # Fallback to default font
        font = ImageFont.load_default()

    text = "K V M"
    # Calculate text position to center it on the screen
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    text_x = screen_left + (screen_width - text_width) / 2
    text_y = screen_top + (screen_height - text_height) / 2

    # Draw text centered on the monitor
    draw.text((text_x, text_y), text, fill=burgundy, font=font)

    # Draw keyboard representation (lower portion - represents Keyboard/Mouse input)
    keyboard_top = screen_top + screen_height + 120
    key_spacing = 20
    num_keys = 6
    key_size = screen_width / num_keys - key_spacing

    keyboard_width = (key_size * num_keys) + (key_spacing * (num_keys - 1))
    keyboard_left = (size - keyboard_width) // 2

    # Draw simplified keyboard keys
    for i in range(num_keys):
        x = keyboard_left + i * (key_size + key_spacing)
        draw.rounded_rectangle(
            [x, keyboard_top, x + key_size, keyboard_top + key_size],
            radius=24,
            fill=cream,
            outline=burgundy,
            width=12,
        )

    # Draw serial connection symbol (lines connecting screen to keyboard)
    # Two parallel lines representing serial data flow
    arrow_spacing = screen_width // 4
    arrow_width = 32
    conn_left_x = size // 2 + arrow_spacing
    conn_right_x = size // 2 - arrow_spacing
    conn_top = screen_top + screen_height - 150
    conn_bottom = keyboard_top + 40

    # Add small arrows indicating data flow direction
    arrow_y = conn_top - (conn_top - conn_bottom) // 2
    arrow_size_x = 40
    arrow_size_y = 80
    arrow_offset = 60
    margin = 80

    # Serial connection lines (parallel lines = data transmission)
    # Left
    draw.line(
        [(conn_right_x, conn_top + arrow_offset), (conn_right_x, conn_bottom + arrow_offset)],
        fill=cream,
        width=arrow_width + margin,
    )
    # Right
    draw.line(
        [(conn_left_x, conn_top), (conn_left_x, conn_bottom)],
        fill=cream,
        width=arrow_width + margin,
    )

    draw.line(
        [(conn_right_x, conn_top + arrow_offset), (conn_right_x, conn_bottom + arrow_offset)],
        fill=steel_blue,
        width=arrow_width,
    )
    # Right
    draw.line(
        [(conn_left_x, conn_top), (conn_left_x, conn_bottom)], fill=steel_blue, width=arrow_width
    )

    # Up arrow on left line
    draw.polygon(
        [
            (conn_right_x, conn_top),
            (conn_right_x - arrow_size_x, arrow_y - arrow_size_y),
            (conn_right_x + arrow_size_x, arrow_y - arrow_size_y),
        ],
        fill=steel_blue,
    )

    # Down arrow on right line
    draw.polygon(
        [  # x , y
            (conn_left_x, conn_bottom + arrow_offset),
            (conn_left_x + arrow_size_x, arrow_y + arrow_size_y + arrow_offset),
            (conn_left_x - arrow_size_x, arrow_y + arrow_size_y + arrow_offset),
        ],
        fill=steel_blue,
    )

    return img


def save_icon_formats(img, base_path):
    """Save icon in different formats for different platforms"""

    # Save PNG at various sizes
    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    png_images = []

    for size in sizes:
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        png_path = os.path.join(base_path, f"icon_{size}.png")
        resized.save(png_path, "PNG")
        png_images.append(resized)
        print(f"Created: {png_path}")

    # Save main PNG
    main_png = os.path.join(base_path, "icon.png")
    img.save(main_png, "PNG")
    print(f"Created: {main_png}")

    # Save ICO for Windows (multiple sizes embedded)
    ico_path = os.path.join(base_path, "icon.ico")
    # ICO format supports multiple sizes - include common Windows sizes
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_images = [img.resize(size, Image.Resampling.LANCZOS) for size in ico_sizes]
    ico_images[0].save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"Created: {ico_path}")

    # For macOS ICNS, we need iconutil (macOS only) or save PNG at required sizes
    # PyInstaller can work with .png and will convert to .icns on macOS
    # But let's create the proper sizes for ICNS
    icns_base = os.path.join(base_path, "icon.iconset")
    os.makedirs(icns_base, exist_ok=True)

    # macOS icon sizes (iconset format)
    mac_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    for filename, size in mac_sizes.items():
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        icon_path = os.path.join(icns_base, filename)
        resized.save(icon_path, "PNG")

    print(f"Created iconset: {icns_base}")
    print("To create .icns on macOS, run: iconutil -c icns icon.iconset")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("Generating KVM Serial application icon...")
    icon = create_icon()

    print("\nSaving icon formats...")
    save_icon_formats(icon, script_dir)

    print("\nIcon generation complete!")
    print("Files created in:", script_dir)
