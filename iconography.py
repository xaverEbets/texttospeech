"""Icon-Zeichnung fuer Fenster- und Tray-Icons.

Die Formen stammen 1:1 aus den macOS-Menueleisten-SVGs in ``icons/``
(viewBox 18x18). Dadurch nutzen Menueleiste, Tray und Fenster dieselbe
Bildsprache – nur Farbe und Hintergrund unterscheiden sich, weil die
Menueleiste Template-Icons braucht, Tray und Fenster aber auf einem
dunklen Slate-Hintergrund sitzen.
"""

import math

from PIL import Image, ImageDraw

# Geomtrie der SVG-Vorlagen
VIEWBOX = 18.0
SUPERSAMPLE = 4

# Farben (identisch zur Palette in app.py)
ICON_FG = (243, 244, 246, 255)
TRAY_BG = (24, 27, 36, 255)
TRAY_RING = (55, 65, 81, 255)
APP_BG_TOP = (31, 36, 48)
APP_BG_BOTTOM = (18, 21, 30)
APP_RING = (42, 47, 62, 255)

BADGE_COLORS = {
    "loading": (99, 102, 241, 255),      # Indigo
    "idle": (16, 185, 129, 255),         # Gruen
    "recording": (239, 68, 68, 255),     # Rot
    "transcribing": (245, 158, 11, 255), # Gelb/Orange
    "error": (244, 63, 94, 255),         # Rot
}

# Wellenform-Balken (mic-working.svg)
WAVE_BARS = [
    (2.5, 7.5, 2.5, 10.5),
    (5.75, 5.0, 5.75, 13.0),
    (9.0, 2.5, 9.0, 15.5),
    (12.25, 5.0, 12.25, 13.0),
    (15.5, 7.5, 15.5, 10.5),
]

# Mikrofon (mic.svg / mic-recording.svg / mic-error.svg)
MIC_CAPSULE = (6.5, 1.7, 11.5, 11.0, 2.5)  # x1, y1, x2, y2, radius
MIC_ARC = (9.0, 8.6, 5.1)
MIC_STEM = (9.0, 13.7, 9.0, 16.0)
MIC_BASE = (6.4, 16.0, 11.6, 16.0)
MIC_SLASH = (2.5, 2.5, 15.5, 15.5)


class _Pen:
    """Zeichnet die 18x18-SVG-Geometrie skaliert auf eine Leinwand."""

    def __init__(self, draw, scale, color):
        self.draw = draw
        self.scale = scale
        self.color = color

    def _pt(self, x, y):
        return (x * self.scale, y * self.scale)

    def line(self, x1, y1, x2, y2, width=1.4):
        stroke = max(1, int(round(width * self.scale)))
        self.draw.line([self._pt(x1, y1), self._pt(x2, y2)], fill=self.color, width=stroke)
        # SVG nutzt runde Linienenden – PIL nicht, daher als Kreise nachziehen.
        cap = (width * self.scale) / 2
        for x, y in ((x1, y1), (x2, y2)):
            px, py = self._pt(x, y)
            self.draw.ellipse((px - cap, py - cap, px + cap, py + cap), fill=self.color)

    def arc(self, cx, cy, radius, start, end, width=1.4):
        stroke = max(1, int(round(width * self.scale)))
        box = (
            (cx - radius) * self.scale,
            (cy - radius) * self.scale,
            (cx + radius) * self.scale,
            (cy + radius) * self.scale,
        )
        self.draw.arc(box, start=start, end=end, fill=self.color, width=stroke)
        cap = (width * self.scale) / 2
        for angle in (start, end):
            px = (cx + radius * math.cos(math.radians(angle))) * self.scale
            py = (cy + radius * math.sin(math.radians(angle))) * self.scale
            self.draw.ellipse((px - cap, py - cap, px + cap, py + cap), fill=self.color)

    def capsule(self, filled=False, width=1.4):
        x1, y1, x2, y2, radius = MIC_CAPSULE
        box = (x1 * self.scale, y1 * self.scale, x2 * self.scale, y2 * self.scale)
        stroke = max(1, int(round(width * self.scale)))
        self.draw.rounded_rectangle(
            box,
            radius=radius * self.scale,
            fill=self.color if filled else None,
            outline=self.color,
            width=stroke,
        )


