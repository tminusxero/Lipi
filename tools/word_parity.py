#!/usr/bin/env python3
"""Whole-word placement parity: where the device puts every glyph of a word
against where HarfBuzz puts it.

    word_parity.py FONT.ttf FONT_N.cpfont WORDS.txt [--tolerance PX] [--show N] [--limit N] [--dump PATH]

hb_parity.py compares glyph *sequences*; this compares glyph *positions* for
the words whose sequences agree: the device model is render.py's draw loop
(advance stepping, mark anchors and placement modes, the class-rule
fallbacks), the reference is HarfBuzz at the file's size. Reported per word:
the largest |dx| over spacing glyphs and marks, and for marks the vertical
offset HarfBuzz applies that the device ignores (dy). Words over the
tolerance are grouped by the glyph that moved. Separately, every mark's contact
with other glyphs is measured on both sides (share of its solid pixels on or next
to other solid ink): MERGED when the device fuses it into a stroke HarfBuzz keeps
it clear of (a reader sees the mark as missing, however small its offset), TOUCHING
when it collides where HarfBuzz leaves it (nearly) free. Thresholds are constants
below, calibrated on 30 hand-checked words; a random sample of 24 flagged words
over the six fonts was real on inspection (2026-09-22). --dump writes one line
per compared word (word, dx, dy, culprits, contact findings) to PATH; nothing else
is written."""
import collections
import os
import subprocess
import sys

import uharfbuzz as hb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import fontcheck  # noqa: E402
import hb_parity  # noqa: E402
import render  # noqa: E402

PLACEHOLDERS = hb_parity.PLACEHOLDERS


class Ref:
    """HarfBuzz glyph names and pixel positions for a word."""

    def __init__(self, ttf, unit_scale, face, load_flags, spec=None):
        self.font = hb.Font(hb.Face(hb.Blob.from_file_path(ttf)))
        # The script is the provider's, as the builder and the device shape it: a
        # token of Common-script characters only (।।) would otherwise be shaped
        # without the Indic features and differ from the same glyphs in running text.
        self.spec = spec
        self.scale = unit_scale
        self.face, self.load_flags = face, load_flags
        self.cache, self.bearings, self.solids = {}, {}, {}

    def bearing(self, gid):
        """FreeType bitmap_left / bitmap_top of a glyph at the file's size (the
        converter rasterises the same way), cached per glyph."""
        if gid not in self.bearings:
            self.face.load_glyph(gid, self.load_flags)
            b = self.face.glyph.bitmap
            self.bearings[gid] = (self.face.glyph.bitmap_left, self.face.glyph.bitmap_top, b.width, b.rows)
        return self.bearings[gid]

    def shape(self, text):
        """[(name, ink_left_px, origin_px, ink_top_px, has_ink, gid)] per glyph: HarfBuzz origin plus FreeType bearing."""
        if text in self.cache:
            return self.cache[text]
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        if self.spec is not None:
            buf.script = self.spec.hb_script
            buf.language = self.spec.hb_language
        hb.shape(self.font, buf, {})
        out, x = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            name = self.font.glyph_to_string(info.codepoint)
            if name not in PLACEHOLDERS:
                left, top, w, h = self.bearing(info.codepoint)
                origin = (x + pos.x_offset) * self.scale
                out.append((name, origin + left, origin, pos.y_offset * self.scale + top, w > 0 and h > 0,
                            info.codepoint))
            x += pos.x_advance
        self.cache[text] = out
        return out

    def solid(self, gid):
        """Pixels (row, col) of a glyph's bitmap at coverage >= 128, cached per glyph."""
        if gid not in self.solids:
            self.face.load_glyph(gid, self.load_flags)
            b = self.face.glyph.bitmap
            self.solids[gid] = [(r, c) for r in range(b.rows) for c in range(b.width) if b.buffer[r * b.pitch + c] >= 128]
        return self.solids[gid]


def device_positions(cps, font):
    """[(cp, ink_left_px, ink_top_px, has_ink, glyph)] as render.draw_line would draw them (blit recorded)."""
    recorded = []

    def record(img, g, x, y):
        # blit draws the bitmap at (x + left, y - top): record that ink corner. A
        # plain glyph's bearing carries any GPOS shift the converter folded in (the
        # danda); a PUA composite's bitmap covers its whole run and is compared with
        # the union ink of that run on the reference side.
        recorded.append((g["cp"], x + g["left"], y - g["top"], g["w"] > 0 and g["h"] > 0, g))

    saved = render.blit
    render.blit = record
    try:
        class Img:
            width, height = 100000, 1000
        render.draw_line(Img(), font, cps, 0, 0)
    finally:
        render.blit = saved
    return recorded


_DEVICE_SOLID = {}


