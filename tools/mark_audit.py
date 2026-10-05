#!/usr/bin/env python3
"""Mark placement audit for a built .cpfont: for every base glyph (letters,
vowel signs, cluster-table composites) x every combining mark (script marks and
PUA mark forms), compare where the device puts the mark (glyph anchors from the
file, else the anchorFor rules as mirrored in render.py) with HarfBuzz's GPOS
position. Errors in pixels at the file's size. Exit 1 with --strict when any
pair is off by more than --tolerance px.
Usage: mark_audit.py FONT.ttf FONT.cpfont [--strict] [--tolerance 1.0] [--show N] [--words WORDS.txt]
The first output line names the inputs (TTF and table hashes); a cpfont whose
table is not a fresh build of the TTF is refused (fontcheck.TableMismatch).
With --words, each mark also gets an in-text line: only the base + mark
sequences that occur in the word list as the device sees it (NFC, as the
reader composes text: Bengali য় is one glyph, Devanagari ड़ stays base + nukta),
each pair weighted by the number of words containing it, and the worst
among those. The all-pairs line still covers every plausible pair, including
sequences no book contains; --strict judges the in-text line when --words is
given, the all-pairs line otherwise. Only pairs the engine really draws as
base then mark are measured: every candidate sequence is shaped by shape_cli
(the firmware's engine with this table) and dropped when the device stream
does not contain the base followed by the mark (a nukta letter the engine
folds to its precomposed glyph, a cluster the table draws as one composite,
a hasanta the engine puts on the last consonant instead of the conjunct)."""
import unicodedata
import os, sys, collections, struct, subprocess, freetype, uharfbuzz as hb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from builder import shaping as indic_shaping  # noqa: E402
import fontcheck  # noqa: E402
import render  # noqa: E402

