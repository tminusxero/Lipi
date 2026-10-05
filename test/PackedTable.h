// Test-side packer for cluster tables in the packed layout (Lipi table
// format 3, Script.h): the same bytes builder/shaping.py's pack_rows writes,
// so the shaper tests exercise the on-device lookup on real geometry.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <vector>

#include "Script.h"

namespace LipiTest {

/// One entry before packing: key bytes (keyByte per codepoint), meta byte
/// and the u16 value, as the builder computes them.
struct Row {
  std::vector<uint8_t> key;
  uint8_t meta = 0;
  uint16_t value = 0;
};

struct Packed {
  std::vector<uint8_t> bytes;
  uint16_t count = 0;
};

/// Packs rows: directory, then per key length its bucket index and entries.
inline Packed packRows(std::vector<Row> rows) {
  Packed out;
  std::map<size_t, std::vector<Row>> byLen;
  for (auto& r : rows) byLen[r.key.size()].push_back(r);
  std::vector<uint8_t> directory;
  std::vector<uint8_t> sections;
  for (size_t len = Lipi::PACKED_MIN_KEY_LEN; len <= Lipi::PACKED_MAX_KEY_LEN; ++len) {
    auto& group = byLen[len];
    std::sort(group.begin(), group.end(), [](const Row& a, const Row& b) { return a.key < b.key; });
    std::vector<std::pair<uint8_t, uint16_t>> buckets;
    for (const auto& r : group) {
      if (buckets.empty() || buckets.back().first != r.key[0]) buckets.emplace_back(r.key[0], 0);
      buckets.back().second++;
    }
    directory.push_back(static_cast<uint8_t>(group.size() & 0xFF));
    directory.push_back(static_cast<uint8_t>(group.size() >> 8));
    directory.push_back(static_cast<uint8_t>(buckets.size()));
    for (const auto& b : buckets) {
      sections.push_back(b.first);
      sections.push_back(static_cast<uint8_t>(b.second & 0xFF));
      sections.push_back(static_cast<uint8_t>(b.second >> 8));
    }
    for (const auto& r : group) {
      sections.insert(sections.end(), r.key.begin() + 1, r.key.end());
      sections.push_back(r.meta);
      sections.push_back(static_cast<uint8_t>(r.value & 0xFF));
      sections.push_back(static_cast<uint8_t>(r.value >> 8));
    }
    out.count = static_cast<uint16_t>(out.count + group.size());
  }
  out.bytes = directory;
  out.bytes.insert(out.bytes.end(), sections.begin(), sections.end());
  return out;
}

/// Meta and value bytes from the builder's fields.
inline Row makeRow(std::vector<uint8_t> key, const uint32_t outCp, const uint8_t preClass, const uint8_t postClass,
                   const bool continues) {
  Row r;
  r.meta = static_cast<uint8_t>(key.size() | (continues ? 0x08 : 0) | (preClass << 4));
  r.value = static_cast<uint16_t>((postClass << 13) | (outCp ? outCp - 0xE000 : 0x1FFF));
  r.key = std::move(key);
  return r;
}

}  // namespace LipiTest
