// Host CLI: reads a .cpfont cluster table (style 0) and prints the shaped
// codepoint stream of each line of stdin as hex codepoints.
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "Lipi.h"
#include "LipiUtf8.h"
static uint16_t u16(const uint8_t* p) { return p[0] | (p[1] << 8); }
static uint32_t u32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24); }
int main(int argc, char** argv) {
  std::vector<uint8_t> file;
  Lipi::ClusterTable table;
  if (argc > 1) {
    std::ifstream f(argv[1], std::ios::binary);
    file.assign(std::istreambuf_iterator<char>(f), {});
    const uint8_t* toc = file.data() + 32;
    uint16_t count = u16(toc + 2);
    uint32_t off = u32(toc + 28);
    // The kind byte carries TOC_KIND_PACKED since table format 3; the packed
    // blob's directory says how many bytes and entries it holds.
    const uint8_t kind = static_cast<uint8_t>(toc[1] & ~Lipi::TOC_KIND_PACKED);
    if ((toc[1] & Lipi::TOC_KIND_PACKED) && Lipi::entrySizeForKind(kind) && count && off && off < file.size()) {
      uint32_t entries = 0;
      const uint32_t bytes = Lipi::packedTableBytes(file.data() + off, kind, &entries);
      if (bytes && entries == count && off + bytes <= file.size()) table = {file.data() + off, count, kind};
    }
    fprintf(stderr, "table entries: %u\n", table.count);
  }
  std::string line;
  while (std::getline(std::cin, line)) {
    std::string out;
    if (!Lipi::shape(line.c_str(), table, out)) out = line;
    auto* p = reinterpret_cast<const unsigned char*>(out.c_str());
    bool first = true;
    while (uint32_t cp = Lipi::utf8Next(&p)) {
      printf(first ? "%04X" : " %04X", cp);
      first = false;
    }
    printf("\n");
  }
}
