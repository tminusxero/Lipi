#!/usr/bin/env python3
"""Compare the device Indic shaper against desktop HarfBuzz over a word list.

    hb_parity.py FONT.ttf FONT.cpfont WORDS.txt [--show N]

The script is read from the cpfont's table kind (indic_shaping.SCRIPTS).

Device side: shape_cli (the firmware's Lipi engine with the .cpfont cluster
table) emits codepoints; each PUA form stands for the HarfBuzz glyph run the
builder rasterised it from (fontcheck proves the file's table is that build's),
other codepoints map to their nominal glyph. Desktop side: HarfBuzz shapes the
whole word. Words whose glyph sequences differ are grouped by the kind of
difference so the gaps can be read off. The first output line names the
inputs (TTF and table hashes).
"""
import collections
import os
import struct
import subprocess
import sys

import uharfbuzz as hb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import fontcheck  # noqa: E402
from builder import shaping as indic_shaping  # noqa: E402

INIT_CP, FINA_CP = 0x2060, 0x2061
INIT_SIGNS = set()  # the script's signs with a word-initial form, set in main()
CLASS_CP, VARIANT_CP, FORMAT_CP, CLASS_INDEX_CP = 0x2062, 0x2063, 0x2064, 0x2100
# Set from the table kind in main(): the script's KA, RA and virama.
KA = RA = VIRAMA = 0
BLOCK_BASE, CONSONANTS = 0, ()
# Glyphs that draw nothing: joiners, the zero-width space some fonts insert after a
# reph (Noto Sans Bengali uni200B, 0 advance, empty bitmap) and null marks.
PLACEHOLDERS = ("space", "uni200B", "uni200C", "uni200D", "NullMark", "dummymarkdeva", "bnNull")
DOTTED_CIRCLES = ("uni25CC", "BASE", "dottedcircle")


def load_table(path):
    """{pua: key} plus the ScriptSpec, read from the cpfont's first style."""
    d = open(path, "rb").read()
    toc = d[32:64]
    kind = toc[1] & ~indic_shaping.TOC_KIND_PACKED  # the flag marks the packed layout
    cnt = struct.unpack_from("<H", toc, 2)[0]
    off = struct.unpack_from("<I", toc, 28)[0]
    spec = next(s for s in indic_shaping.SCRIPTS.values() if s.shape_kind == kind)
    size = indic_shaping.packed_table_bytes(d[off:off + indic_shaping.PACKED_DIRECTORY_BYTES])
    rows = indic_shaping.unpack_table(d[off:off + size])
    assert len(rows) == cnt, (len(rows), cnt)
    out = {}
    fixed = {1: 0x200D, 2: INIT_CP, 3: FINA_CP, 4: CLASS_CP, 5: VARIANT_CP, 6: FORMAT_CP}

    def cp_of(b):
        if b in fixed:
            return fixed[b]
        if 0x10 <= b < 0x20:
            return CLASS_INDEX_CP + (b & 0x0F)
        return spec.block_base + (b & 0x7F)

    for kb, _meta, value in rows:
        key = tuple(cp_of(b) for b in kb)
        value &= 0x1FFF  # post-sign class in the top bits
        if value == 0x1FFF or key[0] in (CLASS_CP, FORMAT_CP):
            continue  # bookkeeping entry without a glyph
        out.setdefault(0xE000 + value, key)
    return out, spec


class Shaper:
    def __init__(self, ttf, spec):
        self.font = hb.Font(hb.Face(hb.Blob.from_file_path(ttf)))
        self.cache = {}
        self.consonants = set(spec.consonants)
        # Letters the font draws as another sequence (Noto Devanagari 2.006: ई = इ + a
        # reph-like mark, ऐ = ए + ै). The device emits the letter's own glyph; both are
        # counted as the drawn sequence. Derived from the font, no per-script list.
        self.decomposed = {}
        for cp in range(spec.block_base, spec.block_base + 0x80):
            gid = self.font.get_nominal_glyph(cp)
            if not gid:
                continue
            nominal = self.font.glyph_to_string(gid)
            run = [g for g in self.names(chr(cp)) if g not in PLACEHOLDERS]
            if run and run != [nominal] and not any(g in DOTTED_CIRCLES for g in run):
                self.decomposed[nominal] = run

    def drawn(self, glyphs):
        """Glyph names with precomposed letters replaced by what the font draws for them."""
        out = []
        for g in glyphs:
            out.extend(self.decomposed.get(g, (g,)))
        return out

    def names(self, text):
        if text in self.cache:
            return self.cache[text]
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.font, buf, {})
        out = [self.font.glyph_to_string(g.codepoint) for g in buf.glyph_infos]
        self.cache[text] = out
        return out

    def nominal(self, cp):
        gid = self.font.get_nominal_glyph(cp)
        return self.font.glyph_to_string(gid) if gid else f"MISSING{cp:04X}"


