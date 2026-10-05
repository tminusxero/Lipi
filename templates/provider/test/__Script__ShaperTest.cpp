// __Script__ShaperTest — the __Script__ provider through the Lipi engine.
// Inputs are codepoint arrays in LOGICAL order; expectations are the visual
// codepoint stream the host draws. Start with reorder-only cases (no table),
// then add a synthetic table with the packing rules of builder/shaping.py for
// the script's conjuncts (see providers/bengali/test for the helpers).

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

#include "Lipi.h"
#include "LipiUtf8.h"

namespace {

constexpr uint32_t BLOCK = __BLOCK__;
constexpr uint32_t KA = BLOCK + 0x15, VIRAMA = BLOCK + 0x4D, I = BLOCK + 0x3F, AA = BLOCK + 0x3E;
using CP = std::vector<uint32_t>;

CP shape(const CP& cps) {
  std::string utf8;
  for (const uint32_t cp : cps) Lipi::utf8Append(cp, utf8);
  std::string shaped;
  const Lipi::ClusterTable noTable{};
  if (!Lipi::shape(utf8.c_str(), noTable, shaped)) return {};
  CP out;
  const auto* p = reinterpret_cast<const unsigned char*>(shaped.c_str());
  while (*p) out.push_back(Lipi::utf8Next(&p));
  return out;
}

TEST(Lipi__Script__, DescriptorIsRegistered) {
  EXPECT_EQ(Lipi::scriptFor(KA), &Lipi::k__Script__);
  EXPECT_EQ(Lipi::k__Script__.shapeKind, __KIND__);
  EXPECT_TRUE(Lipi::isMark(VIRAMA));
}

TEST(Lipi__Script__, PreBaseVowelMovesBeforeConsonant) { EXPECT_EQ(shape({KA, I}), (CP{I, KA})); }

TEST(Lipi__Script__, PostBaseVowelStaysAfterTheCluster) { EXPECT_EQ(shape({KA, AA}), (CP{KA, AA})); }

TEST(Lipi__Script__, UnknownPairKeepsVisibleVirama) { EXPECT_EQ(shape({KA, VIRAMA, KA}), (CP{KA, VIRAMA, KA})); }

}  // namespace
