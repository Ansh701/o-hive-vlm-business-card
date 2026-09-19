from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

OFFICIAL_FIELDS = (
    "first_name",
    "last_name",
    "job_title",
    "company",
    "location",
    "phone_number",
    "email",
)

CARD_DEFINITIONS: dict[str, dict[str, Any]] = {
    "clean-horizontal": {
        "expected": {
            "first_name": "Mina",
            "last_name": "Patel",
            "job_title": "Product Designer",
            "company": "Northstar Studio",
            "location": "Bengaluru, India",
            "phone_number": "+91 98765 43210",
            "email": "mina@northstar.example",
        }
    },
    "vertical": {
        "expected": {
            "first_name": "Kenji",
            "last_name": "Watanabe",
            "job_title": "Principal Consultant",
            "company": "Harbor Grid",
            "location": "Tokyo, Japan",
            "phone_number": "+81 3 5550 0123",
            "email": "kenji@harborgrid.example",
        }
    },
    "low-contrast": {
        "expected": {
            "first_name": "Imani",
            "last_name": "Okafor",
            "job_title": "Research Lead",
            "company": "Pale Field Labs",
            "location": "Lagos, Nigeria",
            "phone_number": "+234 802 555 0194",
            "email": "imani@palefield.example",
        }
    },
    "with-logo": {
        "expected": {
            "first_name": "Elias",
            "last_name": "Berg",
            "job_title": "Founder & CEO",
            "company": "Fjordline Systems",
            "location": "Oslo, Norway",
            "phone_number": "+47 22 55 01 84",
            "email": "elias@fjordline.example",
        }
    },
    "phone-format": {
        "expected": {
            "first_name": "Priya",
            "last_name": "Nair",
            "job_title": "Partnerships Manager",
            "company": "Orbit Commons",
            "location": "Kochi, India",
            "phone_number": "(0484) 555 0138",
            "email": "priya@orbitcommons.example",
        }
    },
    "missing-email": {
        "expected": {
            "first_name": "Thomas",
            "last_name": "Reed",
            "job_title": "Operations Director",
            "company": "Cedar & Row",
            "location": "Bristol, United Kingdom",
            "phone_number": "+44 (0)117 555 0182",
            "email": None,
        }
    },
    "missing-location": {
        "expected": {
            "first_name": "Amina",
            "last_name": "Diallo",
            "job_title": "Account Executive",
            "company": "Kora Works",
            "location": None,
            "phone_number": "+221 33 555 01 27",
            "email": "amina@koraworks.example",
        }
    },
    "complex-name": {
        "expected": {
            "first_name": "María José",
            "last_name": "Carreño Quiñones",
            "job_title": "Global Programs Lead",
            "company": "Lumen Sur",
            "location": "Bogotá, Colombia",
            "phone_number": "+57 601 555 0142",
            "email": "maria.jose@lumensur.example",
        }
    },
    "slightly-rotated": {
        "expected": {
            "first_name": "Luca",
            "last_name": "Bianchi",
            "job_title": "Creative Technologist",
            "company": "Forma Uno",
            "location": "Milano, Italy",
            "phone_number": "+39 02 5550 0164",
            "email": "luca@formauno.example",
        }
    },
}

VARIANTS = tuple(CARD_DEFINITIONS)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["seguisb.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for directory in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
        for name in names + (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]):
            path = directory / name
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start: int,
    *,
    bold: bool,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = start
    while size > 20:
        font = _font(size, bold=bold)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
        size -= 2
    return _font(20, bold=bold)


def _contact_lines(expected: Mapping[str, str | None]) -> list[str]:
    values = [expected["location"], expected["phone_number"], expected["email"]]
    return [value for value in values if value]


