"""Render the demo's receipt photos (Spec §17 step 3). Fictional sample data, clearly marked.

uv run python data/seed/receipts/make_receipts.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def receipt(
    path: Path, merchant: str, lines: list[tuple[str, str]], total: str, date: str, order: str
) -> None:
    w, h = 720, 980
    img = Image.new("RGB", (w, h), (250, 249, 244))
    d = ImageDraw.Draw(img)
    y = 50
    d.text((w // 2, y), merchant.upper(), font=font(44, True), fill=(20, 20, 20), anchor="mt")
    y += 64
    d.text((w // 2, y), "ORDER CONFIRMATION", font=font(24), fill=(60, 60, 60), anchor="mt")
    y += 60
    for label, value in [
        ("Order", order),
        ("Date", date),
        ("Ship to", "A. Rivera, San Francisco CA"),
    ]:
        d.text((60, y), f"{label}:", font=font(24), fill=(40, 40, 40))
        d.text((w - 60, y), value, font=font(24), fill=(40, 40, 40), anchor="ra")
        y += 38
    y += 20
    d.line((50, y, w - 50, y), fill=(120, 120, 120), width=2)
    y += 28
    for item, price in lines:
        d.text((60, y), item, font=font(23), fill=(30, 30, 30))
        d.text((w - 60, y), price, font=font(23), fill=(30, 30, 30), anchor="ra")
        y += 40
    y += 10
    d.line((50, y, w - 50, y), fill=(120, 120, 120), width=2)
    y += 30
    d.text((60, y), "TOTAL (USD)", font=font(34, True), fill=(10, 10, 10))
    d.text((w - 60, y), total, font=font(34, True), fill=(10, 10, 10), anchor="ra")
    y += 80
    d.text((w // 2, y), "Paid with Visa ending 4417", font=font(22), fill=(60, 60, 60), anchor="mt")
    d.text(
        (w // 2, h - 40),
        "SAMPLE RECEIPT - SUBPOENA.AI DEMO DATA",
        font=font(16),
        fill=(150, 150, 150),
        anchor="mb",
    )
    # A little tilt and blur so it looks like a phone photo.
    photo = img.rotate(-2.5, expand=True, fillcolor=(205, 200, 190)).filter(
        ImageFilter.GaussianBlur(0.6)
    )
    photo.convert("RGB").save(path, "JPEG", quality=85)


if __name__ == "__main__":
    receipt(
        HERE / "autozone_order.jpg",
        "AutoZone",
        [
            ("Bilstein B6 shocks (x4)", "$1,180.00"),
            ("Brembo brake kit, front", "$1,436.67"),
            ("E36 coilover set", "$1,550.00"),
            ("Sales tax", "$333.33"),
        ],
        "$4,500.00",
        "2026-10-09",
        "AZ-5521-88412",
    )
    receipt(
        HERE / "electronics_order.jpg",
        "Best Buy",
        [("USB-C cable", "$19.99"), ("Phone case", "$34.99"), ("Sales tax", "$4.39")],
        "$59.37",
        "2026-10-02",
        "BBY01-77310",
    )
    print("wrote", *sorted(p.name for p in HERE.glob("*.jpg")))
