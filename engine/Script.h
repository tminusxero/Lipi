#pragma once

#include <ScriptBlock.h>

#include <cstdint>

/// Per-script data for the Lipi engine. Every Indic block (U+0900..U+0DFF)
/// shares one layout: 128 codepoints with the consonants around offset
/// 0x15..0x39, the nukta at 0x3C, vowel signs at 0x3E..0x4C, the virama at
/// 0x4D and precomposed nukta letters at 0x58..0x5F. A ScriptDesc therefore
/// describes a script as sets of block offsets plus the handful of letters
/// the shaper treats specially, and the shaping code itself is shared.
namespace Lipi {

/// Set of block offsets (cp - blockBase, 0..127).
struct BlockMask {
  uint64_t lo = 0;
  uint64_t hi = 0;

  constexpr bool has(const uint32_t off) const {
    return off < 64 ? ((lo >> off) & 1u) != 0 : off < 128 ? ((hi >> (off - 64)) & 1u) != 0 : false;
  }
  constexpr BlockMask operator|(const BlockMask o) const { return {lo | o.lo, hi | o.hi}; }
};

// Named to stay clear of the Arduino bit() macro.
constexpr BlockMask blockBit(const uint32_t off) {
  return off < 64 ? BlockMask{1ull << off, 0} : BlockMask{0, 1ull << (off - 64)};
}

constexpr BlockMask blockRange(const uint32_t first, const uint32_t last) {
  BlockMask m{};
  for (uint32_t off = first; off <= last; ++off) m = m | blockBit(off);
  return m;
}

/// How a leading (RA, VIRAMA) is drawn: not at all (Tamil) or as a mark over
/// the following consonant. PostBase (a spacing or mark glyph after the
/// cluster, Kannada and Telugu) is reserved: the engine only implements
/// PreBase and treats any other value as None.
enum class RephMode : uint8_t { None, PreBase, PostBase };

/// How the first consonant of a conjunct joins the next one: as a subjoined
/// form under the base or as a half form before it.
enum class JoinStyle : uint8_t { Subjoined, HalfForm };

/// Where the renderer places a combining mark relative to its base glyph
/// (the classes the reader's renderer implements; None = not a mark the
/// engine knows, the renderer's default applies).
enum class MarkAnchor : uint8_t { None, Center, Right, Pen };

/// Two-part vowel sign (ো = ে + া): the sign in the source text, the part
/// drawn before the cluster and the part drawn after it.
struct SplitVowel {
  uint16_t sign;
  uint16_t pre;
  uint16_t post;
};

/// Consonant + nukta pair with a precomposed letter the fonts map instead
/// (composition exclusions, so NFC text keeps them decomposed).
struct NuktaFold {
  uint16_t base;
  uint16_t folded;
};

constexpr uint8_t MAX_SPLIT_VOWELS = 4;
constexpr uint8_t MAX_NUKTA_FOLDS = 8;

struct ScriptDesc {
  uint8_t shapeKind = 0;  ///< cluster-table kind this script reads (SHAPE_KIND_*)
  ScriptBlock block = ScriptBlock::None;
  uint16_t blockBase = 0;  ///< first codepoint of the block (kIndicBlockBase + n * kIndicBlockSize)
  RephMode rephMode = RephMode::None;
  JoinStyle joinStyle = JoinStyle::Subjoined;
  /// The reph mark is drawn after the post-base vowel sign (र्का: ka, aa,
  /// reph) instead of right after the cluster (র্কা: reph, ka, aa). Modifiers
  /// then follow the reph, and the candrabindu is never moved forward.
  bool rephAfterPost = false;

  // Letters the shaper handles by name (0 = the script has none).
  uint16_t virama = 0;
  uint16_t nukta = 0;
  uint16_t ra = 0;
  uint16_t candrabindu = 0;
  uint16_t preSignWithForms = 0;   ///< pre-base sign with contextual forms (ি): sized to its base, fused with a reph
  uint16_t postSignWithForms = 0;  ///< post-base sign with contextual forms (ী)
  uint16_t postBaseConsonant = 0;  ///< consonant whose subjoined form is a spacing post-base glyph (য)

