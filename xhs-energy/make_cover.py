#!/usr/bin/env python3
"""
小红书封面图生成器（本地 PIL）—— 将宇宙能量账号专用

模板：
  yuzhou  — 纯底图风（无文字）
            ① 有底图模式：照片底图，不叠文字
            ② 纯渐变模式：柔和渐变背景（fallback，无底图时使用）

底图放置：~/xiaohongshu-yuzhou/backgrounds/（jpg/png 均可，自动循环）
尺寸：1080×1440（3:4 竖版）
"""

import hashlib
import random
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

COVER_DIR       = Path("/Users/jarvis/xiaohongshu-bot/xhs-energy/covers")
BACKGROUNDS_DIR = Path("/Users/jarvis/xiaohongshu-bot/xhs-energy/backgrounds")
COVER_DIR.mkdir(exist_ok=True)

# 思源宋体（Adobe 出品，线条对比强，专业衬线）
FONT_TITLE = "/Users/jarvis/xiaohongshu-bot/xhs-energy/fonts/SourceHanSerifCN-Regular.ttf"
FONT_BRAND = "/System/Library/Fonts/STHeiti Light.ttc"

W, H = 1080, 1440

# ─── 渐变配色（无底图时 fallback）────────────────────────────────────────────
# (背景顶色, 背景底色, 主标题色, 副文字色, 光晕色)
YUZHOU_THEMES = [
    ((248, 243, 255), (220, 210, 248), (80,  55, 120), (140, 110, 180), (252, 250, 255)),
    ((255, 248, 245), (242, 220, 215), (130, 65,  75), (180, 110, 120), (255, 252, 250)),
    ((255, 252, 245), (238, 218, 200), (110, 70,  60), (165, 115, 95),  (255, 253, 248)),
    ((248, 255, 252), (215, 238, 232), (55,  100, 100),(100, 150, 145), (250, 255, 253)),
    ((255, 251, 246), (248, 228, 210), (140, 85,  55), (190, 130, 100), (255, 252, 248)),
    ((245, 242, 255), (200, 188, 240), (60,  40,  110),(100, 80,  160), (248, 247, 255)),
    ((248, 250, 255), (215, 225, 245), (65,  85,  130),(100, 125, 175), (250, 252, 255)),
    ((255, 250, 250), (240, 218, 222), (120, 60,  80), (170, 110, 130), (255, 252, 252)),
]


# ─── 工具函数 ─────────────────────────────────────────────────────────────────
def _font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()


def _draw_gradient(img: Image.Image, top: tuple, bottom: tuple) -> None:
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def _line_h(font, text: str) -> int:
    try:
        bb = font.getbbox(text)
        return bb[3] - bb[1]
    except Exception:
        return font.size


def _pixel_wrap(text: str, font, max_px: int) -> list[str]:
    """按像素宽度拆行，正确处理中英混排。"""
    result, cur = [], ""
    for ch in text:
        test = cur + ch
        w = font.getbbox(test)[2] - font.getbbox(test)[0]
        if w <= max_px:
            cur = test
        else:
            if cur:
                result.append(cur)
            cur = ch
    if cur:
        result.append(cur)
    return result


def _load_background(index: int) -> Image.Image | None:
    """从 backgrounds/ 加载底图（按 index 循环），调整为 1080×1440 中心裁切。"""
    if not BACKGROUNDS_DIR.exists():
        return None
    imgs = sorted(BACKGROUNDS_DIR.glob("*.jpg")) + \
           sorted(BACKGROUNDS_DIR.glob("*.jpeg")) + \
           sorted(BACKGROUNDS_DIR.glob("*.png"))
    if not imgs:
        return None
    path = imgs[index % len(imgs)]
    try:
        bg = Image.open(path).convert("RGB")
        bg_r = bg.width / bg.height
        tg_r = W / H
        if bg_r > tg_r:
            new_h = H
            new_w = int(H * bg_r)
        else:
            new_w = W
            new_h = int(W / bg_r)
        bg = bg.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - W) // 2
        top  = (new_h - H) // 2
        return bg.crop((left, top, left + W, top + H))
    except Exception:
        return None


def _draw_soft_blob(img: Image.Image, cx: int, cy: int,
                    r: int, color: tuple, alpha: int) -> None:
    """渐变模式专用：在 img 上叠加一个柔边半透明圆形光晕。"""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw   = ImageDraw.Draw(overlay)
    layers  = 20
    for i in range(layers, 0, -1):
        ratio  = i / layers
        radius = int(r * ratio)
        a      = int(alpha * (1 - ratio ** 1.8))
        odraw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*color, a)
        )
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))


# ─── 主渲染函数 ───────────────────────────────────────────────────────────────
def _render_yuzhou(title: str, content: str, index: int) -> Image.Image:
    i_theme = index % len(YUZHOU_THEMES)
    top_c, bot_c, grad_title_c, grad_sub_c, blob_c = YUZHOU_THEMES[i_theme]

    bg_img    = _load_background(index)
    use_photo = bg_img is not None

    # ── 背景层 ─────────────────────────────────────────────────────────────────
    if use_photo:
        img = bg_img.copy()
    else:
        img = Image.new("RGB", (W, H), top_c)
        _draw_gradient(img, top_c, bot_c)
        rng = random.Random(index * 1337)
        for cx_r, cy_r, radius, alpha in [
            (0.72, 0.15, 320, 50),
            (0.18, 0.55, 260, 40),
            (0.60, 0.75, 220, 35),
        ]:
            jx = rng.randint(-60, 60)
            jy = rng.randint(-60, 60)
            _draw_soft_blob(img,
                            int(W * cx_r) + jx,
                            int(H * cy_r) + jy,
                            radius, blob_c, alpha)

    # 不叠加文字，直接返回背景图
    return img.convert("RGB")


# ─── 对外接口 ─────────────────────────────────────────────────────────────────
def generate_cover(title: str, content: str = "",
                   index: int = 0, category: str = "yuzhou") -> str:
    """
    生成封面图，返回本地文件绝对路径。相同参数命中缓存直接返回。

    backgrounds/ 有图 → 照片底图 + 明朝体白色文字
    backgrounds/ 无图 → 纯渐变（fallback）
    """
    bg_imgs = []
    if BACKGROUNDS_DIR.exists():
        bg_imgs = sorted(BACKGROUNDS_DIR.glob("*.jpg")) + \
                  sorted(BACKGROUNDS_DIR.glob("*.png"))
    bg_fingerprint = str(len(bg_imgs))

    cache_key = hashlib.md5(
        f"{category}{title}{content[:200]}{bg_fingerprint}".encode()
    ).hexdigest()[:10]
    out_path = COVER_DIR / f"cover_{cache_key}.jpg"
    if out_path.exists():
        return str(out_path)

    # 背景图按标题哈希选取：同一篇文章固定对应同一张背景，不同文章自动分散
    bg_index = int(cache_key, 16) % max(len(bg_imgs), 1) if bg_imgs else index
    img = _render_yuzhou(title, content, bg_index)
    img.save(str(out_path), "JPEG", quality=94)
    return str(out_path)


if __name__ == "__main__":
    import subprocess

    titles = [
        ("读懂潜意识，才算真正开始掌控自己", ""),
        ("真正的显化，是先成为那个已经拥有的人", ""),
        ("每一次真正的冥想，都在从细胞层面改变你", ""),
    ]

    for i, (t, c) in enumerate(titles):
        path = generate_cover(t, c, index=i, category="yuzhou")
        print(f"封面 {i+1}: {path}")
        subprocess.run(["open", path])
