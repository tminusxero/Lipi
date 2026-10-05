// DevanagariShaperTest — half forms, deferred reph and fused marks for
// Devanagari text through the Lipi engine (kind-2 table).
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

constexpr uint32_t KA = 0x0915, GA = 0x0917, NGA = 0x0919, TTA = 0x091F, TTHA = 0x0920, DDA = 0x0921, TA = 0x0924,
                   DA = 0x0926, NA = 0x0928, MA = 0x092E, YA = 0x092F, RA = 0x0930, SSA = 0x0937, SA = 0x0938,
                   HA = 0x0939, DDDHA = 0x095C, DANDA = 0x0964;
constexpr uint32_t VIRAMA = 0x094D, NUKTA = 0x093C, ZWJ = 0x200D, ZWNJ = 0x200C;
constexpr uint32_t AA = 0x093E, I = 0x093F, II = 0x0940, U = 0x0941, E = 0x0947, O = 0x094B;
constexpr uint32_t CANDRABINDU = 0x0901, ANUSVARA = 0x0902, VISARGA = 0x0903;
constexpr uint8_t KIND = Lipi::SHAPE_KIND_DEVANAGARI;
constexpr size_t ENTRY = Lipi::entrySizeForKind(KIND);
constexpr size_t KEYLEN = Lipi::maxKeyLenForKind(KIND);
const Lipi::ScriptDesc& DEVA = Lipi::kDevanagari;

// Synthetic PUA outputs.
constexpr uint32_t K_HALF = 0xE000;     // क्
constexpr uint32_t S_HALF = 0xE001;     // स्
constexpr uint32_t G_HALF = 0xE002;     // ग्
constexpr uint32_t M_HALF = 0xE003;     // म्
constexpr uint32_t KSSA = 0xE004;       // क्ष
constexpr uint32_t KSSA_HALF = 0xE005;  // क्ष्
constexpr uint32_t TRA = 0xE006;        // त्र
constexpr uint32_t KRA = 0xE007;        // क्र (ka + rakar composite)
constexpr uint32_t EYELASH = 0xE008;    // र्‍ (half ra)
constexpr uint32_t RA_ZWJ_YA = 0xE0F0;  // र‍्य (a font's own form: ra + ZWJ before virama + ya)
constexpr uint32_t RU = 0xE009;         // रु ligature
constexpr uint32_t TTTTHA = 0xE00A;     // ट्ठ ligature (no half form)
constexpr uint32_t TT_HALF = 0xE00B;    // ट्
constexpr uint32_t N_HALF = 0xE00D;     // न्
constexpr uint32_t DU = 0xE00E;         // दु ligature
constexpr uint32_t SSU = 0xE00F;        // षु composite
constexpr uint32_t SHRA = 0xE010;       // श्र ligature
constexpr uint32_t SHA = 0x0936, VA = 0x0935;
constexpr uint32_t DVA = 0xE011;               // द्व ligature (no half form, does not continue)
constexpr uint32_t VYA = 0xE012;               // व्य ligature
constexpr uint32_t V_HALF = 0xE013;            // व्
constexpr uint32_t SSTTA = 0xE014;             // ष्ट ligature, flagged as continuing
constexpr uint32_t SS_HALF = 0xE015;           // ष्
constexpr uint32_t K_VIRAMA = 0xE016;          // क् with its visible virama, placed by the font
constexpr uint32_t I_ANUSVARA_03 = 0xF404;     // िं for क
constexpr uint32_t I_ANUSVARA = 0xF405;        // िं generic
constexpr uint32_t TTRA = 0xE019;              // ट्र (tta with rakar); its own value, not K_VIRAMA's
constexpr uint32_t YU = 0xE017;                // यु composite
constexpr uint32_t TTYA = 0xE018;              // ट्य ligature
constexpr uint32_t II_REPH_ANUSVARA = 0xF605;  // र्ीं generic
constexpr uint32_t I_REPH_ANUSVARA = 0xF406;   // र्िं generic
constexpr uint32_t RAKAR = 0xF000;             // ्र below mark
constexpr uint32_t REPH = 0xF100;              // र् mark
constexpr uint32_t REPH_ANUSVARA = 0xF101;     // र्ं
constexpr uint32_t REPH_E = 0xF102;            // र्े
constexpr uint32_t REPH_E_ANUSVARA = 0xF103;
constexpr uint32_t E_ANUSVARA = 0xF104;  // ें
constexpr uint32_t I_03 = 0xF400;        // ि for क
constexpr uint32_t I_06 = 0xF401;        // ि for क्ष
constexpr uint32_t I_REPH_03 = 0xF402;   // ि fused with a reph, for क
constexpr uint32_t I_REPH = 0xF403;      // ि fused with a reph, generic
constexpr uint32_t II_03 = 0xF600;       // ी for क
constexpr uint32_t II_REPH = 0xF601;     // ी fused with a reph
constexpr uint32_t II_ANUSVARA_03 = 0xF602;
constexpr uint32_t O_ANUSVARA = 0xF603;        // ों (aa + fused e-anusvara)
constexpr uint32_t O_REPH = 0xF604;            // र्ो (aa + fused reph-e)
constexpr uint32_t O_VOWEL_ANUSVARA = 0xE00C;  // ओं (आ + fused e-anusvara)
constexpr uint32_t CANDRA_E = 0x0945, VOWEL_O = 0x0913, VOWEL_AA = 0x0906;
constexpr uint32_t I_CLASS1 = 0xF410, I_CLASS2 = 0xF411, I_ANUSVARA_CLASS2 = 0xF412, II_CLASS1 = 0xF610;
constexpr uint32_t IDX1 = Lipi::KEY_CLASS_INDEX_CP + 1, IDX2 = Lipi::KEY_CLASS_INDEX_CP + 2;

