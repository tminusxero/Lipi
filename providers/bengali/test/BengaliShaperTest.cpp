// BengaliShaperTest — syllable segmentation, vowel-sign reordering and
// cluster-table resolution for Bengali text through the data-driven
// Lipi engine (Bengali descriptor, kind-1 table).
//
// Inputs are codepoint arrays in LOGICAL order; expectations are the visual
// codepoint stream drawText() consumes. The cluster table is a synthetic one
// built with the same packing rules as builder/shaping.py.

#include <gtest/gtest.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "Lipi.h"
#include "LipiUtf8.h"
#include "PackedTable.h"

namespace {

constexpr uint32_t KA = 0x0995, KHA = 0x0996, NA = 0x09A8, TA = 0x09A4, RA = 0x09B0, SA = 0x09B8, SSA = 0x09B7,
                   NNA = 0x09A3, YA = 0x09AF, LA = 0x09B2, BA = 0x09AC, DDA = 0x09A1, SHA = 0x09B6, HA = 0x09B9,
                   TTA = 0x099F, TTHA = 0x09A0, ASSAMESE_RA = 0x09F0, DANDA = 0x0964;
constexpr uint32_t VIRAMA = 0x09CD, NUKTA = 0x09BC, ZWJ = 0x200D, ZWNJ = 0x200C;
constexpr uint32_t AA = 0x09BE, I = 0x09BF, II = 0x09C0, U = 0x09C1, E = 0x09C7, O = 0x09CB, AU = 0x09CC,
                   AU_LEN = 0x09D7;
constexpr uint32_t INIT = Lipi::KEY_INIT_CP, FINA = Lipi::KEY_FINA_CP;
constexpr uint8_t KIND = Lipi::SHAPE_KIND_BENGALI;
constexpr size_t ENTRY = Lipi::entrySizeForKind(KIND);
const Lipi::ScriptDesc& BENGALI = Lipi::kBengali;
constexpr uint32_t CANDRABINDU = 0x0981, ANUSVARA = 0x0982;

// Synthetic PUA outputs.
constexpr uint32_t KSSA = 0xE000;              // ক্ষ
constexpr uint32_t NTRA = 0xE001;              // ন্ত্র
constexpr uint32_t NTA = 0xE002;               // ন্ত
constexpr uint32_t STA = 0xE003;               // স্ত
constexpr uint32_t RKA = 0xE004;               // র্ক (reph composite)
constexpr uint32_t RU = 0xE005;                // রু ligature
constexpr uint32_t RZWJYA = 0xE006;            // র্‍য (the font's form for ra + virama + ZWJ + ya)
constexpr uint32_t YAPHALA = 0xE007;           // ্য spacing post-base form
constexpr uint32_t TTI = 0xE008;               // টি ligature (cluster and sign fused)
constexpr uint32_t NNDDA = 0xE009;             // ণ্ড
constexpr uint32_t SSTTHA = 0xE00A;            // ষ্ঠ
constexpr uint32_t RAPHALA = 0xF000;           // ্র below-base mark
constexpr uint32_t REPH = 0xF100;              // র্ above-base mark
constexpr uint32_t I_WIDE = 0xF400;            // ি sized for ণ্ড (pre-base form)
constexpr uint32_t I_REPH = 0xF401;            // ি fused with a reph, any base
constexpr uint32_t I_REPH_TA = 0xF402;         // ি fused with a reph over ত
constexpr uint32_t E_INIT = 0xF403;            // word-initial ে
constexpr uint32_t AA_FINA = 0xF600;           // word-final া (post-base form)
constexpr uint32_t AU_LEN_FINA = 0xF604;       // word-final ৗ
constexpr uint32_t YAPHALA_FINA = 0xE00B;      // word-final ্য
constexpr uint32_t HYA_FINA = 0xE00C;          // word-final হ্য ligature
constexpr uint32_t II_LONG = 0xF601;           // ী after ষ্ঠ
constexpr uint32_t II_REPH = 0xF602;           // ী fused with a reph
constexpr uint32_t II_REPH_FINA = 0xF603;      // the same at the end of a word
constexpr uint32_t AA_ANUSVARA_FINA = 0xE00E;  // word-final া + ং (Tiro: া.fina before a trailing ং)
constexpr uint32_t YAPHALA_CB = 0xE00F;        // ্য with the candrabindu after it (Tiro order)
constexpr uint32_t YAPHALA_CB_FINA = 0xE013;   // word-final ্য.fina with the candrabindu after it (Tiro)
constexpr uint32_t AU_LEN_CB = 0xE010;         // ৗ.fina + ঁ anywhere in the word (Noto)
constexpr uint32_t TYU = 0xE011;               // ত্যু vowel form
constexpr uint32_t TYU_FINA = 0xE012;          // word-final ত্যু (u on ta, ya-phala.fina)
constexpr uint32_t CB_AFTER_I = 0xF200;        // ঁ.alt after ি (above-centre mark variant)

struct Entry {
  std::vector<uint32_t> key;
  uint32_t out;           // PUA codepoint, 0 for a bookkeeping entry
  uint8_t preClass = 0;   // ি class of the glyph
  uint8_t postClass = 0;  // ী class of the glyph
  bool continues = false;
};

uint8_t keyByte(const uint32_t cp) {
  if (cp == ZWJ) return 0x01;
  if (cp == INIT) return 0x02;
  if (cp == FINA) return 0x03;
  if (cp == Lipi::KEY_CLASS_CP) return 0x04;
  if (cp == Lipi::KEY_VARIANT_CP) return 0x05;
  if (cp == Lipi::KEY_FORMAT_CP) return 0x06;
  if (cp > Lipi::KEY_CLASS_INDEX_CP && cp <= Lipi::KEY_CLASS_INDEX_CP + 15)
    return static_cast<uint8_t>(0x10 | (cp - Lipi::KEY_CLASS_INDEX_CP));
  return static_cast<uint8_t>(cp - 0x0900);
}

// The on-disk layout (packed, format 3): per entry the key bytes, a meta
// byte (length, continues, ি class) and the value (ী class, codepoint -
// 0xE000 or 0x1FFF for no glyph), arranged by key length and first byte.
std::vector<uint8_t> packTable(std::vector<Entry> entries) {
  std::vector<LipiTest::Row> rows;
  for (const auto& e : entries) {
    std::vector<uint8_t> key;
    for (const uint32_t cp : e.key) key.push_back(keyByte(cp));
    rows.push_back(LipiTest::makeRow(std::move(key), e.out, e.preClass, e.postClass, e.continues));
  }
  return LipiTest::packRows(std::move(rows)).bytes;
}

uint16_t entryCount(const std::vector<uint8_t>& bytes) {
  uint32_t n = 0;
  Lipi::packedTableBytes(bytes.data(), KIND, &n);
  return static_cast<uint16_t>(n);
}

// Base table: conjuncts, marks and the cluster-plus-sign forms.
std::vector<Entry> baseEntries() {
  return {
      {{KA, VIRAMA, SSA}, KSSA},
      {{NA, VIRAMA, TA, VIRAMA, RA}, NTRA},
      {{NA, VIRAMA, TA}, NTA},
      {{SA, VIRAMA, TA}, STA},
      {{RA, VIRAMA, KA}, RKA},
      {{RA, U}, RU},
      {{RA, VIRAMA, ZWJ, YA}, RZWJYA},
      {{VIRAMA, YA}, YAPHALA},
      {{VIRAMA, RA}, RAPHALA},
      {{RA, VIRAMA}, REPH},
      {{TTA, I}, TTI},
      {{NNA, VIRAMA, DDA}, NNDDA},
      {{NNA, VIRAMA, DDA, I}, I_WIDE},
      {{RA, VIRAMA, I}, I_REPH},
      {{RA, VIRAMA, TA, I}, I_REPH_TA},
      {{SSA, VIRAMA, TTHA}, SSTTHA},
      {{SSA, VIRAMA, TTHA, II}, II_LONG},
      {{RA, VIRAMA, II}, II_REPH},
      {{RA, VIRAMA, II, FINA}, II_REPH_FINA},
  };
}

// Word-position forms, kept out of the base table so the older tests keep
// their plain signs at word edges.
std::vector<Entry> contextEntries() {
  return {
      {{INIT, E}, E_INIT},
      {{FINA, AA}, AA_FINA},
      {{FINA, AU_LEN}, AU_LEN_FINA},
      {{VIRAMA, YA, FINA}, YAPHALA_FINA},
      {{HA, VIRAMA, YA}, 0xE00D},
      {{HA, VIRAMA, YA, FINA}, HYA_FINA},
      {{AA, ANUSVARA, FINA}, AA_ANUSVARA_FINA},
      {{VIRAMA, YA, CANDRABINDU}, YAPHALA_CB},
      {{VIRAMA, YA, CANDRABINDU, FINA}, YAPHALA_CB_FINA},
      {{AU_LEN, CANDRABINDU}, AU_LEN_CB},
      {{TA, VIRAMA, YA, U}, TYU},
      {{TA, VIRAMA, YA, U, FINA}, TYU_FINA},
      {{CANDRABINDU, I}, CB_AFTER_I},
  };
}

// Sign classes: a ligature and a bare consonant each carry the class of
// the ি/ী drawn next to them; the variant list maps classes to forms.
constexpr uint32_t I_CLASS1 = 0xF410, I_CLASS2 = 0xF411, II_CLASS1 = 0xF610, I_REPH_CLASS2 = 0xF412;
constexpr uint32_t KSSA_CLASSED = 0xE020;  // ক্ষ with classes
constexpr uint32_t IDX1 = Lipi::KEY_CLASS_INDEX_CP + 1, IDX2 = Lipi::KEY_CLASS_INDEX_CP + 2;
std::vector<Entry> classEntries() {
  return {
      {{KHA, VIRAMA, SSA}, KSSA_CLASSED, 2, 1},
      {{Lipi::KEY_CLASS_CP, TTHA}, 0, 1, 1},
      {{Lipi::KEY_VARIANT_CP, I, IDX1}, I_CLASS1},
      {{Lipi::KEY_VARIANT_CP, I, IDX2}, I_CLASS2},
      {{Lipi::KEY_VARIANT_CP, II, IDX1}, II_CLASS1},
      {{Lipi::KEY_VARIANT_CP, RA, VIRAMA, I, IDX2}, I_REPH_CLASS2},
      {{Lipi::KEY_FORMAT_CP, Lipi::KEY_FORMAT_CP}, 0xE000 + Lipi::TABLE_FORMAT},
  };
}

const std::vector<uint8_t>& tableBytes() {
  static const std::vector<uint8_t> bytes = packTable(baseEntries());
  return bytes;
}

const std::vector<uint8_t>& contextTableBytes() {
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    for (const auto& e : contextEntries()) entries.push_back(e);
    return packTable(entries);
  }();
  return bytes;
}

