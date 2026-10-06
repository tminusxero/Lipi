# Devanagari provider

Block U+0900..U+097F (Hindi, Marathi, Nepali, Sanskrit). Table kind 2:
7-byte keys, 10-byte entries.

## What the script needs

- Conjuncts are half forms before a full consonant (`JoinStyle::HalfForm`),
  with true ligatures (क्ष त्र ज्ञ श्र द्य द्ध) and rakar as a below mark; the
  builder keeps only the half forms the device cannot compose from smaller
  pieces, including contextual half forms that change with the next
  consonant.
- The reph is drawn after the post-base sign (`rephAfterPost`): र्का is ka,
  aa, reph.
- ZWJ after a virama selects the half form, ZWNJ the visible virama; the
  eyelash ra falls out of the half-form key.
- Eight nukta letters (क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़) fold to their precomposed
  codepoints.
- Fused forms with the anusvara and candrabindu (कें कों कीं र्कं) and the
  vowel-sign width variants come from the table's sign classes.
- Marks: ऀ ँ ं ऺ ़ ु..ै ् ॑..ॗ ॢ ॣ are non-spacing; the anusvara and the
  above vowel signs attach at the stem on the right, the halant at the pen,
  the rest centred.

## Reference fonts (`fonts.yaml`)

Noto Serif Devanagari (Google Fonts 2.006, with Latin): 1030 table entries.
Tiro Devanagari Sanskrit (Google Fonts): 1470 entries, 14.7 KB, the largest
table of the current providers.

## Parity (tools/hb_parity.py, 12 pt, 2026-09-26; 2026-09-18 in brackets)

| Word list | Words | Noto Serif Devanagari | Tiro Devanagari Sanskrit |
|---|---|---|---|
| Nirmala (Premchand, Hindi) | 6,606 | 100.0% (99.2) | 99.9% (99.9) |
| Bhagavad Gita verses | 4,412 | 99.7% (93.9) | 99.8% (99.8) |
| a Purana edition (OCR text) | 64,941 | 98.3% (95.9) | 98.1% (98.0) |
| Gita with commentaries | 188,305 | 99.7% (93.8) | 99.5% (99.4) |
| a second Purana edition (OCR text) | 75,778 | 98.6% (94.6) | 98.5% (98.0) |

Measured with the identity-checked tools (tools/fontcheck.py; device runs
from the builder's forms). Against the 2026-09-25 run they moved by a few
words: Noto Serif's generic र्िं composite draws the .04 width where
HarfBuzz picks .05 on some bases (21 words in the Purana list, 1 px of hook), which
the earlier expansion hid; Tiro loses 28 words the earlier expansion had
flagged from a wrong glyph name. Mark audit at 16 pt, in-text pairs (the
four lists, weighted by word count): every sign and the reph within 0.6 px
mean in both fonts; open placement items are Tiro's candrabindu (1.5 px
mean, अँ 5.2 px on 20 words, आँ 4.9 px on 39), Tiro ू / ृ on a few
conjuncts (4.5 to 5.0 px, 218 to 272 words), Noto Serif's candrabindu on
ए / आ (4.0 to 4.8 px, 161 words) and its anusvara after four post-sign
composites (19.6 px, 22 words), and the Vedic accents.

Residual groups: Noto's two-glyph ि rule before half-form sequences (the
main Sanskrit gap, a width-class refinement not yet in the table format),
OCR damage in the Purana list (bare anusvara tokens, double viramas), reph
plus anusvara on one base. Precomposed ई and ऐ are counted as the sequence
the Google Fonts Noto draws for them.

Mark placement (tools/mark_audit.py, 16 pt, 2026-09-19): Tiro Devanagari
Sanskrit attaches the anusvara at a point of its own, not at the e-sign or
reph anchor; with the placement modes (CrossInk .cpfont v6) it takes the
extra per-base point and its mean error drops from 2.13 px on 982 bases
(691 over a pixel) to 0.30 px (none). Noto Serif Devanagari was already
within 0.5 px except the Vedic marks, now 0.3 to 0.4 px.

`words.txt` is every third line of the Nirmala list (2,202 words; Premchand,
1927, public domain); it feeds the builder's pair weights and the CI parity
smoke. The full lists live with the reference host and are not published.
