// ScriptTablesTest — the per-script descriptors (providers/*/descriptor.h) against
// the predicates they replaced and the renderer's mark classification.

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "Lipi.h"
#include "PackedTable.h"

namespace {

using Lipi::kBengali;

// The Bengali predicates as they were hard-coded before the descriptors
// existed (the former BengaliShaper.cpp); the descriptor must reproduce them
// exactly.
bool oldConsonant(const uint32_t cp) {
  return (cp >= 0x0995 && cp <= 0x09A8) || (cp >= 0x09AA && cp <= 0x09B0) || cp == 0x09B2 ||
         (cp >= 0x09B6 && cp <= 0x09B9) || cp == 0x09DC || cp == 0x09DD || cp == 0x09DF || cp == 0x09F0 || cp == 0x09F1;
}
bool oldIndependentVowel(const uint32_t cp) {
  return (cp >= 0x0985 && cp <= 0x098C) || cp == 0x098F || cp == 0x0990 || cp == 0x0993 || cp == 0x0994 ||
         cp == 0x09E0 || cp == 0x09E1 || cp == 0x09FC;
}
bool oldSyllableBase(const uint32_t cp) {
  return oldConsonant(cp) || oldIndependentVowel(cp) || cp == 0x09CE || cp == 0x09BD;
}
bool oldPreBaseVowel(const uint32_t cp) { return cp == 0x09BF || cp == 0x09C7 || cp == 0x09C8; }
bool oldPostBaseVowel(const uint32_t cp) { return cp == 0x09BE || cp == 0x09C0 || cp == 0x09D7; }
bool oldBelowVowel(const uint32_t cp) { return (cp >= 0x09C1 && cp <= 0x09C4) || cp == 0x09E2 || cp == 0x09E3; }
bool oldModifier(const uint32_t cp) { return cp == 0x0981 || cp == 0x0982 || cp == 0x0983 || cp == 0x09FE; }
bool oldRa(const uint32_t cp) { return cp == 0x09B0 || cp == 0x09F0; }
uint32_t oldPrecomposedNukta(const uint32_t cp) {
  switch (cp) {
    case 0x09A1:
      return 0x09DC;
    case 0x09A2:
      return 0x09DD;
    case 0x09AF:
      return 0x09DF;
    default:
      return 0;
  }
}

// Every codepoint the sweep covers: the ten Indic blocks plus neighbours,
// so a descriptor cannot claim anything outside its own block.
std::vector<uint32_t> sweep() {
  std::vector<uint32_t> cps;
  for (uint32_t cp = 0x0000; cp < 0x0E80; ++cp) cps.push_back(cp);
  for (uint32_t cp = 0x2000; cp < 0x2070; ++cp) cps.push_back(cp);
  for (uint32_t cp = 0xE000; cp < 0xF900; cp += 7) cps.push_back(cp);
  return cps;
}

}  // namespace

TEST(ScriptTables, BengaliDescriptorIdentity) {
  EXPECT_EQ(kBengali.shapeKind, Lipi::SHAPE_KIND_BENGALI);
  EXPECT_EQ(kBengali.block, ScriptBlock::Bengali);
  EXPECT_EQ(kBengali.blockBase, 0x0980u);
  EXPECT_EQ(kBengali.rephMode, Lipi::RephMode::PreBase);
  EXPECT_EQ(kBengali.joinStyle, Lipi::JoinStyle::Subjoined);
  EXPECT_EQ(kBengali.virama, 0x09CDu);
  EXPECT_EQ(kBengali.nukta, 0x09BCu);
  EXPECT_EQ(kBengali.ra, 0x09B0u);
  EXPECT_EQ(kBengali.candrabindu, 0x0981u);
  EXPECT_EQ(kBengali.preSignWithForms, 0x09BFu);
  EXPECT_EQ(kBengali.postSignWithForms, 0x09C0u);
  EXPECT_EQ(kBengali.postBaseConsonant, 0x09AFu);
  // Every pre-base sign with per-base forms includes the fusable one.
  EXPECT_TRUE(kBengali.in(kBengali.preSignsWithForms, kBengali.preSignWithForms));
  EXPECT_TRUE(kBengali.in(kBengali.preSignsWithForms, 0x09C7));
  EXPECT_TRUE(kBengali.in(kBengali.preSignsWithForms, 0x09C8));
  EXPECT_FALSE(kBengali.in(kBengali.preSignsWithForms, 0x09BE));
  EXPECT_TRUE(Lipi::kDevanagari.in(Lipi::kDevanagari.preSignsWithForms, Lipi::kDevanagari.preSignWithForms));
  EXPECT_FALSE(Lipi::kDevanagari.in(Lipi::kDevanagari.preSignsWithForms, 0x0947));
}