Lipi::ClusterTable table() { return {tableBytes().data(), entryCount(tableBytes()), KIND}; }

Lipi::ClusterTable contextTable() { return {contextTableBytes().data(), entryCount(contextTableBytes()), KIND}; }

Lipi::ClusterTable emptyTable() { return {}; }

// The context table plus the flag a font sets when it draws final forms
// before a danda (Tiro Bangla).
const std::vector<uint8_t>& dandaFinalTableBytes() {
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    for (const auto& e : contextEntries()) entries.push_back(e);
    entries.push_back({{Lipi::KEY_FORMAT_CP, FINA}, 0});
    return packTable(entries);
  }();
  return bytes;
}
Lipi::ClusterTable dandaFinalTable() {
  return {dandaFinalTableBytes().data(), entryCount(dandaFinalTableBytes()), KIND};
}

const std::vector<uint8_t>& classTableBytes() {
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    for (const auto& e : classEntries()) entries.push_back(e);
    return packTable(entries);
  }();
  return bytes;
}
Lipi::ClusterTable classTable() { return {classTableBytes().data(), entryCount(classTableBytes()), KIND}; }

std::string encode(const std::vector<uint32_t>& cps) {
  std::string utf8;
  for (const uint32_t cp : cps) Lipi::utf8Append(cp, utf8);
  return utf8;
}

std::vector<uint32_t> decode(const std::string& utf8) {
  std::vector<uint32_t> cps;
  auto* p = reinterpret_cast<const unsigned char*>(utf8.c_str());
  while (*p) {
    const uint32_t cp = Lipi::utf8Next(&p);
    if (!cp) break;
    cps.push_back(cp);
  }
  return cps;
}

std::vector<uint32_t> shapeWith(const Lipi::ClusterTable& t, const std::vector<uint32_t>& logical) {
  const std::string in = encode(logical);
  std::string out;
  if (!Lipi::shape(in.c_str(), t, out)) return decode(in);
  return decode(out);
}

std::vector<uint32_t> shape(const std::vector<uint32_t>& logical) { return shapeWith(table(), logical); }
std::vector<uint32_t> shapeCtx(const std::vector<uint32_t>& logical) { return shapeWith(contextTable(), logical); }

using CP = std::vector<uint32_t>;

}  // namespace

/* ── Pre-checks and pass-through ────────────────────────────────────── */