struct Entry {
  std::vector<uint32_t> key;
  uint32_t out;           // PUA codepoint, 0 for a bookkeeping entry
  uint8_t preClass = 0;   // ि class of the glyph
  uint8_t postClass = 0;  // ी class of the glyph
  bool continues = false;
};

uint8_t keyByte(const uint32_t cp) {
  if (cp == ZWJ) return 0x01;
  if (cp == Lipi::KEY_CLASS_CP) return 0x04;
  if (cp == Lipi::KEY_VARIANT_CP) return 0x05;
  if (cp == Lipi::KEY_FORMAT_CP) return 0x06;
  if (cp > Lipi::KEY_CLASS_INDEX_CP && cp <= Lipi::KEY_CLASS_INDEX_CP + 15)
    return static_cast<uint8_t>(0x10 | (cp - Lipi::KEY_CLASS_INDEX_CP));
  return static_cast<uint8_t>(0x80 | (cp - 0x0900));
}

// Packed layout (format 3), the bytes builder/shaping.py writes.
std::vector<uint8_t> packTable(const std::vector<Entry>& entries) {
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

const std::vector<uint8_t>& tableBytes() {
  static const std::vector<uint8_t> bytes = packTable({
      {{KA, VIRAMA, ZWJ}, K_HALF},
      {{KA, VIRAMA}, K_VIRAMA},
      {{SA, VIRAMA, ZWJ}, S_HALF},
      {{GA, VIRAMA, ZWJ}, G_HALF, 2, 0},  // ि attaches to ग् with class 2
      {{MA, VIRAMA, ZWJ}, M_HALF},
      {{KA, VIRAMA, SSA}, KSSA},
      {{KA, VIRAMA, SSA, VIRAMA, ZWJ}, KSSA_HALF},
      {{TA, VIRAMA, RA}, TRA, 2, 0},
      {{KA, VIRAMA, RA}, KRA},
      {{RA, VIRAMA, ZWJ}, EYELASH},
      {{RA, ZWJ, VIRAMA, YA}, RA_ZWJ_YA},
      {{RA, U}, RU},
      {{TTA, VIRAMA, TTHA}, TTTTHA},
      {{TTA, VIRAMA, ZWJ}, TT_HALF},
      {{NA, VIRAMA, ZWJ}, N_HALF},
      {{DA, U}, DU},
      {{SSA, U}, SSU},
      {{SHA, VIRAMA, RA}, SHRA},
      {{DA, VIRAMA, VA}, DVA},
      {{VA, VIRAMA, YA}, VYA},
      {{VA, VIRAMA, ZWJ}, V_HALF},
      {{SSA, VIRAMA, TTA}, SSTTA, 0, 0, true},  // continues: ष्ट्वा keeps ष्ट
      {{SSA, VIRAMA, ZWJ}, SS_HALF},
      {{KA, I, ANUSVARA}, I_ANUSVARA_03},
      {{TTA, VIRAMA, RA}, TTRA},
      {{YA, U}, YU},
      {{TTA, VIRAMA, YA}, TTYA},
      {{RA, VIRAMA, II, ANUSVARA}, II_REPH_ANUSVARA},
      {{RA, VIRAMA, I, ANUSVARA}, I_REPH_ANUSVARA},
      {{I, ANUSVARA}, I_ANUSVARA},
      {{VIRAMA, RA}, RAKAR},
      {{RA, VIRAMA}, REPH},
      {{RA, VIRAMA, ANUSVARA}, REPH_ANUSVARA},
      {{RA, VIRAMA, E}, REPH_E},
      {{RA, VIRAMA, E, ANUSVARA}, REPH_E_ANUSVARA},
      {{E, ANUSVARA}, E_ANUSVARA},
      {{KA, I}, I_03},
      {{KA, VIRAMA, SSA, I}, I_06},
      {{RA, VIRAMA, KA, I}, I_REPH_03},
      {{RA, VIRAMA, I}, I_REPH},
      {{KA, II}, II_03},
      {{RA, VIRAMA, II}, II_REPH},
      {{KA, II, ANUSVARA}, II_ANUSVARA_03},
      {{O, ANUSVARA}, O_ANUSVARA},
      {{RA, VIRAMA, O}, O_REPH},
      {{VOWEL_O, ANUSVARA}, O_VOWEL_ANUSVARA},
      // Sign classes: the ligature त्र and the half form स् attach ि of
      // class 2, the bare consonant द draws ि of class 1 and ी of class 1;
      // class 2 also has a variant fused with the anusvara.
      {{Lipi::KEY_CLASS_CP, DA}, 0, 1, 1},
      {{Lipi::KEY_VARIANT_CP, I, IDX1}, I_CLASS1},
      {{Lipi::KEY_VARIANT_CP, I, IDX2}, I_CLASS2},
      {{Lipi::KEY_VARIANT_CP, I, ANUSVARA, IDX2}, I_ANUSVARA_CLASS2},
      {{Lipi::KEY_VARIANT_CP, II, IDX1}, II_CLASS1},
      {{Lipi::KEY_FORMAT_CP, Lipi::KEY_FORMAT_CP}, 0xE000 + Lipi::TABLE_FORMAT},
  });
  return bytes;
}

Lipi::ClusterTable table() { return {tableBytes().data(), entryCount(tableBytes()), KIND}; }

std::string encode(const std::vector<uint32_t>& cps) {
  std::string s;
  for (const uint32_t cp : cps) Lipi::utf8Append(cp, s);
  return s;
}

std::vector<uint32_t> decode(const std::string& s) {
  std::vector<uint32_t> out;
  const auto* p = reinterpret_cast<const unsigned char*>(s.c_str());
  while (*p) out.push_back(Lipi::utf8Next(&p));
  return out;
}

std::vector<uint32_t> shaped(const std::vector<uint32_t>& in, const Lipi::ClusterTable& t = table()) {
  std::string out;
  EXPECT_TRUE(Lipi::shape(encode(in).c_str(), t, out));
  return decode(out);
}

using V = std::vector<uint32_t>;

TEST(LipiDevanagari, HalfFormBeforeFullConsonant) {
  EXPECT_EQ(shaped({KA, VIRAMA, KA}), (V{K_HALF, KA}));
  EXPECT_EQ(shaped({SA, VIRAMA, TA}), (V{S_HALF, TA}));
  EXPECT_EQ(shaped({SA, VIRAMA, TA, VIRAMA, RA}), (V{S_HALF, TRA}));
}

TEST(LipiDevanagari, LigaturesAndTheirHalfForms) {
  EXPECT_EQ(shaped({KA, VIRAMA, SSA}), (V{KSSA}));
  EXPECT_EQ(shaped({KA, VIRAMA, SSA, VIRAMA, MA}), (V{KSSA_HALF, MA}));
  EXPECT_EQ(shaped({KA, VIRAMA, SSA, VIRAMA, MA, VIRAMA, YA}), (V{KSSA_HALF, M_HALF, YA}));
  // A ligature without a half form gives way to half forms when the
  // cluster continues, and is kept when it ends the cluster.
  EXPECT_EQ(shaped({TTA, VIRAMA, TTHA}), (V{TTTTHA}));
  EXPECT_EQ(shaped({TTA, VIRAMA, TTHA, VIRAMA, KA}), (V{TT_HALF, TTHA, VIRAMA, KA}));
  EXPECT_EQ(shaped({TTA, VIRAMA, TTHA, I}), (V{I, TTTTHA}));
  // Whether a ligature forms when the cluster continues is the font's
  // choice, recorded as the ligature key plus a virama: ष्ट्वा keeps ष्ट,
  // द्व्य becomes द ् व्य.
  EXPECT_EQ(shaped({SSA, VIRAMA, TTA, VIRAMA, VA, AA}), (V{SSTTA, VIRAMA, VA, AA}));
  EXPECT_EQ(shaped({DA, VIRAMA, VA, VIRAMA, YA}), (V{DA, VIRAMA, VYA}));
  EXPECT_EQ(shaped({DA, VIRAMA, VA}), (V{DVA}));
  EXPECT_EQ(shaped({SSA, VIRAMA, TTA}), (V{SSTTA}));
  EXPECT_EQ(shaped({SSA, VIRAMA, KA, VIRAMA, VA}), (V{SS_HALF, K_HALF, VA}));  // no ligature: half forms
  // Before a subjoining consonant the ligature yields even with the alias:
  // the rakar attaches to ट (ष् ट्र).
  EXPECT_EQ(shaped({SSA, VIRAMA, TTA, VIRAMA, RA}), (V{SS_HALF, TTRA}));
  // ... and when its last consonant ligates with the next one (ष् ट्य).
  EXPECT_EQ(shaped({SSA, VIRAMA, TTA, VIRAMA, YA}), (V{SS_HALF, TTYA}));
  EXPECT_EQ(shaped({SSA, VIRAMA, TTA, VIRAMA, KA}), (V{SSTTA, VIRAMA, KA}));
}

TEST(LipiDevanagari, RakarIsAMarkNotAHalfForm) {
  EXPECT_EQ(shaped({KA, VIRAMA, RA}), (V{KRA}));        // composite with exact placement
  EXPECT_EQ(shaped({GA, VIRAMA, RA}), (V{GA, RAKAR}));  // ग् half form exists but is not used
  EXPECT_EQ(shaped({GA, VIRAMA, RA, I}), (V{I, GA, RAKAR}));
}

TEST(LipiDevanagari, NoHalfFormFallsBackToVisibleVirama) {
  EXPECT_EQ(shaped({NGA, VIRAMA, KA}), (V{NGA, VIRAMA, KA}));
  EXPECT_EQ(shaped({DDA, VIRAMA, GA}), (V{DDA, VIRAMA, GA}));
  EXPECT_EQ(shaped({KA, VIRAMA}), (V{K_VIRAMA}));      // word-final hasanta: the font-placed composite
  EXPECT_EQ(shaped({NGA, VIRAMA}), (V{NGA, VIRAMA}));  // no composite: visible virama mark
  EXPECT_EQ(shaped({RA, VIRAMA}), (V{RA, VIRAMA}));    // the reph key is a mark, never a composite
  EXPECT_EQ(shaped({KA, VIRAMA, SSA}), (V{KSSA}));     // a conjunct still wins over the composite
}

TEST(LipiDevanagari, JoinersControlTheForm) {
  EXPECT_EQ(shaped({KA, VIRAMA, ZWJ, SSA}), (V{K_HALF, SSA}));         // ZWJ: half form, no ligature
  EXPECT_EQ(shaped({KA, VIRAMA, ZWNJ, SSA}), (V{K_VIRAMA, SSA}));      // ZWNJ: visible virama (composite)
  EXPECT_EQ(shaped({NGA, VIRAMA, ZWNJ, SSA}), (V{NGA, VIRAMA, SSA}));  // ZWNJ, no composite for ङ
  EXPECT_EQ(shaped({RA, VIRAMA, ZWJ, YA}), (V{EYELASH, YA}));          // eyelash ra, no reph
  EXPECT_EQ(shaped({RA, ZWJ, VIRAMA, YA}), (V{RA_ZWJ_YA}));            // ZWJ before virama: the font's form
  EXPECT_EQ(shaped({RA, ZWJ, VIRAMA, KA}), (V{RA, VIRAMA, KA}));       // no form: visible virama, no reph
  EXPECT_EQ(shaped({KA, VIRAMA, ZWJ}), (V{K_HALF}));
}

TEST(LipiDevanagari, RephFollowsThePostBaseSign) {
  EXPECT_EQ(shaped({RA, VIRAMA, KA}), (V{KA, REPH}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, AA}), (V{KA, AA, REPH}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, U}), (V{KA, U, REPH}));
  EXPECT_EQ(shaped({RA, VIRAMA, TA, VIRAMA, RA, AA}), (V{TRA, AA, REPH}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, AA, VISARGA}), (V{KA, AA, REPH, VISARGA}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, AA, CANDRABINDU}), (V{KA, AA, REPH, CANDRABINDU}));
}

