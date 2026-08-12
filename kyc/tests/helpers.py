import io
from PIL import Image, ImageDraw, ImageFont


def create_test_image_bytes(
    width: int = 800,
    height: int = 600,
    color: str = "white",
    format_name: str = "JPEG",
    text_content: str = "",
) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    draw = ImageDraw.Draw(img)

    if text_content:
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
        draw.text((30, 30), text_content, fill="black", font=font)

    # Add facial oval feature simulation
    draw.ellipse(
        (width // 3, height // 4, 2 * width // 3, 3 * height // 4),
        fill="rgb(220, 180, 150)",
        outline="black",
    )
    # Eyes
    draw.ellipse((width // 3 + 40, height // 3, width // 3 + 70, height // 3 + 30), fill="black")
    draw.ellipse(
        (2 * width // 3 - 70, height // 3, 2 * width // 3 - 40, height // 3 + 30), fill="black"
    )

    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


def create_document_image_bytes(
    width: int = 800,
    height: int = 600,
    format_name: str = "JPEG",
) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 20)
        small_font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Header band
    draw.rectangle([0, 0, width, 60], fill="navy")
    draw.text((20, 15), "REPUBLIC OF UGANDA", fill="white", font=font)
    draw.text((20, 40), "NATIONAL IDENTITY CARD", fill="white", font=small_font)

    # Photo placeholder
    photo_x, photo_y, photo_x2, photo_y2 = width - 220, 80, width - 20, 260
    draw.rectangle([photo_x, photo_y, photo_x2, photo_y2], outline="black", width=2)
    draw.ellipse(
        (photo_x + 30, photo_y + 30, photo_x2 - 30, photo_y2 - 30),
        fill="rgb(220, 180, 150)",
        outline="black",
    )

    # Details
    draw.text((20, 80), "Full Name: TEST USER", fill="black", font=font)
    draw.text((20, 120), "Date of Birth: 1990-01-01", fill="black", font=font)
    draw.text((20, 160), "Sex: M", fill="black", font=font)
    draw.text((20, 200), "ID Number: CM9001011234567", fill="black", font=font)
    draw.text((20, 240), "Expiry: 2030-01-01", fill="black", font=font)

    # Bottom decorative line
    draw.rectangle([0, height - 40, width, height], fill="navy")

    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


def create_selfie_image_bytes(
    width: int = 600,
    height: int = 600,
    format_name: str = "JPEG",
) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Face oval
    draw.ellipse(
        (width // 4, height // 4, 3 * width // 4, 3 * height // 4),
        fill="rgb(220, 180, 150)",
        outline="black",
    )
    # Eyes
    draw.ellipse((width // 3, height // 3, width // 3 + 50, height // 3 + 30), fill="black")
    draw.ellipse((2 * width // 3 - 50, height // 3, 2 * width // 3, height // 3 + 30), fill="black")
    # Mouth
    draw.arc(
        (width // 3, height // 2, 2 * width // 3, 3 * height // 2), 0, 180, fill="black", width=3
    )

    buf = io.BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()