def main():
    ttf, cpfont = sys.argv[1], sys.argv[2]
    strict = '--strict' in sys.argv
    tol = float(sys.argv[sys.argv.index('--tolerance') + 1]) if '--tolerance' in sys.argv else 1.0
    show = int(sys.argv[sys.argv.index('--show') + 1]) if '--show' in sys.argv else 4
    wordfile = sys.argv[sys.argv.index('--words') + 1] if '--words' in sys.argv else None
    corpus = None
    if wordfile:
        corpus = [unicodedata.normalize('NFC', w.strip()) for w in open(wordfile, encoding='utf-8') if w.strip()]
    data = open(cpfont, 'rb').read()
    toc = struct.unpack_from("<BBHIIBhhHHBBBII", data, 32)
    kind = toc[1] & ~indic_shaping.TOC_KIND_PACKED
    spec = next(s for s in indic_shaping.SCRIPTS.values() if s.shape_kind == kind)
    render.SPEC = spec
    font = render.load_cpfont(cpfont)
    # Size from the file: advanceY is the line height; recover ppem from the header? Use the
    # bitmap scale the converter used: pixels per unit = size*150/72/upm, with size from the name.
    size = int(cpfont.rsplit('_', 1)[1].split('.')[0])
    face = freetype.Face(ttf); face.set_char_size(size << 6, size << 6, 150, 150)
    unit_scale = (size * 150.0 / 72.0) / face.units_per_EM
    # The forms and the plan the file's table was packed from (fontcheck refuses a
    # table that is not a fresh build of the TTF at this size).
    loaded = fontcheck.load(ttf, cpfont)
    print(loaded.header)
    cp_to_form, plan = loaded.cp_to_form, loaded.plan
    lead = plan.gid(spec.probe)
    def text_of(cp):
        f = cp_to_form.get(cp)
        return (cp,) if f is None else tuple(c for c in f.key if c < 0x2000 or c == indic_shaping.ZWJ)
    def run_of(cp):
        f = cp_to_form.get(cp)
        return [plan.gid(cp)] if f is None else list(f.run.gids)
    block = [cp for cp in range(spec.block_base, spec.block_base + 0x80) if plan.has(cp)]
    def is_mark(cp):
        f = cp_to_form.get(cp)
        if f is not None: return f.kind in indic_shaping.MARK_KINDS
        r = plan.shape((spec.probe, cp)); return len(r.glyphs) == 2 and r.glyphs[0][0] == lead and r.glyphs[1][1] == 0
    RARE = set(spec.rare_marks)  # Vedic and rare marks
    below_signs = set(spec.below_signs)
    def pure_cluster(cp):
        # letters, and composites made only of consonants + virama (+ ZWJ)
        f = cp_to_form.get(cp)
        if f is None: return cp < 0xE000
        return f.kind == indic_shaping.KIND_BASE and all(c in spec.consonants or c in (spec.virama, indic_shaping.ZWJ, spec.nukta) for c in f.key)
    def post_sign_base(cp):
        f = cp_to_form.get(cp)
        if f is None: return spec.block_base + 0x3E <= cp <= spec.block_base + 0x4C and cp not in below_signs and not render.is_combining(cp)
        return f.kind in (indic_shaping.KIND_BASE, indic_shaping.KIND_POST) and any(spec.block_base + 0x3E <= c <= spec.block_base + 0x4C and c not in below_signs for c in f.key) and not any(c in below_signs for c in f.key)
    def plausible(b, m):
        bf, mf = cp_to_form.get(b), cp_to_form.get(m)
        if bf is not None and bf.key[-1] == indic_shaping.ZWJ: return False  # marks never follow a half form
        if mf is not None and bf is not None and len(mf.key) >= 2 and mf.key[0] == spec.virama:
            bk = tuple(bf.key)
            if any(bk[i] == spec.virama and bk[i + 1] in spec.phala_consonants for i in range(len(bk) - 1)):
                return False  # a second rakar / phala on a cluster that already ends in one
        if b >= spec.block_base + 0x66 and b < 0xE000 and b not in spec.consonants: return False  # digits, symbols
        modifiers = tuple(spec.modifiers)
        if post_sign_base(b):  # after a post-base sign: a modifier, or the reph where it follows the sign (र्का)
            return m in modifiers or (spec.reph_after_post and m >= 0xE000 and cp_to_form[m].key[:2] == (spec.ra, spec.virama))
        if m in below_signs or m in (0xF000, 0xF001, 0xF300):
            return pure_cluster(b) and b >= 0xE000 or b in spec.consonants  # a second below mark on a base that has one is not text
        if b < 0xE000 and spec.block_base + 0x04 <= b <= spec.block_base + 0x14:
            return m in modifiers  # only modifiers follow an independent vowel
        return pure_cluster(b) or post_sign_base(b)
    bases = [cp for cp in block + sorted(cp_to_form) if not is_mark(cp) and font['glyph'](cp) and font['glyph'](cp)['adv'] > 0]
    marks = [cp for cp in block + sorted(cp_to_form) if is_mark(cp) and font['glyph'](cp)]

    def mtext_of(m):
        f = cp_to_form.get(m)
        return (m,) if f is None else tuple(c for c in f.key if c < 0x2000 or c == indic_shaping.ZWJ)

    # Pairs as the engine draws them: shape every plausible base + mark text (and
    # the same behind the probe letter, for signs that need a consonant first) with
    # shape_cli and keep the pair only when the device stream has the base's
    # codepoint followed by the mark's.
    candidates = [(b, m) for m in marks for b in bases if plausible(b, m)
                  and tuple(text_of(b)) + tuple(mtext_of(m)) not in plan._table]
    # The four text orders the HarfBuzz side tries below: base + mark, probe + base +
    # mark, mark + base (a reph precedes its base in text), mark + probe + base.
    ORDERS = 4
    seqs = []
    for b, m in candidates:
        bt = ''.join(chr(c) for c in text_of(b))
        mt = ''.join(chr(c) for c in mtext_of(m))
        seqs.extend((bt + mt, chr(spec.probe) + bt + mt, mt + bt, mt + chr(spec.probe) + bt))
    shaped = subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shape_cli'), cpfont],
                            input='\n'.join(seqs) + '\n', capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(shaped) == len(seqs), (len(shaped), len(seqs))
    drawn_as_pair = set()
    for i, (b, m) in enumerate(candidates):
        for line in shaped[ORDERS * i:ORDERS * i + ORDERS]:
            cps = [int(x, 16) for x in line.split()]
            if any(cps[k] == b and cps[k + 1] == m for k in range(len(cps) - 1)):
                drawn_as_pair.add((b, m))
                break
    otherwise = collections.Counter(m for b, m in candidates if (b, m) not in drawn_as_pair)
    print(f'  {len(drawn_as_pair)} of {len(candidates)} plausible pairs are drawn as base + mark by the engine; the rest fold, '
          f'fuse or reorder and are not measured')
    results = collections.defaultdict(list)
    fused = collections.Counter()
    for m in marks:
        mg = font['glyph'](m); mtext, mrun = text_of(m), run_of(m)
        below = render.attaches_below(m)
        for b in bases:
            if (b, m) not in drawn_as_pair: continue
            bg = font['glyph'](b); btext, brun = text_of(b), run_of(b)
            # HarfBuzz: base then mark (reph forms precede their base in text).
            hbx = None
            # Sequences: base + mark; probe + base + mark (a sign needs a consonant first); reph + base
            # (reph forms precede their base in text); reph + probe + sign (the reph drawn after a
            # post-base sign, र्का: ka, aa, reph).
            for seq, led in ((btext + mtext, False), ((spec.probe,) + btext + mtext, True), (mtext + btext, False),
                             (mtext + (spec.probe,) + btext, True)):
                out = plan.shape(seq)
                want = ([lead] if led else []) + brun + mrun
                if out.gids != want: continue
                skip = 1 if led else 0
                pen = sum(g[1] for g in out.glyphs[skip:skip + len(brun)])
                hbx = (pen + out.glyphs[skip + len(brun)][2]) * unit_scale  # px from the base origin
                # Ink left edge of the whole mark run (catches bitmaps baked with a probe offset).
                hbink = min(round((pen + g[2]) * unit_scale) + indic_shaping._glyph_gray(face, g[0], freetype.FT_LOAD_RENDER)[2]
                            for g in out.glyphs[skip + len(brun):] if indic_shaping._glyph_gray(face, g[0], freetype.FT_LOAD_RENDER)[0])
                break
            if hbx is None:
                # the font fuses or reorders this pair: the cluster table covers it, or it never occurs
                fused[m] += 1
                continue
            off = render.mark_offset(below, bg, mg, (bg['adv'] + 8) >> 4)
            if off is not None:
                devx = off
            else:
                anc = render.anchor_for(m)
                if anc == 'PenNative': devx = (bg['adv'] + 8) >> 4
                else: devx = bg['left'] + render.anchor_shift(anc, bg['w'], mg['w']) - mg['left']
            results[m].append((b, devx - hbx, off is not None, devx + mg['left'] - hbink))
    worst_all = 0
    worst_text = 0
    text_pairs = 0

    joiners = set(spec.consonants) | {spec.virama, indic_shaping.ZWJ, spec.nukta}

    def occurrences(b, m):
        """Words of the corpus containing the base + mark sequence (the key text of a
        composite; a PUA mark's key text, e.g. ্র for a rakar mark). A mark whose
        text ends in the virama counts only where nothing joins on after it: a
        virama before another consonant is a conjunct, not a drawn hasanta."""
        mtext = mtext_of(m)
        seq = ''.join(chr(c) for c in text_of(b) + mtext)
        if mtext[-1] != spec.virama:
            return sum(1 for w in corpus if seq in w)
        n = 0
        for w in corpus:
            start = 0
            while True:
                i = w.find(seq, start)
                if i < 0:
                    break
                j = i + len(seq)
                if j >= len(w) or ord(w[j]) not in joiners:
                    n += 1
                    break
                start = i + 1
        return n
    for m in marks:
        rows = results.get(m)
        if not rows:
            if fused[m] or otherwise[m]:
                print(f'  U+{m:04X} {chr(m) if m < 0xE000 else "PUA%04X" % m}: never drawn as base + mark '
                      f'(engine draws {otherwise[m]} pairs otherwise, HarfBuzz fuses {fused[m]})')
            continue
        a = [abs(e) for _, e, _, _ in rows]; anch = sum(1 for _, _, x, _ in rows if x)
        ink = [abs(e) for _, _, _, e in rows]
        bad = [(b, e) for b, e, _, _ in rows if abs(e) > tol]
        if m not in RARE: worst_all = max(worst_all, max(a), max(ink))
        label = (chr(m) if m < 0xE000 else f'PUA{m:04X}') + (' (rare)' if m in RARE else '')
        print(f'  U+{m:04X} {label:14s}: {len(rows):4d} bases, anchored {anch:4d}, mean |err| {sum(a)/len(a):.2f} px, max {max(a):.2f}, >{tol}px: {len(bad)}, ink mean {sum(ink)/len(ink):.2f} max {max(ink):.2f}'
              + ('  worst ' + ' '.join(f'{(chr(b) if b < 0xE000 else "PUA%04X" % b)}{e:+.1f}' for b, e in sorted(bad, key=lambda t: -abs(t[1]))[:show]) if bad else ''))
        if corpus is not None:
            seen = [(b, e, occurrences(b, m)) for b, e, _, _ in rows]
            seen = [(b, e, n) for b, e, n in seen if n]
            if not seen:
                print(f'      in text: none of these pairs occurs in {os.path.basename(wordfile)}')
                continue
            total = sum(n for _, _, n in seen)
            wmean = sum(abs(e) * n for _, e, n in seen) / total
            tbad = [(b, e, n) for b, e, n in seen if abs(e) > tol]
            text_pairs += len(seen)
            if m not in RARE: worst_text = max(worst_text, max(abs(e) for _, e, _ in seen))
            print(f'      in text: {len(seen):4d} pairs in {total:6d} words, weighted mean |err| {wmean:.2f} px, max {max(abs(e) for _, e, _ in seen):.2f}, >{tol}px: {len(tbad)} pairs / {sum(n for _, _, n in tbad)} words'
                  + ('  worst ' + ' '.join(f'{(chr(b) if b < 0xE000 else "PUA%04X" % b)}{e:+.1f}x{n}' for b, e, n in sorted(tbad, key=lambda t: -abs(t[1]))[:show]) if tbad else ''))
    print(f'worst {worst_all:.2f} px over {sum(len(v) for v in results.values())} pairs'
          + (f'; in text: worst {worst_text:.2f} px over {text_pairs} pairs' if corpus is not None else ''))
    judged = worst_text if corpus is not None else worst_all
    return 1 if strict and judged > tol else 0

sys.exit(main())