def _horizontal_card(
    expected: Mapping[str, str | None],
    *,
    background: str = "#F8F5EE",
    ink: str = "#173F3A",
    accent: str = "#C74723",
    logo: bool = False,
) -> Image.Image:
    image = Image.new("RGB", (1200, 700), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((34, 34, 1166, 666), radius=34, outline=accent, width=3)
    draw.rectangle((34, 34, 82, 666), fill=accent)
    if logo:
        draw.ellipse((910, 82, 1080, 252), outline=accent, width=16)
        draw.arc((950, 122, 1120, 292), 120, 300, fill=ink, width=12)
    company = expected["company"] or ""
    name = " ".join(filter(None, [expected["first_name"], expected["last_name"]]))
    draw.text((132, 95), company.upper(), font=_font(29, bold=True), fill=accent)
    draw.text((132, 210), name, font=_fit_text(draw, name, 890, 70, bold=True), fill=ink)
    draw.text((136, 310), expected["job_title"] or "", font=_font(34), fill=ink)
    draw.line((136, 392, 1045, 392), fill=accent, width=3)
    for index, line in enumerate(_contact_lines(expected)):
        draw.text((136, 438 + index * 58), line, font=_font(27), fill=ink)
    return image


def _vertical_card(expected: Mapping[str, str | None]) -> Image.Image:
    image = Image.new("RGB", (760, 1200), "#102B30")
    draw = ImageDraw.Draw(image)
    cream = "#F5EFE2"
    gold = "#E4B960"
    draw.rectangle((54, 54, 706, 1146), outline=gold, width=3)
    draw.ellipse((286, 120, 474, 308), outline=gold, width=10)
    draw.line((380, 145, 380, 283), fill=gold, width=8)
    draw.line((311, 214, 449, 214), fill=gold, width=8)
    company = expected["company"] or ""
    name = " ".join(filter(None, [expected["first_name"], expected["last_name"]]))
    draw.text((380, 358), company.upper(), anchor="ma", font=_font(26, bold=True), fill=gold)
    draw.multiline_text(
        (380, 460),
        name,
        anchor="ma",
        align="center",
        spacing=9,
        font=_fit_text(draw, name, 590, 60, bold=True),
        fill=cream,
    )
    draw.text((380, 610), expected["job_title"] or "", anchor="ma", font=_font(29), fill=cream)
    draw.line((150, 705, 610, 705), fill=gold, width=2)
    for index, line in enumerate(_contact_lines(expected)):
        draw.text((380, 770 + index * 67), line, anchor="ma", font=_font(24), fill=cream)
    return image


def _low_contrast_card(expected: Mapping[str, str | None]) -> Image.Image:
    image = Image.new("RGB", (1200, 700), "#E7E2D7")
    draw = ImageDraw.Draw(image)
    ink = "#96948E"
    name = " ".join(filter(None, [expected["first_name"], expected["last_name"]]))
    draw.text((100, 80), "PALE FIELD LABS", font=_font(30, bold=True), fill="#A9A59C")
    draw.text((100, 220), name, font=_font(68, bold=True), fill=ink)
    draw.text((103, 318), expected["job_title"] or "", font=_font(33), fill=ink)
    for index, line in enumerate(_contact_lines(expected)):
        draw.text((103, 440 + index * 52), line, font=_font(26), fill=ink)
    return image


def _rotated_card(expected: Mapping[str, str | None]) -> Image.Image:
    card = _horizontal_card(expected, background="#FCF8EF", ink="#191C1B", accent="#176A62")
    rotated = card.rotate(4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="#D8D3CA")
    canvas = Image.new("RGB", (1400, 900), "#D8D3CA")
    position = (
        (canvas.width - rotated.width) // 2,
        (canvas.height - rotated.height) // 2,
    )
    canvas.paste(rotated, position)
    return canvas


def generate_cards(output_directory: Path) -> dict[str, dict[str, Any]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, Any]] = {}
    for variant, definition in CARD_DEFINITIONS.items():
        expected = definition["expected"]
        if variant == "vertical":
            image = _vertical_card(expected)
        elif variant == "low-contrast":
            image = _low_contrast_card(expected)
        elif variant == "with-logo":
            image = _horizontal_card(expected, logo=True, background="#EEF4F1")
        elif variant == "slightly-rotated":
            image = _rotated_card(expected)
        else:
            image = _horizontal_card(expected)
        filename = f"{variant}.png"
        image.save(output_directory / filename, format="PNG", optimize=True)
        manifest[variant] = {
            "filename": filename,
            "expected": dict(expected),
            "synthetic": True,
        }
    return manifest


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "evaluation" / "cards"
    manifest = generate_cards(output)
    ground_truth = root / "evaluation" / "ground-truth.json"
    ground_truth.parent.mkdir(parents=True, exist_ok=True)
    ground_truth.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(manifest)} synthetic cards in {output}")


if __name__ == "__main__":
    main()
