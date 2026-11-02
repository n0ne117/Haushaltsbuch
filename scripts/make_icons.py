"""Generate the PWA icons in app/static/icons/ (dev tool; needs Pillow, which WeasyPrint pulls in).

    .venv/bin/python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
BLUE = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)
LINE = (37, 99, 235, 110)
S = 1024  # draw large, then downscale for smooth edges


def draw(rounded: bool) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle((0, 0, S - 1, S - 1), radius=220, fill=BLUE)
    else:  # maskable: full bleed, content stays inside the central safe zone
        d.rectangle((0, 0, S, S), fill=BLUE)

    # Open book: two pages meeting at the spine, inside the maskable safe zone (~60 %).
    left = [(262, 330), (496, 380), (496, 720), (262, 670)]
    right = [(762, 330), (528, 380), (528, 720), (762, 670)]
    d.polygon(left, fill=WHITE)
    d.polygon(right, fill=WHITE)

    # Ledger lines on both pages.
    for i in range(5):
        y = 420 + i * 52
        d.line([(300, y - 22), (462, y + 12)], fill=LINE, width=14)
        d.line([(562, y + 12), (724, y - 22)], fill=LINE, width=14)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rounded, maskable = draw(True), draw(False)
    for size in (192, 512):
        rounded.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png", optimize=True)
    maskable.resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png", optimize=True)
    maskable.resize((180, 180), Image.LANCZOS).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    rounded.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png", optimize=True)


if __name__ == "__main__":
    main()
