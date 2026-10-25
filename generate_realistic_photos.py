"""Generate realistic studio product packshots for all 18 catalog products."""
import os
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(ROOT, "media", "products")

SIZE = 512

def studio_backdrop(bg_top="#f5f7fa", bg_bottom="#e4e8ec"):
    img = Image.new("RGB", (SIZE, SIZE))
    draw = ImageDraw.Draw(img)
    # subtle studio radial/vertical gradient
    for y in range(SIZE):
        t = y / SIZE
        r1, g1, b1 = int(bg_top[1:3], 16), int(bg_top[3:5], 16), int(bg_top[5:7], 16)
        r2, g2, b2 = int(bg_bottom[1:3], 16), int(bg_bottom[3:5], 16), int(bg_bottom[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b))
    
    # soft floor shadow base
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.ellipse([SIZE * 0.2, SIZE * 0.78, SIZE * 0.8, SIZE * 0.88], fill=(30, 40, 55, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    img.paste(shadow, (0, 0), shadow)
    return img

def render_smartphone():
    img = studio_backdrop("#f8fafc", "#e2e8f0")
    draw = ImageDraw.Draw(img)
    # Phone body
    bx0, by0, bx1, by1 = 150, 70, 362, 430
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=32, fill="#1e293b", outline="#64748b", width=3)
    # Screen bezel
    sx0, sy0, sx1, sy1 = bx0 + 8, by0 + 10, bx1 - 8, by1 - 10
    # Wallpaper gradient
    for y in range(int(sy0), int(sy1)):
        t = (y - sy0) / (sy1 - sy0)
        r = int(14 + (99 - 14) * t)
        g = int(165 + (102 - 165) * t)
        b = int(233 + (241 - 233) * t)
        draw.line([(sx0, y), (sx1, y)], fill=(r, g, b))
    # Screen reflection gloss
    gloss = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gloss)
    gdraw.polygon([(sx0, sy0), (sx1 - 40, sy0), (sx0, sy0 + 180)], fill=(255, 255, 255, 45))
    img.paste(gloss, (0, 0), gloss)
    # Camera punch hole
    draw.ellipse([252, by0 + 16, 260, by0 + 24], fill="#0f172a")
    # Home pill
    draw.rounded_rectangle([226, by1 - 16, 286, by1 - 12], radius=2, fill="#cbd5e1")
    return img

def render_bulb():
    img = studio_backdrop("#fefce8", "#fef08a")
    draw = ImageDraw.Draw(img)
    # Glow effect
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([140, 70, 372, 302], fill=(250, 204, 21, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(30))
    img.paste(glow, (0, 0), glow)
    # Glass bulb dome
    draw.ellipse([160, 90, 352, 282], fill="#fffbeb", outline="#fef08a", width=3)
    draw.polygon([(190, 230), (322, 230), (290, 330), (222, 330)], fill="#fef3c7")
    # Metal screw base
    for i in range(4):
        y = 330 + i * 16
        draw.rounded_rectangle([216, y, 296, y + 14], radius=4, fill="#94a3b8", outline="#475569", width=2)
    draw.ellipse([236, 394, 276, 412], fill="#334155")
    return img

def render_ceiling_fan():
    img = studio_backdrop("#f1f5f9", "#cbd5e1")
    draw = ImageDraw.Draw(img)
    # Motor hub center
    cx, cy = 256, 256
    # 3 blades
    for angle in [0, 120, 240]:
        rad = math.radians(angle)
        dx = math.cos(rad)
        dy = math.sin(rad)
        p1 = (cx + dx * 30 - dy * 18, cy + dy * 30 + dx * 18)
        p2 = (cx + dx * 200 - dy * 32, cy + dy * 200 + dx * 32)
        p3 = (cx + dx * 215, cy + dy * 215)
        p4 = (cx + dx * 200 + dy * 32, cy + dy * 200 - dx * 32)
        p5 = (cx + dx * 30 + dy * 18, cy + dy * 30 - dx * 18)
        draw.polygon([p1, p2, p3, p4, p5], fill="#0284c7", outline="#0369a1", width=2)
    draw.ellipse([cx - 48, cy - 48, cx + 48, cy + 48], fill="#0f172a", outline="#38bdf8", width=4)
    draw.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], fill="#e0f2fe")
    return img

