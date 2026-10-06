#!/usr/bin/env python3
"""Host emulation of GfxRenderer::drawText for a .cpfont: renders shaped
codepoint streams (from shape_cli) into a PNG so Bengali output can be
checked visually without hardware. Mirrors the advance stepping (12.4
fixed-point differential rounding) and the combining-mark anchoring in
the host renderer (CrossInk lib/EpdFont/EpdFontData.h), driven by the script's spec."""
import os, struct, subprocess, sys
from PIL import Image, ImageDraw

def load_cpfont(path):
    data = open(path, "rb").read()
    assert data[:8] == b"CPFONT\0\0"
    toc = struct.unpack_from("<BBHIIBhhHHBBBII", data, 32)
    (sid, skind, scount, ivc, gc, advY, asc, desc, kL, kR, kLc, kRc, lig, dataOff, shapeOff) = toc
    ivs = [struct.unpack_from("<III", data, dataOff + 12 * i) for i in range(ivc)]
    glyphsOff = dataOff + 12 * ivc
    kernL = glyphsOff + 16 * gc
    kernR = kernL + 3 * kL
    kernM = kernR + 3 * kR
    ligOff = kernM + kLc * kRc
    bmpOff = ligOff + 8 * lig
    def glyph(cp):
        for a, b, o in ivs:
            if a <= cp <= b:
                idx = o + cp - a
                w, h, adv, left, top, dlen, aa, ab, doff = struct.unpack_from("<BBHhhHBBI", data, glyphsOff + 16 * idx)
                extra, doff = doff >> 24, doff & 0xFFFFFF  # the top byte of the data offset is a base's third anchor
                return dict(w=w, h=h, adv=adv, left=left, top=top, above=aa, below=ab, extra=extra,
                            bits=data[bmpOff + doff: bmpOff + doff + dlen])
        return None
    def classes(off, count):
        return {struct.unpack_from("<H", data, off + 3 * i)[0]: data[off + 3 * i + 2] for i in range(count)}
    left_classes, right_classes = classes(kernL, kL), classes(kernR, kR)

    def kern(left_cp, right_cp):
        # Mirrors EpdFont::getKerning for SD-card fonts: 1-based classes into the
        # dense int8 matrix, 4.4 fixed-point (the same 1/16 px unit as advances).
        lc, rc = left_classes.get(left_cp, 0), right_classes.get(right_cp, 0)
        if not lc or not rc:
            return 0
        return struct.unpack_from("<b", data, kernM + (lc - 1) * kRc + (rc - 1))[0]
    return dict(glyph=glyph, kern=kern, advanceY=advY, ascender=asc, descender=desc)

# The script's mark facts come from its builder spec (providers/*/spec.py), set by
# the caller or from the cpfont's table kind in main(); no per-script list here.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from builder import shaping as indic_shaping  # noqa: E402

SPEC = None

def spec_for_cpfont(path):
    kind = open(path, "rb").read()[33] & ~indic_shaping.TOC_KIND_PACKED
    return next((s for s in indic_shaping.SCRIPTS.values() if s.shape_kind == kind), None)

def is_combining(cp):
    return 0x0300 <= cp <= 0x036F or (SPEC is not None and SPEC.is_mark(cp))

def attaches_below(cp):
    # Mirrors combiningMark::attachesBelow through the spec.
    return SPEC is not None and SPEC.attaches_below(cp)

def anchored_offset(base_byte, mark_byte):
    # Mirrors glyphAnchor::markOffset (half pixels biased by 128; 0 = none).
    if not base_byte or not mark_byte: return None
    half = (base_byte - 128) - (mark_byte - 128)
    return (half + 1) // 2 if half >= 0 else -((-half + 1) // 2)

def mark_offset(below, bg, mg, adv_px):
    # Mirrors glyphAnchor::markOffsetWithMode (placement modes) through the builder's helper.
    return indic_shaping.mark_offset_px(below, (bg.get("above", 0), bg.get("below", 0), bg.get("extra", 0)), adv_px,
                                        (mg.get("above", 0), mg.get("below", 0)))

def anchor_for(cp):
    # Mirrors the host renderer's anchor choice (Lipi::anchorClass) through the spec.
    cls = SPEC.anchor_class(cp) if SPEC is not None else None
    return {"Center": "CenterNative", "Right": "RightNative", "Pen": "PenNative"}.get(cls, "CenterRaised")

def anchor_shift(anchor, base_w, mark_w):
    if anchor == "LeftNative": return 0
    if anchor == "RightNative": return base_w - mark_w
    return base_w // 2 - mark_w // 2

def raise_above(anchor, mark_top, mark_h, base_top):
    if anchor != "CenterRaised": return 0
    if mark_top - mark_h <= 0: return 0
    gap = mark_top - mark_h - base_top
    return (1 - gap) if gap < 1 else 0

def blit(img, g, x, y_baseline):
    px = img.load()
    w, h = g["w"], g["h"]
    bits = g["bits"]
    for r in range(h):
        for c in range(w):
            i = r * w + c
            v = (bits[i // 4] >> (6 - 2 * (i % 4))) & 3
            if v:
                X = x + g["left"] + c
                Y = y_baseline - g["top"] + r
                if 0 <= X < img.width and 0 <= Y < img.height:
                    shade = 255 - v * 85
                    px[X, Y] = min(px[X, Y], shade)

def draw_line(img, font, cps, x, y_baseline):
    lastX, lastLeft, lastW, lastTop = x, 0, 0, 0
    lastBase = {}
    prevAdv = 0
    prev = 0
    for cp in cps:
        g = font["glyph"](cp)
        if is_combining(cp):
            if not g: continue
            below = attaches_below(cp)
            off = mark_offset(below, lastBase, g, (prevAdv + 8) >> 4)
            anc = anchor_for(cp)
            if off is not None:
                cx, rb = lastX + off, 0
            else:
                rb = raise_above(anc, g["top"], g["h"], lastTop)
                if anc == "PenNative":
                    cx = lastX + ((prevAdv + 8) >> 4)
                else:
                    cx = lastX + lastLeft + anchor_shift(anc, lastW, g["w"]) - g["left"]
            blit(img, g, cx, y_baseline - rb)
            continue
        if prev:
            # GfxRenderer snaps previous advance + kern as one sum (12.4 and 4.4 share a unit).
            lastX += (prevAdv + font.get("kern", lambda a, b: 0)(prev, cp) + 8) >> 4
        if g is None:
            g = font["glyph"](0xFFFD)
        lastLeft, lastW, lastTop, prevAdv = g["left"], g["w"], g["top"], g["adv"]
        lastBase = g
        blit(img, g, lastX, y_baseline)
        prev = cp
    return lastX + ((prevAdv + 8) >> 4)

def main():
    cpfont, out_png, textfile = sys.argv[1], sys.argv[2], sys.argv[3]
    global SPEC
    SPEC = spec_for_cpfont(cpfont)
    font = load_cpfont(cpfont)
    lines = [l.rstrip("\n") for l in open(textfile, encoding="utf-8")]
    shaped = subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "shape_cli"), cpfont], input="\n".join(lines) + "\n",
                            capture_output=True, text=True).stdout.splitlines()
    lh = font["advanceY"] + 6
    img = Image.new("L", (900, lh * len(lines) + 20), 255)
    for i, line in enumerate(shaped):
        cps = [int(t, 16) for t in line.split()] if line.strip() else []
        draw_line(img, font, cps, 10, 10 + i * lh + font["ascender"])
    img.save(out_png)
    print("wrote", out_png, img.size)

if __name__ == "__main__":
    main()