TEST(LipiBengali, MayNeedShapingByteScan) {
  EXPECT_TRUE(Lipi::mayNeedShaping(encode({KA}).c_str()));
  EXPECT_TRUE(Lipi::mayNeedShaping(encode({0x09E6}).c_str()));  // digit zero, second byte 0xA7
  EXPECT_FALSE(Lipi::mayNeedShaping("plain ascii"));
  EXPECT_TRUE(Lipi::mayNeedShaping(encode({0x0915}).c_str()));   // Devanagari ka
  EXPECT_FALSE(Lipi::mayNeedShaping(encode({0x0A15}).c_str()));  // Gurmukhi ka: no descriptor yet
  EXPECT_FALSE(Lipi::mayNeedShaping(nullptr));
}

TEST(LipiBengali, EmptyInputIsRejected) {
  std::string out = "untouched";
  EXPECT_FALSE(Lipi::shape("", table(), out));
  EXPECT_EQ(out, "untouched");
}

TEST(LipiBengali, NonBengaliPassesThrough) {
  EXPECT_EQ(shape({'a', 'b', ' ', 0x00E9}), (CP{'a', 'b', ' ', 0x00E9}));
  // Latin and Bengali mixed: only the Bengali syllable is touched.
  EXPECT_EQ(shape({'A', ' ', KA, I, ' ', 'B'}), (CP{'A', ' ', I, KA, ' ', 'B'}));
}

TEST(LipiBengali, DigitsAndDandaPassThrough) {
  EXPECT_EQ(shape({0x09E7, 0x09E8, 0x0964}), (CP{0x09E7, 0x09E8, 0x0964}));
}

/* ── Vowel signs ────────────────────────────────────────────────────── */

TEST(LipiBengali, PreBaseVowelMovesBeforeConsonant) {
  EXPECT_EQ(shape({KA, I}), (CP{I, KA}));
  EXPECT_EQ(shape({KA, E}), (CP{E, KA}));
  EXPECT_EQ(shape({KA, 0x09C8}), (CP{0x09C8, KA}));
}

TEST(LipiBengali, TwoPartVowelsSplitAroundTheCluster) {
  EXPECT_EQ(shape({KA, O}), (CP{E, KA, AA}));
  EXPECT_EQ(shape({KA, AU}), (CP{E, KA, AU_LEN}));
  // Already-decomposed source text (e + aa) lands in the same visual order.
  EXPECT_EQ(shape({KA, E, AA}), (CP{E, KA, AA}));
}

TEST(LipiBengali, PostBaseVowelAndModifiersStayAfterTheCluster) {
  EXPECT_EQ(shape({KA, AA}), (CP{KA, AA}));
  EXPECT_EQ(shape({KA, AA, CANDRABINDU}), (CP{KA, CANDRABINDU, AA}));  // candrabindu sits on the consonant
  // বাংলা
  EXPECT_EQ(shape({BA, AA, ANUSVARA, LA, AA}), (CP{BA, AA, ANUSVARA, LA, AA}));
}

TEST(LipiBengali, PreBaseVowelPrecedesWholeConjunct) {
  // শিক্ষা: i-sign before sha, then the ksha composite, then aa.
  EXPECT_EQ(shape({SHA, I, KA, VIRAMA, SSA, AA}), (CP{I, SHA, KSSA, AA}));
}

TEST(LipiBengali, IndependentVowelTakesModifiers) { EXPECT_EQ(shape({0x0985, ANUSVARA}), (CP{0x0985, ANUSVARA})); }

TEST(LipiBengali, StrayVowelSignPassesThrough) { EXPECT_EQ(shape({I, KA}), (CP{I, KA})); }

/* ── Cluster table resolution ───────────────────────────────────────── */

TEST(LipiBengali, LookupMatchesExactLengthOnly) {
  const uint32_t ksha[] = {KA, VIRAMA, SSA};
  const uint32_t kshna[] = {KA, VIRAMA, SSA, VIRAMA, NNA};
  EXPECT_EQ(Lipi::lookupCluster(table(), BENGALI, ksha, 3), KSSA);
  EXPECT_EQ(Lipi::lookupCluster(table(), BENGALI, kshna, 5), 0u);
  EXPECT_EQ(Lipi::lookupCluster(table(), BENGALI, ksha, 1), 0u);
  EXPECT_EQ(Lipi::lookupCluster(emptyTable(), BENGALI, ksha, 3), 0u);
  // A table of another kind is not consulted for this script.
  Lipi::ClusterTable other = table();
  other.kind = 2;
  EXPECT_EQ(Lipi::lookupCluster(other, BENGALI, ksha, 3), 0u);
}

TEST(LipiBengali, ConjunctPairFromTable) { EXPECT_EQ(shape({KA, VIRAMA, SSA}), (CP{KSSA})); }

TEST(LipiBengali, TripleFromTableWinsOverGreedyPieces) { EXPECT_EQ(shape({NA, VIRAMA, TA, VIRAMA, RA}), (CP{NTRA})); }

TEST(LipiBengali, UnknownTripleDecomposesIntoPairPlusSubjoinedForm) {
  // স্ত্র: no triple entry, so স্ত composite + ra-phala mark.
  EXPECT_EQ(shape({SA, VIRAMA, TA, VIRAMA, RA}), (CP{STA, RAPHALA}));
  // ন্ত্য: pair + ya-phala spacing form.
  EXPECT_EQ(shape({NA, VIRAMA, TA, VIRAMA, YA}), (CP{NTA, YAPHALA}));
}

TEST(LipiBengali, UnknownPairKeepsVisibleHasanta) { EXPECT_EQ(shape({KA, VIRAMA, KHA}), (CP{KA, VIRAMA, KHA})); }

TEST(LipiBengali, TrailingHasantaIsAMarkNotAKey) {
  // Word-final virama stays after its consonant, including after ra where the
  // (ra, virama) key would otherwise resolve to the reph mark.
  EXPECT_EQ(shape({KA, VIRAMA}), (CP{KA, VIRAMA}));
  EXPECT_EQ(shape({RA, VIRAMA}), (CP{RA, VIRAMA}));
}

TEST(LipiBengali, ClusterOfFourConsonantsWalksGreedily) {
  // ন্ত্র্য: triple composite, then the ya-phala form.
  EXPECT_EQ(shape({NA, VIRAMA, TA, VIRAMA, RA, VIRAMA, YA}), (CP{NTRA, YAPHALA}));
}

/* ── Reph ───────────────────────────────────────────────────────────── */

TEST(LipiBengali, RephCompositeFromTable) { EXPECT_EQ(shape({RA, VIRAMA, KA}), (CP{RKA})); }