TEST(LipiDevanagari, RephFusedWithPreAndPostSigns) {
  EXPECT_EQ(shaped({RA, VIRAMA, KA, I}), (V{I_REPH_03, KA}));  // per-base fused ि
  EXPECT_EQ(shaped({RA, VIRAMA, GA, I}), (V{I_REPH, GA}));     // generic fused ि
  EXPECT_EQ(shaped({RA, VIRAMA, KA, II}), (V{KA, II_REPH}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, O}), (V{KA, O_REPH}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, II, ANUSVARA}), (V{KA, II_REPH_ANUSVARA}));  // fused generic beats plain per-base
  EXPECT_EQ(shaped({RA, VIRAMA, KA, II, VISARGA}), (V{KA, II_REPH, VISARGA}));
}

TEST(LipiDevanagari, RephFusedWithAboveSignAndModifier) {
  EXPECT_EQ(shaped({RA, VIRAMA, KA, E}), (V{KA, REPH_E}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, ANUSVARA}), (V{KA, REPH_ANUSVARA}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, E, ANUSVARA}), (V{KA, REPH_E_ANUSVARA}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, AA, ANUSVARA}), (V{KA, AA, REPH_ANUSVARA}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, ANUSVARA, VISARGA}), (V{KA, REPH_ANUSVARA, VISARGA}));
}