def render_sunglasses(color="#0f172a", lens_color="#1e293b"):
    img = studio_backdrop("#f8fafc", "#f1f5f9")
    draw = ImageDraw.Draw(img)
    # Left lens
    draw.rounded_rectangle([110, 180, 240, 290], radius=24, fill=lens_color, outline=color, width=8)
    # Right lens
    draw.rounded_rectangle([272, 180, 402, 290], radius=24, fill=lens_color, outline=color, width=8)
    # Bridge
    draw.arc([236, 175, 276, 215], start=180, end=360, fill=color, width=8)
    # Browline & Temples
    draw.line([(85, 195), (120, 190)], fill=color, width=8)
    draw.line([(395, 190), (427, 195)], fill=color, width=8)
    # Reflection sheen on lenses
    gloss = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gloss)
    gdraw.line([(140, 195), (200, 275)], fill=(255, 255, 255, 80), width=6)
    gdraw.line([(302, 195), (362, 275)], fill=(255, 255, 255, 80), width=6)
    img.paste(gloss, (0, 0), gloss)
    return img

def render_kurta():
    img = studio_backdrop("#fdf4ff", "#fae8ff")
    draw = ImageDraw.Draw(img)
    # Handloom Kurta folded garment
    draw.polygon([(170, 110), (342, 110), (390, 190), (340, 410), (172, 410), (122, 190)],
                 fill="#9333ea", outline="#6b21a8", width=3)
    # Mandarin collar
    draw.polygon([(216, 110), (296, 110), (280, 170), (232, 170)], fill="#a855f7", outline="#581c87", width=2)
    # Placket & Wooden buttons
    draw.rectangle([248, 170, 264, 300], fill="#c084fc")
    for by in [190, 230, 270]:
        draw.ellipse([251, by, 261, by + 10], fill="#d97706", outline="#78350f", width=1)
    # Fine woven texture lines
    for ly in range(120, 400, 12):
        draw.line([(180, ly), (332, ly)], fill="#7e22ce", width=1)
    return img

def render_tiffin():
    img = studio_backdrop("#f8fafc", "#e2e8f0")
    draw = ImageDraw.Draw(img)
    # 3-tier steel tiffin
    for i, (y0, y1) in enumerate([(270, 360), (180, 265), (95, 175)]):
        draw.rounded_rectangle([150, y0, 362, y1], radius=16, fill="#cbd5e1", outline="#475569", width=3)
        # Specular steel sheen
        draw.line([(190, y0 + 5), (190, y1 - 5)], fill="#ffffff", width=8)
        draw.line([(210, y0 + 5), (210, y1 - 5)], fill="#f1f5f9", width=4)
    # Carrying handle arch
    draw.arc([180, 35, 332, 120], start=180, end=360, fill="#334155", width=8)
    draw.line([(180, 77), (180, 115)], fill="#334155", width=6)
    draw.line([(332, 77), (332, 115)], fill="#334155", width=6)
    return img

def render_mixer_grinder():
    img = studio_backdrop("#f1f5f9", "#e2e8f0")
    draw = ImageDraw.Draw(img)
    # Motor Base
    draw.polygon([(160, 400), (352, 400), (332, 250), (180, 250)], fill="#e2e8f0", outline="#475569", width=3)
    # Control Knob
    draw.ellipse([236, 320, 276, 360], fill="#0284c7", outline="#0369a1", width=3)
    draw.line([(256, 325), (256, 345)], fill="#ffffff", width=4)
    # Stainless Steel Jar
    draw.polygon([(190, 245), (322, 245), (312, 120), (200, 120)], fill="#94a3b8", outline="#334155", width=3)
    # Specular shine
    draw.line([(230, 125), (225, 240)], fill="#ffffff", width=6)
    # Lid & Handle
    draw.ellipse([195, 110, 317, 130], fill="#1e293b")
    draw.arc([310, 140, 360, 220], start=270, end=90, fill="#1e293b", width=8)
    return img

def render_dinner_set():
    img = studio_backdrop("#f8fafc", "#f1f5f9")
    draw = ImageDraw.Draw(img)
    # Main Hard-Anodised Thali
    draw.ellipse([90, 120, 422, 420], fill="#1e293b", outline="#64748b", width=4)
    draw.ellipse([120, 150, 392, 390], fill="#0f172a", outline="#475569", width=2)
    # Specular ring
    draw.arc([130, 160, 382, 380], start=200, end=340, fill="#64748b", width=3)
    # 3 Small Katoris (bowls)
    for cx, cy in [(180, 230), (256, 190), (332, 230)]:
        draw.ellipse([cx - 36, cy - 36, cx + 36, cy + 36], fill="#334155", outline="#94a3b8", width=2)
    # Center tumbler cup
    draw.ellipse([236, 260, 276, 300], fill="#475569", outline="#cbd5e1", width=2)
    return img