TEST(LipiBengali, RephMarkFollowsTheRestOfTheCluster) {
  // র্ক্ষ: no composite, so ksha then the reph mark over it.
  EXPECT_EQ(shape({RA, VIRAMA, KA, VIRAMA, SSA}), (CP{KSSA, REPH}));
  // র্কি: i-sign first, then the reph composite.
  EXPECT_EQ(shape({RA, VIRAMA, KA, I}), (CP{I, RKA}));
  // র্খা: no composite for kha; reph mark sits before the post-base aa.
  EXPECT_EQ(shape({RA, VIRAMA, KHA, AA}), (CP{KHA, REPH, AA}));
}

TEST(LipiBengali, RephWithoutGlyphKeepsLogicalOrder) {
  EXPECT_EQ(shapeWith(emptyTable(), {RA, VIRAMA, KA}), (CP{RA, VIRAMA, KA}));
}

/* ── Joiners, nukta, below-base vowels ──────────────────────────────── */

TEST(LipiBengali, ZwjAfterViramaSelectsTheJoinerForm) {
  EXPECT_EQ(shape({RA, VIRAMA, ZWJ, YA}), (CP{RZWJYA}));
  // Without a table entry the joiner is dropped and the letters stay visible.
  EXPECT_EQ(shapeWith(emptyTable(), {RA, VIRAMA, ZWJ, YA}), (CP{RA, VIRAMA, YA}));
}

TEST(LipiBengali, ZwjBeforeViramaKeepsRaWholeWithItsPhala) {
  // র‍্য (Unicode order for ra + ya-phala): no reph, the ya-phala follows the ra.
  EXPECT_EQ(shape({RA, ZWJ, VIRAMA, YA, AA}), (CP{RA, YAPHALA, AA}));
  // র‍্ক: no reph composite; no form for virama + ka, so the virama stays visible.
  EXPECT_EQ(shape({RA, ZWJ, VIRAMA, KA}), (CP{RA, VIRAMA, KA}));
  EXPECT_EQ(shapeWith(emptyTable(), {RA, ZWJ, VIRAMA, YA}), (CP{RA, VIRAMA, YA}));
}

TEST(LipiBengali, ZwnjAfterViramaBlocksTheConjunct) {
  EXPECT_EQ(shape({KA, VIRAMA, ZWNJ, SSA}), (CP{KA, VIRAMA, SSA}));
}

TEST(LipiBengali, LooseJoinersAreDropped) { EXPECT_EQ(shape({KA, ZWNJ, KA, ZWJ}), (CP{KA, KA})); }

TEST(LipiBengali, NuktaFoldsIntoPrecomposedLetter) {
  EXPECT_EQ(shape({DDA, NUKTA}), (CP{0x09DC}));
  EXPECT_EQ(shape({YA, NUKTA, AA}), (CP{0x09DF, AA}));
  // A nukta on a letter with no precomposed form stays as a mark.
  EXPECT_EQ(shape({KA, NUKTA}), (CP{KA, NUKTA}));
}

TEST(LipiBengali, BelowVowelLigatesWhenTheFontHasOne) {
  EXPECT_EQ(shape({RA, U}), (CP{RU}));
  EXPECT_EQ(shape({KA, U}), (CP{KA, U}));
  // The ligature key also applies with a pre-base sign present elsewhere.
  EXPECT_EQ(shape({HA, U, KA, I}), (CP{HA, U, I, KA}));
}

TEST(LipiBengali, BelowVowelStaysAfterClusterAndBeforeRephMark) {
  EXPECT_EQ(shape({KA, VIRAMA, SSA, U}), (CP{KSSA, U}));
  // OpenType order: the below sign attaches first, the reph goes over both.
  EXPECT_EQ(shape({RA, VIRAMA, KHA, U}), (CP{KHA, U, REPH}));
  // A below-vowel ligature still applies under a reph (র্রু).
  EXPECT_EQ(shape({RA, VIRAMA, RA, U}), (CP{RU, REPH}));
}

/* ── Desktop parity: Assamese ra, mark order, contextual forms ──────── */

TEST(LipiBengali, AssameseRaShapesLikeRaInsideConjuncts) {
  // ত্ৰি with U+09F0: same lookups as ত্রি (ra-phala under ta), sign first.
  EXPECT_EQ(shape({TA, VIRAMA, ASSAMESE_RA, I}), (CP{I, TA, RAPHALA}));
  EXPECT_EQ(shape({ASSAMESE_RA, VIRAMA, KA}), (CP{RKA}));
  // Standing alone it keeps its own glyph.
  EXPECT_EQ(shape({ASSAMESE_RA, AA, KA}), (CP{ASSAMESE_RA, AA, KA}));
}

TEST(LipiBengali, CandrabinduAttachesToTheConsonantBeforeThePostBaseSign) {
  EXPECT_EQ(shape({TA, AA, CANDRABINDU, RA}), (CP{TA, CANDRABINDU, AA, RA}));
  EXPECT_EQ(shape({KA, U, CANDRABINDU}), (CP{KA, U, CANDRABINDU}));
  EXPECT_EQ(shape({KA, AA, ANUSVARA, KA}), (CP{KA, AA, ANUSVARA, KA}));
}

TEST(LipiBengali, PreBaseSignTakesTheFormForItsCluster) {
  EXPECT_EQ(shape({TTA, I}), (CP{TTI}));                         // fused ligature
  EXPECT_EQ(shape({NNA, VIRAMA, DDA, I}), (CP{I_WIDE, NNDDA}));  // wide sign, cluster as usual
  EXPECT_EQ(shape({KA, I}), (CP{I, KA}));                        // no form: plain sign
  EXPECT_EQ(shape({TTA, I, AA}), (CP{TTI, AA}));
}

TEST(LipiBengali, PreBaseSignFusesWithTheReph) {
  EXPECT_EQ(shape({RA, VIRAMA, TA, I}), (CP{I_REPH_TA, TA}));  // exact form for this base
  EXPECT_EQ(shape({RA, VIRAMA, KHA, I}), (CP{I_REPH, KHA}));   // generic fused form
  EXPECT_EQ(shape({RA, VIRAMA, KA, I}), (CP{I, RKA}));         // whole-cluster composite wins
  // No reph glyph at all: logical order, plain sign.
  EXPECT_EQ(shapeWith(emptyTable(), {RA, VIRAMA, TA, I}), (CP{I, RA, VIRAMA, TA}));
}