TEST(LipiDevanagari, SignsFusedWithTheAnusvara) {
  EXPECT_EQ(shaped({KA, E, ANUSVARA}), (V{KA, E_ANUSVARA}));
  EXPECT_EQ(shaped({KA, O, ANUSVARA}), (V{KA, O_ANUSVARA}));
  EXPECT_EQ(shaped({KA, II, ANUSVARA}), (V{KA, II_ANUSVARA_03}));
  EXPECT_EQ(shaped({GA, II, ANUSVARA}), (V{GA, II, ANUSVARA}));  // no form for this base
  EXPECT_EQ(shaped({KA, I, ANUSVARA}), (V{I_ANUSVARA_03, KA}));  // ि fused with the anusvara, per base
  EXPECT_EQ(shaped({GA, I, ANUSVARA}), (V{I_ANUSVARA, GA}));     // generic
  EXPECT_EQ(shaped({KA, I, VISARGA}), (V{I_03, KA, VISARGA}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, I, ANUSVARA}), (V{I_REPH_ANUSVARA, KA}));  // fused generic beats plain per-base
  EXPECT_EQ(shaped({RA, VIRAMA, KA, I, VISARGA}), (V{I_REPH_03, KA, VISARGA}));
  EXPECT_EQ(shaped({KA, E}), (V{KA, E}));
  EXPECT_EQ(shaped({KA, ANUSVARA}), (V{KA, ANUSVARA}));
  EXPECT_EQ(shaped({VOWEL_O, ANUSVARA}), (V{O_VOWEL_ANUSVARA}));
  EXPECT_EQ(shaped({VOWEL_AA, ANUSVARA}), (V{VOWEL_AA, ANUSVARA}));
  EXPECT_EQ(shaped({VOWEL_O, VISARGA}), (V{VOWEL_O, VISARGA}));
  // The post-base sign precedes an above sign, which precedes the reph.
  EXPECT_EQ(shaped({MA, AA, CANDRA_E}), (V{MA, AA, CANDRA_E}));
  EXPECT_EQ(shaped({RA, VIRAMA, MA, AA, CANDRA_E}), (V{MA, AA, CANDRA_E, REPH}));
}

