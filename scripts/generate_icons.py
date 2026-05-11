#!/usr/bin/env python3
"""Generate addon icon and banner PNGs for odoo-webhooks.

This script writes icon.png files into each addon static/description folder.
It can also generate marketing banners into assets/banners.
Banner text rendering uses Pillow when --banner is selected.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageDraw = None
    ImageFont = None


PRIMARY = "#5B4FE8"
WHITE = "#FFFFFF"

ADDON_ICON_MAP = {
    "bwt_webhooks_core": "core",
    "bwt_webhooks_inbound": "inbound",
    "bwt_webhooks_outbound": "outbound",
    "bwt_connector_webhooks_core": "connector",
    "bwt_connector_webhooks_inbound": "connector_inbound",
    "bwt_connector_webhooks_outbound": "connector_outbound",
}

BANNER_TEXT = {
    "bwt_webhooks_core": "Webhooks Framework - Orchestration",
    "bwt_webhooks_inbound": "Webhooks Framework - Inbound Gateway",
    "bwt_webhooks_outbound": "Webhooks Framework - Outbound Delivery",
    "bwt_connector_webhooks_core": "Webhooks Connector - Core Orchestration",
    "bwt_connector_webhooks_inbound": "Webhooks Connector - Inbound Gateway",
    "bwt_connector_webhooks_outbound": "Webhooks Connector - Outbound Delivery",
}


def hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        alpha,
    )


class Canvas:
    def __init__(self, width: int, height: int, background: tuple[int, int, int, int]):
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 4)
        if background[3] > 0:
            self.fill(background)

    def _index(self, x: int, y: int) -> int:
        return (y * self.width + x) * 4

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        i = self._index(x, y)
        self.pixels[i : i + 4] = bytes(color)

    def fill(self, color: tuple[int, int, int, int]) -> None:
        r, g, b, a = color
        row = bytes([r, g, b, a]) * self.width
        for y in range(self.height):
            start = y * self.width * 4
            self.pixels[start : start + self.width * 4] = row

    def fill_rect(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int, int]) -> None:
        x0 = max(0, min(self.width, x0))
        x1 = max(0, min(self.width, x1))
        y0 = max(0, min(self.height, y0))
        y1 = max(0, min(self.height, y1))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            start = (y * self.width + x0) * 4
            end = start + (x1 - x0) * 4
            self.pixels[start:end] = row

    def fill_circle(self, cx: int, cy: int, r: int, color: tuple[int, int, int, int]) -> None:
        if r <= 0:
            return
        r2 = r * r
        for y in range(cy - r, cy + r + 1):
            if y < 0 or y >= self.height:
                continue
            dy = y - cy
            dx = int(math.sqrt(max(r2 - dy * dy, 0)))
            x0 = max(cx - dx, 0)
            x1 = min(cx + dx + 1, self.width)
            row = bytes(color) * (x1 - x0)
            start = (y * self.width + x0) * 4
            end = start + (x1 - x0) * 4
            self.pixels[start:end] = row

    def fill_round_rect(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        r: int,
        color: tuple[int, int, int, int],
    ) -> None:
        if r <= 0:
            self.fill_rect(x0, y0, x1, y1, color)
            return
        self.fill_rect(x0 + r, y0, x1 - r, y1, color)
        self.fill_rect(x0, y0 + r, x1, y1 - r, color)
        self.fill_circle(x0 + r, y0 + r, r, color)
        self.fill_circle(x1 - r - 1, y0 + r, r, color)
        self.fill_circle(x0 + r, y1 - r - 1, r, color)
        self.fill_circle(x1 - r - 1, y1 - r - 1, r, color)

    def fill_polygon(self, points: list[tuple[int, int]], color: tuple[int, int, int, int]) -> None:
        if len(points) < 3:
            return
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        min_y = max(min_y, 0)
        max_y = min(max_y, self.height - 1)
        for y in range(min_y, max_y + 1):
            intersections = []
            for i in range(len(points)):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % len(points)]
                if y0 == y1:
                    continue
                if y < min(y0, y1) or y >= max(y0, y1):
                    continue
                x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                intersections.append(x)
            intersections.sort()
            for i in range(0, len(intersections), 2):
                if i + 1 >= len(intersections):
                    break
                x_start = int(math.ceil(intersections[i]))
                x_end = int(math.floor(intersections[i + 1]))
                if x_end < x_start:
                    continue
                self.fill_rect(x_start, y, x_end + 1, y + 1, color)


def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(pixels[start : start + stride])
    compressed = zlib.compress(bytes(raw), level=9)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = zlib.crc32(chunk_type)
        crc = zlib.crc32(data, crc)
        crc_bytes = struct.pack(">I", crc & 0xFFFFFFFF)
        return length + chunk_type + data + crc_bytes

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = header
    data += chunk(b"IHDR", ihdr)
    data += chunk(b"IDAT", compressed)
    data += chunk(b"IEND", b"")
    path.write_bytes(data)


def draw_base(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    pad = int(round(6 * scale))
    radius = int(round(18 * scale))
    canvas.fill_round_rect(pad, pad, canvas.width - pad, canvas.height - pad, radius, colors["primary"])


def draw_line(canvas: Canvas, x0: int, y0: int, x1: int, y1: int, thickness: int, color: tuple[int, int, int, int]) -> None:
    if x0 == x1:
        y_start, y_end = sorted([y0, y1])
        half = thickness // 2
        canvas.fill_rect(x0 - half, y_start, x0 + half + 1, y_end, color)
    elif y0 == y1:
        x_start, x_end = sorted([x0, x1])
        half = thickness // 2
        canvas.fill_rect(x_start, y0 - half, x_end, y0 + half + 1, color)


def draw_ring(
    canvas: Canvas,
    cx: int,
    cy: int,
    outer_r: int,
    inner_r: int,
    color: tuple[int, int, int, int],
    bg: tuple[int, int, int, int],
) -> None:
    canvas.fill_circle(cx, cy, outer_r, color)
    canvas.fill_circle(cx, cy, inner_r, bg)


def fill_diamond(canvas: Canvas, cx: int, cy: int, r: int, color: tuple[int, int, int, int]) -> None:
    canvas.fill_polygon(
        [
            (cx, cy - r),
            (cx + r, cy),
            (cx, cy + r),
            (cx - r, cy),
        ],
        color,
    )


def icon_core(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Hub orchestrator: diamond core (tilted square) with four connected nodes."""
    cx = int(round(64 * scale))
    cy = int(round(64 * scale))
    hub_r = int(round(16 * scale))  # diamond half-diagonal
    node_r = int(round(7 * scale))
    dist = int(round(42 * scale))
    thick = int(round(3 * scale))

    nodes = [
        (cx, cy - dist),
        (cx, cy + dist),
        (cx - dist, cy),
        (cx + dist, cy),
    ]
    draw_line(canvas, cx, cy, cx, nodes[0][1], thick, colors["shape"])
    draw_line(canvas, cx, cy, cx, nodes[1][1], thick, colors["shape"])
    draw_line(canvas, cx, cy, nodes[2][0], cy, thick, colors["shape"])
    draw_line(canvas, cx, cy, nodes[3][0], cy, thick, colors["shape"])

    fill_diamond(canvas, cx, cy, hub_r, colors["shape"])

    for x, y in nodes:
        canvas.fill_circle(x, y, node_r, colors["shape"])


