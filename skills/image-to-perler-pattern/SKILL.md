---
name: image-to-perler-pattern
description: Convert a user-provided image, photo, icon, or illustration into a printable fuse-bead/perler-bead pattern with a color-coded grid, preview, palette legend, bead counts, and machine-readable CSV. Use for 拼豆图纸, 拼拼豆, fuse beads, Hama beads, or Perler patterns. Do not use for cross-stitch or pixel art that is not intended as a bead pattern.
---

# Image to Perler Pattern

Turn the supplied image into a buildable one-bead-per-cell pattern. Preserve the recognizable subject before chasing photographic detail.

## Inputs and defaults

- Require one readable local raster image. If the user supplied an attachment, resolve its local path first.
- Respect any requested bead width, height, board size, palette, background treatment, or color limit.
- If the user does not specify dimensions, choose exactly one of these three square tiers after inspecting visual complexity:
  - `29×29`: flat icons, logos, emoji, silhouettes, or subjects with large solid regions and few essential details.
  - `58×58`: ordinary isolated objects, illustrated characters, or moderately detailed faces where eyes, mouth, and silhouette must remain recognizable.
  - `104×104`: photographic portraits, fur or hair texture, subtle facial expressions, gradients, multiple small features, complex backgrounds, or requests that prioritize resemblance over bead count.
- Never use 29×29 for a photographic human or animal face. When uncertain between tiers, generate the lower-tier preview first and escalate if eyes, mouth, text, or silhouette collapse. State the selected tier and why.
- Use roughly 12–18 colors at 29×29, 18–30 at 58×58, and 24–40 at 104×104. Default to no dithering. Dithering often creates scattered single beads; enable it only when the user prefers tonal detail over easy assembly.
- Transparent pixels are empty cells. An opaque background remains part of the pattern unless the user asks to remove it.
- Default to the bundled standard 221-color MARD palette in [assets/mard_221_pixel_beads.csv](assets/mard_221_pixel_beads.csv), transcribed from the user-selected [Pixel Beads MARD chart](https://www.pixel-beads.com/zh-tw/mard-bead-color-chart). Its HEX values are screen approximations; physical beads still vary by lighting, batch, and material.
- Use [assets/generic_palette.csv](assets/generic_palette.csv) only when the user explicitly requests a brand-neutral approximation. Accept another brand or inventory palette through a CSV with `code,name,hex` columns.

## Create the pattern

Run [scripts/make_pattern.py](scripts/make_pattern.py). It requires Python 3 and Pillow.

```powershell
python scripts/make_pattern.py INPUT_IMAGE --output-dir OUTPUT_DIR --max-beads 40 --colors 20
```

Useful options:

- `--width N` / `--height N`: exact grid bounds; with both, use `--fit contain|cover|stretch`.
- `--palette FILE.csv`: map to a real bead palette.
- `--label-style code`: print MARD or other palette codes directly in each occupied cell and in `pattern.csv`; otherwise compact symbols are used with a legend.
- `--dither`: allow Floyd–Steinberg dithering.
- `--trim-transparent`: remove transparent outer margins before resizing.
- `--remove-border-color FFFFFF --border-tolerance 32`: remove only edge-connected pixels near a background color, preserving enclosed whites such as eyes and teeth.
- `--tile-size 29`: split printable PDF pages into board-sized sections.
- `--background HEX`: turn transparency into a bead color instead of empty cells.

Use the bundled Python runtime when the system `python` command is unavailable. Keep outputs in a dedicated folder near the source or in the user's requested destination.

## Verify before delivery

Inspect `preview.png` and `pattern.png`. Confirm that:

- the subject is recognizable at normal viewing size;
- important facial features, lettering, and silhouettes did not collapse;
- empty cells match the intended background;
- the legend symbols match the grid;
- `materials.csv` counts add up to the non-empty bead total in `metadata.json`;
- the PDF page tiles cover every row and column exactly once.

If recognition is weak, rerun with a larger grid, a tighter crop, a simpler background, or a slightly larger color limit. Prefer the smallest pattern that remains clearly recognizable.

## Deliver

Provide links to the output folder and at least these files:

- `pattern.pdf` — printable board-sized pages;
- `pattern.png` — full labeled grid;
- `preview.png` — clean mosaic preview;
- `materials.csv` — color/code, hex value, and bead count;
- `pattern.csv` — row/column bead symbols;
- `metadata.json` — dimensions, settings, totals, and output manifest.

Briefly report the grid size, number of colors, total beads, palette source, and that screen HEX values are approximations of physical beads.
