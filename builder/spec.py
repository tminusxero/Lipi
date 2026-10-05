"""ScriptSpec: everything the font builder knows about one script, plus the
cluster-table format constants its keys use. One instance per script lives
in providers/<script>/spec.py and mirrors the device descriptor beside it
(descriptor.h). The engine code (builder/shaping.py) never names a script."""

from __future__ import annotations

import dataclasses

ZWJ = 0x200D
# Pseudo-codepoints for the word-position markers (Lipi::KEY_*_CP).
INIT_CP = 0x2060
FINA_CP = 0x2061
# Pseudo-codepoints for the table's bookkeeping keys (Lipi::KEY_*_CP):
# the sign classes of a bare consonant, a vowel sign's variant list, the
# format marker, and class index n as CLASS_INDEX_CP + n.
CLASS_CP = 0x2062
VARIANT_CP = 0x2063
FORMAT_CP = 0x2064
CLASS_INDEX_CP = 0x2100
MAX_SIGN_CLASS = 15
# Table format written by this builder (Lipi::TABLE_FORMAT): 3 = the packed
# layout (directory of counts per key length, one section per length with
# first-byte buckets; see docs/table-format.md).
TABLE_FORMAT = 3
PACKED_MIN_KEY_LEN = 2
PACKED_MAX_KEY_LEN = 7
PACKED_DIRECTORY_BYTES = (PACKED_MAX_KEY_LEN - PACKED_MIN_KEY_LEN + 1) * 3
# Set on the table kind byte of a host's font file to mark a packed table
# (Lipi::TOC_KIND_PACKED): readers that predate format 3 then ignore it.
TOC_KIND_PACKED = 0x80
VALUE_NO_GLYPH = 0x1FFF

KEY_ZWJ = 0x01
KEY_INIT = 0x02
KEY_FINA = 0x03
KEY_CLASS = 0x04
KEY_VARIANT = 0x05
KEY_FORMAT = 0x06
KEY_CLASS_INDEX = 0x10  # | n
# Table kinds, one per script, declared by each ScriptSpec (Lipi::SHAPE_KIND_*).
# Kind 1 keeps the original 5-byte keys; every later kind up to
# SHAPE_KIND_LAST shares the 7-byte geometry. The reserved numbers are listed
# in docs/file-formats.md.
SHAPE_KIND_LAST = 10
# Largest table the device loads (Lipi::MAX_SHAPE_TABLE_BYTES).
MAX_TABLE_BYTES = 16384

PUA_BASE = (0xE000, 0xEFFF)
PUA_BELOW = (0xF000, 0xF0FF)
PUA_ABOVE = (0xF100, 0xF1FF)
PUA_ABOVE_CENTER = (0xF200, 0xF2FF)
PUA_BELOW_RIGHT = (0xF300, 0xF3FF)
PUA_PRE = (0xF400, 0xF5FF)
PUA_POST = (0xF600, 0xF7FF)
PUA_PRECONS = (0xF800, 0xF8FF)

KIND_BASE = "base"
KIND_BELOW = "below"                # zero-advance mark centred under the base
KIND_ABOVE = "above"                # zero-advance mark at the base's top right
KIND_ABOVE_CENTER = "above_center"  # zero-advance mark centred over the base
KIND_BELOW_RIGHT = "below_right"    # zero-advance mark at the base's bottom right
KIND_PRE = "pre"          # spacing form of a pre-base sign, drawn before the cluster
KIND_POST = "post"        # spacing form of a post-base sign, drawn after the cluster
KIND_PRECONS = "precons"  # spacing consonant form drawn before the cluster
KIND_META = "meta"        # bookkeeping entry without a glyph (consonant classes)
MARK_KINDS = (KIND_BELOW, KIND_ABOVE, KIND_ABOVE_CENTER, KIND_BELOW_RIGHT)
PUA_RANGES = {
    KIND_BASE: PUA_BASE, KIND_BELOW: PUA_BELOW, KIND_ABOVE: PUA_ABOVE, KIND_ABOVE_CENTER: PUA_ABOVE_CENTER,
    KIND_BELOW_RIGHT: PUA_BELOW_RIGHT, KIND_PRE: PUA_PRE, KIND_POST: PUA_POST, KIND_PRECONS: PUA_PRECONS,
}



def max_key_len_for_kind(kind):
    """Longest cluster key of a shape kind (0 = no table)."""
    if kind == 1:
        return 5
    if 2 <= kind <= SHAPE_KIND_LAST:
        return 7
    return 0


def entry_size_for_kind(kind):
    """Cluster table entry size for a shape kind (0 = no table): key,
    length byte and u16 output codepoint."""
    key_len = max_key_len_for_kind(kind)
    return key_len + 3 if key_len else 0


