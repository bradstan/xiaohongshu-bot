#!/usr/bin/env python3
"""
小红书封面图生成器（本地 PIL）—— 将宇宙能量账号专用

模板：
  yuzhou  — 照片底图 + 标题文字叠加
            ① 有底图模式：照片底图 + 底部渐变遮罩 + 思源宋体白色标题 + 品牌名
            ② 纯渐变模式：柔和渐变背景 + 主题色文字（fallback，无底图时使用）

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

    # ── 文字叠加层 ─────────────────────────────────────────────────────────────
    if use_photo:
        # 照片底图：底部叠渐变遮罩，让白色文字可读
        img_rgba = img.convert("RGBA")
        overlay  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        odraw    = ImageDraw.Draw(overlay)
        mask_start = int(H * 0.42)
        for y in range(mask_start, H):
            t = (y - mask_start) / (H - mask_start)
            a = int(190 * (t ** 0.6))
            odraw.line([(0, y), (W, y)], fill=(0, 0, 0, a))
        img = Image.alpha_composite(img_rgba, overlay).convert("RGB")
        title_rgb = (255, 252, 245)   # 暖白
        brand_rgb = (220, 215, 205)   # 浅米白
    else:
        # 纯渐变 fallback：用主题色
        title_rgb = grad_title_c
        brand_rgb = grad_sub_c

    draw = ImageDraw.Draw(img)

    # 标题
    clean_title = re.sub(
        r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s：:·\-—()（）【】%！!？?，。、]',
        '', title
    )
    fs         = 90 if len(clean_title) <= 9 else 76 if len(clean_title) <= 14 else 64
    title_font = _font(FONT_TITLE, fs)
    MAX_W      = W - 130
    lines      = _pixel_wrap(clean_title, title_font, MAX_W)
    lh         = _line_h(title_font, lines[0] if lines else "测") + 22
    total_h    = lh * len(lines)

    # 文字区块底边固定在距底部 160px，向上延伸
    text_y = H - 160 - total_h

    for line in lines:
        bbox = title_font.getbbox(line)
        lw   = bbox[2] - bbox[0]
        x    = (W - lw) // 2
        draw.text((x, text_y), line, font=title_font, fill=title_rgb)
        text_y += lh

    # 装饰细线
    line_y = text_y + 18
    draw.line([(W // 2 - 55, line_y), (W // 2 + 55, line_y)],
              fill=title_rgb, width=2)

    # 品牌名（右下角）
    brand_font = _font(FONT_BRAND, 42)
    draw.text((W - 68, H - 88), "SS心灵疗愈所",
              font=brand_font, fill=brand_rgb)

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