TEST(LipiDevanagari, PreBaseSignForms) {
  EXPECT_EQ(shaped({KA, I}), (V{I_03, KA}));
  EXPECT_EQ(shaped({KA, VIRAMA, SSA, I}), (V{I_06, KSSA}));
  EXPECT_EQ(shaped({SA, VIRAMA, TA, I}), (V{I, S_HALF, TA}));  // no form: plain sign
  EXPECT_EQ(shaped({HA, I, NGA}), (V{I, HA, NGA}));
}

TEST(LipiDevanagari, BelowVowelLigatureAndNuktaFold) {
  EXPECT_EQ(shaped({RA, U}), (V{RU}));
  EXPECT_EQ(shaped({KA, U}), (V{KA, U}));
  EXPECT_EQ(shaped({NA, VIRAMA, DA, U}), (V{N_HALF, DU}));     // sign ligature of the last consonant
  EXPECT_EQ(shaped({NA, VIRAMA, KA, U}), (V{N_HALF, KA, U}));  // none: plain sign
  EXPECT_EQ(shaped({KA, VIRAMA, SSA, U}), (V{KSSA, U}));       // ligature keeps the sign after it
  EXPECT_EQ(shaped({SHA, VIRAMA, RA, U}), (V{SHRA, U}));       // rakar ligature, not श् + रु
  EXPECT_EQ(shaped({TA, VIRAMA, RA, U}), (V{TRA, U}));
  EXPECT_EQ(shaped({SA, VIRAMA, SSA, U}), (V{S_HALF, SSU}));  // no ligature: the sign joins ष
  EXPECT_EQ(shaped({DA, U, ANUSVARA}), (V{DU, ANUSVARA}));
  EXPECT_EQ(shaped({DA, VIRAMA, VA, VIRAMA, YA, U}), (V{DA, VIRAMA, VYA, U}));  // final ligature keeps the sign
  EXPECT_EQ(shaped({DDA, NUKTA}), (V{DDDHA}));
  EXPECT_EQ(shaped({DDA, NUKTA, VIRAMA, GA}), (V{DDDHA, VIRAMA, GA}));
  EXPECT_EQ(shaped({TA, NUKTA}), (V{TA, NUKTA}));  // no precomposed letter
}

