"""OpenAI image enhancement helpers for Divide Scanned Images."""

from __future__ import annotations

import base64
import json
import os
import struct
import urllib.error
import urllib.request
import uuid
import zlib

OPENAI_IMAGE_EDIT_URL = "https://api.openai.com/v1/images/edits"
OPENAI_IMAGE_MODEL = "gpt-image-1"
ENHANCE_PROMPT = (
    "Restore and improve this scanned vintage family photo while preserving the original composition, people, "
    "clothing, expressions, pose, and background. Correct fading, haze, low contrast, color cast, dust, scratches, "
    "and scan artifacts. Improve sharpness and facial clarity naturally, without making the image look modern, "
    "artificial, airbrushed, or like a new photo. Keep the film-photo look, realistic grain, realistic lighting, "
    "and the same framing. Do not change identities, do not add or remove people, do not invent new objects, "
    "and do not alter clothing designs or text except to make existing details clearer."
)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def rgba_to_png_bytes(rgba: bytes | bytearray | memoryview, width: int, height: int) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    expected = width * height * 4
    if len(rgba) < expected:
        raise ValueError("rgba buffer is smaller than width * height * 4")

    rows = []
    row_length = width * 4
    for y in range(height):
        start = y * row_length
        rows.append(b"\x00" + bytes(rgba[start : start + row_length]))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), level=6))
        + _png_chunk(b"IEND", b"")
    )


def enhanced_output_path(path: str) -> str:
    stem, _ext = os.path.splitext(path)
    return f"{stem}-enhanced.png"


def image_edit_size(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    return "1024x1536" if height > width else "1536x1024"


def _multipart_body(fields: dict[str, str], files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    boundary = f"----DivideScannedImages{uuid.uuid4().hex}"
    boundary_bytes = boundary.encode("ascii")
    body = bytearray()

    for name, value in fields.items():
        body.extend(b"--" + boundary_bytes + b"\r\n")
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for name, filename, content_type, data in files:
        body.extend(b"--" + boundary_bytes + b"\r\n")
        disposition = f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        body.extend(disposition.encode("utf-8"))
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(data)
        body.extend(b"\r\n")

    body.extend(b"--" + boundary_bytes + b"--\r\n")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def enhance_png_with_openai(
    png_bytes: bytes,
    api_key: str,
    width: int,
    height: int,
    prompt: str = ENHANCE_PROMPT,
    model: str = OPENAI_IMAGE_MODEL,
    timeout: int = 240,
) -> bytes:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    fields = {
        "model": model,
        "prompt": prompt,
        "size": image_edit_size(width, height),
        "quality": "high",
        "output_format": "png",
    }
    body, content_type = _multipart_body(fields, [("image", "crop.png", "image/png", png_bytes)])
    request = urllib.request.Request(
        OPENAI_IMAGE_EDIT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI image edit failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI image edit request failed: {exc}") from exc

    data = json.loads(payload.decode("utf-8"))
    images = data.get("data") or []
    if not images or not images[0].get("b64_json"):
        raise RuntimeError("OpenAI image edit response did not include b64_json image data.")
    return base64.b64decode(images[0]["b64_json"])
