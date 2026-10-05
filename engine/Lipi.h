#pragma once

#include <cstdint>
#include <string>

#include "LipiMarks.h"
#include "Registry.h"

/// Indic text shaping without an OpenType engine.
///
/// Fonts render the Indic scripts through GSUB/GPOS: consonant clusters
/// joined by a virama become conjunct glyphs, a leading ra becomes a reph
/// mark over the following consonant, and vowel signs attach before, after,
/// below or above the cluster. None of that fits on the device, so the font
/// builder (builder/shaping.py) pre-shapes every cluster
/// form the font provides into a Private Use Area glyph and stores a sorted
/// cluster table in the .cpfont. This module does the rest at draw time,
/// driven by the per-script descriptors (Script.h, providers/*/descriptor.h):
///
///   * splits logical text into orthographic syllables,
///   * moves pre-base vowel signs (ি ে ৈ, and the ে half of ো ৌ) in front of
///     the cluster and post-base signs behind it,
///   * resolves each consonant cluster through the table with longest-match
///     lookups, splitting off the reph and subjoined forms it composes itself,
///   * leaves below/above marks after their base so the renderer's
///     combining-mark path anchors them (see isMark, attachesBelow and
///     anchorClass in LipiMarks.h).
///
/// The output is a UTF-8 codepoint stream in visual order that the existing
/// measurement and drawing loops consume unchanged. Fonts without a cluster
/// table still get the reordering and mark handling; conjuncts then show as
/// consonant + visible hasanta + consonant. Scripts without a descriptor in
/// kScriptByBlock pass through untouched.
namespace Lipi {

/// Cluster table: a packed blob (Script.h, "Packed table layout") of entries
/// keyed by cluster codepoints, one byte per codepoint: 0x80 | (cp -
/// blockBase) for the script's block, 0x01 for ZWJ, 0x02 for KEY_INIT_CP,
/// 0x03 for KEY_FINA_CP, 0x04..0x06 for the bookkeeping keys above, 0x10 | n
/// for a class index. Each entry carries a meta byte and a uint16 LE value.
/// Meta: bits 0-2 key length, bit 3 "continues" (the ligature also forms
/// with a following virama + consonant), bits 4-7 the pre-base sign class of
/// the glyph. Value: bits 0-12 output codepoint minus 0xE000 (0x1FFF = no
/// glyph), bits 13-15 the post-base sign class. Keys cover consonant
/// clusters, clusters plus a vowel sign (below-base, ি, ী), reph plus ি/ী,
/// and the INIT/FINA context forms. Kind 1 allows 5-byte keys, kinds 2..10
/// 7-byte keys.
///
/// Sign classes: a glyph's class says which contextual variant of ি (pre) or
/// ী (post) the font draws next to it; {KEY_VARIANT_CP, sign[, modifier],
/// KEY_CLASS_INDEX_CP + n} maps class n to the variant glyph, and
/// {KEY_CLASS_CP, consonant} carries the classes of a bare consonant.
struct ClusterTable {
  const uint8_t* entries = nullptr;  ///< the packed blob: directory, then one section per key length
  uint16_t count = 0;                ///< entries in the blob (the sum of the directory's counts)
  uint8_t kind = 0;                  ///< SHAPE_KIND_*; a table is only read by the script of the same kind
};

/// Size in bytes of a packed table whose directory starts at `directory`,
/// for `kind`, with the entry count written to `count` when given; 0 when
/// the directory is inconsistent (entries at a length the kind does not
/// allow, or buckets without entries). A host reads the directory first to
/// know how much to load.
uint32_t packedTableBytes(const uint8_t* directory, uint8_t kind, uint32_t* count = nullptr);

/// A decoded table entry.
struct Entry {
  uint32_t cp = 0;  ///< output codepoint, 0 when the entry has none (or was not found)
  uint8_t preClass = 0;
  uint8_t postClass = 0;
  bool continues = false;
  bool found = false;
};
constexpr uint16_t VALUE_NO_GLYPH = 0x1FFF;

/// Byte-level pre-check: true when the UTF-8 text can contain a codepoint
/// from a block that has a shaper (lead byte 0xE0 followed by one of the
/// block's continuation bytes).
bool mayNeedShaping(const char* utf8);

/// Exact lookup of a cluster key (2..maxKeyLenForKind codepoints) built from
/// `script`. Returns the output codepoint, or 0 when the table has no such
/// entry or is not of the script's kind.
uint32_t lookupCluster(const ClusterTable& table, const ScriptDesc& script, const uint32_t* cps, uint32_t len);
/// The same lookup with the whole entry decoded.
Entry lookupEntry(const ClusterTable& table, const ScriptDesc& script, const uint32_t* cps, uint32_t len);
/// Format number recorded in the table's marker entry, 0 when there is none.
uint8_t tableFormat(const ClusterTable& table);
/// Part of a danda's advance, in 1/256, that is built-in space the font drops
/// after a space character (Tiro: "X ।" and "X।" put the danda in the same
/// place). A host laying out words takes advance * share / 256 off the space
/// before a word that starts with `cp`. 0 when the table records none or `cp`
/// is not a danda.
uint8_t dandaSpaceShare(const ClusterTable& table, uint32_t cp);

/// Shapes `utf8` into `out` (cleared first). Codepoints of scripts without a
/// descriptor pass through in place; ZWJ/ZWNJ are consumed. Returns false,
/// leaving `out` untouched, when the text is null or empty.
bool shape(const char* utf8, const ClusterTable& table, std::string& out);

}  // namespace Lipi