TEST(LipiDevanagari, OtherKindTableGivesReorderingOnly) {
  Lipi::ClusterTable bengaliKind = table();
  bengaliKind.kind = Lipi::SHAPE_KIND_BENGALI;
  EXPECT_EQ(shaped({KA, VIRAMA, SSA, I}, bengaliKind), (V{I, KA, VIRAMA, SSA}));
  EXPECT_EQ(shaped({RA, VIRAMA, KA, AA}, bengaliKind), (V{RA, VIRAMA, KA, AA}));
  const Lipi::ClusterTable none{nullptr, 0, 0};
  EXPECT_EQ(shaped({KA, VIRAMA, KA}, none), (V{KA, VIRAMA, KA}));
}

TEST(LipiDevanagari, SignVariantsFollowTheGlyphClasses) {
  // A ligature that is the whole cluster: ि of its class.
  EXPECT_EQ(shaped({TA, VIRAMA, RA, I}), (V{I_CLASS2, TRA}));
  // A half form the sign attaches to: the class of the first glyph.
  EXPECT_EQ(shaped({GA, VIRAMA, TA, I}), (V{I_CLASS2, G_HALF, TA}));
  // A half form without a class, or a bare consonant first: plain ि.
  EXPECT_EQ(shaped({KA, VIRAMA, TA, I}), (V{I, K_HALF, TA}));
  EXPECT_EQ(shaped({TA, I}), (V{I, TA}));
  // A bare consonant with classes, alone and as the last glyph.
  EXPECT_EQ(shaped({DA, I}), (V{I_CLASS1, DA}));
  EXPECT_EQ(shaped({DA, II}), (V{DA, II_CLASS1}));
  EXPECT_EQ(shaped({KA, VIRAMA, DA, II}), (V{K_HALF, DA, II_CLASS1}));
  // The anusvara fuses with the class variant when the list has one. A base
  // with a class but no fused variant of that class is one the font does not
  // fuse for (Noto Bengali's wide ি): the plain class variant and the
  // modifier on its own, not the generic fused form shaped on the probe.
  EXPECT_EQ(shaped({TA, VIRAMA, RA, I, ANUSVARA}), (V{I_ANUSVARA_CLASS2, TRA}));
  EXPECT_EQ(shaped({DA, I, ANUSVARA}), (V{I_CLASS1, DA, ANUSVARA}));
  // Per-base forms keep priority (क has its own ि and ी forms).
  EXPECT_EQ(shaped({KA, I}), (V{I_03, KA}));
  EXPECT_EQ(shaped({KA, II}), (V{KA, II_03}));
  EXPECT_EQ(Lipi::tableFormat(table()), Lipi::TABLE_FORMAT);
}

