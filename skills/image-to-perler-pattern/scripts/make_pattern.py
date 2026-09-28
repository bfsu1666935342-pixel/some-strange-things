#!/usr/bin/env python3
"""Create printable fuse-bead patterns from raster images."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:
    raise SystemExit("Pillow is required. Install it with: python -m pip install Pillow") from exc


SYMBOLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789abcdefghijklmnopqrstuvwxyz"
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
DEFAULT_PALETTE = ASSETS_DIR / "mard_221_pixel_beads.csv"
GENERIC_PALETTE = ASSETS_DIR / "generic_palette.csv"
MARD_PALETTE_SOURCE = "https://www.pixel-beads.com/zh-tw/mard-bead-color-chart"


@dataclass(frozen=True)
class PaletteColor:
    code: str
    name: str
    rgb: tuple[int, int, int]

    @property
    def hex(self) -> str:
        return "#{:02X}{:02X}{:02X}".format(*self.rgb)


def pixel_data(image: Image.Image):
    """Return flattened pixels across supported Pillow versions."""
    method = getattr(image, "get_flattened_data", None)
    return method() if method else image.getdata()


def parse_hex(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"invalid hex color: {value!r}")
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"invalid hex color: {value!r}") from exc


def load_palette(path: Path) -> list[PaletteColor]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = {f.strip().lower(): f for f in (reader.fieldnames or [])}
        if "hex" not in fields:
            raise ValueError("palette CSV must contain code,name,hex columns (hex is required)")
        colors: list[PaletteColor] = []
        for index, row in enumerate(reader, start=1):
            raw_hex = (row.get(fields["hex"]) or "").strip()
            if not raw_hex:
                continue
            code = ((row.get(fields.get("code", "")) or "") if "code" in fields else "").strip() or f"C{index:02d}"
            name = ((row.get(fields.get("name", "")) or "") if "name" in fields else "").strip() or code
            colors.append(PaletteColor(code, name, parse_hex(raw_hex)))
    if len(colors) < 2:
        raise ValueError("palette must contain at least two valid colors")
    if len({c.code for c in colors}) != len(colors):
        raise ValueError("palette color codes must be unique")
    return colors


def srgb_channel_to_linear(value: int) -> float:
    channel = value / 255.0
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (srgb_channel_to_linear(v) for v in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        delta = 6 / 29
        return t ** (1 / 3) if t > delta**3 else t / (3 * delta**2) + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def nearest_palette_index(rgb: tuple[int, int, int], palette_labs: Sequence[tuple[float, float, float]]) -> int:
    lab = rgb_to_lab(rgb)
    return min(range(len(palette_labs)), key=lambda i: lab_distance(lab, palette_labs[i]))


def trim_transparent(image: Image.Image) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox else image


def remove_border_color(image: Image.Image, target: tuple[int, int, int], tolerance: int) -> Image.Image:
    """Make edge-connected pixels near target transparent, preserving enclosed whites."""
    result = image.copy()
    width, height = result.size
    pixels = result.load()
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def matches(x: int, y: int) -> bool:
        rgba = pixels[x, y]
        return rgba[3] > 0 and max(abs(rgba[channel] - target[channel]) for channel in range(3)) <= tolerance

    for x in range(width):
        queue.append((x, 0))
        if height > 1:
            queue.append((x, height - 1))
    for y in range(1, height - 1):
        queue.append((0, y))
        if width > 1:
            queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        pos = y * width + x
        if visited[pos]:
            continue
        visited[pos] = 1
        if not matches(x, y):
            continue
        r, g, b, _alpha = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)
        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    return result


def resolve_grid_size(source_size: tuple[int, int], width: int | None, height: int | None, max_beads: int) -> tuple[int, int]:
    source_w, source_h = source_size
    if width and height:
        return width, height
    if width:
        return width, max(1, round(source_h * width / source_w))
    if height:
        return max(1, round(source_w * height / source_h)), height
    scale = max_beads / max(source_w, source_h)
    return max(1, round(source_w * scale)), max(1, round(source_h * scale))


def resize_to_grid(image: Image.Image, size: tuple[int, int], fit: str) -> Image.Image:
    target_w, target_h = size
    if fit == "stretch":
        return image.resize(size, Image.Resampling.LANCZOS)
    if fit == "cover":
        return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    contained = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(contained, ((target_w - contained.width) // 2, (target_h - contained.height) // 2))
    return canvas


def choose_palette_subset(
    image: Image.Image,
    usable_mask: list[bool],
    palette: Sequence[PaletteColor],
    max_colors: int,
) -> list[int]:
    pixels = list(pixel_data(image))
    opaque = [rgba[:3] for rgba, use in zip(pixels, usable_mask) if use]
    if not opaque:
        return []
    sample = Image.new("RGB", (len(opaque), 1))
    sample.putdata(opaque)
    adaptive_count = min(max_colors, len(palette), len(set(opaque)))
    quantized = sample.quantize(colors=max(1, adaptive_count), method=Image.Quantize.MEDIANCUT)
    counts = Counter(pixel_data(quantized))
    raw_palette = quantized.getpalette() or []
    palette_labs = [rgb_to_lab(color.rgb) for color in palette]
    selected: list[int] = []
    for adaptive_index, _count in counts.most_common():
        start = adaptive_index * 3
        rgb = tuple(raw_palette[start : start + 3])
        if len(rgb) != 3:
            continue
        mapped = nearest_palette_index(rgb, palette_labs)  # type: ignore[arg-type]
        if mapped not in selected:
            selected.append(mapped)
        if len(selected) >= max_colors:
            break
    return selected or [nearest_palette_index(opaque[0], palette_labs)]


def map_pixels(
    image: Image.Image,
    palette: Sequence[PaletteColor],
    selected: Sequence[int],
    alpha_threshold: int,
    dither: bool,
) -> list[list[int | None]]:
    width, height = image.size
    pixels = [list(map(float, rgba)) for rgba in pixel_data(image)]
    selected_labs = [rgb_to_lab(palette[i].rgb) for i in selected]
    grid: list[list[int | None]] = [[None for _ in range(width)] for _ in range(height)]

    def add_error(x: int, y: int, error: tuple[float, float, float], factor: float) -> None:
        if 0 <= x < width and 0 <= y < height:
            pos = y * width + x
            if pixels[pos][3] > alpha_threshold:
                for channel in range(3):
                    pixels[pos][channel] = min(255.0, max(0.0, pixels[pos][channel] + error[channel] * factor))

    for y in range(height):
        for x in range(width):
            pos = y * width + x
            r, g, b, alpha = pixels[pos]
            if alpha <= alpha_threshold or not selected:
                continue
            source_rgb = (round(r), round(g), round(b))
            local_index = nearest_palette_index(source_rgb, selected_labs)
            palette_index = selected[local_index]
            grid[y][x] = palette_index
            if dither:
                target = palette[palette_index].rgb
                error = tuple(source_rgb[c] - target[c] for c in range(3))
                add_error(x + 1, y, error, 7 / 16)
                add_error(x - 1, y + 1, error, 3 / 16)
                add_error(x, y + 1, error, 5 / 16)
                add_error(x + 1, y + 1, error, 1 / 16)
    return grid


def find_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf"),
        Path("C:/Windows/Fonts") / ("msyhbd.ttc" if bold else "msyh.ttc"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def contrasting_text(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return (20, 20, 20) if luminance > 155 else (255, 255, 255)


def ordered_used_indices(grid: Sequence[Sequence[int | None]], palette: Sequence[PaletteColor]) -> list[int]:
    counts = Counter(cell for row in grid for cell in row if cell is not None)
    return sorted(counts, key=lambda i: (-counts[i], palette[i].code))


def symbol_map_for(grid: Sequence[Sequence[int | None]], palette: Sequence[PaletteColor]) -> dict[int, str]:
    used = ordered_used_indices(grid, palette)
    if len(used) > len(SYMBOLS):
        raise ValueError(f"pattern uses {len(used)} colors but only {len(SYMBOLS)} symbols are available")
    return {palette_index: SYMBOLS[i] for i, palette_index in enumerate(used)}


def draw_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    x = left + (right - left - (bbox[2] - bbox[0])) / 2
    y = top + (bottom - top - (bbox[3] - bbox[1])) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)


def render_preview(grid: Sequence[Sequence[int | None]], palette: Sequence[PaletteColor], cell: int = 20) -> Image.Image:
    height, width = len(grid), len(grid[0])
    image = Image.new("RGBA", (width * cell, height * cell), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    inset = max(1, cell // 12)
    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            if value is None:
                continue
            draw.ellipse(
                (x * cell + inset, y * cell + inset, (x + 1) * cell - inset - 1, (y + 1) * cell - inset - 1),
                fill=palette[value].rgb + (255,),
            )
    return image


def render_full_pattern(
    grid: Sequence[Sequence[int | None]],
    palette: Sequence[PaletteColor],
    symbols: dict[int, str],
    title: str,
    cell: int = 30,
) -> Image.Image:
    height, width = len(grid), len(grid[0])
    margin_left, margin_top, margin_right = 54, 76, 30
    legend_row_h = 34
    used = ordered_used_indices(grid, palette)
    legend_cols = max(1, min(3, math.ceil(len(used) / 12)))
    rows_per_col = math.ceil(len(used) / legend_cols) if used else 1
    canvas_w = max(margin_left + width * cell + margin_right, 40 + legend_cols * 330)
    grid_bottom = margin_top + height * cell
    legend_top = grid_bottom + 45
    canvas_h = legend_top + rows_per_col * legend_row_h + 35
    image = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(image)
    title_font = find_font(24, bold=True)
    label_font = find_font(max(9, min(14, cell // 2)), bold=True)
    coord_font = find_font(12)
    legend_font = find_font(16)
    draw.text((margin_left, 22), title, font=title_font, fill=(20, 20, 20))

    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            box = (margin_left + x * cell, margin_top + y * cell, margin_left + (x + 1) * cell, margin_top + (y + 1) * cell)
            fill = (255, 255, 255) if value is None else palette[value].rgb
            draw.rectangle(box, fill=fill, outline=(145, 145, 145), width=1)
            if value is not None:
                draw_centered(draw, box, symbols[value], label_font, contrasting_text(fill))

    for x in range(width):
        if x == 0 or (x + 1) % 5 == 0 or x == width - 1:
            text = str(x + 1)
            bbox = draw.textbbox((0, 0), text, font=coord_font)
            draw.text((margin_left + x * cell + (cell - (bbox[2] - bbox[0])) / 2, margin_top - 20), text, font=coord_font, fill=(40, 40, 40))
    for y in range(height):
        if y == 0 or (y + 1) % 5 == 0 or y == height - 1:
            text = str(y + 1)
            bbox = draw.textbbox((0, 0), text, font=coord_font)
            draw.text((margin_left - 10 - (bbox[2] - bbox[0]), margin_top + y * cell + 7), text, font=coord_font, fill=(40, 40, 40))

    counts = Counter(cell_value for row in grid for cell_value in row if cell_value is not None)
    for position, palette_index in enumerate(used):
        col, row = divmod(position, rows_per_col)
        x, y = 40 + col * 330, legend_top + row * legend_row_h
        draw.rectangle((x, y + 3, x + 25, y + 28), fill=palette[palette_index].rgb, outline=(70, 70, 70))
        label = symbols[palette_index]
        code_part = "" if label == palette[palette_index].code else f"  {palette[palette_index].code}"
        legend = f"{label}{code_part}  {palette[palette_index].name}  {palette[palette_index].hex}  x{counts[palette_index]}"
        draw.text((x + 34, y + 5), legend, font=legend_font, fill=(25, 25, 25))
    return image


def render_tile_page(
    grid: Sequence[Sequence[int | None]],
    palette: Sequence[PaletteColor],
    symbols: dict[int, str],
    bounds: tuple[int, int, int, int],
    page_number: int,
    page_count: int,
) -> Image.Image:
    x0, y0, x1, y1 = bounds
    tile_width, tile_height = x1 - x0, y1 - y0
    cell = max(8, min(34, 1020 // max(1, tile_width), 1000 // max(1, tile_height)))
    margin_left, margin_top = 110, 130
    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    title_font = find_font(27, bold=True)
    label_font = find_font(15, bold=True)
    coord_font = find_font(14)
    legend_font = find_font(15)
    draw.text((70, 45), f"Perler Pattern - page {page_number}/{page_count}", font=title_font, fill=(20, 20, 20))
    draw.text((70, 85), f"Columns {x0 + 1}-{x1}, rows {y0 + 1}-{y1}", font=coord_font, fill=(50, 50, 50))

    tile_used: set[int] = set()
    for gy in range(y0, y1):
        for gx in range(x0, x1):
            value = grid[gy][gx]
            box = (
                margin_left + (gx - x0) * cell,
                margin_top + (gy - y0) * cell,
                margin_left + (gx - x0 + 1) * cell,
                margin_top + (gy - y0 + 1) * cell,
            )
            fill = (255, 255, 255) if value is None else palette[value].rgb
            draw.rectangle(box, fill=fill, outline=(110, 110, 110), width=1)
            if value is not None:
                tile_used.add(value)
                draw_centered(draw, box, symbols[value], label_font, contrasting_text(fill))

    for gx in range(x0, x1):
        text = str(gx + 1)
        bbox = draw.textbbox((0, 0), text, font=coord_font)
        draw.text((margin_left + (gx - x0) * cell + (cell - (bbox[2] - bbox[0])) / 2, margin_top - 24), text, font=coord_font, fill=(40, 40, 40))
    for gy in range(y0, y1):
        text = str(gy + 1)
        bbox = draw.textbbox((0, 0), text, font=coord_font)
        draw.text((margin_left - 12 - (bbox[2] - bbox[0]), margin_top + (gy - y0) * cell + 8), text, font=coord_font, fill=(40, 40, 40))

    legend_y = margin_top + (y1 - y0) * cell + 45
    local_counts = Counter(grid[y][x] for y in range(y0, y1) for x in range(x0, x1) if grid[y][x] is not None)
    for offset, palette_index in enumerate(sorted(tile_used, key=lambda i: symbols[i])):
        col, row = divmod(offset, 15)
        x, y = margin_left + col * 280, legend_y + row * 28
        draw.rectangle((x, y, x + 21, y + 21), fill=palette[palette_index].rgb, outline=(80, 80, 80))
        label = symbols[palette_index]
        code_part = "" if label == palette[palette_index].code else f" {palette[palette_index].code}"
        text = f"{label}{code_part} {palette[palette_index].hex} x{local_counts[palette_index]}"
        draw.text((x + 29, y + 2), text, font=legend_font, fill=(25, 25, 25))
    return page


def save_csvs(
    output_dir: Path,
    grid: Sequence[Sequence[int | None]],
    palette: Sequence[PaletteColor],
    symbols: dict[int, str],
) -> tuple[Path, Path]:
    pattern_path = output_dir / "pattern.csv"
    with pattern_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row/col", *range(1, len(grid[0]) + 1)])
        for row_number, row in enumerate(grid, start=1):
            writer.writerow([row_number, *(symbols[value] if value is not None else "." for value in row)])

    materials_path = output_dir / "materials.csv"
    counts = Counter(value for row in grid for value in row if value is not None)
    with materials_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "code", "name", "hex", "count"])
        for palette_index in ordered_used_indices(grid, palette):
            color = palette[palette_index]
            writer.writerow([symbols[palette_index], color.code, color.name, color.hex, counts[palette_index]])
    return pattern_path, materials_path


def tile_bounds(width: int, height: int, tile_size: int) -> Iterable[tuple[int, int, int, int]]:
    for y0 in range(0, height, tile_size):
        for x0 in range(0, width, tile_size):
            yield x0, y0, min(width, x0 + tile_size), min(height, y0 + tile_size)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a raster image into a printable fuse-bead pattern.")
    parser.add_argument("input", type=Path, help="source image path")
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for generated files")
    parser.add_argument("--width", type=positive_int, help="grid width in beads")
    parser.add_argument("--height", type=positive_int, help="grid height in beads")
    parser.add_argument("--max-beads", type=positive_int, default=40, help="maximum grid dimension when width/height are omitted")
    parser.add_argument("--colors", type=positive_int, default=20, help="maximum number of bead colors")
    parser.add_argument("--palette", type=Path, default=DEFAULT_PALETTE, help="CSV palette with code,name,hex columns")
    parser.add_argument("--label-style", choices=("symbol", "code"), default="symbol", help="cell labels: compact symbols or palette codes")
    parser.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain", help="fit mode for fixed dimensions")
    parser.add_argument("--dither", action="store_true", help="enable Floyd-Steinberg dithering")
    parser.add_argument("--trim-transparent", action="store_true", help="crop transparent outer margins")
    parser.add_argument("--alpha-threshold", type=int, default=64, help="alpha at or below this value is empty (0-255)")
    parser.add_argument("--remove-border-color", help="make edge-connected pixels near this hex color transparent")
    parser.add_argument("--border-tolerance", type=int, default=32, help="per-channel tolerance for --remove-border-color (0-255)")
    parser.add_argument("--background", help="hex color used to fill transparency before conversion")
    parser.add_argument("--tile-size", type=positive_int, default=29, help="maximum rows/columns per printable page")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        raise SystemExit(f"input image not found: {args.input}")
    if not args.palette.is_file():
        raise SystemExit(f"palette CSV not found: {args.palette}")
    if not 0 <= args.alpha_threshold <= 255:
        raise SystemExit("--alpha-threshold must be between 0 and 255")
    if not 0 <= args.border_tolerance <= 255:
        raise SystemExit("--border-tolerance must be between 0 and 255")

    palette = load_palette(args.palette)
    max_colors = min(args.colors, len(palette), len(SYMBOLS))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(args.input) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGBA")
    source_size = source.size
    if args.remove_border_color:
        source = remove_border_color(source, parse_hex(args.remove_border_color), args.border_tolerance)
    if args.trim_transparent:
        source = trim_transparent(source)
    if args.background:
        background = Image.new("RGBA", source.size, parse_hex(args.background) + (255,))
        background.alpha_composite(source)
        source = background

    grid_size = resolve_grid_size(source.size, args.width, args.height, args.max_beads)
    resized = resize_to_grid(source, grid_size, args.fit)
    usable_mask = [pixel[3] > args.alpha_threshold for pixel in pixel_data(resized)]
    selected = choose_palette_subset(resized, usable_mask, palette, max_colors)
    grid = map_pixels(resized, palette, selected, args.alpha_threshold, args.dither)
    symbols = symbol_map_for(grid, palette)
    labels = {index: palette[index].code for index in symbols} if args.label_style == "code" else symbols

    preview_path = args.output_dir / "preview.png"
    pattern_path = args.output_dir / "pattern.png"
    pdf_path = args.output_dir / "pattern.pdf"
    pages_dir = args.output_dir / "print_pages"
    pages_dir.mkdir(exist_ok=True)
    for old_page in pages_dir.glob("page-*.png"):
        old_page.unlink()

    render_preview(grid, palette).save(preview_path)
    render_full_pattern(grid, palette, labels, f"Perler Pattern - {grid_size[0]} x {grid_size[1]} beads").save(pattern_path)
    pattern_csv, materials_csv = save_csvs(args.output_dir, grid, palette, labels)

    bounds = list(tile_bounds(grid_size[0], grid_size[1], args.tile_size))
    pages: list[Image.Image] = []
    page_paths: list[str] = []
    for page_number, area in enumerate(bounds, start=1):
        page = render_tile_page(grid, palette, labels, area, page_number, len(bounds))
        page_path = pages_dir / f"page-{page_number:03d}.png"
        page.save(page_path)
        page_paths.append(str(page_path.relative_to(args.output_dir)))
        pages.append(page)
    if pages:
        pages[0].save(pdf_path, save_all=True, append_images=pages[1:], resolution=150.0)

    counts = Counter(value for row in grid for value in row if value is not None)
    total_cells = grid_size[0] * grid_size[1]
    palette_path = args.palette.resolve()
    if palette_path == DEFAULT_PALETTE.resolve():
        palette_kind = "mard_221_screen_reference"
        palette_source = MARD_PALETTE_SOURCE
    elif palette_path == GENERIC_PALETTE.resolve():
        palette_kind = "generic_approximation"
        palette_source = None
    else:
        palette_kind = "user_supplied"
        palette_source = None

    metadata = {
        "input": str(args.input.resolve()),
        "source_size_px": {"width": source_size[0], "height": source_size[1]},
        "grid_size_beads": {"width": grid_size[0], "height": grid_size[1]},
        "palette": str(palette_path),
        "palette_kind": palette_kind,
        "palette_source": palette_source,
        "label_style": args.label_style,
        "fit": args.fit,
        "dither": args.dither,
        "removed_border_color": args.remove_border_color,
        "border_tolerance": args.border_tolerance if args.remove_border_color else None,
        "colors_requested": args.colors,
        "colors_used": len(counts),
        "total_beads": sum(counts.values()),
        "empty_cells": total_cells - sum(counts.values()),
        "tile_size": args.tile_size,
        "page_count": len(bounds),
        "outputs": {
            "preview": preview_path.name,
            "full_pattern": pattern_path.name,
            "print_pdf": pdf_path.name,
            "pattern_csv": pattern_csv.name,
            "materials_csv": materials_csv.name,
            "print_pages": page_paths,
        },
    }
    metadata_path = args.output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