  // Block offset sets.
  BlockMask consonants;
  BlockMask independentVowels;
  BlockMask extraBases;         ///< other letters vowel signs attach to (khanda ta, avagraha)
  BlockMask preBase;            ///< vowel signs drawn before the cluster
  BlockMask postBase;           ///< vowel signs drawn after the cluster
  BlockMask below;              ///< vowel signs drawn under the base
  BlockMask above;              ///< vowel signs drawn over the base (े ै)
  BlockMask modifiers;          ///< candrabindu, anusvara, visarga and the like
  BlockMask nonSpacing;         ///< everything drawn as a zero-advance overlay (see isMark in Registry.h)
  BlockMask raFolds;            ///< letters keyed and treated as RA inside a conjunct (ৰ)
  BlockMask initSigns;          ///< pre-base signs with a word-initial form (ে ৈ)
  BlockMask preSignsWithForms;  ///< pre-base signs with per-base forms / sign classes (ি; Noto Sans Bengali: ে ৈ too);
                                ///< preSignWithForms is the one of them that also fuses with a reph or modifier
  BlockMask candrabinduBeforePost;  ///< post-base signs the candrabindu is drawn before (া ী)

  // Mark placement for the renderer (see attachesBelow / anchorClass in
  // Registry.h): marks that hang from the base's below anchor rather than its
  // above anchor, and the anchor class of each mark. A mark in none of the
  // anchor sets takes the renderer's default placement.
  BlockMask attachBelow;
  BlockMask anchorCenter;  ///< centred on the base at font-native height
  BlockMask anchorRight;   ///< right edges aligned (anusvara, above signs at the stem)
  BlockMask anchorPen;     ///< at the pen position after the base (a visible virama)

  SplitVowel splitVowels[MAX_SPLIT_VOWELS] = {};
  uint8_t splitVowelCount = 0;
  NuktaFold nuktaFolds[MAX_NUKTA_FOLDS] = {};
  uint8_t nuktaFoldCount = 0;

  constexpr bool inBlock(const uint32_t cp) const { return cp >= blockBase && cp < blockBase + 0x80u; }
  // The block's ten digits (offset 0x66..0x6F in every Indic block).
  constexpr bool isDigit(const uint32_t cp) const { return cp >= blockBase + 0x66u && cp <= blockBase + 0x6Fu; }
  constexpr bool in(const BlockMask& m, const uint32_t cp) const { return inBlock(cp) && m.has(cp - blockBase); }

  constexpr bool isConsonant(const uint32_t cp) const { return in(consonants, cp); }
  constexpr bool isIndependentVowel(const uint32_t cp) const { return in(independentVowels, cp); }
  /// Anything vowel signs and modifiers can attach to.
  constexpr bool isSyllableBase(const uint32_t cp) const {
    return isConsonant(cp) || isIndependentVowel(cp) || in(extraBases, cp);
  }
  constexpr bool isPreBaseVowel(const uint32_t cp) const { return in(preBase, cp); }
  constexpr bool isPostBaseVowel(const uint32_t cp) const { return in(postBase, cp); }
  constexpr bool isBelowVowel(const uint32_t cp) const { return in(below, cp); }
  constexpr bool isAboveVowel(const uint32_t cp) const { return in(above, cp); }
  constexpr bool isModifier(const uint32_t cp) const { return in(modifiers, cp); }
  constexpr bool isRa(const uint32_t cp) const { return cp == ra || in(raFolds, cp); }