def _draw_glyph(pen, state):
    """Zeichnet das Status-Symbol passend zum Menueleisten-SVG."""
    if state in ("loading", "transcribing"):
        for x1, y1, x2, y2 in WAVE_BARS:
            pen.line(x1, y1, x2, y2, width=1.6)
        return

    pen.capsule(filled=(state == "recording"))
    pen.arc(*MIC_ARC, start=0, end=180)
    pen.line(*MIC_STEM)
    pen.line(*MIC_BASE)

    if state == "error":
        pen.line(*MIC_SLASH)


def _glyph_layer(state, box, color=ICON_FG):
    """Rendert das Symbol in eine transparente, quadratische Ebene."""
    n = max(1, int(round(box * SUPERSAMPLE)))
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    _draw_glyph(_Pen(ImageDraw.Draw(img), n / VIEWBOX, color), state)
    return img.resize((max(1, int(round(box))),) * 2, Image.LANCZOS)


def tray_icon(state="idle", size=64):
    """Tray-Icon: dunkler Kreis + Symbol + farbiger Status-Punkt."""
    scale = SUPERSAMPLE
    n = size * scale
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = round(size * 0.0625) * scale
    draw.ellipse(
        (margin, margin, n - margin, n - margin),
        fill=TRAY_BG,
        outline=TRAY_RING,
        width=max(1, round(size * 0.03125)) * scale,
    )

    glyph_box = size * 0.56
    glyph = _glyph_layer(state, glyph_box * scale)
    offset = ((n - glyph.width) // 2 - scale, (n - glyph.height) // 2 - 2 * scale)
    img.alpha_composite(glyph, (max(0, offset[0]), max(0, offset[1])))

    badge = (
        round(size * 0.656) * scale,
        round(size * 0.656) * scale,
        round(size * 0.938) * scale,
        round(size * 0.938) * scale,
    )
    draw.ellipse(
        badge,
        fill=BADGE_COLORS.get(state, BADGE_COLORS["idle"]),
        outline=TRAY_BG,
        width=max(1, round(size * 0.047)) * scale,
    )
    return img.resize((size, size), Image.LANCZOS)


def app_icon(size=256):
    """Fenster-/App-Icon: abgerundetes Slate-Quadrat mit Mikrofon-Symbol."""
    scale = SUPERSAMPLE
    n = size * scale
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    # Dezenter Verlauf von oben nach unten
    gradient = Image.new("RGB", (1, n))
    pixels = []
    for y in range(n):
        t = y / max(1, n - 1)
        pixels.append(
            tuple(
                round(APP_BG_TOP[i] + (APP_BG_BOTTOM[i] - APP_BG_TOP[i]) * t) for i in range(3)
            )
        )
    gradient.putdata(pixels)
    gradient = gradient.resize((n, n))

    mask = Image.new("L", (n, n), 0)
    radius = size * 0.225 * scale
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=radius, fill=255)
    img.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, n - 1, n - 1),
        radius=radius,
        outline=APP_RING,
        width=max(1, round(size * 0.0125)) * scale,
    )

    glyph_box = size * 0.58 * scale
    glyph = _glyph_layer("idle", glyph_box)
    img.alpha_composite(
        glyph,
        ((n - glyph.width) // 2, (n - glyph.height) // 2),
    )
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    from pathlib import Path

    out = Path(__file__).resolve().parent / "icons" / "app.png"
    app_icon(256).save(out)
    print(f"Fenster-Icon geschrieben: {out}")
