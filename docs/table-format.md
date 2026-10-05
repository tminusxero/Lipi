# Cluster table format

A Lipi font carries one cluster table per script. The builder
(`builder/shaping.py`) writes it, the engine (`engine/Lipi.cpp`) reads it.
Lipi specifies only the table bytes and the Private Use codepoints they map
to; where the bytes live is the host's font container (CrossInk keeps them in
the `.cpfont` style TOC: kind, entry count and file offset, see the reader's
`docs/file-formats.md`).

## Kinds

Every script declares a table kind in its descriptor (`ScriptDesc::shapeKind`)
and spec (`ScriptSpec.shape_kind`). The kind fixes the key geometry (the
"entry size" is the unpacked row, key + meta + value, that the budget checks
reason in; the packed layout below stores each key at its own length):

| Kind | Script | Max key bytes | Unpacked entry size |
|------|--------|---------------|---------------------|
| 0 | none | | |
| 1 | Bengali | 5 | 8 |
| 2 | Devanagari | 7 | 10 |
| 3 | Tamil (reserved) | 7 | 10 |
| 4 | Gurmukhi (reserved) | 7 | 10 |
| 5 | Gujarati (reserved) | 7 | 10 |
| 6 | Odia (reserved) | 7 | 10 |
| 7 | Sinhala (reserved) | 7 | 10 |
| 8 | Kannada (reserved) | 7 | 10 |
| 9 | Telugu (reserved) | 7 | 10 |
| 10 | Malayalam (reserved) | 7 | 10 |

Kind 1 keeps the original 5-byte keys so shipped Bengali fonts stay valid;
kinds 2 to `SHAPE_KIND_LAST` (10) share the 7-byte geometry, long enough for a
four-consonant cluster, a ligature half form ending in ZWJ, or a cluster plus
vowel sign plus context marker. The engine reads a table only when its kind
equals the descriptor's; anything else, and any table over
`MAX_SHAPE_TABLE_BYTES` (16384), is ignored by the host loader. A new provider
takes the reserved number of its script.

## Layout (table format 3, packed)

The table is one blob:

- a directory of 18 bytes: for each key length 2..7, a `uint16_t` LE entry
  count and a `uint8_t` bucket count (lengths a kind does not allow hold
  zeros);
- then, for each key length in turn, the length's section: its bucket
  index (per bucket the first key byte and a `uint16_t` LE entry count,
  sorted by that byte), followed by its entries, each the key bytes after
  the first (length - 1 bytes), a `meta` byte and a `uint16_t` LE `value`,
  sorted bytewise inside each bucket.

A key is found by its length's section, its first byte's bucket and a
binary search on the remaining bytes; keys are prefix-free (no key contains
`0x00`), so the bytes alone identify an entry. A host reads the directory
first and sizes the load from it (`Lipi::packedTableBytes`); in a font file
the table kind byte carries `TOC_KIND_PACKED` (`0x80`) so a reader that
predates this layout ignores the table instead of misreading it. Before
format 3 every entry was a fixed `key[maxKeyLen] + meta + value` row (8 or
10 bytes); packing saves 25 to 40% (Noto Serif Bengali 7,984 -> 5,975 B,
Tiro Devanagari Sanskrit 14,700 -> 8,605 B at 12 pt).

- `meta` bits 0-2: number of key bytes (2 or more); bit 3: the ligature
  also forms when a further virama + consonant follows (the shaper keeps it
  instead of falling back to half forms); bits 4-7: the pre-base sign class
  of the glyph (see below), 0 for none.
- `value` bits 0-12: output codepoint minus `0xE000`, or `0x1FFF` for an
  entry without a glyph; bits 13-15: the post-base sign class of the glyph.

## Key alphabet

- `0x00` never occurs in a key (it padded the fixed rows of format 2)
- `0x01` zero-width joiner (half forms)
- `0x02` word-initial marker, placed before a pre-base vowel sign
- `0x03` word-final marker, placed after a post-base vowel sign
- `0x04` sign classes of a bare consonant: key `04 <consonant>`, no glyph
- `0x05` variant list of a vowel sign: key `05 <sign> [<modifier>] 1n` or
  `05 <ra> <virama> <sign> [<modifier>] 1n` for the sign fused with a reph,
  or `05 02 <sign> 1n` for the sign's word-initial form on that class (Noto
  Sans Bengali খে: ে.long.init), mapping class `n` to the variant glyph.
  The pre-base signs of a script share one class per glyph (a class stands
  for the glyph's ি variant and its ে variant together), so a variant list
  exists per sign and the class numbering is common to them.
- `0x06` format marker: key `06 06`, value = the table format (2). The engine
  ignores a table without it (older builders); `06 03` (no glyph) is present
  when the font draws word-final forms before a danda; `06 01` (no glyph)
  when the font joins conjuncts with half forms although its script
  subjoins (Hind Siliguri for Bengali): the engine then resolves clusters
  the half-form way, and the table carries `<C> <virama> 01` half-form keys.
- `0x10 | n` class index `n` (1..15) inside a variant-list key
- `0x80 | (cp - blockBase)` for a codepoint of the script's 128-codepoint
  block (`blockBase` = `0x0900 + n * 0x80`); letters in the descriptor's
  `raFolds` are keyed as the script's ra

## Keys for font-specific modifier behaviour

The device carries no per-font rules; the builder writes keys for behaviour
that differs between fonts of one script:

- `<sign> <modifier> 03`: the sign's word-final form when only that modifier
  follows it; the value is a spacing form of both glyphs. Absent, the sign
  stays plain before a spacing modifier.
- `<virama> <post-base consonant> <modifier>`: the post-base consonant form
  and the modifier as one spacing form when the font orders them differently
  from the shaper's default.
- `<modifier> <sign>` (modifier first): a variant of the modifier drawn after
  the pre-base sign when the sign itself keeps its form. The value is a mark.
- `<sign> <modifier>`: generic sign + modifier forms and their sign-class
  variants; a base that has its own sign class but no fused variant of that
  class takes the class variant and the modifier drawn on its own.

## Sign classes

Sign classes replace one entry per (cluster, vowel sign) pair: the font draws
the pre-base sign (ি, ि) in a width that depends on the glyph it attaches to,
and the post-base sign (ী, ी) in one that depends on the last glyph of the
cluster. Every composite, half form and bare consonant carries the class of
the variant the font chooses next to it, and the shaper picks the variant
from the list: the pre-base sign from the first glyph when it is a half form
that attaches the sign or the whole cluster as one glyph, the post-base sign
from the last glyph. Fused sign + modifier and sign + reph variants have their
own lists, written only when every glyph of a class shares the fused form.
Forms the classes cannot express keep their per-cluster entries.

## Output codepoints

Output codepoints lie in the Private Use Area; the range tells the renderer
how to place the glyph without a lookup. See `pua-classes.md`.