@dataclasses.dataclass(frozen=True)
class ScriptSpec:
    """Everything the enumeration needs to know about one script. Mirrors
    Lipi::ScriptDesc on the device (providers/<script>/descriptor.h); the two must agree
    on the letters below or the device will look up keys the table does not hold."""
    name: str
    shape_kind: int
    block_base: int              # first codepoint of the block (0x0900 + n * 0x80)
    hb_script: str               # HarfBuzz script and language tags
    hb_language: str
    intervals: tuple             # (start, end) pairs the preset covers
    probe: int                   # KA: shaped after a key to hide word-final forms
    consonants: tuple            # every consonant of the script
    cluster_consonants: tuple    # consonants that take part in conjuncts
    virama: int
    nukta: int
    ra: int
    post_base_consonant: int     # consonant whose subjoined form is a spacing post-base glyph (ya)
    ra_folds: tuple              # letters keyed and shaped as ra inside a conjunct
    below_vowels: tuple
    pre_sign_with_forms: int     # pre-base sign with contextual forms (ি); also the one fused with a reph / modifier
    post_sign_with_forms: int    # post-base sign with contextual forms (ী)
    init_signs: tuple            # pre-base signs with a word-initial form
    fina_signs: tuple            # post-base signs with a word-final form
    form_probe_bases: tuple      # bases tried when isolating a subjoined form
    pre_signs_with_forms: tuple = ()  # every pre-base sign with per-base forms (ি ে ৈ); () = the one above
    post_signs_with_forms: tuple = ()  # every post-base sign with per-base forms (ী ৗ); () = the one above
    join_style: str = "subjoined"  # "subjoined" (Bengali) or "half" (Devanagari half forms)
    reph_after_post: bool = False  # the reph mark follows the post-base sign
    mark_fusion: bool = False      # enumerate signs/reph fused with modifiers (कें, र्कं, कीं)
    post_vowels: tuple = ()        # post-base signs tried for fused forms
    above_vowels: tuple = ()       # above-base signs tried for fused forms
    modifiers: tuple = ()          # anusvara, candrabindu, visarga
    independent_vowels: tuple = ()  # tried fused with the modifiers (ओं)
    candrabindu_before_post: tuple = ()  # post signs the device draws the candrabindu before (া ী)
    # Mark placement, mirroring the descriptor's nonSpacing / attachBelow /
    # anchor masks: the renderer draws these as zero-advance overlays.
    marks: tuple = ()          # every non-spacing codepoint of the block
    attach_below: tuple = ()   # marks that take the base's below anchor
    anchor_center: tuple = ()  # centred on the base at font-native height
    anchor_right: tuple = ()   # right edges aligned
    anchor_pen: tuple = ()     # at the pen after the base (a visible virama)
    below_signs: tuple = ()    # vowel signs and virama drawn under the base (anchor audit set)
    rare_marks: tuple = ()     # Vedic and other marks the mark audit does not report on
    phala_consonants: tuple = ()  # consonants whose form after a virama is a subjoined/phala glyph (the mark audit
                                  # skips a second such mark on a cluster that already ends in one)
    dandas: tuple = ()         # sentence punctuation shared by the Indic scripts

    @property
    def max_key_len(self):
        return max_key_len_for_kind(self.shape_kind)

    @property
    def entry_size(self):
        return entry_size_for_kind(self.shape_kind)

    @property
    def candrabindu(self):
        return self.block_base + 0x01

    @property
    def consonant_set(self):
        return frozenset(self.consonants)

    def in_block(self, cp):
        return self.block_base <= cp < self.block_base + 0x80

    # Mirrors of Lipi::isMark / attachesBelow / anchorClass (Registry.h) for
    # the script's block and the PUA mark classes.
    def is_mark(self, cp):
        return cp in self.marks or PUA_BELOW[0] <= cp <= PUA_BELOW_RIGHT[1]

    def attaches_below(self, cp):
        return (cp in self.attach_below or PUA_BELOW[0] <= cp <= PUA_BELOW[1]
                or PUA_BELOW_RIGHT[0] <= cp <= PUA_BELOW_RIGHT[1])

    def anchor_class(self, cp):
        """"Center", "Right", "Pen" or None (the renderer's default)."""
        if PUA_BELOW[0] <= cp <= PUA_BELOW[1] or PUA_ABOVE_CENTER[0] <= cp <= PUA_ABOVE_CENTER[1]:
            return "Center"
        if PUA_ABOVE[0] <= cp <= PUA_ABOVE[1] or PUA_BELOW_RIGHT[0] <= cp <= PUA_BELOW_RIGHT[1]:
            return "Right"
        if cp in self.anchor_center:
            return "Center"
        if cp in self.anchor_right:
            return "Right"
        if cp in self.anchor_pen:
            return "Pen"
        return None
