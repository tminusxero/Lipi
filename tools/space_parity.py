#!/usr/bin/env python3
"""Inter-word parity for a word that starts with a danda: the gap between the
previous word's ink and the danda's ink, device against HarfBuzz.

    space_parity.py FONT.ttf FONT_N.cpfont BOOK.epub|TEXT.txt [--tolerance PX] [--show N]

word_parity.py shapes one word at a time, so it cannot see the space between
words. Here every "word SPACE danda-word" of the book's paragraphs is shaped by
HarfBuzz as one run (what a HarfBuzz-based reader draws: Tiro drops the danda's
built-in space after a space character) and laid out by the device model: each
word through shape_cli and render.py's draw loop, the words joined by the
reader's space (GfxRenderer::getSpaceAdvance for SD fonts: the space advance,
minus the danda's share from the cluster table when the font records one).
Reported for the device without the share ("before") and with it ("after"):
occurrences whose gap differs from HarfBuzz by more than the tolerance, and
the mean and largest difference. Reads its inputs, writes nothing."""
import collections
import html
import os
import re
import subprocess
import sys
import zipfile

import freetype
import uharfbuzz as hb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import fontcheck  # noqa: E402
import hb_parity  # noqa: E402
import render  # noqa: E402
from builder import shaping as indic_shaping  # noqa: E402

DANDAS = (0x0964, 0x0965)
BLOCK_TAG = re.compile(r"<(?:/?(?:p|div|h[1-6]|li|td|th|tr|blockquote|section)\b[^>]*|br\s*/?)>", re.I)


def paragraphs(path):
    """Paragraph texts of an EPUB (block tags split, inline tags dropped) or lines of a text file."""
    if not path.endswith(".epub"):
        yield from open(path, encoding="utf-8")
        return
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if name.endswith((".xhtml", ".html", ".htm")):
                text = z.read(name).decode("utf-8", "ignore")
                text = re.sub(r"<(script|style|head)\b.*?</\1>", "", text, flags=re.S | re.I)
                for block in BLOCK_TAG.split(text):
                    yield html.unescape(re.sub(r"<[^>]+>", "", block))


def pairs(path):
    """Counter of (previous word, danda word) over the book."""
    out = collections.Counter()
    for para in paragraphs(path):
        words = para.split()
        for prev, word in zip(words, words[1:]):
            if ord(word[0]) in DANDAS:
                out[(prev, word)] += 1
    return out


def table_shares(cpfont):
    """{danda cp: share/256} from the cluster table's 06 02 1n rows."""
    d = open(cpfont, "rb").read()
    off = int.from_bytes(d[32 + 28:32 + 32], "little")
    if not off:
        return {}
    size = indic_shaping.packed_table_bytes(d[off:off + indic_shaping.PACKED_DIRECTORY_BYTES])
    shares = {}
    for kb, _meta, value in indic_shaping.unpack_table(d[off:off + size]):
        if len(kb) == 3 and kb[0] == indic_shaping.KEY_FORMAT and kb[1] == indic_shaping.KEY_INIT:
            shares[DANDAS[(kb[2] & 0x0F) - 1]] = value & 0x1FFF
    return shares


class Reference:
    """HarfBuzz + FreeType ink extents of the two words shaped as one run."""

    def __init__(self, ttf, spec, size):
        self.font = hb.Font(hb.Face(hb.Blob.from_file_path(ttf)))
        self.spec = spec
        self.face = freetype.Face(ttf)
        self.face.set_char_size(size << 6, size << 6, 150, 150)
        self.scale = (size * 150.0 / 72.0) / self.face.units_per_EM
        self.ink = {}

    def extent(self, gid):
        if gid not in self.ink:
            self.face.load_glyph(gid, freetype.FT_LOAD_RENDER)
            g = self.face.glyph
            self.ink[gid] = (g.bitmap_left, g.bitmap.width) if g.bitmap.width and g.bitmap.rows else None
        return self.ink[gid]

    def gap(self, prev, word):
        """Danda ink left minus the previous word's ink right, in px."""
        buf = hb.Buffer()
        buf.add_codepoints([ord(c) for c in prev + " " + word])
        buf.script, buf.language = self.spec.hb_script, self.spec.hb_language
        buf.direction = "ltr"
        hb.shape(self.font, buf, {})
        split = len(prev) + 1  # clusters are codepoint indices; the space is split - 1
        right, left, x = None, None, 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            ext = self.extent(info.codepoint)
            if ext is not None:
                ink_l = (x + pos.x_offset) * self.scale + ext[0]
                if info.cluster < split - 1:
                    right = max(right if right is not None else ink_l + ext[1], ink_l + ext[1])
                elif info.cluster >= split and left is None:
                    left = ink_l
            x += pos.x_advance
        return None if right is None or left is None else left - right