def expand(cp, key, sh):
    """HarfBuzz glyphs a PUA form stands for, re-derived from its key the way
    the builder obtains it. Kept as the fallback for a table entry the builder
    holds no run for; the tools take every run they can from the builder's
    forms (fontcheck.runs), which is what the bitmap was drawn from."""
    ka = sh.nominal(KA)
    plain = tuple(c for c in key if c not in (INIT_CP, FINA_CP))
    text = "".join(chr(c) for c in plain)
    pre, post = indic_shaping.PUA_PRE, indic_shaping.PUA_POST
    if (pre[0] <= cp <= pre[1] or post[0] <= cp <= post[1]) and plain[0] == VIRAMA:
        # A post-base consonant form fused with a modifier (Tiro ্যঁ): carrier first and
        # last; the word-final one (FINA key) is shaped at the end of the word.
        if key[-1] == FINA_CP:
            run = [g for g in sh.names(chr(KA) + text) if g not in PLACEHOLDERS]
            return run[1:] if run and run[0] == ka else run
        run = [g for g in sh.names(chr(KA) + text + chr(KA)) if g not in PLACEHOLDERS]
        return run[1:-1] if len(run) >= 2 and run[0] == ka and run[-1] == ka else run
    if pre[0] <= cp <= pre[1] or post[0] <= cp <= post[1]:
        # Sign forms: the glyphs of the run that are not the base's own. The
        # base is the key without the sign, modifiers and reph; generic keys
        # (no base) are shaped on the probe letter.
        body = list(plain)
        if body[:2] == [RA, VIRAMA]:
            body = body[2:]
        base = [c for c in body if c in sh.consonants or c == VIRAMA or c == 0x200D]
        while base and base[-1] == VIRAMA:
            base.pop()
        generic = not base and key[0] not in (INIT_CP, FINA_CP)
        if not base:
            base = [KA]
            if body[:1] and body[0] not in sh.consonants:
                text = "".join(chr(c) for c in plain[:len(plain) - len(body)]) + chr(KA) + "".join(chr(c) for c in body)
        final = key[-1] == FINA_CP or key[0] == FINA_CP or key[-1] == VIRAMA  # a consonant + visible virama composite
        is_pre = pre[0] <= cp <= pre[1]
        # A sign with a word-initial form (ে ৈ) was shaped behind a probe letter
        # by the builder unless the key carries the INIT marker.
        lead = key[0] != INIT_CP and any(c in INIT_SIGNS for c in plain)

        def tail_of(t, base_run):
            t = (chr(KA) if lead else "") + t
            run = [g for g in (sh.names(t) if final else sh.names(t + chr(KA))) if g not in PLACEHOLDERS]
            if lead and run and run[0] == ka:
                run = run[1:]
            if not final and run and run[-1] == ka:
                run = run[:-1]
            n = len(base_run)
            if is_pre:
                return run[:-n] if run[-n:] == base_run else None
            return run[n:] if run[n:] and run[:n] == base_run else None

        if generic:
            # A generic form is the tail most consonants share (as the builder
            # chooses it), not the probe letter's.
            prefix = "".join(chr(c) for c in plain[:len(plain) - len(body)])
            rest = "".join(chr(c) for c in body)
            tails = collections.Counter()
            for c in sorted(sh.consonants):
                t = tail_of(prefix + chr(c) + rest, [sh.nominal(c)])
                if t:
                    tails[tuple(t)] += 1
            if tails:
                return list(tails.most_common(1)[0][0])
        base_run = [g for g in sh.names("".join(chr(c) for c in base)) if g not in PLACEHOLDERS]
        t = tail_of(text, base_run)
        if t is not None:
            return t
        run = [g for g in sh.names((chr(KA) if lead else "") + text) if g not in PLACEHOLDERS]
        if lead and run and run[0] == ka:
            run = run[1:]
        return run[:1] if is_pre else run[-1:]
    if len(key) == 2 and 0 <= key[0] - BLOCK_BASE <= 3 and key[0] != key[1]:
        # A modifier variant after a sign (ঁ.alt after a wide ি), keyed modifier + sign:
        # the modifier glyph that differs from the plain one on some consonant.
        plain_mod = sh.names(chr(KA) + chr(key[0]))[-1:]
        for c in CONSONANTS:
            names = sh.names(chr(c) + chr(key[1]) + chr(key[0]))
            if len(names) == 3 and names[-1:] != plain_mod:
                return names[-1:]
        return plain_mod
    if 0xF100 <= cp <= 0xF1FF or 0xF000 <= cp <= 0xF0FF:
        if plain[:2] == (RA, VIRAMA):  # reph (fused with signs): carrier after the ra + virama
            carried = "".join(chr(c) for c in plain[:2]) + chr(KA) + "".join(chr(c) for c in plain[2:])
            return [g for g in sh.names(carried) if g != ka]
        if plain[0] == VIRAMA:  # subjoined mark (rakar, ra-phala): alone it sits on a dotted circle
            alone = [g for g in sh.names(text) if g != "uni25CC"]
            if alone:
                return alone
        return [g for g in sh.names(chr(KA) + text) if g != ka]  # fused sign: carrier first
    if key[-1] == FINA_CP:  # a word-final form alone; a leading virama sits on a dotted circle
        return [g for g in sh.names(text) if g not in DOTTED_CIRCLES]
    if plain[0] == VIRAMA:  # spacing post-base form (ya-phala): carrier first
        return [g for g in sh.names(chr(KA) + text + chr(KA)) if g != ka]
    if key[-1] == VIRAMA:  # consonant + visible virama composite: only ever drawn at the end of a word
        return sh.names(text)
    # Composites are shaped in word-internal context by the builder (a probe
    # letter after them, and one before when a sign with a word-initial form
    # is involved and the key carries no INIT marker).
    lead = key[0] != INIT_CP and any(c in INIT_SIGNS for c in plain)
    run = sh.names((chr(KA) if lead else "") + text + chr(KA))
    if lead and run and run[0] == ka:
        run = run[1:]
    return run[:-1] if run and run[-1] == ka else sh.names(text)