TEST(LipiDevanagari, PassThroughAndMixedScripts) {
  EXPECT_EQ(shaped({KA, DANDA, ' ', 'a'}), (V{KA, DANDA, ' ', 'a'}));
  EXPECT_EQ(shaped({0x0915, ' ', 0x0995, 0x09BF}), (V{0x0915, ' ', 0x09BF, 0x0995}));  // Bengali reordered too
  EXPECT_EQ(shaped({0x0966, 0x0967}), (V{0x0966, 0x0967}));                            // digits
  EXPECT_EQ(shaped({ZWJ, KA, ZWNJ}), (V{KA}));
}

TEST(LipiDevanagari, MarksAreZeroAdvanceOverlays) {
  for (const uint32_t cp : {U, E, ANUSVARA, CANDRABINDU, NUKTA, VIRAMA, RAKAR, REPH, REPH_E}) {
    EXPECT_TRUE(Lipi::isMark(cp)) << std::hex << cp;
  }
  for (const uint32_t cp : {AA, I, II, O, VISARGA, K_HALF, KSSA, I_03, II_03, O_REPH}) {
    EXPECT_FALSE(Lipi::isMark(cp)) << std::hex << cp;
  }
}

TEST(LipiDevanagari, GenericSignFormCannotBeAComposite) {
  // Builders before 2026-09-19 wrote the probe letter's whole run (ि, क,
  // reph-anusvara) as a composite under the base-less key र्िं; the engine
  // then drew that composite in place of the real base (मूर्तिं came out as
  // मूर्किं). A composite hit on a generic key is ignored: the sign, the base
  // and the fused mark are assembled as without the entry.
  constexpr uint32_t BOGUS = 0xE0FE;
  const std::vector<Entry> common = {
      {{RA, VIRAMA}, REPH},
      {{RA, VIRAMA, ANUSVARA}, REPH_ANUSVARA},
      {{I, ANUSVARA}, I_ANUSVARA},
      {{Lipi::KEY_FORMAT_CP, Lipi::KEY_FORMAT_CP}, 0xE000 + Lipi::TABLE_FORMAT},
  };
  std::vector<Entry> withBogus = common;
  withBogus.push_back({{RA, VIRAMA, I, ANUSVARA}, BOGUS});
  std::vector<Entry> withBogusMod = common;
  withBogusMod.push_back({{I, ANUSVARA}, BOGUS});  // the same under the sign + modifier key
  const auto clean = packTable(common), bogus = packTable(withBogus), bogusMod = packTable(withBogusMod);
  const Lipi::ClusterTable tClean{clean.data(), entryCount(clean), KIND};
  const Lipi::ClusterTable tBogus{bogus.data(), entryCount(bogus), KIND};
  const Lipi::ClusterTable tBogusMod{bogusMod.data(), entryCount(bogusMod), KIND};
  const V word = {MA, U, RA, VIRAMA, TA, I, ANUSVARA};  // मूर्तिं
  const V expected = shaped(word, tClean);
  EXPECT_NE(std::find(expected.begin(), expected.end(), TA), expected.end());
  EXPECT_EQ(shaped(word, tBogus), expected);
  EXPECT_EQ(shaped(word, tBogusMod), V({MA, U, I, TA, REPH_ANUSVARA}));
  // With the generic िं form present it is the one drawn, and the reph stays plain.
  EXPECT_EQ(shaped({RA, VIRAMA, TA, I, ANUSVARA}, tBogus), (V{I_ANUSVARA, TA, REPH}));
}

