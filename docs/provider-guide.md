# Adding a script: the provider guide

A provider is a directory under `providers/` that declares everything the
engine and the builder need to know about one script. Nothing in `engine/`
or `builder/` names a script; if you find yourself editing them to land a
provider, stop and read `CONTRIBUTING.md` (engine changes are the other
half of that guide).

## 1. Copy the template

```sh
python3 tools/new_provider.py tamil Tamil 0x0B80 3
```

creates `providers/tamil/` from `templates/provider/` with the names, block
base and table kind filled in (the kind is the script's reserved number in
`docs/table-format.md`). Every field in the generated files is commented.

## 2. Fill the descriptor (`descriptor.h`)

One `constexpr ScriptDesc makeTamil()`. Everything is data:

- identity: `shapeKind`, `block` (`ScriptBlock` enum value), `blockBase`. A script
  outside `U+0900..U+0DFF` also needs engine work first (`ScriptBlock.h`, the
  key-byte scheme, `mayNeedShaping`'s lead-byte mask): see `docs/interfaces.md` 3.5.
- rules: `rephMode` (None / PreBase; PostBase is reserved and not implemented), `joinStyle` (Subjoined /
  HalfForm; a font may still join with half forms, the table flag `06 01`
  says so), `rephAfterPost`
- named letters: `virama`, `nukta`, `ra`, `candrabindu`,
  `preSignWithForms` (the pre-base sign fused with a reph or modifier),
  `postSignWithForms`, `postBaseConsonant` (0 = none)
- letter classes as block-offset masks (`blockBit`, `blockRange`):
  `consonants`, `independentVowels`, `extraBases`, `preBase`, `postBase`,
  `below`, `above`, `modifiers`, `nonSpacing`, `raFolds`, `initSigns`,
  `preSignsWithForms` (every pre-base sign with per-base forms, sharing one
  class per glyph; Bengali ি ে ৈ), `candrabinduBeforePost`
- mark placement masks: `attachBelow`, `anchorCenter`, `anchorRight`,
  `anchorPen` (subsets of `nonSpacing`; a mark in none of the anchor sets
  takes the host's default)
- `splitVowels` (two-part signs: sign, pre part, post part) and
  `nuktaFolds` (consonant + nukta with a precomposed letter)

The Unicode chart of the block gives the offsets; every Indic block from
Devanagari to Sinhala shares the layout (consonants at `0x15..0x39`, nukta
`0x3C`, signs `0x3E..0x4C`, virama `0x4D`, digits `0x66..0x6F`).

## 3. Fill the builder spec (`spec.py`)

The mirror of the descriptor for the Python side, plus what only the builder
needs: HarfBuzz script and language tags, the interval preset the host's
converter exposes, the probe letter (KA), the consonants that take part in
conjuncts, the bases tried when isolating a subjoined form, enumeration
switches (`mark_fusion`, `post_vowels`, `above_vowels`, `modifiers`,
`independent_vowels`), the mark sets (`marks`, `attach_below`,
`anchor_center`, `anchor_right`, `anchor_pen`, `below_signs`,
`rare_marks`), and `dandas`. `builder/test_shaping.py` has a consistency
test for the sets; add a mirror check against the descriptor in your test
once the numbers are final.

## 4. Register it

Two lines in `engine/Registry.h` (the `#include` under its macro and the
table entry) and one line in `builder/registry.py`. The macro
`LIPI_WITH_TAMIL` lets a host leave the provider out.

## 5. Get a font and a word list

`fonts.yaml` names the recommended family (Google Fonts, with its licence).
Put a word list in `words.txt`: a few thousand distinct words of modern prose
in the script, taken from a public-domain text (Wikisource is a good source;
do not commit words drawn from a book still in copyright). The builder weights
its mark-anchor choices by the (base, mark) pairs in this list, so the sample
must resemble what readers will read: an old-orthography sample measurably
worsened Bengali placement. Keep any larger, non-publishable lists outside the
repo. How the existing providers made theirs is in their READMEs.

## 6. Build and measure

```sh
# a table for the reference font (through the host converter, or directly)
python3 -c "from builder import shaping; ..."   # see builder/test_shaping.py::_build
# the .cpfont's table is the builder's own for this TTF (every tool checks this first)
python3 tools/fontcheck.py FONT.ttf FONT_12.cpfont
# parity against HarfBuzz on the word list
python3 tools/hb_parity.py FONT.ttf FONT_12.cpfont providers/tamil/words.txt
# mark placement
python3 tools/mark_audit.py FONT.ttf FONT_16.cpfont
```

Targets before a provider is done: parity at or above 97% identical glyph
sequences on the word list, every residual group named and explained in the
README; mark audit within the tolerances of the existing providers; table
size well under 16 KB (the existing tables are 8 to 15 KB).

## 7. Tests

`test/<Script>ShaperTest.cpp` from the template: syllable split, pre-base
reorder, split vowels, the script's conjuncts and reph handling, pass-through
of other scripts, and a table-kind mismatch case. Add the file to
`test/CMakeLists.txt`. A golden entry count and table hash for the reference
font goes into `builder/test_shaping.py`'s `GOLDEN` table.

## 8. Open the pull request

The PR states: font family and version, table entries and bytes, parity per
word list with the residual groups, mark audit numbers, and known gaps. CI
runs the host tests, the builder goldens, the parity smoke on `words.txt`
and the engine purity grep.
