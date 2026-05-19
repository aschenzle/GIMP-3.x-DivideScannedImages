"""Core crop detection for Divide Scanned Images.

This module intentionally has no GIMP imports so the component detection and
crop extraction can be tested with normal Python.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

RGBA = Tuple[int, int, int, int]
BBox = Tuple[int, int, int, int]  # min_x, min_y, max_x_exclusive, max_y_exclusive
ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class Component:
    bbox: BBox
    area: int

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]


@dataclass(frozen=True)
class Crop:
    component: Component
    rect: BBox

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def normalize_rgba(color: Sequence[int]) -> RGBA:
    if len(color) < 3:
        raise ValueError("color must have at least three components")
    alpha = color[3] if len(color) > 3 else 255
    return (
        clamp(int(color[0]), 0, 255),
        clamp(int(color[1]), 0, 255),
        clamp(int(color[2]), 0, 255),
        clamp(int(alpha), 0, 255),
    )


def _pixel_at(rgba: bytes | bytearray | memoryview, width: int, x: int, y: int) -> RGBA:
    offset = (y * width + x) * 4
    return (rgba[offset], rgba[offset + 1], rgba[offset + 2], rgba[offset + 3])


def sample_background(
    rgba: bytes | bytearray | memoryview,
    width: int,
    height: int,
    corner: str = "top-left",
    x_offset: int = 25,
    y_offset: int = 25,
    radius: int = 5,
) -> RGBA:
    """Average a small square around the requested background sample point."""

    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    if len(rgba) < width * height * 4:
        raise ValueError("rgba buffer is smaller than width * height * 4")

    corner = corner.lower()
    if corner == "top-right":
        cx = width - 1 - x_offset
        cy = y_offset
    elif corner == "bottom-left":
        cx = x_offset
        cy = height - 1 - y_offset
    elif corner == "bottom-right":
        cx = width - 1 - x_offset
        cy = height - 1 - y_offset
    else:
        cx = x_offset
        cy = y_offset

    cx = clamp(cx, 0, width - 1)
    cy = clamp(cy, 0, height - 1)
    x0 = clamp(cx - radius, 0, width - 1)
    x1 = clamp(cx + radius, 0, width - 1)
    y0 = clamp(cy - radius, 0, height - 1)
    y1 = clamp(cy + radius, 0, height - 1)

    totals = [0, 0, 0, 0]
    count = 0
    for y in range(y0, y1 + 1):
        row = y * width * 4
        for x in range(x0, x1 + 1):
            i = row + x * 4
            totals[0] += rgba[i]
            totals[1] += rgba[i + 1]
            totals[2] += rgba[i + 2]
            totals[3] += rgba[i + 3]
            count += 1

    return tuple(round(channel / count) for channel in totals)  # type: ignore[return-value]


def _is_foreground(pixel: RGBA, background: RGBA, threshold: int) -> bool:
    if pixel[3] == 0:
        return False
    threshold = clamp(threshold, 0, 255)
    return max(abs(pixel[0] - background[0]), abs(pixel[1] - background[1]), abs(pixel[2] - background[2])) > threshold


def build_foreground_mask(
    rgba: bytes | bytearray | memoryview,
    width: int,
    height: int,
    background: Sequence[int],
    threshold: int,
    progress_callback: Optional[ProgressCallback] = None,
    progress_start: float = 0.0,
    progress_span: float = 1.0,
) -> bytearray:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    if len(rgba) < width * height * 4:
        raise ValueError("rgba buffer is smaller than width * height * 4")

    bg = normalize_rgba(background)
    mask = bytearray(width * height)
    total = width * height
    update_step = max(width * 16, 10000)
    for p in range(total):
        i = p * 4
        if _is_foreground((rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]), bg, threshold):
            mask[p] = 1
        if progress_callback is not None and p % update_step == 0:
            progress_callback(progress_start + progress_span * (p / max(1, total)), "Building foreground mask...")
    if progress_callback is not None:
        progress_callback(progress_start + progress_span, "Foreground mask ready.")
    return mask


def connected_components(
    mask: bytearray,
    width: int,
    height: int,
    min_size: int,
    limit: int,
    eight_connected: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    progress_start: float = 0.0,
    progress_span: float = 1.0,
) -> List[Component]:
    """Return foreground components in scan order, consuming the mask."""

    if len(mask) != width * height:
        raise ValueError("mask dimensions do not match width * height")

    neighbors4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
    neighbors8 = neighbors4 + ((-1, -1), (1, -1), (-1, 1), (1, 1))
    neighbors = neighbors8 if eight_connected else neighbors4
    components: List[Component] = []
    max_items = max(0, int(limit))

    total = width * height
    update_step = max(width * 16, 10000)
    queue_update_step = 10000
    for start in range(total):
        if progress_callback is not None and start % update_step == 0:
            progress_callback(progress_start + progress_span * (start / max(1, total)), "Finding crop regions...")
        if mask[start] != 1:
            continue

        queue = [start]
        mask[start] = 0
        head = 0
        area = 0
        min_x = max_x = start % width
        min_y = max_y = start // width

        while head < len(queue):
            current = queue[head]
            head += 1
            if progress_callback is not None and head % queue_update_step == 0:
                progress_callback(progress_start + progress_span * (start / max(1, total)), "Tracing crop boundary...")
            x = current % width
            y = current // width
            area += 1
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y

            for dx, dy in neighbors:
                nx = x + dx
                ny = y + dy
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                ni = ny * width + nx
                if mask[ni] == 1:
                    mask[ni] = 0
                    queue.append(ni)

        bbox = (min_x, min_y, max_x + 1, max_y + 1)
        comp = Component(bbox=bbox, area=area)
        if comp.width > min_size and comp.height > min_size and comp.width < width and comp.height < height:
            components.append(comp)
            if max_items and len(components) >= max_items:
                break

    if progress_callback is not None:
        progress_callback(progress_start + progress_span, "Crop regions ready.")
    return components


def plan_crop(component: Component, padding: int, square: bool) -> Crop:
    x0, y0, x1, y1 = component.bbox
    padding = max(0, int(padding))

    if square:
        width = x1 - x0
        height = y1 - y0
        side = max(width, height) + padding * 2
        center_x = (x0 + x1) / 2.0
        center_y = (y0 + y1) / 2.0
        left = math.floor(center_x - side / 2.0)
        top = math.floor(center_y - side / 2.0)
        rect = (left, top, left + side, top + side)
    else:
        rect = (x0 - padding, y0 - padding, x1 + padding, y1 + padding)

    return Crop(component=component, rect=rect)


def detect_crops(
    rgba: bytes | bytearray | memoryview,
    width: int,
    height: int,
    background: Sequence[int],
    threshold: int = 25,
    min_size: int = 100,
    limit: int = 10,
    padding: int = 0,
    square: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Crop]:
    mask = build_foreground_mask(
        rgba,
        width,
        height,
        background,
        threshold,
        progress_callback=progress_callback,
        progress_start=0.0,
        progress_span=0.55,
    )
    components = connected_components(
        mask,
        width,
        height,
        min_size,
        limit,
        progress_callback=progress_callback,
        progress_start=0.55,
        progress_span=0.45,
    )
    return [plan_crop(component, padding, square) for component in components]


def extract_crop_rgba(
    rgba: bytes | bytearray | memoryview,
    width: int,
    height: int,
    crop: Crop | BBox,
    fill: Sequence[int],
) -> Tuple[bytes, int, int]:
    rect = crop.rect if isinstance(crop, Crop) else crop
    x0, y0, x1, y1 = rect
    out_width = x1 - x0
    out_height = y1 - y0
    if out_width <= 0 or out_height <= 0:
        raise ValueError("crop rectangle must have positive dimensions")

    fill_rgba = normalize_rgba(fill)
    output = bytearray(fill_rgba * (out_width * out_height))

    src_x0 = clamp(x0, 0, width)
    src_y0 = clamp(y0, 0, height)
    src_x1 = clamp(x1, 0, width)
    src_y1 = clamp(y1, 0, height)

    if src_x0 >= src_x1 or src_y0 >= src_y1:
        return bytes(output), out_width, out_height

    copy_width = src_x1 - src_x0
    for sy in range(src_y0, src_y1):
        dy = sy - y0
        src_start = (sy * width + src_x0) * 4
        src_end = src_start + copy_width * 4
        dst_start = (dy * out_width + (src_x0 - x0)) * 4
        output[dst_start : dst_start + copy_width * 4] = rgba[src_start:src_end]

    return bytes(output), out_width, out_height


def rotate_rgba_clockwise(
    rgba: bytes | bytearray | memoryview,
    width: int,
    height: int,
) -> Tuple[bytes, int, int]:
    """Rotate an RGBA buffer 90 degrees clockwise."""

    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    if len(rgba) < width * height * 4:
        raise ValueError("rgba buffer is smaller than width * height * 4")

    out_width = height
    out_height = width
    output = bytearray(out_width * out_height * 4)

    for y in range(height):
        for x in range(width):
            src = (y * width + x) * 4
            dst_x = height - 1 - y
            dst_y = x
            dst = (dst_y * out_width + dst_x) * 4
            output[dst : dst + 4] = rgba[src : src + 4]

    return bytes(output), out_width, out_height


def iter_supported_files(directory: str, extensions: Iterable[str]) -> List[str]:
    import os

    normalized = {ext.lower().lstrip(".") for ext in extensions}
    files = []
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in normalized:
            files.append(path)
    return sorted(files, key=lambda value: value.lower())