  constexpr uint32_t precomposedNukta(const uint32_t cp) const {
    for (uint8_t i = 0; i < nuktaFoldCount; ++i) {
      if (nuktaFolds[i].base == cp) return nuktaFolds[i].folded;
    }
    return 0;
  }
  constexpr const SplitVowel* splitVowel(const uint32_t cp) const {
    for (uint8_t i = 0; i < splitVowelCount; ++i) {
      if (splitVowels[i].sign == cp) return &splitVowels[i];
    }
    return nullptr;
  }
};

/// Cluster table kinds, one per script. A .cpfont carries one table and its
/// kind; the shaper only reads a table whose kind matches the script's
/// descriptor. Kind 1 keeps the original 5-byte-key geometry; every later kind
/// shares the wider one (see entrySizeForKind).
constexpr uint8_t SHAPE_KIND_BENGALI = 1;
constexpr uint8_t SHAPE_KIND_DEVANAGARI = 2;
constexpr uint8_t SHAPE_KIND_LAST = 10;  ///< kinds 3..10 are reserved for the scripts listed in docs/file-formats.md

/// PUA allocation shared with builder/shaping.py (writer) and Registry.h (mark
/// classification). The range a codepoint falls in tells the renderer how to
/// place it without a table lookup.
constexpr uint32_t PUA_BASE_FIRST = 0xE000;  ///< spacing glyphs: composites, post-base forms
constexpr uint32_t PUA_BASE_LAST = 0xEFFF;
constexpr uint32_t PUA_BELOW_FIRST = 0xF000;  ///< below-base marks (ra-phala, ba-phala)
constexpr uint32_t PUA_BELOW_LAST = 0xF0FF;
constexpr uint32_t PUA_ABOVE_FIRST = 0xF100;  ///< above-base marks anchored at the right edge (reph)
constexpr uint32_t PUA_ABOVE_LAST = 0xF1FF;
constexpr uint32_t PUA_ABOVE_CENTER_FIRST =
    0xF200;  ///< above-base marks centred on the base (tippi, addak, above vowel forms)
constexpr uint32_t PUA_ABOVE_CENTER_LAST = 0xF2FF;
constexpr uint32_t PUA_BELOW_RIGHT_FIRST =
    0xF300;  ///< below-base marks anchored at the right edge (subjoined consonants)
constexpr uint32_t PUA_BELOW_RIGHT_LAST = 0xF3FF;
/// Contextual forms of vowel signs: spacing glyphs that replace the sign
/// itself while the cluster is shaped as usual. A pre-base form (ি sized to
/// its base, word-initial ে/ৈ, ি fused with a reph) is drawn before the
/// cluster; a post-base form (ী variants, word-final া/ী, ী fused with a
/// reph) after it.
constexpr uint32_t PUA_PRE_FIRST = 0xF400;
constexpr uint32_t PUA_PRE_LAST = 0xF5FF;
constexpr uint32_t PUA_POST_FIRST = 0xF600;
constexpr uint32_t PUA_POST_LAST = 0xF7FF;
/// Spacing consonant forms drawn before the cluster they belong to
/// (Malayalam ്ര): emitted after the pre-base vowel sign, before the base.
constexpr uint32_t PUA_PRECONS_FIRST = 0xF800;
constexpr uint32_t PUA_PRECONS_LAST = 0xF8FF;

/// Context markers that can appear in cluster keys next to a vowel sign:
/// KEY_INIT before ে/ৈ at the start of a word, KEY_FINA after া/ী at the
/// end of one. They are key bytes 0x02 and 0x03; these pseudo-codepoints
/// only exist so callers can build keys with the same lookup function.
constexpr uint32_t KEY_INIT_CP = 0x2060;
constexpr uint32_t KEY_FINA_CP = 0x2061;
/// Pseudo-codepoints for the table's own bookkeeping entries (key bytes 0x04,
/// 0x05, 0x06): the vowel-sign classes of a bare consonant, the variant list
/// of a vowel sign, and the format marker.
constexpr uint32_t KEY_CLASS_CP = 0x2062;
constexpr uint32_t KEY_VARIANT_CP = 0x2063;
constexpr uint32_t KEY_FORMAT_CP = 0x2064;
/// {KEY_FORMAT_CP, KEY_FINA_CP} (no glyph) is present when the font draws the
/// word-final forms before a danda (Tiro Bangla বা।); without it a danda keeps
/// the sign in its ordinary form, as Noto does.
/// {KEY_FORMAT_CP, ZWJ} (no glyph) is present when the font joins conjuncts
/// with half forms although the script's descriptor subjoins (Hind Siliguri
/// for Bengali); the engine then resolves clusters as for JoinStyle::HalfForm.
/// {KEY_FORMAT_CP, KEY_INIT_CP, class index n} -> PUA_BASE_FIRST + share is
/// present when danda n (1 = single, 2 = double) carries built-in space
/// that the font drops after a space character; share is that space in
/// 1/256 of the danda's advance (Lipi::dandaSpaceShare).
/// {KEY_CLASS_CP, consonant} (no glyph) carries a bare consonant's pre- and
/// post-sign classes in the entry's class fields; {KEY_CLASS_CP, half-form
/// key...} (no glyph) carries the row of a half form whose ि variant depends
/// on the consonant that follows (row = pre class | post class << 4).
/// {KEY_VARIANT_CP, sign, class index n} -> the sign's glyph for class n;
/// {KEY_VARIANT_CP, ZWJ, sign, blockBase + row, class index column} -> the
/// class the sign takes after a half form of that row when the next
/// consonant's class is column - 1 (column 15 = another half form follows).
/// Class index n (1..15) inside a variant-list key: key byte 0x10 | n.
constexpr uint32_t KEY_CLASS_INDEX_CP = 0x2100;
constexpr uint8_t MAX_SIGN_CLASS = 15;
/// Table format written by the current builder (format marker entry
/// {KEY_FORMAT_CP, KEY_FORMAT_CP} -> this number). Format 3 is the packed
/// layout below; tables without the marker, or with another number, were
/// written by another builder and are ignored.
constexpr uint8_t TABLE_FORMAT = 3;

/// Packed table layout (format 3). The blob starts with a directory of
/// PACKED_DIRECTORY_BYTES: for each key length 2..7, a uint16 LE entry count
/// and a uint8 bucket count. Then, for each length in turn, the bucket index
/// (per bucket: the first key byte and a uint16 LE entry count, sorted by
/// that byte) followed by the entries of the length: the remaining key bytes
/// (length - 1), the meta byte and the uint16 LE value, sorted bytewise
/// inside each bucket. A key is found by its length's section, its first
/// byte's bucket and a binary search on the rest. Lengths beyond the kind's
/// maxKeyLenForKind hold zero counts.
constexpr uint32_t PACKED_MIN_KEY_LEN = 2;
constexpr uint32_t PACKED_MAX_KEY_LEN = 7;
constexpr uint32_t PACKED_DIRECTORY_BYTES = (PACKED_MAX_KEY_LEN - PACKED_MIN_KEY_LEN + 1) * 3;
/// A host that stores the table kind in a byte sets this flag on it to say
/// the table is packed; a reader that predates format 3 then sees an unknown
/// kind and ignores the table instead of misreading it.
constexpr uint8_t TOC_KIND_PACKED = 0x80;

/// Key geometry per kind: kind 1 (Bengali) allows 5-byte keys, kinds 2..10
/// 7-byte keys, long enough for a four-consonant cluster, a ligature half
/// form ending in ZWJ, or a cluster plus vowel sign plus context marker.
/// entrySizeForKind is the unpacked row (key[maxKeyLen] + meta + u16) that
/// the budget checks and the tests reason in; the packed table stores each
/// key at its own length. Both return 0 for kinds this build does not read,
/// and the loader then ignores the table.
constexpr uint32_t maxKeyLenForKind(const uint8_t kind) {
  if (kind == SHAPE_KIND_BENGALI) return 5;
  if (kind >= SHAPE_KIND_DEVANAGARI && kind <= SHAPE_KIND_LAST) return 7;
  return 0;
}
constexpr uint32_t entrySizeForKind(const uint8_t kind) {
  const uint32_t keyLen = maxKeyLenForKind(kind);
  return keyLen == 0 ? 0 : keyLen + 3;
}
static_assert(maxKeyLenForKind(SHAPE_KIND_LAST) <= PACKED_MAX_KEY_LEN, "the directory covers every key length");
/// Longest key any kind allows; sizes the probe buffers.
constexpr uint32_t MAX_KEY_CAP = 7;
static_assert(maxKeyLenForKind(SHAPE_KIND_LAST) <= MAX_KEY_CAP, "probe buffers are sized by MAX_KEY_CAP");
/// Largest cluster table a font may carry. The table stays resident per
/// loaded style (Tiro Bangla is 8.5 KB), so the loader ignores anything
/// bigger instead of letting a hostile header claim 80 KB on the C3.
constexpr uint32_t MAX_SHAPE_TABLE_BYTES = 16384;

}  // namespace Lipi