TEST(ScriptTables, BengaliMasksMatchTheOriginalPredicates) {
  for (const uint32_t cp : sweep()) {
    EXPECT_EQ(kBengali.isConsonant(cp), oldConsonant(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isIndependentVowel(cp), oldIndependentVowel(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isSyllableBase(cp), oldSyllableBase(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isPreBaseVowel(cp), oldPreBaseVowel(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isPostBaseVowel(cp), oldPostBaseVowel(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isBelowVowel(cp), oldBelowVowel(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isModifier(cp), oldModifier(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.isRa(cp), oldRa(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.precomposedNukta(cp), oldPrecomposedNukta(cp)) << std::hex << cp;
    EXPECT_EQ(kBengali.inBlock(cp), cp >= 0x0980 && cp <= 0x09FF) << std::hex << cp;
  }
}

TEST(ScriptTables, BengaliSplitVowels) {
  ASSERT_EQ(kBengali.splitVowelCount, 2);
  const auto* o = kBengali.splitVowel(0x09CB);
  ASSERT_NE(o, nullptr);
  EXPECT_EQ(o->pre, 0x09C7u);
  EXPECT_EQ(o->post, 0x09BEu);
  const auto* au = kBengali.splitVowel(0x09CC);
  ASSERT_NE(au, nullptr);
  EXPECT_EQ(au->pre, 0x09C7u);
  EXPECT_EQ(au->post, 0x09D7u);
  EXPECT_EQ(kBengali.splitVowel(0x09C7), nullptr);
}

TEST(ScriptTables, NonSpacingMaskMatchesIsMark) {
  // The renderer decides zero-advance placement from Lipi::isMark; each
  // descriptor's mask is the same set for the script's own block, and blocks
  // without a descriptor have no marks.
  for (uint32_t cp = 0x0900; cp < 0x0E00; ++cp) {
    const auto* d = Lipi::scriptFor(cp);
    EXPECT_EQ(d ? d->in(d->nonSpacing, cp) : false, Lipi::isMark(cp)) << std::hex << cp;
  }
  EXPECT_FALSE(Lipi::isMark(0x08FF));
  EXPECT_FALSE(Lipi::isMark(0x0E00));
  // Below vowels and the modifiers drawn as marks are non-spacing; the
  // spacing signs are not.
  for (uint32_t cp = 0x0980; cp <= 0x09FF; ++cp) {
    if (kBengali.isBelowVowel(cp)) {
      EXPECT_TRUE(kBengali.in(kBengali.nonSpacing, cp)) << std::hex << cp;
    }
    if (kBengali.isPreBaseVowel(cp) || kBengali.isPostBaseVowel(cp)) {
      EXPECT_FALSE(kBengali.in(kBengali.nonSpacing, cp)) << std::hex << cp;
    }
  }
  EXPECT_TRUE(kBengali.in(kBengali.nonSpacing, kBengali.virama));
  EXPECT_TRUE(kBengali.in(kBengali.nonSpacing, kBengali.nukta));
  EXPECT_TRUE(kBengali.in(kBengali.nonSpacing, kBengali.candrabindu));
}

TEST(ScriptTables, ScriptLookupByBlock) {
  EXPECT_EQ(Lipi::scriptFor(0x0995), &kBengali);  // ক
  EXPECT_EQ(Lipi::scriptFor(0x0980), &kBengali);
  EXPECT_EQ(Lipi::scriptFor(0x09FF), &kBengali);
  EXPECT_EQ(Lipi::scriptFor(0x0915), &Lipi::kDevanagari);  // Devanagari ka
  EXPECT_EQ(Lipi::scriptFor(0x0964), &Lipi::kDevanagari);  // danda: passes through as a non-base
  EXPECT_EQ(Lipi::scriptFor(0x0A15), nullptr);             // Gurmukhi ka: no shaper yet
  EXPECT_EQ(Lipi::scriptFor('a'), nullptr);
  EXPECT_EQ(Lipi::scriptFor(0x4E00), nullptr);
  EXPECT_EQ(Lipi::kScriptByBlock[static_cast<uint8_t>(ScriptBlock::None)], nullptr);
  for (uint8_t b = 0; b < static_cast<uint8_t>(ScriptBlock::COUNT); ++b) {
    const auto* d = Lipi::kScriptByBlock[b];
    if (d) {
      EXPECT_EQ(d->block, static_cast<ScriptBlock>(b));
    }
  }
}

TEST(ScriptTables, DevanagariDescriptor) {
  const auto& d = Lipi::kDevanagari;
  EXPECT_EQ(d.shapeKind, Lipi::SHAPE_KIND_DEVANAGARI);
  EXPECT_EQ(d.blockBase, 0x0900u);
  EXPECT_EQ(d.joinStyle, Lipi::JoinStyle::HalfForm);
  EXPECT_TRUE(d.rephAfterPost);
  EXPECT_EQ(d.splitVowelCount, 0);
  EXPECT_EQ(d.postBaseConsonant, 0u);
  for (uint32_t cp = 0x0915; cp <= 0x0939; ++cp) EXPECT_TRUE(d.isConsonant(cp)) << std::hex << cp;
  for (uint32_t cp = 0x0958; cp <= 0x095F; ++cp) {
    EXPECT_TRUE(d.isConsonant(cp)) << std::hex << cp;
    EXPECT_EQ(d.precomposedNukta(cp), 0u) << std::hex << cp;  // already precomposed
  }
  EXPECT_EQ(d.precomposedNukta(0x0915), 0x0958u);
  EXPECT_EQ(d.precomposedNukta(0x091C), 0x095Bu);
  EXPECT_EQ(d.precomposedNukta(0x0921), 0x095Cu);
  EXPECT_EQ(d.precomposedNukta(0x092F), 0x095Fu);
  EXPECT_EQ(d.precomposedNukta(0x0924), 0u);
  EXPECT_TRUE(d.isIndependentVowel(0x0905));
  EXPECT_TRUE(d.isIndependentVowel(0x0972));
  EXPECT_TRUE(d.isSyllableBase(0x0950));  // om
  EXPECT_TRUE(d.isSyllableBase(0x093D));  // avagraha
  EXPECT_FALSE(d.isSyllableBase(0x0964));
  EXPECT_TRUE(d.isPreBaseVowel(0x093F));
  EXPECT_TRUE(d.isPostBaseVowel(0x093E));
  EXPECT_TRUE(d.isPostBaseVowel(0x094B));
  EXPECT_TRUE(d.isPostBaseVowel(0x094C));
  EXPECT_TRUE(d.isAboveVowel(0x0947));
  EXPECT_TRUE(d.isAboveVowel(0x0945));
  EXPECT_TRUE(d.isBelowVowel(0x0941));
  EXPECT_TRUE(d.isBelowVowel(0x0943));
  EXPECT_TRUE(d.isModifier(0x0902));
  EXPECT_TRUE(d.isModifier(0x0903));
  EXPECT_TRUE(d.isModifier(0x0951));
  // Every vowel sign is exactly one of pre/post/above/below.
  for (uint32_t cp = 0x093A; cp <= 0x094F; ++cp) {
    if (cp == 0x093C || cp == 0x093D || cp == 0x094D) continue;
    const int classes = d.isPreBaseVowel(cp) + d.isPostBaseVowel(cp) + d.isAboveVowel(cp) + d.isBelowVowel(cp);
    EXPECT_EQ(classes, 1) << std::hex << cp;
    EXPECT_FALSE(d.isConsonant(cp) || d.isModifier(cp)) << std::hex << cp;
  }
}

TEST(ScriptTables, PackedDirectorySizesTheTable) {
  // Directory: per key length 2..7 a u16 entry count and a u8 bucket count;
  // a section costs 3 bytes per bucket plus (length + 2) per entry.
  const LipiTest::Packed packed = LipiTest::packRows({
      LipiTest::makeRow({0x95, 0xCD}, 0xE000, 0, 0, false),
      LipiTest::makeRow({0x95, 0xCD, 0xB7}, 0xE001, 0, 0, false),
      LipiTest::makeRow({0x96, 0xCD, 0xB7}, 0xE002, 0, 0, false),
      LipiTest::makeRow({0x96, 0xCD, 0xB8}, 0xE003, 0, 0, false),
  });
  EXPECT_EQ(packed.count, 4u);
  EXPECT_EQ(packed.bytes.size(), Lipi::PACKED_DIRECTORY_BYTES + (3 + 1 * 4) + (2 * 3 + 3 * 5));
  uint32_t count = 0;
  EXPECT_EQ(Lipi::packedTableBytes(packed.bytes.data(), Lipi::SHAPE_KIND_BENGALI, &count), packed.bytes.size());
  EXPECT_EQ(count, 4u);
  // A length the kind does not allow, or buckets without entries, is rejected.
  std::vector<uint8_t> bad = packed.bytes;
  bad[(6 - 2) * 3] = 1;  // one entry (in one bucket) of length 6: fine for kind 2, not for kind 1
  bad[(6 - 2) * 3 + 2] = 1;
  EXPECT_EQ(Lipi::packedTableBytes(bad.data(), Lipi::SHAPE_KIND_BENGALI, nullptr), 0u);
  EXPECT_NE(Lipi::packedTableBytes(bad.data(), Lipi::SHAPE_KIND_DEVANAGARI, nullptr), 0u);
  bad = packed.bytes;
  bad[(4 - 2) * 3 + 2] = 1;  // a bucket at length 4 with no entries
  EXPECT_EQ(Lipi::packedTableBytes(bad.data(), Lipi::SHAPE_KIND_BENGALI, nullptr), 0u);
  EXPECT_EQ(Lipi::packedTableBytes(nullptr, Lipi::SHAPE_KIND_BENGALI, nullptr), 0u);
  EXPECT_EQ(Lipi::packedTableBytes(packed.bytes.data(), 0, nullptr), 0u);
  // The lookup reads the packed rows: the format marker style keys included.
  const Lipi::ClusterTable table{packed.bytes.data(), packed.count, Lipi::SHAPE_KIND_BENGALI};
  const uint32_t two[2] = {0x0995, 0x09CD};
  const uint32_t three[3] = {0x0996, 0x09CD, 0x09B8};
  const uint32_t missing[3] = {0x0997, 0x09CD, 0x09B8};
  EXPECT_EQ(Lipi::lookupCluster(table, kBengali, two, 2), 0xE000u);
  EXPECT_EQ(Lipi::lookupCluster(table, kBengali, three, 3), 0xE003u);
  EXPECT_EQ(Lipi::lookupCluster(table, kBengali, missing, 3), 0u);
}

TEST(ScriptTables, TableKindGeometry) {
  // Kind 1 is frozen: existing Bengali fonts must keep loading.
  EXPECT_EQ(Lipi::entrySizeForKind(Lipi::SHAPE_KIND_BENGALI), 8u);
  EXPECT_EQ(Lipi::maxKeyLenForKind(Lipi::SHAPE_KIND_BENGALI), 5u);
  // Every later script shares the wider geometry.
  for (uint8_t kind = Lipi::SHAPE_KIND_DEVANAGARI; kind <= Lipi::SHAPE_KIND_LAST; ++kind) {
    EXPECT_EQ(Lipi::entrySizeForKind(kind), 10u) << int(kind);
    EXPECT_EQ(Lipi::maxKeyLenForKind(kind), 7u) << int(kind);
  }
  EXPECT_EQ(Lipi::SHAPE_KIND_LAST, 10);
  EXPECT_EQ(Lipi::entrySizeForKind(0), 0u);
  EXPECT_EQ(Lipi::maxKeyLenForKind(0), 0u);
  EXPECT_EQ(Lipi::entrySizeForKind(11), 0u);
  EXPECT_EQ(Lipi::entrySizeForKind(255), 0u);
  // The budget holds the largest table built so far (Tiro Bangla, 1064
  // kind-1 entries) with room for the wider kinds.
  EXPECT_GE(Lipi::MAX_SHAPE_TABLE_BYTES, 1064u * 8u);
  EXPECT_LE(Lipi::MAX_SHAPE_TABLE_BYTES, 16384u);
  // key + length byte + u16 output fit the entry for every readable kind.
  for (uint32_t kind = 0; kind < 256; ++kind) {
    const uint32_t size = Lipi::entrySizeForKind(static_cast<uint8_t>(kind));
    const uint32_t keyLen = Lipi::maxKeyLenForKind(static_cast<uint8_t>(kind));
    if (size == 0) {
      EXPECT_EQ(keyLen, 0u);
      continue;
    }
    EXPECT_EQ(size, keyLen + 3);
    EXPECT_LE(keyLen, Lipi::MAX_KEY_CAP);
  }
}

TEST(ScriptTables, Kind1KeysAreCodepointMinus0x0900) {
  // A kind-1 entry whose key bytes are cp - 0x0900 (the format the Bengali
  // font builder writes) is found for every letter of the block, and the
  // Assamese ra probes as ra.
  std::vector<uint8_t> bytes;
  std::vector<uint32_t> letters;
  for (uint32_t cp = 0x0980; cp <= 0x09FF; ++cp) {
    if (kBengali.isConsonant(cp) && cp != 0x09F0) letters.push_back(cp);
  }
  // Output U+E000 + (cp - 0x0980), stored as the offset from U+E000.
  std::vector<LipiTest::Row> rows;
  for (const uint32_t cp : letters) {
    rows.push_back(
        LipiTest::makeRow({static_cast<uint8_t>(cp - 0x0900), 0xCD, 0x95}, 0xE000 + (cp - 0x0980), 0, 0, false));
  }
  const LipiTest::Packed packed = LipiTest::packRows(rows);
  bytes = packed.bytes;
  const Lipi::ClusterTable table{bytes.data(), packed.count, Lipi::SHAPE_KIND_BENGALI};
  EXPECT_EQ(packed.count, letters.size());
  uint32_t counted = 0;
  EXPECT_EQ(Lipi::packedTableBytes(bytes.data(), Lipi::SHAPE_KIND_BENGALI, &counted), bytes.size());
  EXPECT_EQ(counted, letters.size());
  for (const uint32_t cp : letters) {
    const uint32_t key[3] = {cp, 0x09CD, 0x0995};
    EXPECT_EQ(Lipi::lookupCluster(table, kBengali, key, 3), 0xE000u + (cp - 0x0980)) << std::hex << cp;
  }
  const uint32_t assamese[3] = {0x09F0, 0x09CD, 0x0995};
  EXPECT_EQ(Lipi::lookupCluster(table, kBengali, assamese, 3), 0xE000u + (0x09B0 - 0x0980));
  const uint32_t devanagari[3] = {0x0915, 0x09CD, 0x0995};
  EXPECT_EQ(Lipi::lookupCluster(table, kBengali, devanagari, 3), 0u);
}

TEST(ScriptTables, Kind2TablesHoldSevenByteKeys) {
  // A 10-byte-entry table of another kind is read with 7-byte keys by a
  // script of that kind (here Bengali letters under kind 2, standing in for
  // the scripts that use it), and stays invisible to kind-1 Bengali.
  Lipi::ScriptDesc kind2 = kBengali;
  kind2.shapeKind = Lipi::SHAPE_KIND_DEVANAGARI;
  const LipiTest::Packed packed = LipiTest::packRows({
      LipiTest::makeRow({0x95, 0xCD, 0xB7}, 0xE000, 0, 0, false),                          // ক্ষ
      LipiTest::makeRow({0x95, 0xCD, 0xB7, 0xCD, 0xA3, 0xCD, 0xAF}, 0xE001, 0, 0, false),  // ক্ষ্ণ্য: a seven-byte key
      LipiTest::makeRow({0xB8, 0xCD, 0xA4, 0xCD, 0xB0, 0xBF, 0x03}, 0xE002, 0, 0, false),  // স্ত্রি + FINA
  });
  const Lipi::ClusterTable table{packed.bytes.data(), packed.count, Lipi::SHAPE_KIND_DEVANAGARI};
  const uint32_t ksha[3] = {0x0995, 0x09CD, 0x09B7};
  const uint32_t seven[7] = {0x0995, 0x09CD, 0x09B7, 0x09CD, 0x09A3, 0x09CD, 0x09AF};
  const uint32_t fina[7] = {0x09B8, 0x09CD, 0x09A4, 0x09CD, 0x09B0, 0x09BF, Lipi::KEY_FINA_CP};
  EXPECT_EQ(Lipi::lookupCluster(table, kind2, ksha, 3), 0xE000u);
  EXPECT_EQ(Lipi::lookupCluster(table, kind2, seven, 7), 0xE001u);
  EXPECT_EQ(Lipi::lookupCluster(table, kind2, fina, 7), 0xE002u);
  EXPECT_EQ(Lipi::lookupCluster(table, kind2, seven, 6), 0u);    // prefix is not an entry
  EXPECT_EQ(Lipi::lookupCluster(table, kBengali, ksha, 3), 0u);  // kind mismatch
  const uint32_t eight[8] = {0x0995, 0x09CD, 0x0995, 0x09CD, 0x0995, 0x09CD, 0x0995, 0x09CD};
  EXPECT_EQ(Lipi::lookupCluster(table, kind2, eight, 8), 0u);  // longer than any key
}

TEST(ScriptTables, EntryMetaAndValueBits) {
  // Meta byte: length (bits 0-2), continues (bit 3), pre-sign class (bits
  // 4-7). Value: post-sign class (bits 13-15), codepoint - 0xE000, with
  // 0x1FFF for an entry without a glyph.
  Lipi::ScriptDesc kind2 = kBengali;
  kind2.shapeKind = Lipi::SHAPE_KIND_DEVANAGARI;
  // Rows as the builder packs them: {CLASS, ক} pre 2, post 1, no glyph
  // (meta 0x22, value 0x3FFF); ক্ষ len 3, continues, pre 5, post 0, U+F234
  // (meta 0x5B, value 0x1234).
  const LipiTest::Packed packed = LipiTest::packRows({
      LipiTest::makeRow({0x04, 0x95}, 0, 2, 1, false),
      LipiTest::makeRow({0x95, 0xCD, 0xB7}, 0xF234, 5, 0, true),
  });
  const Lipi::ClusterTable table{packed.bytes.data(), packed.count, Lipi::SHAPE_KIND_DEVANAGARI};
  const uint32_t cls[2] = {Lipi::KEY_CLASS_CP, 0x0995};
  const Lipi::Entry a = Lipi::lookupEntry(table, kind2, cls, 2);
  EXPECT_TRUE(a.found);
  EXPECT_EQ(a.cp, 0u);
  EXPECT_EQ(a.preClass, 2);
  EXPECT_EQ(a.postClass, 1);
  EXPECT_FALSE(a.continues);
  const uint32_t ksha[3] = {0x0995, 0x09CD, 0x09B7};
  const Lipi::Entry b = Lipi::lookupEntry(table, kind2, ksha, 3);
  EXPECT_TRUE(b.found);
  EXPECT_EQ(b.cp, 0xF234u);
  EXPECT_EQ(b.preClass, 5);
  EXPECT_EQ(b.postClass, 0);
  EXPECT_TRUE(b.continues);
  EXPECT_EQ(Lipi::lookupCluster(table, kind2, cls, 2), 0u);
  EXPECT_EQ(Lipi::tableFormat(table), 0);                        // no marker
  EXPECT_FALSE(Lipi::lookupEntry(table, kind2, ksha, 2).found);  // prefix, wrong length
}

TEST(ScriptTables, PuaRangesAnchorAsTheBuilderExpects) {
  for (uint32_t cp = Lipi::PUA_BELOW_FIRST; cp <= Lipi::PUA_BELOW_LAST; ++cp) {
    EXPECT_TRUE(Lipi::isMark(cp)) << std::hex << cp;
    EXPECT_EQ(Lipi::anchorClass(cp), Lipi::MarkAnchor::Center) << std::hex << cp;
  }
  for (uint32_t cp = Lipi::PUA_ABOVE_FIRST; cp <= Lipi::PUA_ABOVE_LAST; ++cp) {
    EXPECT_TRUE(Lipi::isMark(cp)) << std::hex << cp;
    EXPECT_EQ(Lipi::anchorClass(cp), Lipi::MarkAnchor::Right) << std::hex << cp;
  }
  for (uint32_t cp = Lipi::PUA_ABOVE_CENTER_FIRST; cp <= Lipi::PUA_ABOVE_CENTER_LAST; ++cp) {
    EXPECT_TRUE(Lipi::isMark(cp)) << std::hex << cp;
    EXPECT_EQ(Lipi::anchorClass(cp), Lipi::MarkAnchor::Center) << std::hex << cp;
  }
  for (uint32_t cp = Lipi::PUA_BELOW_RIGHT_FIRST; cp <= Lipi::PUA_BELOW_RIGHT_LAST; ++cp) {
    EXPECT_TRUE(Lipi::isMark(cp)) << std::hex << cp;
    EXPECT_EQ(Lipi::anchorClass(cp), Lipi::MarkAnchor::Right) << std::hex << cp;
  }
  for (uint32_t cp = Lipi::PUA_BASE_FIRST; cp <= Lipi::PUA_BASE_LAST; cp += 0x11) {
    EXPECT_FALSE(Lipi::isMark(cp)) << std::hex << cp;
  }
  // Sign forms and pre-base consonant forms are spacing glyphs.
  for (uint32_t cp = Lipi::PUA_PRE_FIRST; cp <= Lipi::PUA_PRECONS_LAST; ++cp) {
    EXPECT_FALSE(Lipi::isMark(cp)) << std::hex << cp;
  }
  // The classes tile F000..F6FF without gaps or overlap.
  EXPECT_EQ(Lipi::PUA_ABOVE_FIRST, Lipi::PUA_BELOW_LAST + 1);
  EXPECT_EQ(Lipi::PUA_ABOVE_CENTER_FIRST, Lipi::PUA_ABOVE_LAST + 1);
  EXPECT_EQ(Lipi::PUA_BELOW_RIGHT_FIRST, Lipi::PUA_ABOVE_CENTER_LAST + 1);
  EXPECT_EQ(Lipi::PUA_PRE_FIRST, Lipi::PUA_BELOW_RIGHT_LAST + 1);
  EXPECT_EQ(Lipi::PUA_POST_FIRST, Lipi::PUA_PRE_LAST + 1);
  EXPECT_EQ(Lipi::PUA_PRECONS_FIRST, Lipi::PUA_POST_LAST + 1);
  // Bengali non-spacing marks anchor at the font's own height; only the
  // hasanta hangs from the right stem.
  for (uint32_t cp = 0x0980; cp <= 0x09FF; ++cp) {
    if (Lipi::isMark(cp)) {
      const auto expected = cp == 0x09CD ? Lipi::MarkAnchor::Pen : Lipi::MarkAnchor::Center;
      EXPECT_EQ(Lipi::anchorClass(cp), expected) << std::hex << cp;
    }
  }
}

// --- The renderer's mark queries before they moved into the descriptors -----
//
// utf8IsIndicMark, combiningMark::attachesBelow and combiningMark::anchorFor as
// the CrossInk reader had them at tag pre-lipi, copied verbatim except that
// anchorFor's result is expressed as MarkAnchor and its Hebrew cases (which
// stayed in the reader) are dropped. The engine's replacements must agree on
// every codepoint, so the move cannot change a single mark's placement.
namespace legacy {

bool utf8IsIndicMark(const uint32_t cp) {
  if (cp >= 0xF000 && cp <= 0xF3FF) return true;  // PUA mark classes
  if (cp < 0x0900 || cp >= 0x0E00) return false;
  const uint32_t off = (cp - 0x0900) & 0x7F;
  switch ((cp - 0x0900) >> 7) {
    case 0:  // Devanagari: ऀ ँ ं ऺ ़ ु..ै ् ॑..ॗ ॢ ॣ
      return off <= 0x02 || off == 0x3A || off == 0x3C || (off >= 0x41 && off <= 0x48) || off == 0x4D ||
             (off >= 0x51 && off <= 0x57) || off == 0x62 || off == 0x63;
    case 1:  // Bengali: ঁ ় ু ূ ৃ ৄ ্ ৢ ৣ ৾
      return off == 0x01 || off == 0x3C || (off >= 0x41 && off <= 0x44) || off == 0x4D || off == 0x62 || off == 0x63 ||
             off == 0x7E;
    default:
      return false;
  }
}

constexpr bool attachesBelow(const uint32_t cp) {
  return (cp >= 0x09C1 && cp <= 0x09C4) || cp == 0x09BC || cp == 0x09CD || cp == 0x09E2 || cp == 0x09E3 ||
         (cp >= 0x0941 && cp <= 0x0944) || cp == 0x093C || cp == 0x094D || cp == 0x0952 || cp == 0x0956 ||
         cp == 0x0957 || cp == 0x0962 || cp == 0x0963 || (cp >= 0xF000 && cp <= 0xF0FF) ||
         (cp >= 0xF300 && cp <= 0xF3FF);
}

using Lipi::MarkAnchor;

constexpr MarkAnchor anchorFor(const uint32_t cp) {
  if ((cp >= 0x09C1 && cp <= 0x09C4) || cp == 0x09BC || cp == 0x09E2 || cp == 0x09E3 ||
      (cp >= 0xF000 && cp <= 0xF0FF) || (cp >= 0xF200 && cp <= 0xF2FF)) {
    return MarkAnchor::Center;
  }
  if (cp == 0x0981 || cp == 0x09FE) return MarkAnchor::Center;
  if (cp == 0x09CD || cp == 0x094D) return MarkAnchor::Pen;
  if ((cp >= 0xF100 && cp <= 0xF1FF) || (cp >= 0xF300 && cp <= 0xF3FF)) return MarkAnchor::Right;
  if ((cp >= 0x0941 && cp <= 0x0944) || cp == 0x0956 || cp == 0x0957 || cp == 0x0962 || cp == 0x0963 || cp == 0x093C ||
      cp == 0x0952) {
    return MarkAnchor::Center;
  }
  if (cp == 0x0900 || cp == 0x0901 || cp == 0x0951 || cp == 0x0953 || cp == 0x0954) return MarkAnchor::Center;
  if (cp == 0x0902 || cp == 0x093A || (cp >= 0x0945 && cp <= 0x0948) || cp == 0x0955) return MarkAnchor::Right;
  return MarkAnchor::None;
}

}  // namespace legacy

TEST(ScriptTables, MarkQueriesMatchThePreLipiRendererOnEveryCodepoint) {
  for (uint32_t cp = 0; cp <= 0x10000; ++cp) {
    EXPECT_EQ(Lipi::isMark(cp), legacy::utf8IsIndicMark(cp)) << std::hex << cp;
    EXPECT_EQ(Lipi::attachesBelow(cp), legacy::attachesBelow(cp)) << std::hex << cp;
    EXPECT_EQ(Lipi::anchorClass(cp), legacy::anchorFor(cp)) << std::hex << cp;
  }
}

TEST(ScriptTables, DescriptorMarkSetsAreConsistent) {
  // Every anchored or below-attached mark is non-spacing, and no mark sits in
  // two anchor classes.
  for (const auto* d : Lipi::kScriptByBlock) {
    if (!d) continue;
    for (uint32_t off = 0; off < 0x80; ++off) {
      const uint32_t cp = d->blockBase + off;
      const int classes = d->in(d->anchorCenter, cp) + d->in(d->anchorRight, cp) + d->in(d->anchorPen, cp);
      EXPECT_LE(classes, 1) << std::hex << cp;
      if (classes || d->in(d->attachBelow, cp)) EXPECT_TRUE(d->in(d->nonSpacing, cp)) << std::hex << cp;
    }
  }
}