TEST(LipiDevanagari, RephFusionWinsOverTheSignModifierForm) {
  // A font that stacks the modifier on the reph (Tiro कर्हाँ) has a form for that
  // pair. Taking the generic sign + modifier form (ाँ) first would consume the
  // modifier and leave the reph to be drawn alone, which the renderer then puts
  // past the cluster. With a reph present the reph form wins; without one the
  // sign + modifier form is still used.
  constexpr uint32_t AA_CANDRABINDU = 0xF640;   // ाँ drawn as one post-base form
  constexpr uint32_t REPH_CANDRABINDU = 0xF102; // र्ँ drawn as one mark
  const std::vector<Entry> entries = {
      {{RA, VIRAMA}, REPH},
      {{RA, VIRAMA, CANDRABINDU}, REPH_CANDRABINDU},
      {{AA, CANDRABINDU}, AA_CANDRABINDU},
      {{Lipi::KEY_FORMAT_CP, Lipi::KEY_FORMAT_CP}, 0xE000 + Lipi::TABLE_FORMAT},
  };
  const auto packed = packTable(entries);
  const Lipi::ClusterTable table{packed.data(), entryCount(packed), KIND};
  EXPECT_EQ(shaped({KA, RA, VIRAMA, HA, AA, CANDRABINDU}, table), (V{KA, HA, AA, REPH_CANDRABINDU}));  // कर्हाँ
  EXPECT_EQ(shaped({KA, HA, AA, CANDRABINDU}, table), (V{KA, HA, AA_CANDRABINDU}));                    // कहाँ
}

}  // namespace

TEST(LipiDevanagari, SignBeforeAHalfFormFollowsTheNextGlyph) {
  // Noto Serif Devanagari sizes ि before a half form by the half form and the
  // glyph after it (षि + व -> ि.12). The half form's row ({CLASS, half key}) and
  // the cell {VARIANT, ZWJ, ि, row letter, next class + 1} give the class; the
  // class lists then pick the glyph, fused with the anusvara where one exists.
  constexpr uint32_t ROW1 = 0x0900 + 1;
  const std::vector<Entry> entries = {
      {{KA, VIRAMA, ZWJ}, K_HALF},
      {{SA, VIRAMA, ZWJ}, S_HALF},
      {{Lipi::KEY_CLASS_CP, KA, VIRAMA, ZWJ}, 0, 1, 0},  // row 1
      {{Lipi::KEY_CLASS_CP, DA}, 0, 1, 1},               // द: class 1
      {{Lipi::KEY_VARIANT_CP, I, IDX1}, I_CLASS1},
      {{Lipi::KEY_VARIANT_CP, I, IDX2}, I_CLASS2},
      {{Lipi::KEY_VARIANT_CP, I, ANUSVARA, IDX2}, I_ANUSVARA_CLASS2},
      // Row 1 before class 1 (द) takes class 2; before a class-0 consonant, class 1;
      // before another half form (column 15), class 2.
      {{Lipi::KEY_VARIANT_CP, ZWJ, I, ROW1, Lipi::KEY_CLASS_INDEX_CP + 2}, 0, 2, 0},
      {{Lipi::KEY_VARIANT_CP, ZWJ, I, ROW1, Lipi::KEY_CLASS_INDEX_CP + 1}, 0, 1, 0},
      {{Lipi::KEY_VARIANT_CP, ZWJ, I, ROW1, Lipi::KEY_CLASS_INDEX_CP + 15}, 0, 2, 0},
      {{Lipi::KEY_FORMAT_CP, Lipi::KEY_FORMAT_CP}, 0xE000 + Lipi::TABLE_FORMAT},
  };
  const auto packed = packTable(entries);
  const Lipi::ClusterTable t{packed.data(), entryCount(packed), KIND};
  EXPECT_EQ(shaped({KA, VIRAMA, DA, I}, t), (V{I_CLASS2, K_HALF, DA}));
  EXPECT_EQ(shaped({KA, VIRAMA, TA, I}, t), (V{I_CLASS1, K_HALF, TA}));
  EXPECT_EQ(shaped({KA, VIRAMA, SA, VIRAMA, TA, I}, t), (V{I_CLASS2, K_HALF, S_HALF, TA}));
  EXPECT_EQ(shaped({KA, VIRAMA, DA, I, ANUSVARA}, t), (V{I_ANUSVARA_CLASS2, K_HALF, DA}));
  // A half form without a row keeps today's rule (plain ि).
  EXPECT_EQ(shaped({SA, VIRAMA, DA, I}, t), (V{I, S_HALF, DA}));
}
