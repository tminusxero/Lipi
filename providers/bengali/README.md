# Bengali provider

Block U+0980..U+09FF (Bangla, Assamese). Table kind 1: 5-byte keys, 8-byte
entries, the original geometry kept so shipped fonts stay valid.

## What the script needs

- Conjuncts are subjoined forms under the base (`JoinStyle::Subjoined`); a
  leading র + virama becomes a reph mark drawn right after the cluster
  (`RephMode::PreBase`). Some fonts join with half forms instead (Hind
  Siliguri: 29 of 32 consonants); the builder detects that, enumerates the
  font as a half-form script and flags the table (`06 01`), and the engine
  resolves its clusters the Devanagari way.
- Pre-base signs ি ে ৈ move before the cluster; two-part signs ো ৌ split
  into ে before and া / ৗ after it.
- য after a virama is a spacing post-base form (ya-phala), split off so below
  signs and the candrabindu attach to the base.
- ি and ী take contextual forms sized to the glyph they attach to; word-
  initial ে/ৈ and word-final া/ী/ৗ have their own forms; all of it comes from
  the table's sign classes and INIT/FINA keys. Some fonts also vary ে/ৈ by
  the letter (Noto Sans Bengali: ে.long on খ গ ণ থ প শ, ে.long.init at the
  start of a word): `preSignsWithForms` lists every pre-base sign with
  per-base forms, they share one class per glyph, and the word-initial
  variant of a class is keyed `05 02 <sign> 1n`.
- Nukta letters ড় ঢ় য় fold to their precomposed codepoints; ৰ is keyed as র
  inside conjuncts (Assamese).
- Marks: ঁ ় ু ূ ৃ ৄ ্ ৢ ৣ ৾ are non-spacing; the hasanta hangs at the pen
  after its base, the rest sit centred; below signs, nukta and the hasanta
  take the below anchor.

## Reference fonts (`fonts.yaml`)

Noto Serif Bengali (Google Fonts 3.000): 998 table entries. Tiro Bangla
(Google Fonts): 1032 entries, including the word-final forms before a danda
and the final ya-phala before a modifier that Noto does not have. Hind
Siliguri (Google Fonts 1.001, sans): 1006 entries (32 half forms, 354 pairs
of which 101 continue, 80 triples), the half-form flag set.

## Parity (tools/hb_parity.py, 12 pt, 2026-09-18)

| Word list | Words | Noto Serif Bengali | Tiro Bangla | Hind Siliguri | Noto Sans Bengali |
|---|---|---|---|---|---|
| Feluda samagra | 33,770 | 99.8% | 98.9% | 99.4% | 99.3% |
| Musafir | 12,148 | 100.0% | 99.0% | 99.6% | 99.4% |
| Panchatantra | 11,697 | 99.9% | 98.9% | 99.6% | 99.5% |
| The same lists with a trailing danda | | unchanged | unchanged | unchanged | unchanged |

(Tiro Bangla 98.8 / 99.0 / 98.8 before the ে/ৈ composites of 2026-09-19.)

Residual groups: ি before three-consonant clusters (the fused form needs a
6-byte key, kind 1 allows 5), ি fused with the candrabindu on some bases,
Tiro's headline-connector glyphs, Hind's taller ৗ after some bases, broken
source sequences in the books.

Noto Sans Bengali (Google Fonts 3.011, sans), measured 2026-09-19 with the
ে/ৈ classes, 12 pt: Feluda 99.3%, Musafir 99.4%, Panchatantra 99.5% (91.6 /
91.9 / 93.0 before them); 1,713 rows, 13,704 bytes, 26 joint classes of
which 15 fit the class field (the rest keep per-base forms). Its below
signs sat 6 to 7 px off until the anchor pass chose its probe by outcome
(the ba-phala mark, present on a homogeneous few conjuncts, had beaten ু);
at 16 pt they are now within 0.7 px, the nukta 2.1 px mean. The ে/ৈ
enumeration also gives Tiro Bangla 42 headline-connector composites of ্র
conjuncts with ে/ৈ (Feluda 98.8 to 98.9%).

Mark audit at 16 pt after the outcome-based probe (2026-09-19): Noto Serif
Bengali and Tiro Bangla take the reph as the above probe (reph 0.34 / 0.32
px mean, was 0.89 / 1.29; candrabindu 0.72 / 0.90, was 0.31 / 0.32, off by
more than a pixel on 58 / 68 conjuncts); their hasanta and vocalic signs
improve (Tiro ৃ 0.79 to 0.41, ্ 0.79 to 0.40). One anchor per class per
glyph cannot serve both the reph and the candrabindu on every conjunct.

Placement modes and the third base point (2026-09-19, CrossInk .cpfont v6):
a mark is measured from the class anchor, the other class's anchor, the
base's advance (pen) or a third per-base point, whichever fits the font.
At 16 pt: Hind Siliguri's nukta, hasanta and ৢ ৣ hang at the pen (2.2-2.4
px mean to 0.24), Tiro Bangla's candrabindu takes the extra point (0.90 to
0.32) and its nukta and phala marks the pen (1.9-3.2 to 0.24-0.28), Noto
Sans Bengali's phalas follow the above anchor (2.1-2.3 to 0.42 / 0.73),
Noto Serif Bengali's ba-phala 1.32 to 0.31. Its candrabindu (0.72) and
hasanta (0.70) keep the class anchor: no other point was clearly better.

Mark audit (tools/mark_audit.py, 16 pt): Hind's below signs ু ূ ৃ and the
reph sit within 0.4 px of HarfBuzz; its hasanta and nukta on conjuncts were
2.2 to 2.4 px off on average and the candrabindu 1.3 px until the placement
modes above (0.24 to 0.27 px on 2026-09-19).

Re-measured 2026-09-26 with the identity-checked tools (every tool now loads
the font through tools/fontcheck.py, which refuses a .cpfont whose table is
not a fresh build of the TTF, and takes every device-side run from the
builder's own forms). The audit's all-pairs means are no longer comparable
with the figures above: it now measures every plausible pair the engine draws
as base + mark, including sequences no book contains (a candrabindu after a
dead consonant, a nukta after a conjunct), and those dominate the means
(Hind hasanta 2.46 px, Noto Serif ba-phala 2.90 px over all pairs). The
figure that matters for readers is the in-text one (`--words`, pairs that
occur in the Feluda + Musafir + Panchatantra lists, weighted by word count,
a hasanta counted only where it is drawn): every mark of every family within
0.6 px mean, except Hind ূ / ৃ on one conjunct composite (4.5 px, 7 words)
and Hind's hasanta after two conjuncts (4.3 to 4.6 px, 4 words). Reph 0.26
to 0.40 px, candrabindu 0.31 to 0.52 px, ু 0.26 to 0.32 px in all four.
Whole-word placement (tools/word_parity.py, 16 pt, 1.5 px tolerance) over
the three lists: Noto Serif 106 words, Noto Sans 147, Tiro 82, Hind 746 (its
candrabindu height, a vertical offset the format does not carry yet).

`words.txt` is every sixth line of the Musafir list (2,025 words), a CI
sample; the full lists live with the reference host.