TEST(LipiBengali, WordInitialEFormAppliesOnlyAtTheStart) {
  EXPECT_EQ(shapeCtx({KA, E}), (CP{E_INIT, KA}));
  EXPECT_EQ(shapeCtx({KA, KA, E}), (CP{KA, E, KA}));
  EXPECT_EQ(shapeCtx({0x20, KA, E}), (CP{0x20, E_INIT, KA}));
  EXPECT_EQ(shapeCtx({KA, E, KA, E}), (CP{E_INIT, KA, E, KA}));
}

// The builder writes {INIT, base.., sign} when a base has its own word-initial
// form (Noto Sans Bengali খে: ে.long.init; Tiro Bangla খ্রে: one composite);
// it beats the generic initial form, applies at the start of a word only, and
// a composite stands for the cluster too.
TEST(LipiBengali, WordInitialFormOfTheBaseBeatsTheGenericOne) {
  constexpr uint32_t E_INIT_KHA = 0xF404, KSSE_INIT = 0xE024;
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    for (const auto& e : contextEntries()) entries.push_back(e);
    entries.push_back({{INIT, KHA, E}, E_INIT_KHA});
    entries.push_back({{INIT, KA, VIRAMA, SSA, E}, KSSE_INIT});
    return packTable(entries);
  }();
  const Lipi::ClusterTable t{bytes.data(), entryCount(bytes), KIND};
  EXPECT_EQ(shapeWith(t, {KHA, E}), (CP{E_INIT_KHA, KHA}));        // the base's own form
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, SSA, E}), (CP{KSSE_INIT}));  // a composite replaces the cluster
  EXPECT_EQ(shapeWith(t, {KA, E}), (CP{E_INIT, KA}));              // no per-base form: the generic one
  EXPECT_EQ(shapeWith(t, {KA, KHA, E}), (CP{KA, E, KHA}));         // not word-initial
  EXPECT_EQ(shapeWith(t, {0x20, KA, VIRAMA, SSA, E}), (CP{0x20, KSSE_INIT}));
}

TEST(LipiBengali, DandaEndsTheWordWhenTheFontSaysSo) {
  const auto t = dandaFinalTable();
  EXPECT_EQ(shapeWith(t, {KA, AA, DANDA}), (CP{KA, AA_FINA, DANDA}));
  EXPECT_EQ(shapeWith(t, {KA, AA, 0x0965}), (CP{KA, AA_FINA, 0x0965}));
  EXPECT_EQ(shapeWith(t, {NA, VIRAMA, YA, DANDA}), (CP{NA, YAPHALA_FINA, DANDA}));
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, YA, CANDRABINDU, DANDA}), (CP{KA, YAPHALA_CB_FINA, DANDA}));
  // Inside a word nothing changes; without the flag the danda is script text.
  EXPECT_EQ(shapeWith(t, {KA, AA, KA}), (CP{KA, AA, KA}));
  EXPECT_EQ(shapeCtx({NA, VIRAMA, YA, DANDA}), (CP{NA, YAPHALA, DANDA}));
}

TEST(LipiBengali, WordFinalAaFormAppliesOnlyAtTheEnd) {
  EXPECT_EQ(shapeCtx({KA, AA}), (CP{KA, AA_FINA}));
  EXPECT_EQ(shapeCtx({KA, AA, KA}), (CP{KA, AA, KA}));
  EXPECT_EQ(shapeCtx({KA, AA, ','}), (CP{KA, AA_FINA, ','}));
  EXPECT_EQ(shapeCtx({KA, AA, DANDA}), (CP{KA, AA, DANDA}));  // without the font's flag the danda is script text
  EXPECT_EQ(shapeCtx({KA, O}), (CP{E_INIT, KA, AA_FINA}));    // two-part sign: both halves
  EXPECT_EQ(shapeCtx({KA, AA, CANDRABINDU}), (CP{KA, CANDRABINDU, AA_FINA}));
  // Anusvara and visarga follow the sign, so it is not final unless the font
  // has a sign + modifier + FINA form (FinalFormBeforeATrailingModifier).
  EXPECT_EQ(shapeCtx({NA, AA, 0x0983}), (CP{NA, AA, 0x0983}));
  EXPECT_EQ(shape({KA, AA, ANUSVARA}), (CP{KA, AA, ANUSVARA}));
}

TEST(LipiBengali, AuLengthMarkFinalFormBeforeCandrabindu) {
  EXPECT_EQ(shapeCtx({KA, AU}), (CP{E_INIT, KA, AU_LEN_FINA}));
  EXPECT_EQ(shapeCtx({KA, AU, KA}), (CP{E_INIT, KA, AU_LEN, KA}));
  // Fonts differ on ৗ before a candrabindu: the pair is a table form (Noto:
  // ৗ.fina + ঁ), consumed with the modifier; with none the sign stays plain.
  EXPECT_EQ(shapeCtx({KA, AU, CANDRABINDU, KA}), (CP{E_INIT, KA, AU_LEN_CB, KA}));
  EXPECT_EQ(shape({KA, AU, CANDRABINDU, KA}), (CP{E, KA, AU_LEN, CANDRABINDU, KA}));
}

TEST(LipiBengali, FinalFormBeforeATrailingModifier) {
  // Tiro applies া.fina when only ং/ঃ follows (বাং, ডাঃ): the sign + modifier +
  // FINA form; mid-word and without the form the sign stays plain.
  EXPECT_EQ(shapeCtx({KA, AA, ANUSVARA}), (CP{KA, AA_ANUSVARA_FINA}));
  EXPECT_EQ(shapeCtx({KA, AA, ANUSVARA, KA}), (CP{KA, AA, ANUSVARA, KA}));
  EXPECT_EQ(shapeCtx({NA, AA, 0x0983}), (CP{NA, AA, 0x0983}));
  EXPECT_EQ(shape({KA, AA, ANUSVARA}), (CP{KA, AA, ANUSVARA}));
}

TEST(LipiBengali, YaPhalaCarriesTheCandrabinduWhenTheFontDrawsItAfter) {
  // Default order: ঁ before the ya-phala (Noto); Tiro's table pairs them.
  EXPECT_EQ(shape({KA, VIRAMA, YA, AA, CANDRABINDU}), (CP{KA, CANDRABINDU, YAPHALA, AA}));
  EXPECT_EQ(shapeCtx({KA, VIRAMA, YA, AA, CANDRABINDU, KA}), (CP{KA, YAPHALA_CB, AA, KA}));
}

