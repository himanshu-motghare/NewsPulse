"""Pure-Pillow graphics (no Tk needed): gradients and the NewsPulse logo."""
from __future__ import annotations

from PIL import Image, ImageDraw

PURPLE = "#7C5CFF"
BLUE = "#3B82F6"


def _rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def gradient_image(width: int, height: int, start: str = PURPLE, end: str = BLUE,
                   radius: int = 0) -> Image.Image:
    """Horizontal purple -> blue gradient (optionally with rounded corners)."""
    c1, c2 = _rgb(start), _rgb(end)
    img = Image.new("RGBA", (max(1, width), max(1, height)))
    draw = ImageDraw.Draw(img)
    for x in range(img.width):
        t = x / max(1, img.width - 1)
        draw.line([(x, 0), (x, img.height)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)) + (255,))
    if radius:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
        img.putalpha(mask)
    return img


def draw_logo(size: int = 64) -> Image.Image:
    """The NewsPulse logo: gradient rounded square with a white pulse line."""
    scale = 4
    big = size * scale
    img = gradient_image(big, big, PURPLE, BLUE, radius=big // 4)
    draw = ImageDraw.Draw(img)
    pts = [(0.16, 0.55), (0.34, 0.55), (0.43, 0.28), (0.55, 0.76), (0.64, 0.45), (0.71, 0.55), (0.84, 0.55)]
    draw.line([(x * big, y * big) for x, y in pts], fill="white", width=max(2, big // 11), joint="curve")
    return img.resize((size, size), Image.LANCZOS)
