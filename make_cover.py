#!/usr/bin/env python3
"""
小红书封面图生成器（本地 PIL）
风格：渐变背景 + 大字标题 + 关键要点，模仿小红书爆款排版
尺寸：1080×1440（3:4 竖版）
"""

import hashlib
import re
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COVER_DIR = Path(__file__).parent / "covers"
COVER_DIR.mkdir(exist_ok=True)

# CJK fonts: try system fonts in order
def _find_cjk_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""

def _find_cjk_font_light() -> str:
    candidates = [
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""

FONT_BOLD  = _find_cjk_font()
FONT_LIGHT = _find_cjk_font_light()

W, H = 1080, 1440

# 5 种渐变主题：(顶部色, 底部色, 强调色, 文字色)
THEMES = [
    ((180, 20,  20),  (100, 8,   8),   (255, 220, 50),  (255, 255, 255)),  # 深红+金
    ((15,  55,  150), (8,   30,  90),  (80,  200, 255), (255, 255, 255)),  # 深蓝+青
    ((20,  100, 80),  (8,   55,  40),  (160, 255, 180), (255, 255, 255)),  # 墨绿+薄荷
    ((80,  20,  160), (40,  8,   90),  (255, 200, 80),  (255, 255, 255)),  # 深紫+金
    ((180, 80,  10),  (100, 40,  5),   (255, 240, 120), (255, 255, 255)),  # 深橙+黄
]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _draw_gradient(img: Image.Image, top: tuple, bottom: tuple) -> None:
    """逐行填充渐变背景"""
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def _wrap_text(draw: ImageDraw.Draw, text: str, font, fill, x: int, y: int,
               max_w: int, line_gap: int = 10) -> int:
    """自动换行绘制文字，返回最终 y 坐标（基于实际行高）"""
    char_w = font.size
    chars_per = max(1, (max_w) // char_w)
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            continue
        if len(para) <= chars_per:
            lines.append(para)
        else:
            lines.extend(textwrap.wrap(para, width=chars_per))
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        # 用 getbbox 取实际行高，更准确
        try:
            bbox = font.getbbox(line)
            line_h = bbox[3] - bbox[1]
        except Exception:
            line_h = font.size
        y += line_h + line_gap
    return y


def extract_key_points(content: str, max_points: int = 3) -> list[str]:
    """从文章正文提取 2-3 个关键要点，优先选有实质内容的短句"""
    points = []

    # 过滤黑名单词（这些词出现在要点里没意义）
    BLACKLIST = re.compile(
        r'^(适用|结果|操作|当前|经验公式|黄金法则|注意|例如|比如|举例|说明|\d+[%％元万].*$)'
    )

    def is_valid(s: str) -> bool:
        s = s.strip()
        if len(s) < 5 or len(s) > 14:
            return False
        if re.match(r'^[\d\s\-=→+]+$', s):  # 纯数字/符号
            return False
        if BLACKLIST.match(s):
            return False
        if s in points:
            return False
        return True

    def clean(s: str) -> str:
        """去掉粗体标记、首尾冒号、空格"""
        s = re.sub(r'\*+', '', s)
        s = s.strip().lstrip('：:·・').rstrip('：:。')
        return s

    # 1. 优先取 ## / ### 标题（去掉 emoji 和纯序号前缀）
    h_matches = re.findall(r'^(#{2,3})\s+(.+)$', content, re.MULTILINE)
    for hashes, m in h_matches:
        m = re.sub(r'^[❌✅⚠️💡🔥⚡️]+\s*', '', m)
        m = re.sub(r'^\d+[\.、]\s*', '', m)
        # ### 三级标题如有冒号，只取冒号后面部分（去掉「情况一：」这类前缀）
        if len(hashes) == 3 and '：' in m:
            m = m.split('：', 1)[1]
        m = clean(m)
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 2. 取 **粗体**，排除「表现」「为什么」「正确做法」这类标签词
    LABEL_WORDS = re.compile(r'^(表现|为什么|正确做法|建议|注意|结果|操作|当前)')
    bold_matches = re.findall(r'\*\*([^*]+)\*\*', content)
    for m in bold_matches:
        m = clean(m)
        if LABEL_WORDS.match(m):
            continue
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    # 3. 兜底：取数字列表项
    num_matches = re.findall(r'^\d+[.、]\s+(.+)$', content, re.MULTILINE)
    for m in num_matches:
        m = clean(m)
        if is_valid(m):
            points.append(m)
        if len(points) >= max_points:
            return points

    return points[:max_points]


def generate_cover(title: str, content: str = "", index: int = 0) -> str:
    """
    生成封面图，返回本地文件绝对路径（字符串）。
    相同 title+content 命中缓存直接返回。
    """
    cache_key = hashlib.md5(f"{title}{content[:200]}".encode()).hexdigest()[:10]
    out_path = COVER_DIR / f"cover_{cache_key}.jpg"
    if out_path.exists():
        return str(out_path)

    top_c, bot_c, accent, text_c = THEMES[index % len(THEMES)]

    img = Image.new("RGB", (W, H), top_c)
    _draw_gradient(img, top_c, bot_c)
    draw = ImageDraw.Draw(img)

    # ── 半透明顶部暗条（增强可读性）──────────────────────
    overlay = Image.new("RGBA", (W, 180), (0, 0, 0, 60))
    img.paste(Image.new("RGB", (W, 180), (0, 0, 0)), (0, 0),
              Image.new("L", (W, 180), 60))

    # ── 品牌名 ───────────────────────────────────────────
    brand_font = _font(FONT_LIGHT, 58)
    draw.text((72, 64), "期权研究室", font=brand_font, fill=(*accent, 255))

    # ── 品牌下装饰线 ─────────────────────────────────────
    draw.rectangle([72, 130, 320, 138], fill=accent)

    # ── 主标题 ───────────────────────────────────────────
    # 清除 emoji 以免 PIL 渲染异常，保留文字
    clean_title = re.sub(r'[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s：:·\-—()（）【】%！!？?]', '', title)
    clean_title = clean_title.strip()

    title_font_size = 112 if len(clean_title) <= 10 else 96 if len(clean_title) <= 14 else 82
    title_font = _font(FONT_BOLD, title_font_size)
    title_y = _wrap_text(draw, clean_title, title_font, text_c,
                          72, 450, W - 144, line_gap=16)
    title_y += 80

    # ── 分隔点 ───────────────────────────────────────────
    for i in range(3):
        draw.ellipse([72 + i * 24, title_y, 84 + i * 24, title_y + 12], fill=accent)
    title_y += 48

    # ── 关键要点 ─────────────────────────────────────────
    if content:
        points = extract_key_points(content, max_points=3)
    else:
        points = []

    if points:
        pt_font = _font(FONT_LIGHT, 64)
        for pt in points:
            pt_text = f">> {pt}"
            draw.text((72, title_y), pt_text, font=pt_font, fill=text_c)
            try:
                line_h = pt_font.getbbox(pt_text)[3] - pt_font.getbbox(pt_text)[1]
            except Exception:
                line_h = pt_font.size
            title_y += line_h + 36
    else:
        # 没提取到要点时，显示副标题占位
        sub_font = _font(FONT_LIGHT, 68)
        sub = "美股期权深度分析"
        draw.text((72, title_y), sub, font=sub_font, fill=(*accent,))

    # ── 底部渐变暗条 ─────────────────────────────────────
    for y in range(H - 160, H):
        alpha = int(180 * (y - (H - 160)) / 160)
        r = max(0, top_c[0] - 40)
        g = max(0, top_c[1] - 40)
        b = max(0, top_c[2] - 40)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # ── 底部 slogan ──────────────────────────────────────
    slogan_font = _font(FONT_LIGHT, 50)
    draw.text((72, H - 100), "美股 · 期权 · 财富自由", font=slogan_font,
              fill=(255, 255, 255, 180))

    # ── 右下角期数 ──────────────────────────────────────
    num_font = _font(FONT_BOLD, 54)
    num_str = f"#{index + 1:02d}"
    draw.text((W - 110, H - 98), num_str, font=num_font, fill=accent)

    img.save(str(out_path), "JPEG", quality=93)
    return str(out_path)


if __name__ == "__main__":
    # 读一篇真实文章测试
    sample_content = """
## LEAPS实战教程：3步选出最优期权

## 第一步：选到期时间
**原则：至少买1年后的**

- 2027年1月（推荐）：时间够长，时间价值衰减慢
- 2026年9月：不推荐，太近

## 第二步：选执行价
- ITM（实值）：权利金贵，但安全
- ATM（平值）：平衡之选
- OTM（虚值）：权利金便宜，杠杆高

## 第三步：看权利金
**成本比率 < 15% → 便宜**
**成本比率 > 25% → 贵了**
"""
    path = generate_cover("LEAPS实战教程", sample_content, index=0)
    print(f"生成封面图: {path}")
    import subprocess
    subprocess.run(["open", path])  # macOS 预览

    path2 = generate_cover("特斯拉FSD订阅制期权机会", "**FSD订阅费带来稳定现金流**\n- 买入TSLA LEAPS\n- 等待催化剂\n**执行价$400**", index=1)
    print(f"生成封面图2: {path2}")
    subprocess.run(["open", path2])