TEST(LipiBengali, WordFinalYaPhalaWithModifierTakesTheFinalPair) {
  // ব্যঁ at the end of a word: the final pair; inside a word or with a vowel
  // sign after the ya-phala, the ordinary pair.
  EXPECT_EQ(shapeCtx({KA, VIRAMA, YA, CANDRABINDU}), (CP{KA, YAPHALA_CB_FINA}));
  EXPECT_EQ(shapeCtx({KA, VIRAMA, YA, CANDRABINDU, KA}), (CP{KA, YAPHALA_CB, KA}));
  EXPECT_EQ(shapeCtx({KA, VIRAMA, YA, AA, CANDRABINDU}), (CP{KA, YAPHALA_CB, AA_FINA}));
  // No final pair for the anusvara in this table: the ordinary order stays.
  EXPECT_EQ(shapeCtx({KA, VIRAMA, YA, ANUSVARA}), (CP{KA, YAPHALA, ANUSVARA}));
}

TEST(LipiBengali, FinalYaPhalaAfterABelowVowel) {
  // মৃত্যু: the vowel stays on ত and the ya-phala takes its final form, as one
  // cluster + vowel + FINA composite; mid-word the vowel form is used.
  EXPECT_EQ(shapeCtx({TA, VIRAMA, YA, U}), (CP{TYU_FINA}));
  // Mid-word, with no ত্য cluster form, the ya-phala is split off as usual.
  EXPECT_EQ(shapeCtx({TA, VIRAMA, YA, U, KA}), (CP{TA, U, YAPHALA, KA}));
}

TEST(LipiBengali, DigitsDoNotContinueAWord) {
  // ২৩শে: the sign after the digits takes its word-initial form.
  EXPECT_EQ(shapeCtx({0x09E8, 0x09E9, KA, E}), (CP{0x09E8, 0x09E9, E_INIT, KA}));
}

TEST(LipiBengali, ModifierVariantAfterThePreBaseSign) {
  // Noto draws ঁ.alt after a wide ি: keyed modifier + sign, drawn in the
  // candrabindu's place; a spacing modifier is unaffected.
  EXPECT_EQ(shapeCtx({KA, I, CANDRABINDU}), (CP{I, KA, CB_AFTER_I}));
  EXPECT_EQ(shapeCtx({KA, I, ANUSVARA}), (CP{I, KA, ANUSVARA}));
  EXPECT_EQ(shapeCtx({KA, AA, CANDRABINDU}), (CP{KA, CANDRABINDU, AA_FINA}));
}

TEST(LipiBengali, YaPhalaFollowsBelowSignsAndCandrabindu) {
  // No ত্য composite in the table: ta, the below sign, then the ya-phala.
  EXPECT_EQ(shape({TA, VIRAMA, YA, U}), (CP{TA, U, YAPHALA}));
  EXPECT_EQ(shape({HA, VIRAMA, YA, AA, CANDRABINDU}), (CP{HA, CANDRABINDU, YAPHALA, AA}));
  EXPECT_EQ(shape({RA, VIRAMA, TA, VIRAMA, YA, U}), (CP{TA, U, REPH, YAPHALA}));
  EXPECT_EQ(shape({TA, VIRAMA, YA}), (CP{TA, YAPHALA}));
}

TEST(LipiBengali, IndependentVowelTakesAYaPhala) {
  EXPECT_EQ(shape({0x0985, VIRAMA, YA, AA, KA}), (CP{0x0985, YAPHALA, AA, KA}));
}

TEST(LipiBengali, CandrabinduStaysAfterTheAuLengthMark) {
  EXPECT_EQ(shape({KA, AU, CANDRABINDU, KA}), (CP{E, KA, AU_LEN, CANDRABINDU, KA}));
}

TEST(LipiBengali, WordFinalYaPhalaForms) {
  EXPECT_EQ(shapeCtx({NA, VIRAMA, YA}), (CP{NA, YAPHALA_FINA}));
  EXPECT_EQ(shapeCtx({NA, VIRAMA, YA, KA}), (CP{NA, YAPHALA, KA}));
  EXPECT_EQ(shapeCtx({NA, VIRAMA, YA, AA}), (CP{NA, YAPHALA, AA_FINA}));
  EXPECT_EQ(shapeCtx({HA, VIRAMA, YA}), (CP{HYA_FINA}));
  EXPECT_EQ(shapeCtx({HA, VIRAMA, YA, CANDRABINDU}), (CP{0xE00D, CANDRABINDU}));
}

TEST(LipiBengali, PostBaseIiFormsForClusterAndReph) {
  EXPECT_EQ(shape({SSA, VIRAMA, TTHA, II}), (CP{SSTTHA, II_LONG}));
  EXPECT_EQ(shape({RA, VIRAMA, TA, II, KA}), (CP{TA, II_REPH, KA}));
  EXPECT_EQ(shape({RA, VIRAMA, TA, II}), (CP{TA, II_REPH_FINA}));
  EXPECT_EQ(shape({KA, II, KA}), (CP{KA, II, KA}));
}

/* ── Sign classes ───────────────────────────────────────────────────── */

TEST(LipiBengali, SignVariantsFollowTheGlyphClasses) {
  const auto t = classTable();
  // A ligature with classes: ি from its pre class, ী from its post class.
  EXPECT_EQ(shapeWith(t, {KHA, VIRAMA, SSA, I}), (CP{I_CLASS2, KSSA_CLASSED}));
  EXPECT_EQ(shapeWith(t, {KHA, VIRAMA, SSA, II}), (CP{KSSA_CLASSED, II_CLASS1}));
  // A bare consonant takes its classes from the {KEY_CLASS_CP, c} entry.
  EXPECT_EQ(shapeWith(t, {TTHA, I}), (CP{I_CLASS1, TTHA}));
  EXPECT_EQ(shapeWith(t, {TTHA, II}), (CP{TTHA, II_CLASS1}));
  // ী follows the last glyph of a sequence; ি stays plain in front of a
  // sequence whose first glyph is not a half form.
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, TTHA, II}), (CP{KA, VIRAMA, TTHA, II_CLASS1}));
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, TTHA, I}), (CP{I, KA, VIRAMA, TTHA}));
  // No class, or no variant for the class: the plain sign as before.
  EXPECT_EQ(shapeWith(t, {KA, I}), (CP{I, KA}));
  EXPECT_EQ(shapeWith(t, {KHA, VIRAMA, SSA, II, KA}), (CP{KSSA_CLASSED, II_CLASS1, KA}));
  // A per-base form still wins over the class (টি composite).
  EXPECT_EQ(shapeWith(t, {TTA, I}), (CP{TTI}));
  // With a reph the class variant fused with the reph replaces the generic one.
  EXPECT_EQ(shapeWith(t, {RA, VIRAMA, KHA, VIRAMA, SSA, I}), (CP{I_REPH_CLASS2, KSSA_CLASSED}));
  EXPECT_EQ(shapeWith(t, {RA, VIRAMA, TTHA, I}), (CP{I_REPH, TTHA}));  // class 1 has no reph variant
  EXPECT_EQ(Lipi::tableFormat(t), Lipi::TABLE_FORMAT);
  EXPECT_EQ(Lipi::tableFormat(table()), 0);
}

