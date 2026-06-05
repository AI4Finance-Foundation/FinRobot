"""Build the full Tauri icon set from the chosen design (B: robot head+shoulders
on a blue->violet squircle). Produces a 1024 master with macOS-standard margin,
then every PNG size the bundle references, plus icon.icns (via iconutil) and a
multi-size icon.ico.

Run from desktop/scripts/. Writes the .iconset + 1024 master here; the final
assets are written straight into ../src-tauri/icons/.
"""
import os
import subprocess
from PIL import Image, ImageDraw

LANCZOS = Image.Resampling.LANCZOS
ICONS_DIR = os.path.abspath("../src-tauri/icons")

robot = Image.open("robot-shot.png").convert("RGBA")
robot = robot.crop(robot.getbbox())
rw, rh = robot.size
head = robot.crop((0, 0, rw, int(rh * 0.46)))
head = head.crop(head.getbbox())


def diag_gradient(size, c0, c1):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / size
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
        d.line([(0, y), (size, y)], fill=col + (255,))
    return img


def master(size=1024, margin_frac=0.085):
    """Squircle tile inset by `margin_frac` on each side (macOS Dock convention),
    robot composited on top."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inset = int(size * margin_frac)
    tile = size - 2 * inset

    grad = diag_gradient(tile, (59, 130, 246), (139, 92, 246))
    mask = Image.new("L", (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, tile - 1, tile - 1], radius=int(tile * 0.235), fill=255
    )
    canvas.paste(grad, (inset, inset), mask)

    # place head: 0.74 of the tile width, slightly below center
    target_w = int(tile * 0.74)
    fg = head.resize((target_w, int(head.size[1] * target_w / head.size[0])), LANCZOS)
    x = inset + (tile - target_w) // 2
    y = inset + int((tile - fg.size[1]) / 2 + tile * 0.04)
    # clip robot to the tile so nothing spills past the squircle
    tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tmp.paste(fg, (x, y), fg)
    tile_mask_full = Image.new("L", (size, size), 0)
    ImageDraw.Draw(tile_mask_full).rounded_rectangle(
        [inset, inset, size - inset - 1, size - inset - 1],
        radius=int(tile * 0.235), fill=255,
    )
    canvas.paste(tmp, (0, 0), Image.composite(tmp.getchannel("A"), Image.new("L", (size, size), 0), tile_mask_full))
    return canvas


m = master(1024)
m.save("icon-master-1024.png")
print("master built")

# --- flat PNGs referenced by tauri.conf bundle.icon + the Windows Store logos
png_targets = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
    "Square30x30Logo.png": 30,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89,
    "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
}
for name, sz in png_targets.items():
    m.resize((sz, sz), LANCZOS).save(os.path.join(ICONS_DIR, name))
print("png set written")

# --- icns via iconutil
iconset = "FinRobot.iconset"
os.makedirs(iconset, exist_ok=True)
icns_map = [
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
]
for sz, fname in icns_map:
    m.resize((sz, sz), LANCZOS).save(os.path.join(iconset, fname))
subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(ICONS_DIR, "icon.icns")], check=True)
print("icns written")

# --- multi-size ico
m.save(os.path.join(ICONS_DIR, "icon.ico"),
       sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ico written")
print("ALL DONE ->", ICONS_DIR)