def device_word(cps, font):
    """(ink extents [(left, right)], end x) of a word drawn at x = 0: the ink from
    render.draw_line (kerned, as the device draws), the end from the unkerned
    advance sum the device lays the next word out from (GfxRenderer::getTextAdvanceX
    reads the SD advance table without kerning; the layout-kerning decision is open,
    handoff item 2)."""
    inks = []

    def record(img, g, x, y):
        if g["w"] and g["h"]:
            inks.append((x + g["left"], x + g["left"] + g["w"]))

    saved = render.blit
    render.blit = record
    try:
        class Img:
            width, height = 100000, 1000
        render.draw_line(Img(), font, cps, 0, 0)
    finally:
        render.blit = saved
    end_fp = 0
    for cp in cps:
        if render.is_combining(cp):
            continue
        g = font["glyph"](cp)
        if g is not None:
            end_fp += g["adv"]
    return inks, (end_fp + 8) >> 4  # fp4::toPixel


def main():
    ttf, cpfont, book = sys.argv[1:4]
    tol = float(sys.argv[sys.argv.index("--tolerance") + 1]) if "--tolerance" in sys.argv else 1.0
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 5
    _table, spec = hb_parity.load_table(cpfont)
    print(fontcheck.load(ttf, cpfont).header)  # the table is this TTF's build, or stop here
    render.SPEC = spec
    size = int(cpfont.rsplit("_", 1)[1].split(".")[0])
    font = render.load_cpfont(cpfont)
    space_fp = font["glyph"](0x20)["adv"]
    shares = table_shares(cpfont)
    found = pairs(book)
    if not found:
        print(f"{os.path.basename(book)}: no danda after a space")
        return
    keys = list(found)
    words = sorted({w for pair in keys for w in pair})
    shaped = subprocess.run([os.path.join(HERE, "shape_cli"), cpfont], input="\n".join(words) + "\n",
                            capture_output=True, text=True).stdout.splitlines()
    assert len(shaped) == len(words), (len(shaped), len(words))
    cps_of = {w: [int(t, 16) for t in line.split()] for w, line in zip(words, shaped)}
    ref = Reference(ttf, spec, size)
    stats = {"before": [], "after": []}
    worst = []
    for prev, word in keys:
        n = found[(prev, word)]
        want = ref.gap(prev, word)
        prev_inks, prev_end = device_word(cps_of[prev], font)
        word_inks, _ = device_word(cps_of[word], font)
        if want is None or not prev_inks or not word_inks:
            continue
        danda = cps_of[word][0]
        lead_fp = font["glyph"](danda)["adv"] * shares.get(danda, 0) // 256
        for label, lead in (("before", 0), ("after", lead_fp)):
            space_px = (space_fp - lead + 8) >> 4  # fp4::toPixel
            got = prev_end + space_px + word_inks[0][0] - max(r for _l, r in prev_inks)
            stats[label].append((got - want, n))
            if label == "after":
                worst.append((abs(got - want), n, prev, word, got, want))
    total = sum(n for _d, n in stats["after"])
    share_txt = " ".join(f"U+{cp:04X} {s}/256" for cp, s in sorted(shares.items())) or "none"
    print(f"{os.path.basename(cpfont)} {os.path.basename(book)}: {total} dandas after a space "
          f"({len(stats['after'])} pairs), table share {share_txt}")
    for label in ("before", "after"):
        rows = stats[label]
        off = sum(n for d, n in rows if abs(d) > tol)
        mean = sum(abs(d) * n for d, n in rows) / total
        print(f"  {label:6s}: over {tol:g} px {off:6d} ({100.0 * off / total:5.1f}%), "
              f"mean |gap - HarfBuzz| {mean:4.2f} px, max {max(abs(d) for d, _n in rows):4.1f} px")
    for d, n, prev, word, got, want in sorted(worst, reverse=True)[:show]:
        print(f"    {prev} {word}  x{n}: device gap {got:.1f} px, HarfBuzz {want:.1f} px")


if __name__ == "__main__":
    main()
