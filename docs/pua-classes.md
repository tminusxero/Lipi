# Private Use Area classes

The builder allocates every shaped glyph a codepoint in the Private Use
Area, in a range that tells the renderer how to draw it. The engine exposes
the ranges as constants in `engine/Script.h` and answers the placement
questions through `Registry.h` (`isMark`, `attachesBelow`, `anchorClass`).

| Range | Class | Advance | Placement |
|-------|-------|---------|-----------|
| `U+E000-U+EFFF` | base | spacing | cluster composite or post-base consonant form; drawn like a letter |
| `U+F000-U+F0FF` | below | zero | mark centred below the base (ra-phala, ba-phala, rakar) |
| `U+F100-U+F1FF` | above | zero | mark above the base, right edges aligned (reph) |
| `U+F200-U+F2FF` | above centre | zero | mark centred above the base (tippi, addak, above vowel forms) |
| `U+F300-U+F3FF` | below right | zero | mark below the base, right edges aligned (subjoined consonants) |
| `U+F400-U+F5FF` | pre-base sign form | spacing | drawn instead of the vowel sign before the cluster (sized ি, word-initial ে/ৈ, ি fused with a reph) |
| `U+F600-U+F7FF` | post-base sign form | spacing | drawn instead of the vowel sign after the cluster (ী variants, word-final া/ী, fused with a reph or modifier) |
| `U+F800-U+F8FF` | pre-base consonant form | spacing | drawn before the cluster it belongs to (Malayalam ്ര; reserved) |

Rules that follow from the classes:

- `isMark(cp)` is true for `U+F000-U+F3FF` and for a script's non-spacing
  codepoints (its descriptor's `nonSpacing` mask); everything else advances
  the cursor.
- `attachesBelow(cp)` is true for `U+F000-U+F0FF`, `U+F300-U+F3FF` and the
  descriptor's `attachBelow` mask: these marks take the base's below anchor,
  all other marks the above anchor.
- `anchorClass(cp)` is `Center` for `U+F000-U+F0FF` and `U+F200-U+F2FF`,
  `Right` for `U+F100-U+F1FF` and `U+F300-U+F3FF`, and for a script's own marks
  whatever its descriptor says (`anchorCenter`, `anchorRight`, `anchorPen`);
  `None` for anything else, which the renderer places by its own default.

The classes tile `U+F000-U+F8FF` without gaps; a test in
`test/ScriptTablesTest.cpp` checks the constants.