def icon_inbound(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Inbound: arrows into a diamond hub from nodes."""
    cx = int(round(64 * scale))
    cy = int(round(64 * scale))
    hub_r = int(round(18 * scale))  # diamond half-diagonal
    node_r = int(round(7 * scale))
    dist = int(round(42 * scale))
    thick = int(round(3 * scale))
    ah = int(round(6 * scale))
    aw = int(round(10 * scale))

    nodes = [
        (cx, cy - dist),
        (cx, cy + dist),
        (cx - dist, cy),
        (cx + dist, cy),
    ]

    # Lines
    draw_line(canvas, cx, cy, cx, nodes[0][1], thick, colors["shape"])
    draw_line(canvas, cx, cy, cx, nodes[1][1], thick, colors["shape"])
    draw_line(canvas, cx, cy, nodes[2][0], cy, thick, colors["shape"])
    draw_line(canvas, cx, cy, nodes[3][0], cy, thick, colors["shape"])

    # Arrowheads pointing INWARD
    canvas.fill_polygon([(cx, cy - hub_r - 2), (cx - aw // 2, cy - hub_r - 2 - ah), (cx + aw // 2, cy - hub_r - 2 - ah)], colors["shape"])  # N
    canvas.fill_polygon([(cx, cy + hub_r + 2), (cx - aw // 2, cy + hub_r + 2 + ah), (cx + aw // 2, cy + hub_r + 2 + ah)], colors["shape"])  # S
    canvas.fill_polygon([(cx - hub_r - 2, cy), (cx - hub_r - 2 - ah, cy - aw // 2), (cx - hub_r - 2 - ah, cy + aw // 2)], colors["shape"])  # W
    canvas.fill_polygon([(cx + hub_r + 2, cy), (cx + hub_r + 2 + ah, cy - aw // 2), (cx + hub_r + 2 + ah, cy + aw // 2)], colors["shape"])  # E

    # Central diamond
    fill_diamond(canvas, cx, cy, hub_r, colors["shape"])

    # Outer nodes
    for x, y in nodes:
        draw_ring(canvas, x, y, node_r, node_r - int(round(3 * scale)), colors["shape"], colors["primary"])


def icon_outbound(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Outbound: arrows out of a diamond hub to nodes."""
    cx = int(round(64 * scale))
    cy = int(round(64 * scale))
    hub_r = int(round(18 * scale))  # diamond half-diagonal
    node_r = int(round(7 * scale))
    dist = int(round(42 * scale))
    thick = int(round(3 * scale))
    ah = int(round(6 * scale))
    aw = int(round(10 * scale))

    nodes = [
        (cx, cy - dist),
        (cx, cy + dist),
        (cx - dist, cy),
        (cx + dist, cy),
    ]

    # Lines
    draw_line(canvas, cx, cy, cx, nodes[0][1], thick, colors["shape"])
    draw_line(canvas, cx, cy, cx, nodes[1][1], thick, colors["shape"])
    draw_line(canvas, cx, cy, nodes[2][0], cy, thick, colors["shape"])
    draw_line(canvas, cx, cy, nodes[3][0], cy, thick, colors["shape"])

    # Arrowheads pointing OUTWARD
    canvas.fill_polygon([(cx, cy - dist + node_r + 2), (cx - aw // 2, cy - dist + node_r + 2 + ah), (cx + aw // 2, cy - dist + node_r + 2 + ah)], colors["shape"])  # N
    canvas.fill_polygon([(cx, cy + dist - node_r - 2), (cx - aw // 2, cy + dist - node_r - 2 - ah), (cx + aw // 2, cy + dist - node_r - 2 - ah)], colors["shape"])  # S
    canvas.fill_polygon([(cx - dist + node_r + 2, cy), (cx - dist + node_r + 2 + ah, cy - aw // 2), (cx - dist + node_r + 2 + ah, cy + aw // 2)], colors["shape"])  # W
    canvas.fill_polygon([(cx + dist - node_r - 2, cy), (cx + dist - node_r - 2 - ah, cy - aw // 2), (cx + dist - node_r - 2 - ah, cy + aw // 2)], colors["shape"])  # E

    # Central diamond (hollow)
    fill_diamond(canvas, cx, cy, hub_r, colors["shape"])
    fill_diamond(canvas, cx, cy, hub_r - int(round(4 * scale)), colors["primary"])

    # Outer nodes
    for x, y in nodes:
        canvas.fill_circle(x, y, node_r, colors["shape"])


def icon_connector(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Connector: two rounded squares linked by a bridge."""
    cx = int(round(64 * scale))
    cy = int(round(64 * scale))
    sq = int(round(12 * scale))
    gap = int(round(10 * scale))
    radius = int(round(4 * scale))
    bar_h = int(round(3 * scale))

    left_x = cx - gap - sq
    right_x = cx + gap + sq

    canvas.fill_round_rect(left_x - sq, cy - sq, left_x + sq, cy + sq, radius, colors["shape"])
    canvas.fill_round_rect(right_x - sq, cy - sq, right_x + sq, cy + sq, radius, colors["shape"])
    canvas.fill_rect(left_x + sq, cy - bar_h // 2, right_x - sq, cy + bar_h // 2 + 1, colors["shape"])


def icon_connector_inbound(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Connector Inbound: bridge with an arrow pointing right."""
    icon_connector(canvas, scale, colors)
    cx = int(round(64 * scale))
    cy = int(round(64 * scale))
    ah = int(round(8 * scale))
    aw = int(round(12 * scale))
    gap = int(round(10 * scale))

    # Arrowhead pointing right
    canvas.fill_polygon([(cx + gap - 1, cy), (cx + gap - 1 - ah, cy - aw // 2), (cx + gap - 1 - ah, cy + aw // 2)], colors["shape"])


def icon_connector_outbound(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Connector Outbound: bridge with an arrow pointing left."""
    icon_connector(canvas, scale, colors)
    cx = int(round(64 * scale))
    cy = int(round(64 * scale))
    ah = int(round(8 * scale))
    aw = int(round(12 * scale))
    gap = int(round(10 * scale))

    # Arrowhead pointing left
    canvas.fill_polygon([(cx - gap + 1, cy), (cx - gap + 1 + ah, cy - aw // 2), (cx - gap + 1 + ah, cy + aw // 2)], colors["shape"])


def icon_glue(canvas: Canvas, scale: float, colors: dict[str, tuple[int, int, int, int]]) -> None:
    """Glue: interlocking chain links."""
    cy = int(round(64 * scale))
    left_x = int(round(54 * scale))
    right_x = int(round(74 * scale))
    outer_r = int(round(16 * scale))
    inner_r = int(round(11 * scale))

    draw_ring(canvas, left_x, cy, outer_r, inner_r, colors["shape"], colors["primary"])
    draw_ring(canvas, right_x, cy, outer_r, inner_r, colors["shape"], colors["primary"])


def build_icon(size: int, icon_type: str) -> bytearray:
    colors = {
        "primary": hex_to_rgba(PRIMARY),
        "shape": hex_to_rgba(WHITE),
    }
    canvas = Canvas(size, size, (0, 0, 0, 0))
    scale = size / 128.0
    draw_base(canvas, scale, colors)

    if icon_type == "core":
        icon_core(canvas, scale, colors)
    elif icon_type == "inbound":
        icon_inbound(canvas, scale, colors)
    elif icon_type == "outbound":
        icon_outbound(canvas, scale, colors)
    elif icon_type == "connector":
        icon_connector(canvas, scale, colors)
    elif icon_type == "connector_inbound":
        icon_connector_inbound(canvas, scale, colors)
    elif icon_type == "connector_outbound":
        icon_connector_outbound(canvas, scale, colors)
    elif icon_type == "glue":
        icon_glue(canvas, scale, colors)
    else:
        raise ValueError(f"Unknown icon type: {icon_type}")

    return canvas.pixels


def _require_pillow() -> None:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow is required for banner text rendering. Install with `pip install pillow`.")


def _apply_font_variations(font: "ImageFont.FreeTypeFont", wght: int | None = None, wdth: int | None = None) -> None:
    if not hasattr(font, "get_variation_axes"):
        return
    axes = font.get_variation_axes()
    values = []
    for axis in axes:
        tag = axis.get("tag")
        value = axis.get("default", axis.get("min", 0))
        if tag == "wght" and wght is not None:
            value = min(axis["max"], max(axis["min"], wght))
        elif tag == "wdth" and wdth is not None:
            value = min(axis["max"], max(axis["min"], wdth))
        values.append(value)
    font.set_variation_by_axes(values)


def _load_font(font_path: Path, size: int, *, wght: int | None = None, wdth: int | None = None) -> "ImageFont.FreeTypeFont":
    _require_pillow()
    font = ImageFont.truetype(str(font_path), size=size)
    _apply_font_variations(font, wght=wght, wdth=wdth)
    return font


def _line_gap(font: "ImageFont.FreeTypeFont") -> int:
    return max(2, int(round(font.size * 0.12)))


def _text_bbox(draw: "ImageDraw.ImageDraw", text: str, font: "ImageFont.FreeTypeFont") -> tuple[int, int, int, int]:
    if "\n" not in text:
        if hasattr(draw, "textbbox"):
            return draw.textbbox((0, 0), text, font=font)
        width, height = draw.textsize(text, font=font)
        return (0, 0, width, height)

    lines = text.splitlines() or [""]
    widths = []
    heights = []
    for line in lines:
        if hasattr(draw, "textbbox"):
            bbox = draw.textbbox((0, 0), line, font=font)
            widths.append(bbox[2] - bbox[0])
            heights.append(bbox[3] - bbox[1])
        else:
            width, height = draw.textsize(line, font=font)
            widths.append(width)
            heights.append(height)
    width = max(widths) if widths else 0
    height = sum(heights) + _line_gap(font) * (len(lines) - 1)
    return (0, 0, width, height)


def _fit_font_size(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font_path: Path,
    max_width: int,
    max_height: int,
    base_size: int,
    wght: int,
    wdth: int,
) -> tuple["ImageFont.FreeTypeFont", int, int]:
    size = base_size
    last = None
    while size >= 10:
        font = _load_font(font_path, size, wght=wght, wdth=wdth)
        bbox = _text_bbox(draw, text, font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        last = (font, width, height)
        if width <= max_width and height <= max_height:
            return last
        size -= 2
    if last is None:
        font = _load_font(font_path, 10, wght=wght, wdth=wdth)
        bbox = _text_bbox(draw, text, font)
        return (font, bbox[2] - bbox[0], bbox[3] - bbox[1])
    return last


def draw_cover_text(
    canvas: Canvas,
    text: str,
    font_path: Path,
    text_x: int,
    text_max_width: int,
) -> None:
    _require_pillow()
    image = Image.frombytes("RGBA", (canvas.width, canvas.height), bytes(canvas.pixels))
    draw = ImageDraw.Draw(image)
    text = text.upper().replace(" - ", "\n")
    max_height = int(canvas.height * 0.45)
    base_size = int(canvas.height * 0.16)
    font, width, height = _fit_font_size(
        draw,
        text,
        font_path,
        text_max_width,
        max_height,
        base_size,
        wght=600,
        wdth=100,
    )
    text_y = int(round((canvas.height - height) / 2))
    shift_left = int(round(canvas.width * 0.03))
    centered_x = int(round((canvas.width - width) / 2)) - shift_left
    text_x = max(text_x, centered_x)
    line_gap = _line_gap(font)
    shadow = hex_to_rgba("#16142B", 140)
    draw.multiline_text((text_x + 2, text_y + 2), text, font=font, fill=shadow, spacing=line_gap)
    draw.multiline_text((text_x, text_y), text, font=font, fill=hex_to_rgba(WHITE), spacing=line_gap)
    canvas.pixels = bytearray(image.tobytes())


def make_linear_gradient(width: int, height: int, colors: list[tuple[int, int, int]]) -> bytearray:
    """Create a left-to-right linear gradient (opaque)."""
    pixels = bytearray(width * height * 4)
    stops = len(colors) - 1
    if stops <= 0:
        r, g, b = colors[0]
        for i in range(0, len(pixels), 4):
            pixels[i : i + 4] = bytes((r, g, b, 255))
        return pixels

    for x in range(width):
        t = x / max(width - 1, 1)
        idx = min(int(t * stops), stops - 1)
        local_t = (t - (idx / stops)) * stops
        r0, g0, b0 = colors[idx]
        r1, g1, b1 = colors[idx + 1]
        r = int(round(r0 + (r1 - r0) * local_t))
        g = int(round(g0 + (g1 - g0) * local_t))
        b = int(round(b0 + (b1 - b0) * local_t))
        for y in range(height):
            i = (y * width + x) * 4
            pixels[i : i + 4] = bytes((r, g, b, 255))
    return pixels


def draw_wave_band(
    canvas: Canvas,
    top: int,
    height: int,
    amplitude: int,
    period: int,
    color: tuple[int, int, int, int],
    invert: bool = False,
) -> None:
    """Draw a sine-wave band across the canvas."""
    w = canvas.width
    for x in range(w):
        phase = (2.0 * math.pi * x) / max(period, 1)
        offset = int(round(math.sin(phase) * amplitude))
        y0 = top + offset
        y1 = y0 + height
        if invert:
            y0, y1 = y1, y0
        canvas.fill_rect(x, min(y0, y1), x + 1, max(y0, y1), color)


def draw_dot_grid(
    canvas: Canvas,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    spacing: int,
    r: int,
    color: tuple[int, int, int, int],
) -> None:
    """Draw a subtle dot grid."""
    for y in range(y0, y1, spacing):
        for x in range(x0, x1, spacing):
            canvas.fill_circle(x, y, r, color)


def draw_banner_base(canvas: Canvas) -> None:
    """Draw gradient background and subtle patterning."""
    gradient = make_linear_gradient(
        canvas.width,
        canvas.height,
        [
            (91, 79, 232),
            (90, 104, 232),
            (72, 144, 232),
        ],
    )
    canvas.pixels = gradient
    mist = hex_to_rgba("#E6E5F2", 90)
    cloud = hex_to_rgba("#F5F4FF", 70)
    draw_wave_band(canvas, int(canvas.height * 0.18), int(canvas.height * 0.18), 10, 160, mist)
    draw_wave_band(canvas, int(canvas.height * 0.72), int(canvas.height * 0.14), 8, 140, cloud, invert=True)
    draw_dot_grid(
        canvas,
        int(canvas.width * 0.05),
        int(canvas.height * 0.15),
        int(canvas.width * 0.35),
        int(canvas.height * 0.8),
        spacing=28,
        r=2,
        color=hex_to_rgba("#FFFFFF", 80),
    )


def draw_banner_icon(canvas: Canvas, icon_type: str, x: int, y: int, size: int) -> None:
    """Render an existing icon into the banner canvas (top-left at x,y)."""
    icon_pixels = build_icon(size, icon_type)
    for iy in range(size):
        for ix in range(size):
            i = (iy * size + ix) * 4
            if icon_pixels[i + 3] == 0:
                continue
            canvas.set_pixel(x + ix, y + iy, tuple(icon_pixels[i : i + 4]))


def draw_banner_composition(canvas: Canvas, icon_type: str) -> None:
    """Compose a banner: large icon plus supporting nodes."""
    draw_banner_base(canvas)
    icon_size = int(round(canvas.height * 0.72))
    icon_x = int(round(canvas.width * 0.08))
    icon_y = int(round((canvas.height - icon_size) / 2))
    draw_banner_icon(canvas, icon_type, icon_x, icon_y, icon_size)

    node_color = hex_to_rgba("#FFFFFF", 210)
    line_color = hex_to_rgba("#FFFFFF", 120)
    cx = int(round(canvas.width * 0.72))
    cy = int(round(canvas.height * 0.52))
    orbit = int(round(canvas.height * 0.26))
    nodes = [
        (cx - orbit, cy - int(orbit * 0.4)),
        (cx + orbit, cy - int(orbit * 0.2)),
        (cx - int(orbit * 0.2), cy + orbit),
    ]
    for nx, ny in nodes:
        draw_line(canvas, cx, cy, nx, ny, int(round(canvas.height * 0.015)), line_color)
        canvas.fill_circle(nx, ny, int(round(canvas.height * 0.04)), node_color)
    fill_diamond(canvas, cx, cy, int(round(canvas.height * 0.06)), node_color)


def build_banner(width: int, height: int, icon_type: str) -> bytearray:
    canvas = Canvas(width, height, (0, 0, 0, 0))
    draw_banner_composition(canvas, icon_type)
    return canvas.pixels


def draw_cover_base(canvas: Canvas) -> None:
    gradient = make_linear_gradient(
        canvas.width,
        canvas.height,
        [
            (91, 79, 232),
            (92, 108, 232),
            (86, 140, 228),
        ],
    )
    canvas.pixels = gradient
    mist = hex_to_rgba("#E6E5F2", 70)
    cloud = hex_to_rgba("#F5F4FF", 60)
    draw_wave_band(canvas, int(canvas.height * 0.16), int(canvas.height * 0.2), 10, 180, mist)
    draw_wave_band(canvas, int(canvas.height * 0.7), int(canvas.height * 0.16), 8, 160, cloud, invert=True)
    draw_dot_grid(
        canvas,
        int(canvas.width * 0.55),
        int(canvas.height * 0.18),
        int(canvas.width * 0.95),
        int(canvas.height * 0.82),
        spacing=24,
        r=2,
        color=hex_to_rgba("#FFFFFF", 70),
    )


def draw_cover_composition(canvas: Canvas, icon_type: str, text: str, font_path: Path) -> None:
    draw_cover_base(canvas)

    icon_size = int(round(canvas.height * 0.52))
    icon_x = int(round(canvas.width * 0.04))
    icon_y = int(round((canvas.height - icon_size) / 2))
    draw_banner_icon(canvas, icon_type, icon_x, icon_y, icon_size)

    accent = hex_to_rgba("#FFFFFF", 60)
    fill_diamond(
        canvas,
        int(round(canvas.width * 0.78)),
        int(round(canvas.height * 0.52)),
        int(round(canvas.height * 0.2)),
        accent,
    )

    text_left = icon_x + icon_size + int(round(canvas.width * 0.03))
    text_right = int(round(canvas.width * 0.95))
    text_max_width = text_right - text_left
    draw_cover_text(canvas, text, font_path, text_left, text_max_width)


def build_cover(width: int, height: int, icon_type: str, text: str, font_path: Path) -> bytearray:
    canvas = Canvas(width, height, (0, 0, 0, 0))
    draw_cover_composition(canvas, icon_type, text, font_path)
    return canvas.pixels


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_banner_font(repo_root: Path) -> Path:
    font_path = repo_root / "assets" / "fonts" / "space-grotesk" / "SpaceGrotesk[wght].ttf"
    if not font_path.exists():
        raise FileNotFoundError("Banner font not found. Expected assets/fonts/space-grotesk/SpaceGrotesk[wght].ttf")
    return font_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate odoo-webhooks addon icons, banners, or covers.")
    parser.add_argument("--size", type=int, default=512, help="Icon size in pixels (default: 512)")
    parser.add_argument("--banner", action="store_true", help="Generate banner PNGs instead of icons")
    parser.add_argument("--banner-size", type=str, default="528x264", help="Banner size WxH (default: 528x264)")
    parser.add_argument("--cover", action="store_true", help="Generate cover PNGs instead of icons")
    parser.add_argument("--cover-size", type=str, default="1920x640", help="Cover size WxH (default: 1920x640)")
    parser.add_argument("--dry-run", action="store_true", help="Print target files without writing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    size = args.size
    banner_size = args.banner_size
    cover_size = args.cover_size

    if args.banner and args.cover:
        print("Choose either --banner or --cover.")  # pylint: disable=print-used
        return 1

    if not args.banner and not args.cover and size < 64:
        print("Size must be at least 64.")  # pylint: disable=print-used
        return 1

    banner_w = banner_h = 0
    banner_scale = 2
    render_banner_w = render_banner_h = 0
    cover_w = cover_h = 0
    if args.banner:
        try:
            banner_w, banner_h = [int(p) for p in banner_size.lower().split("x", 1)]
        except ValueError as exc:
            raise ValueError("Invalid --banner-size, expected WxH like 528x264") from exc
        if banner_w < 528 or banner_h < 264:
            print("Banner size must be at least 528x264.")  # pylint: disable=print-used
            return 1
        render_banner_w = banner_w * banner_scale
        render_banner_h = banner_h * banner_scale

    if args.cover:
        try:
            cover_w, cover_h = [int(p) for p in cover_size.lower().split("x", 1)]
        except ValueError as exc:
            raise ValueError("Invalid --cover-size, expected WxH like 1920x640") from exc
        if cover_w < 320 or cover_h < 200:
            print("Cover size must be at least 320x200.")  # pylint: disable=print-used
            return 1

    repo_root = resolve_repo_root()
    banner_font = None
    if args.banner:
        try:
            _require_pillow()
        except RuntimeError as exc:
            print(str(exc))  # pylint: disable=print-used
            return 1
        try:
            banner_font = resolve_banner_font(repo_root)
        except FileNotFoundError as exc:
            print(str(exc))  # pylint: disable=print-used
            return 1
    if args.banner:
        banner_root = repo_root / "assets" / "banners"
        banner_root.mkdir(parents=True, exist_ok=True)
        for addon, icon_type in ADDON_ICON_MAP.items():
            banner_path = banner_root / f"{addon}.png"
            banner_text = BANNER_TEXT.get(addon, addon.replace("_", " "))
            if args.dry_run:
                print(f"[dry-run] {banner_path} ({icon_type})")  # pylint: disable=print-used
                continue
            pixels = build_cover(render_banner_w, render_banner_h, icon_type, banner_text, banner_font)
            image = Image.frombytes("RGBA", (render_banner_w, render_banner_h), bytes(pixels))
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            image = image.resize((banner_w, banner_h), resample=resample)
            write_png(banner_path, banner_w, banner_h, bytearray(image.tobytes()))
            print(f"Wrote {banner_path} ({icon_type})")  # pylint: disable=print-used
    elif args.cover:
        cover_root = repo_root / "assets" / "covers"
        cover_root.mkdir(parents=True, exist_ok=True)
        for addon, icon_type in ADDON_ICON_MAP.items():
            cover_path = cover_root / f"{addon}.png"
            if args.dry_run:
                print(f"[dry-run] {cover_path} ({icon_type})")  # pylint: disable=print-used
                continue
            pixels = build_banner(cover_w, cover_h, icon_type)
            write_png(cover_path, cover_w, cover_h, pixels)
            print(f"Wrote {cover_path} ({icon_type})")  # pylint: disable=print-used
    else:
        for addon, icon_type in ADDON_ICON_MAP.items():
            icon_path = repo_root / addon / "static" / "description" / "icon.png"
            if args.dry_run:
                print(f"[dry-run] {icon_path} ({icon_type})")  # pylint: disable=print-used
                continue
            icon_path.parent.mkdir(parents=True, exist_ok=True)
            pixels = build_icon(size, icon_type)
            write_png(icon_path, size, size, pixels)
            print(f"Wrote {icon_path} ({icon_type})")  # pylint: disable=print-used

    return 0


if __name__ == "__main__":
    sys.exit(main())