/* ── Mark classification shared with the renderer ───────────────────── */

TEST(LipiBengali, PuaMarkRangesAreCombiningMarks) {
  EXPECT_TRUE(Lipi::isMark(RAPHALA));
  EXPECT_TRUE(Lipi::isMark(REPH));
  EXPECT_TRUE(Lipi::isMark(U));
  EXPECT_TRUE(Lipi::isMark(VIRAMA));
  EXPECT_TRUE(Lipi::isMark(CANDRABINDU));
  EXPECT_FALSE(Lipi::isMark(KSSA));
  EXPECT_FALSE(Lipi::isMark(YAPHALA));
  EXPECT_FALSE(Lipi::isMark(AA));
  EXPECT_FALSE(Lipi::isMark(ANUSVARA));
}

/* ── A font that joins with half forms (Hind Siliguri) ──────────────── */

namespace {

constexpr uint32_t K_HALF = 0xE020, KH_HALF = 0xE021, S_HALF = 0xE022, KKA = 0xE023;

// The base table plus half forms, with or without the flag a font sets when
// it joins conjuncts with half forms although Bengali subjoins.
const std::vector<uint8_t>& halfFormTableBytes(const bool flagged) {
  static const std::vector<uint8_t> flaggedBytes = [] {
    auto entries = baseEntries();
    entries.push_back({{KA, VIRAMA, ZWJ}, K_HALF});
    entries.push_back({{KHA, VIRAMA, ZWJ}, KH_HALF});
    entries.push_back({{SA, VIRAMA, ZWJ}, S_HALF});
    entries.push_back({{KA, VIRAMA, KA}, KKA});
    entries.push_back({{Lipi::KEY_FORMAT_CP, ZWJ}, 0});
    return packTable(entries);
  }();
  static const std::vector<uint8_t> plainBytes = [] {
    auto entries = baseEntries();
    entries.push_back({{KA, VIRAMA, ZWJ}, K_HALF});
    entries.push_back({{KHA, VIRAMA, ZWJ}, KH_HALF});
    entries.push_back({{SA, VIRAMA, ZWJ}, S_HALF});
    entries.push_back({{KA, VIRAMA, KA}, KKA});
    return packTable(entries);
  }();
  return flagged ? flaggedBytes : plainBytes;
}
Lipi::ClusterTable halfFormTable(const bool flagged) {
  return {halfFormTableBytes(flagged).data(), entryCount(halfFormTableBytes(flagged)), KIND};
}

}  // namespace

TEST(LipiBengali, TableFlagSwitchesConjunctsToHalfForms) {
  const auto t = halfFormTable(true);
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, KHA}), (CP{K_HALF, KHA}));
  EXPECT_EQ(shapeWith(t, {KHA, VIRAMA, SA, VIRAMA, TA}), (CP{KH_HALF, STA}));
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, KHA, I}), (CP{I, K_HALF, KHA}));
  // Ligatures and subjoined marks of the base table still win.
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, SSA}), (CP{KSSA}));
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, KA}), (CP{KKA}));
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, RA}), (CP{KA, RAPHALA}));
  EXPECT_EQ(shapeWith(t, {RA, VIRAMA, KA, VIRAMA, KHA}), (CP{K_HALF, KHA, REPH}));
  // A consonant without a half form keeps its visible virama.
  EXPECT_EQ(shapeWith(t, {TTA, VIRAMA, KHA}), (CP{TTA, VIRAMA, KHA}));
}

/* ── A second pre-base sign with class variants (Noto Sans Bengali ে) ── */

namespace {

constexpr uint32_t E_CLASS1 = 0xF430;       // ে.long on the glyphs of class 1 (not I_CLASS1's value: a ি/ে
constexpr uint32_t E_INIT_CLASS1 = 0xF431;  // mix-up must show); ে.long.init: the same class at the start of a word

// The class table plus the word-initial ে and its class variants; ি keeps
// its own lists, the classes are shared.
const std::vector<uint8_t>& eClassTableBytes() {
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    for (const auto& e : contextEntries()) entries.push_back(e);
    for (const auto& e : classEntries()) entries.push_back(e);
    entries.push_back({{Lipi::KEY_VARIANT_CP, E, IDX1}, E_CLASS1});
    entries.push_back({{Lipi::KEY_VARIANT_CP, INIT, E, IDX1}, E_INIT_CLASS1});
    return packTable(entries);
  }();
  return bytes;
}
Lipi::ClusterTable eClassTable() { return {eClassTableBytes().data(), entryCount(eClassTableBytes()), KIND}; }

}  // namespace

TEST(LipiBengali, SecondPreSignFollowsTheSharedClasses) {
  const auto t = eClassTable();
  // Inside a word: ে takes the class variant of the glyph it attaches to; a
  // glyph whose class has no ে variant, or with no class, keeps the plain sign.
  EXPECT_EQ(shapeWith(t, {KA, TTHA, E}), (CP{KA, E_CLASS1, TTHA}));
  EXPECT_EQ(shapeWith(t, {KA, KHA, VIRAMA, SSA, E}), (CP{KA, E, KSSA_CLASSED}));
  EXPECT_EQ(shapeWith(t, {KA, KA, E}), (CP{KA, E, KA}));
  // At the start of a word: the class's initial variant, else the generic one.
  EXPECT_EQ(shapeWith(t, {TTHA, E}), (CP{E_INIT_CLASS1, TTHA}));
  EXPECT_EQ(shapeWith(t, {KA, E}), (CP{E_INIT, KA}));
  EXPECT_EQ(shapeWith(t, {KHA, VIRAMA, SSA, E}), (CP{E_INIT, KSSA_CLASSED}));
  // ি is untouched by the ে lists.
  EXPECT_EQ(shapeWith(t, {TTHA, I}), (CP{I_CLASS1, TTHA}));
  EXPECT_EQ(shapeWith(t, {KA, TTHA, I}), (CP{KA, I_CLASS1, TTHA}));
  // The two-part sign ো splits into ে + া; the ে half follows the class too
  // (and the া half takes its word-final form from the context table).
  EXPECT_EQ(shapeWith(t, {KA, TTHA, O}), (CP{KA, E_CLASS1, TTHA, AA_FINA}));
}

TEST(LipiBengali, HalfFormKeysAreInertWithoutTheFlag) {
  const auto t = halfFormTable(false);
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, KHA}), (CP{KA, VIRAMA, KHA}));
  EXPECT_EQ(shapeWith(t, {KHA, VIRAMA, SA, VIRAMA, TA}), (CP{KHA, VIRAMA, STA}));
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, KA}), (CP{KKA}));
}