def render_cosmetics_bottle(name="toner", liquid="#f43f5e"):
    img = studio_backdrop("#fff1f2", "#ffe4e6")
    draw = ImageDraw.Draw(img)
    # Bottle Body
    draw.rounded_rectangle([180, 150, 332, 400], radius=24, fill=liquid, outline="#be123c", width=3)
    # Glass sheen
    draw.line([(205, 165), (205, 385)], fill="#ffffff", width=8)
    # Label
    draw.rectangle([195, 220, 317, 330], fill="#ffffff", outline="#fecdd3", width=2)
    draw.line([(215, 250), (297, 250)], fill="#e11d48", width=3)
    draw.line([(225, 275), (287, 275)], fill="#9f1239", width=2)
    draw.line([(230, 295), (282, 295)], fill="#fda4af", width=2)
    # Nozzle / Cap
    draw.rounded_rectangle([226, 85, 286, 148], radius=6, fill="#e2e8f0", outline="#64748b", width=2)
    draw.rectangle([216, 140, 296, 150], fill="#cbd5e1")
    return img

def render_neem_facewash():
    img = studio_backdrop("#f0fdf4", "#dcfce7")
    draw = ImageDraw.Draw(img)
    # Cosmetic Tube
    draw.polygon([(185, 110), (327, 110), (312, 370), (200, 370)], fill="#16a34a", outline="#15803d", width=3)
    # Crimp top
    draw.rectangle([180, 95, 332, 110], fill="#14532d")
    # Botanical leaf motif on tube
    draw.ellipse([230, 200, 282, 270], fill="#86efac", outline="#22c55e", width=2)
    # Flip cap base
    draw.rounded_rectangle([216, 370, 296, 415], radius=6, fill="#f8fafc", outline="#64748b", width=2)
    return img

def render_attar():
    img = studio_backdrop("#fefce8", "#fef9c3")
    draw = ImageDraw.Draw(img)
    # Cut Crystal Bottle Body
    draw.polygon([(200, 210), (312, 210), (332, 330), (256, 390), (180, 330)], fill="#eab308", outline="#ca8a04", width=3)
    # Facets
    draw.line([(256, 210), (256, 390)], fill="#fef08a", width=2)
    draw.line([(200, 210), (256, 390)], fill="#fde047", width=1)
    draw.line([(312, 210), (256, 390)], fill="#fde047", width=1)
    # Gold Filigree Dome Cap
    draw.ellipse([216, 95, 296, 185], fill="#d97706", outline="#78350f", width=3)
    draw.ellipse([240, 80, 272, 100], fill="#b45309")
    draw.rectangle([236, 185, 276, 210], fill="#f59e0b", outline="#92400e", width=2)
    return img

def render_cricket_bat():
    img = studio_backdrop("#fefce8", "#fef08a")
    draw = ImageDraw.Draw(img)
    # Willow blade
    draw.polygon([(220, 160), (292, 160), (300, 420), (212, 420)], fill="#fde68a", outline="#d97706", width=3)
    # Bat wood grains
    for gx in [235, 252, 268, 282]:
        draw.line([(gx, 165), (gx, 415)], fill="#f59e0b", width=1)
    # Brand sticker chevron
    draw.polygon([(225, 210), (287, 210), (256, 260)], fill="#dc2626")
    # Handle with rubber spiral grip
    for i in range(7):
        hy = 65 + i * 14
        draw.rounded_rectangle([244, hy, 268, hy + 12], radius=3, fill="#1e293b", outline="#0f172a", width=1)
    return img

def render_helmet():
    img = studio_backdrop("#f8fafc", "#e2e8f0")
    draw = ImageDraw.Draw(img)
    # Aerodynamic shell
    draw.polygon([(140, 270), (160, 150), (260, 110), (370, 150), (390, 240), (330, 290), (180, 290)],
                 fill="#0f172a", outline="#0284c7", width=4)
    # Air vent cutouts
    for vx, vy, w, h in [(200, 160, 35, 20), (256, 145, 40, 22), (315, 160, 35, 20), (230, 210, 45, 18), (285, 210, 45, 18)]:
        draw.ellipse([vx, vy, vx + w, vy + h], fill="#0284c7")
    # Chin strap
    draw.line([(200, 285), (256, 380)], fill="#475569", width=4)
    draw.line([(320, 285), (256, 380)], fill="#475569", width=4)
    return img