FALLBACKS = collections.Counter()  # PUA cps expanded from their key because the builder held no run


def device_glyphs(cps, table, sh, runs):
    out = []
    for cp in cps:
        if cp in runs:
            out.extend(g for g in runs[cp] if g not in PLACEHOLDERS)  # the builder's own run
        elif cp in table:
            FALLBACKS[cp] += 1
            out.extend(g for g in expand(cp, table[cp], sh) if g not in PLACEHOLDERS)
        elif cp == 0x200C or cp == 0x200D:
            continue
        else:
            out.append(sh.nominal(cp))
    return out


def classify(dev, ref):
    if dev == ref:
        return None
    if sorted(dev) == sorted(ref):
        return "order"
    extra_ref = collections.Counter(ref) - collections.Counter(dev)
    extra_dev = collections.Counter(dev) - collections.Counter(ref)
    variants = [g for g in extra_ref if "." in g]
    if variants and not [g for g in extra_dev if "." in g]:
        return "variant:" + ",".join(sorted({g.split(".", 1)[1] for g in variants}))
    virama = f"uni{VIRAMA:04X}"
    if virama in extra_dev and virama not in extra_ref:
        return "missing-conjunct"
    if any(g in DOTTED_CIRCLES for g in extra_ref):
        return "dotted-circle"
    return "other"


def main():
    ttf, cpfont, wordfile = sys.argv[1:4]
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 5
    words = [w.strip() for w in open(wordfile, encoding="utf-8") if w.strip()]
    global KA, RA, VIRAMA, BLOCK_BASE, CONSONANTS, INIT_SIGNS
    table, spec = load_table(cpfont)
    KA, RA, VIRAMA = spec.probe, spec.ra, spec.virama
    BLOCK_BASE, CONSONANTS, INIT_SIGNS = spec.block_base, spec.consonants, set(spec.init_signs)
    sh = Shaper(ttf, spec)
    # Every form's glyphs come from the builder's own run for this table
    # (fontcheck refuses a table that is not a fresh build of the TTF).
    loaded = fontcheck.load(ttf, cpfont)
    print(loaded.header)
    runs = fontcheck.runs(loaded, sh.font)
    res = subprocess.run([os.path.join(HERE, "shape_cli"), cpfont], input="\n".join(words) + "\n",
                         capture_output=True, text=True, check=True)
    lines = res.stdout.splitlines()
    assert len(lines) == len(words), (len(lines), len(words))
    groups = collections.defaultdict(list)
    same = 0
    for w, line in zip(words, lines):
        cps = [int(t, 16) for t in line.split()]
        dev = sh.drawn(device_glyphs(cps, table, sh, runs))
        ref = sh.drawn([g for g in sh.names(w) if g not in PLACEHOLDERS])  # joiners and placeholders draw nothing
        kind = classify(dev, ref)
        if kind is None:
            same += 1
        else:
            groups[kind].append((w, dev, ref))
    print(f"{len(words)} words, {same} identical ({100.0 * same / len(words):.1f}%)")
    for nominal, run in sorted(sh.decomposed.items()):
        print(f"  counted as drawn: {nominal} = {' '.join(run)}")
    if FALLBACKS:
        print(f"  {len(FALLBACKS)} table entries without a builder run were expanded from their key: "
              + " ".join(f"U+{cp:04X}x{n}" for cp, n in FALLBACKS.most_common(5)))
    for kind, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"\n== {kind}: {len(items)}")
        for w, dev, ref in items[:show]:
            print(f"  {w}")
            print(f"    device: {' '.join(dev)}")
            print(f"    hb    : {' '.join(ref)}")


if __name__ == "__main__":
    main()