def device_solid(g):
    """Pixels (row, col) of a device glyph at 2-bit value >= 2 (the converter's coverage >= 128), cached per cp."""
    if g["cp"] not in _DEVICE_SOLID:
        w, bits = g["w"], g["bits"]
        _DEVICE_SOLID[g["cp"]] = [(i // w, i % w) for i in range(w * g["h"]) if (bits[i // 4] >> (6 - 2 * (i % 4))) & 3 >= 2]
    return _DEVICE_SOLID[g["cp"]]


def touching(mark, others):
    """Share of the mark's solid pixels that lie on, or next to (8-neighbourhood), solid ink of
    other glyphs: a small mark that touches a stroke fuses with it on the page. Both arguments
    are lists of (x0, y0, pixels)."""
    pix = {(y0 + r, x0 + c) for x0, y0, px in mark for r, c in px}
    if not pix:
        return 0.0
    ink = set()
    for x0, y0, px in others:
        ink.update((y0 + r, x0 + c) for r, c in px)
    near = sum(1 for y, x in pix if any((y + a, x + b) in ink for a in (-1, 0, 1) for b in (-1, 0, 1)))
    return near / len(pix)


# Contact thresholds (share of a mark's solid pixels on or next to other ink), from the
# 2026-09-22 calibration: fused dots read 1.00 (भूमिं), collisions 0.39-0.77, clean marks 0.00-0.09.
MERGED_DEVICE, MERGED_REFERENCE = 0.8, 0.2
TOUCHING_DEVICE, TOUCHING_MARGIN = 0.3, 0.25


def main():
    ttf, cpfont, wordfile = sys.argv[1:4]
    tol = float(sys.argv[sys.argv.index("--tolerance") + 1]) if "--tolerance" in sys.argv else 1.5
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 4
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    dump = open(sys.argv[sys.argv.index("--dump") + 1], "w", encoding="utf-8") if "--dump" in sys.argv else None
    table, spec = hb_parity.load_table(cpfont)
    render.SPEC = spec
    hb_parity.KA, hb_parity.RA, hb_parity.VIRAMA = spec.probe, spec.ra, spec.virama
    hb_parity.BLOCK_BASE, hb_parity.CONSONANTS = spec.block_base, tuple(spec.consonants)
    hb_parity.INIT_SIGNS = set(spec.init_signs)  # expand() needs it; hb_parity.main sets it too
    size = int(cpfont.rsplit("_", 1)[1].split(".")[0])
    font = render.load_cpfont(cpfont)
    base_glyph = font["glyph"]

    def glyph(cp):
        g = base_glyph(cp)
        if g is not None:
            g = dict(g, cp=cp)
        return g
    font["glyph"] = glyph
    import freetype
    face = freetype.Face(ttf)
    face.set_char_size(size << 6, size << 6, 150, 150)
    unit_scale = (size * 150.0 / 72.0) / face.units_per_EM
    ref = Ref(ttf, unit_scale, face, freetype.FT_LOAD_RENDER, spec)
    sh = hb_parity.Shaper(ttf, spec)
    # Every form's glyphs come from the builder's own run for this table (fontcheck
    # refuses a table that is not a fresh build of the TTF), as hb_parity.main does.
    loaded = fontcheck.load(ttf, cpfont)
    print(loaded.header)
    runs = fontcheck.runs(loaded, sh.font)
    words = [w.strip() for w in open(wordfile, encoding="utf-8") if w.strip()]
    if limit:
        words = words[:limit]
    shaped = subprocess.run([os.path.join(HERE, "shape_cli"), cpfont], input="\n".join(words) + "\n",
                            capture_output=True, text=True).stdout.splitlines()
    assert len(shaped) == len(words), (len(shaped), len(words))
    compared = skipped = over = dotted = 0
    groups = collections.defaultdict(list)
    contact_groups = collections.defaultdict(list)
    for word, line in zip(words, shaped):
        cps = [int(t, 16) for t in line.split()]
        dev = device_positions(cps, font)
        # Expand the device stream to HarfBuzz glyph names with a device x per glyph,
        # exactly as hb_parity.device_glyphs does (sign variants by class come from the
        # builder's own enumeration), then to what the font draws for a precomposed
        # letter, so both sides carry one name per drawn glyph. Only the first name of
        # a run gets the device position, and spans its run: the reference side of a
        # multi-glyph run is the union ink of its glyphs (the bitmap was rendered from
        # that run, so its ink corner need not belong to the first glyph, which may be
        # a mark with a large GPOS offset: तर्कैः).
        names, xs, ys, is_mark, spans, entry = [], [], [], [], [], []
        for e, (cp, x, y, ink, _) in enumerate(dev):
            if cp in runs:
                run = [g for g in runs[cp] if g not in PLACEHOLDERS]
            elif cp in table:
                run = [g for g in hb_parity.expand(cp, table[cp], sh) if g not in PLACEHOLDERS]
            elif cp in (0x200C, 0x200D):
                continue
            else:
                run = [sh.nominal(cp)]
            run = sh.drawn(run)  # ई = इ + reph mark: one device glyph, two reference glyphs
            for i, g in enumerate(run):
                names.append(g)
                xs.append(x if i == 0 and ink else None)  # inner glyphs: not compared
                ys.append(y)
                is_mark.append(render.is_combining(cp) if i == 0 else None)
                spans.append(len(run) if i == 0 else None)
                entry.append(e)
        r = ref.shape(word)
        rnames = sh.drawn([g[0] for g in r])
        if any(g[0] in hb_parity.DOTTED_CIRCLES for g in r):
            dotted += 1  # HarfBuzz props a word-initial mark on a dotted circle, the device does not
            continue
        if rnames != names or len(r) != len(names):
            skipped += 1  # sequence differs: hb_parity's business
            continue
        compared += 1
        # Per-step deltas, not absolute positions: the renderer snaps each advance
        # to a pixel (12.4 differential rounding), which drifts up to a pixel or
        # two over a long word by design. A spacing glyph is measured from the
        # previous spacing glyph, a mark from its base.
        # Ink corners on both sides; the reference y grows upwards (bitmap_top),
        # the device y downwards (baseline - top), so compare mark heights as
        # (mark top - base top) on each side.
        maxdx, maxdy, culprit_x, culprit_y = 0.0, 0.0, None, None
        prev = None  # (ref x, ref top, dev x, dev top) of the last spacing glyph
        for j, (dx_dev, dy_dev, mark, span) in enumerate(zip(xs, ys, is_mark, spans)):
            inked = [g for g in r[j:j + span] if g[4]] if dx_dev is not None else []
            if not inked:
                continue
            name = r[j][0]
            rx, rtop = min(g[1] for g in inked), max(g[3] for g in inked)
            if prev is not None:
                dx = abs((rx - prev[0]) - (dx_dev - prev[2]))
                dy = abs((rtop - prev[1]) + (dy_dev - prev[3])) if mark else 0.0
                if dx > maxdx:
                    maxdx, culprit_x = dx, name
                if dy > maxdy:
                    maxdy, culprit_y = dy, name
            if not mark or prev is None:
                prev = (rx, rtop, dx_dev, dy_dev)
        if maxdx > tol or maxdy > tol:
            over += 1
            culprit = culprit_x if maxdx > tol else culprit_y + " (dy)"
            groups[culprit].append((word, maxdx, maxdy))
        # Contact of every mark with the other glyphs, device vs reference.
        contacts = []
        dev_boxes = [(x, y, device_solid(g)) for _, x, y, ink, g in dev]
        ref_boxes = [(round(g[1]), -round(g[3]), ref.solid(g[5])) for g in r]
        for j, (mark, span) in enumerate(zip(is_mark, spans)):
            if not mark or xs[j] is None:
                continue
            e = entry[j]
            on_device = touching([dev_boxes[e]], dev_boxes[:e] + dev_boxes[e + 1:])
            if on_device < TOUCHING_DEVICE:
                continue
            in_reference = touching(ref_boxes[j:j + span], ref_boxes[:j] + ref_boxes[j + span:])
            if on_device >= MERGED_DEVICE and in_reference < MERGED_REFERENCE:
                kind = "merged"
            elif on_device - in_reference >= TOUCHING_MARGIN:
                kind = "touching"
            else:
                continue
            contacts.append(f"{kind}:{r[j][0]}")
            contact_groups[(kind, r[j][0])].append((word, on_device, in_reference))
        if dump:
            dump.write(f"{word}\t{maxdx:.1f}\t{maxdy:.1f}\t{culprit_x or '-'}\t{culprit_y or '-'}\t{','.join(contacts) or '-'}\n")
    print(f"{len(words)} words, {compared} compared, {skipped} skipped (sequence differs), "
          f"{dotted} skipped (dotted circle), "
          f"{over} over {tol} px ({100.0 * over / max(compared, 1):.2f}%), "
          f"{sum(len(v) for k, v in contact_groups.items() if k[0] == 'merged')} marks merged, "
          f"{sum(len(v) for k, v in contact_groups.items() if k[0] == 'touching')} touching")
    for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"== {key}: {len(items)}")
        for word, dx, dy in sorted(items, key=lambda t: -max(t[1], t[2]))[:show]:
            print(f"  {word}  dx {dx:.1f} dy {dy:.1f}")
    print(f"-- contact: merged = device >= {MERGED_DEVICE:.0%} and HarfBuzz < {MERGED_REFERENCE:.0%} of the mark's "
          f"pixels on or next to other ink; touching = device >= {TOUCHING_DEVICE:.0%} and "
          f">= {TOUCHING_MARGIN:.0%} above HarfBuzz")
    for (kind, key), items in sorted(contact_groups.items(), key=lambda kv: (kv[0][0] != "merged", -len(kv[1]))):
        print(f"-- {kind} {key}: {len(items)}")
        for word, dev_share, ref_share in sorted(items, key=lambda t: t[2] - t[1])[:show]:
            print(f"  {word}  device {dev_share:.2f} reference {ref_share:.2f}")
    if dump:
        dump.close()


if __name__ == "__main__":
    main()