def render_skipping_rope():
    img = studio_backdrop("#faf5ff", "#f3e8ff")
    draw = ImageDraw.Draw(img)
    # Coiled cable
    draw.arc([130, 140, 382, 360], start=30, end=330, fill="#9333ea", width=8)
    draw.arc([160, 170, 352, 330], start=40, end=320, fill="#a855f7", width=6)
    # Left foam handle
    draw.rounded_rectangle([100, 170, 130, 300], radius=8, fill="#1e293b", outline="#7e22ce", width=3)
    # Right foam handle
    draw.rounded_rectangle([382, 170, 412, 300], radius=8, fill="#1e293b", outline="#7e22ce", width=3)
    return img

def render_science_kit():
    img = studio_backdrop("#eff6ff", "#dbeafe")
    draw = ImageDraw.Draw(img)
    # Wooden Kit Box
    draw.rounded_rectangle([120, 140, 392, 390], radius=16, fill="#b45309", outline="#78350f", width=4)
    draw.rectangle([140, 160, 372, 370], fill="#fef3c7")
    # Test tubes
    for tx, col in [(170, "#ef4444"), (210, "#3b82f6"), (250, "#10b981")]:
        draw.rounded_rectangle([tx, 190, tx + 24, 310], radius=10, fill=col, outline="#334155", width=2)
        draw.ellipse([tx - 2, 185, tx + 26, 195], fill="#cbd5e1")
    # Glass prism triangle
    draw.polygon([(320, 200), (355, 270), (285, 270)], fill="#67e8f9", outline="#0891b2", width=2)
    return img

def render_ludo():
    img = studio_backdrop("#fff7ed", "#ffedd5")
    draw = ImageDraw.Draw(img)
    # Crafted Wooden Board
    draw.rounded_rectangle([110, 110, 402, 402], radius=18, fill="#b45309", outline="#78350f", width=4)
    draw.rectangle([130, 130, 382, 382], fill="#fef3c7", outline="#92400e", width=2)
    # 4 Quadrants
    draw.rectangle([140, 140, 230, 230], fill="#ef4444")
    draw.rectangle([282, 140, 372, 230], fill="#3b82f6")
    draw.rectangle([140, 282, 230, 372], fill="#eab308")
    draw.rectangle([282, 282, 372, 372], fill="#22c55e")
    # Center diamond
    draw.polygon([(256, 235), (277, 256), (256, 277), (235, 256)], fill="#ffffff")
    return img

def render_puzzle():
    img = studio_backdrop("#f0fdf4", "#dcfce7")
    draw = ImageDraw.Draw(img)
    # Interlocking puzzle tile
    draw.rounded_rectangle([130, 130, 382, 382], radius=20, fill="#f59e0b", outline="#b45309", width=4)
    # Puzzle tabs & blanks
    draw.ellipse([236, 105, 276, 155], fill="#f59e0b", outline="#b45309", width=3)
    draw.ellipse([357, 236, 407, 276], fill="#f59e0b", outline="#b45309", width=3)
    draw.ellipse([236, 357, 276, 407], fill="#dcfce7") # blank
    draw.ellipse([105, 236, 155, 276], fill="#dcfce7") # blank
    # Colorful artwork pattern
    draw.ellipse([200, 200, 312, 312], fill="#3b82f6", outline="#1d4ed8", width=3)
    draw.polygon([(256, 215), (280, 270), (232, 270)], fill="#fde047")
    return img

RENDERERS = {
    "ELE-1001": render_ceiling_fan,
    "ELE-1002": render_smartphone,
    "ELE-1003": render_bulb,
    "FAS-2001": lambda: render_sunglasses("#b45309", "#451a03"),
    "FAS-2002": lambda: render_sunglasses("#0f172a", "#1e293b"),
    "FAS-2003": render_kurta,
    "HOM-3001": render_tiffin,
    "HOM-3002": render_mixer_grinder,
    "HOM-3003": render_dinner_set,
    "BEA-4001": lambda: render_cosmetics_bottle("toner", "#f43f5e"),
    "BEA-4002": render_neem_facewash,
    "BEA-4003": render_attar,
    "SPO-5001": render_cricket_bat,
    "SPO-5002": render_helmet,
    "SPO-5003": render_skipping_rope,
    "BOO-6001": render_science_kit,
    "BOO-6002": render_ludo,
    "BOO-6003": render_puzzle,
}

def main():
    count = 0
    for sku, fn in RENDERERS.items():
        sku_dir = os.path.join(MEDIA_DIR, sku)
        os.makedirs(sku_dir, exist_ok=True)
        img = fn()
        out_path = os.path.join(sku_dir, "main.png")
        img.save(out_path, "PNG")
        count += 1
        print(f"Generated studio packshot for {sku} -> {out_path}")
    print(f"Done! {count} realistic product images created.")

if __name__ == "__main__":
    main()
