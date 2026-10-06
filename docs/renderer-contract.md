# Renderer contract

What a host must do to draw Lipi output. CrossInk (as CrossIndix) is the
reference host; the file and line pointers below name its implementation.

## 1. Build fonts with the builder

`builder/shaping.py` enumerates the cluster forms a font provides (HarfBuzz),
rasterises each composite once and returns three things the host stores in
its font file: the composite bitmaps keyed by their PUA codepoint, the cluster
table bytes (`docs/table-format.md`) with the script's kind, and per-glyph
mark anchors (`compute_anchors`). The host's converter calls
`build_shaping(font_path, spec, face, unit_scale, load_flags, ...)`; the
CrossInk converter is `lib/EpdFont/scripts/fontconvert_sdcard.py`.

## 2. Hand the table to the engine

At draw time the host owns the table bytes (resident while the font is
loaded; share one copy between sizes of a family whose bytes are identical)
and passes a `Lipi::ClusterTable{entries, count, kind}` to `Lipi::shape`.
Text whose bytes cannot contain a shaped script is skipped cheaply with
`Lipi::mayNeedShaping(utf8)`.

## 3. Shape before measuring and drawing

`Lipi::shape(utf8, table, out)` turns logical text into a UTF-8 codepoint
stream in visual order: Unicode letters and signs, plus PUA composites and
marks. The host measures and draws that stream with its ordinary glyph loop.
Both the measuring pass and the drawing pass must shape the same way, so
word widths match what is drawn (CrossInk: `GfxRenderer::resolveShapedText`).

## 4. Place marks

For every codepoint the host asks:

- `Lipi::isMark(cp)`: zero advance, overlay on the preceding base glyph.
- `Lipi::attachesBelow(cp)`: use the base's below anchor, else the above one.
- `Lipi::anchorClass(cp)`: when the font has no anchors for the pair, place
  the mark centred (`Center`), right-aligned (`Right`) or at the pen after
  the base (`Pen`); `None` means the host's own default.

With anchors from the builder the mark cursor is
`base cursor + (basePoint - markAnchor)`; the class rules are the fallback
for built-in fonts and pairs the probe marks never attach to. A base carries
up to three points (above, below, extra) and every mark a value plus a
placement mode saying which point the value is measured from: the anchor
of its class, the anchor of the other class, the base's advance (pen), or
the extra point. The builder picks the mode per mark and font by residual
(`compute_anchors`, `mark_offset_px` is the host's reference rule; CrossInk:
`glyphAnchor::markOffsetWithMode` in `lib/EpdFont/EpdFontData.h`, the draw
loops in `GfxRenderer.cpp`; a font stores the bytes in its own container,
CrossIndix's `.cpfont` glyph record).

## 5. Warm the advance table once per paragraph

Hosts that cache glyph advances per page should feed the shaped forms of the
paragraph's words through the cache before layout, deduplicated by codepoint
(a bitset over the Indic blocks and the PUA), so composites are measured
with warm advances. CrossInk: `appendShapedIndicText` in `GfxRenderer.cpp`.

## 6. Route UI text by block

`scriptBlockOf(cp)` (`engine/ScriptBlock.h`, a free function outside the namespace) names the block of a
codepoint so a host can pick a fallback font family for UI strings; the
probe letter per block (`scriptProbe`) tests whether a font file covers it.

## What Lipi does not do

No line breaking, no bidi, no font file format, no glyph rasterisation on the
device, no dynamic loading: providers are compiled in (`Registry.h`).