/* ── Danda space share (Tiro: the danda's built-in space goes after a space) ── */

TEST(LipiBengali, DandaSpaceShareComesFromTheTable) {
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    entries.push_back({{Lipi::KEY_FORMAT_CP, INIT, Lipi::KEY_CLASS_INDEX_CP + 1}, 0xE000 + 129});
    entries.push_back({{Lipi::KEY_FORMAT_CP, INIT, Lipi::KEY_CLASS_INDEX_CP + 2}, 0xE000 + 95});
    return packTable(entries);
  }();
  const Lipi::ClusterTable t{bytes.data(), entryCount(bytes), KIND};
  EXPECT_EQ(Lipi::dandaSpaceShare(t, 0x0964), 129);
  EXPECT_EQ(Lipi::dandaSpaceShare(t, 0x0965), 95);
  EXPECT_EQ(Lipi::dandaSpaceShare(t, KA), 0);
  EXPECT_EQ(Lipi::dandaSpaceShare(t, 0x0020), 0);
  // Fonts without the entries (Noto) keep the space as it is.
  EXPECT_EQ(Lipi::dandaSpaceShare(table(), 0x0964), 0);
  // The entries change nothing in shaping.
  EXPECT_EQ(shapeWith(t, {KA, 0x0964}), shapeWith(table(), {KA, 0x0964}));
}

/* ── Bengali pass 2026-09-25 ──────────────────────────────────────────── */

constexpr uint32_t YA_AA_CANDRABINDU = 0xE040;  // ্যাঁ as the font orders it (Noto Sans: ya-phala, ঁ, া)
constexpr uint32_t RTTHA = 0xE041;              // র্ঠ, reph composite carrying ঠ's class
constexpr uint32_t E_LONG_RT = 0xF420;          // ে sized for class 1

TEST(LipiBengali, YaPhalaWithSignAndModifierIsOneFormWhenTheFontOrdersThem) {
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    entries.push_back({{VIRAMA, YA, AA, CANDRABINDU}, YA_AA_CANDRABINDU});
    return packTable(entries);
  }();
  const Lipi::ClusterTable t{bytes.data(), entryCount(bytes), KIND};
  // ক্যাঁ: the form replaces the ya-phala, the sign and the modifier.
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, YA, AA, CANDRABINDU}), (CP{KA, YA_AA_CANDRABINDU}));
  // ক্যঁ without a sign keeps the default order.
  EXPECT_EQ(shapeWith(t, {KA, VIRAMA, YA, CANDRABINDU}), shapeWith(table(), {KA, VIRAMA, YA, CANDRABINDU}));
}

TEST(LipiBengali, LigatureStaysBeforeTheWordFinalVirama) {
  // Hind অস্ত্: স্ত + a visible virama, not স্ + ত্.
  const auto t = halfFormTable(true);
  EXPECT_EQ(shapeWith(t, {SA, VIRAMA, TA, VIRAMA}), (CP{STA, VIRAMA}));
}

TEST(LipiBengali, ClassVariantUnderARephComposite) {
  // Noto Sans অর্থে: the reph composite carries the class of the letter under
  // the reph, and ে takes that class's variant.
  static const std::vector<uint8_t> bytes = [] {
    auto entries = baseEntries();
    for (const auto& e : classEntries()) entries.push_back(e);
    entries.push_back({{RA, VIRAMA, TTHA}, RTTHA, 1, 0});
    entries.push_back({{Lipi::KEY_VARIANT_CP, E, IDX1}, E_LONG_RT});
    return packTable(entries);
  }();
  const Lipi::ClusterTable t{bytes.data(), entryCount(bytes), KIND};
  // Inside a word (a word-initial ে takes its own form).
  EXPECT_EQ(shapeWith(t, {KA, RA, VIRAMA, TTHA, E}), (CP{KA, E_LONG_RT, RTTHA}));
  EXPECT_EQ(shapeWith(t, {KA, TTHA, E}), (CP{KA, E_LONG_RT, TTHA}));
}

TEST(LipiBengali, ShapedTextIsNotShapedAgain) {
  // ো splits into a pre form and া; shaping that output a second time moved the
  // pre form again (জোরে came back as two pre forms and no ে). A stream that
  // already holds a Private Use form of the engine is returned unchanged.
  const std::vector<uint32_t> once = shapeCtx({KA, TTHA, O});
  ASSERT_EQ(once.back(), AA_FINA);  // the word-final া form: a Private Use glyph in the stream
  std::string twice;
  EXPECT_FALSE(Lipi::shape(encode(once).c_str(), contextTable(), twice));
  EXPECT_TRUE(twice.empty());
}

TEST(LipiBengali, FusedFormsBeatClassVariants) {
  // The class variant of a sign fused with the reph (ি+reph for class 2)
  // replaces the generic fused form, never a per-base one: র্তি keeps its own
  // composite although ত is of class 2, র্খি takes the variant, and without
  // a reph variant the plain class variant does not replace the generic
  // fused form (a plain sign variant never stands in for reph + sign).
  static const std::vector<uint8_t> withReph = [] {
    auto entries = baseEntries();
    for (const auto& e : classEntries()) entries.push_back(e);
    entries.push_back({{Lipi::KEY_CLASS_CP, TA}, 0, 2, 0});
    entries.push_back({{Lipi::KEY_CLASS_CP, KHA}, 0, 2, 0});
    return packTable(entries);
  }();
  const Lipi::ClusterTable t{withReph.data(), entryCount(withReph), KIND};
  EXPECT_EQ(shapeWith(t, {RA, VIRAMA, TA, I}), (CP{I_REPH_TA, TA}));
  EXPECT_EQ(shapeWith(t, {RA, VIRAMA, KHA, I}), (CP{I_REPH_CLASS2, KHA}));
  static const std::vector<uint8_t> plainOnly = [] {
    auto entries = baseEntries();
    for (const auto& e : classEntries()) {
      if (e.key.size() == 5 && e.key[1] == RA) continue;  // no reph-fused variant list
      entries.push_back(e);
    }
    entries.push_back({{Lipi::KEY_CLASS_CP, KHA}, 0, 2, 0});
    return packTable(entries);
  }();
  const Lipi::ClusterTable p{plainOnly.data(), entryCount(plainOnly), KIND};
  EXPECT_EQ(shapeWith(p, {RA, VIRAMA, KHA, I}), (CP{I_REPH, KHA}));
  EXPECT_EQ(shapeWith(p, {KHA, I}), (CP{I_CLASS2, KHA}));
}
