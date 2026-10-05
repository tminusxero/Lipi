#include "Lipi.h"

#include <cstring>

#include "LipiUtf8.h"

namespace {

using Lipi::ClusterTable;
using Lipi::Entry;
using Lipi::JoinStyle;
using Lipi::RephMode;
using Lipi::ScriptDesc;

constexpr uint32_t ZWNJ = 0x200C;
constexpr uint32_t ZWJ = 0x200D;

// Longest consonant cluster collected per syllable. Real clusters hold at
// most four consonants; anything longer simply starts a new cluster.
constexpr int MAX_CLUSTER = 12;
constexpr int MAX_BELOW = 2;
constexpr int MAX_MODIFIERS = 4;
constexpr int MAX_KEY = static_cast<int>(Lipi::MAX_KEY_CAP);
// Column of a half-form pair variant when another half form follows (the
// sign classes take columns class + 1). Mirror of the builder's HALF_PAIR_FOLLOWS.
constexpr uint8_t HALF_PAIR_FOLLOWS = 14;

// UTF-8 continuation bytes (after a 0xE0 lead) that start a block with a
// descriptor: two per block, since a 128-codepoint block spans two 64-point
// runs. Bit n stands for byte 0x80 + n. Computed once at start-up rather than
// as a constant expression: GCC under -fsanitize=undefined refuses a null test
// on the address of a constexpr descriptor inside constant evaluation
// ("(&kDevanagari == 0) is not a constant expression", g++ 13, any standard).
uint64_t shapedContinuationBytes() {
  uint64_t mask = 0;
  for (const ScriptDesc* d : Lipi::kScriptByBlock) {
    if (!d) continue;
    const uint32_t first = (d->blockBase >> 6) & 0x3F;
    mask |= 1ull << first;
    mask |= 1ull << (first + 1);
  }
  return mask;
}
const uint64_t kShapedContinuationBytes = shapedContinuationBytes();

uint8_t keyByte(const ScriptDesc& d, uint32_t cp) {
  if (cp == ZWJ) return 0x01;
  if (cp == Lipi::KEY_INIT_CP) return 0x02;
  if (cp == Lipi::KEY_FINA_CP) return 0x03;
  if (cp == Lipi::KEY_CLASS_CP) return 0x04;
  if (cp == Lipi::KEY_VARIANT_CP) return 0x05;
  if (cp == Lipi::KEY_FORMAT_CP) return 0x06;
  if (cp > Lipi::KEY_CLASS_INDEX_CP && cp <= Lipi::KEY_CLASS_INDEX_CP + Lipi::MAX_SIGN_CLASS)
    return static_cast<uint8_t>(0x10 | (cp - Lipi::KEY_CLASS_INDEX_CP));
  if (d.in(d.raFolds, cp)) cp = d.ra;
  if (d.inBlock(cp)) return static_cast<uint8_t>(0x80 | (cp - d.blockBase));
  return 0;
}

bool isComposite(const uint32_t cp) { return cp >= Lipi::PUA_BASE_FIRST && cp <= Lipi::PUA_BASE_LAST; }

void put(const uint32_t cp, std::string& out) { Lipi::utf8Append(cp, out); }

// Reads one codepoint ahead of the current one so a virama can be classified
// by what follows it before it is consumed.
struct Cursor {
  const unsigned char* p;
  uint32_t cur = 0;

  explicit Cursor(const char* text) : p(reinterpret_cast<const unsigned char*>(text)) { advance(); }
  void advance() { cur = *p ? Lipi::utf8Next(&p) : 0; }
  uint32_t peek() const {
    const unsigned char* q = p;
    return *q ? Lipi::utf8Next(&q) : 0;
  }
};

// One orthographic syllable in logical order, split into the pieces the
// emitter places: reph count, the remaining consonant cluster, and the
// vowel signs / modifiers around it.
struct Syllable {
  uint32_t cluster[MAX_CLUSTER];
  int n = 0;
  int rephs = 0;  // leading (ra, virama) pairs drawn as a mark
  int start = 0;  // index of the first cluster codepoint after the rephs
  uint32_t pre = 0;
  uint32_t post = 0;
  uint32_t above = 0;
  uint32_t below[MAX_BELOW] = {0, 0};
  int belowCount = 0;
  uint32_t mods[MAX_MODIFIERS];
  int modCount = 0;
  bool wordStart = false;  // nothing from the script's block precedes it
  bool wordEnd = false;    // nothing from the script's block follows it

  const uint32_t* rest() const { return cluster + start; }
  int restLen() const { return n - start; }
};

struct Emitter {
  const ScriptDesc& d;
  const ClusterTable& table;
  std::string& out;
  // Longest key the table can hold; 0 when there is no table for this script.
  const int maxKey;
  // Conjuncts join as half forms: the script's way, or this font's (the
  // table's half-form flag: Hind Siliguri writes Bengali with half forms).
  const bool halfForms;

  Emitter(const ScriptDesc& desc, const ClusterTable& t, std::string& o, const bool tableHalfForms)
      : d(desc),
        table(t),
        out(o),
        maxKey(t.kind == desc.shapeKind ? static_cast<int>(Lipi::maxKeyLenForKind(t.kind)) : 0),
        halfForms(desc.joinStyle == JoinStyle::HalfForm || (maxKey > 0 && tableHalfForms)) {}

  // Entry of the last successful lookup, so a caller that accepts a hit can
  // keep the glyph's sign classes and continuation flag.
  mutable Entry hit_{};

  void put(const uint32_t cp) const { ::put(cp, out); }
  uint32_t lookup(const uint32_t* cps, const int len) const {
    const Entry e = Lipi::lookupEntry(table, d, cps, static_cast<uint32_t>(len));
    if (e.cp) hit_ = e;
    return e.cp;
  }

  // One glyph of the emitted cluster with what the table knows about it.
  struct Piece {
    uint32_t cp = 0;
    uint8_t preClass = 0;
    uint8_t postClass = 0;
    bool half = false;  // a half form (key ending in ZWJ)
    uint8_t row = 0;    // half form whose pre-base sign follows the next glyph: its row, 0 = none
  };
  static constexpr int MAX_PIECES = MAX_CLUSTER + 1;

  // Classes of a bare consonant, from its {KEY_CLASS_CP, c} entry.
  Piece bare(const uint32_t cp) const {
    Piece p;
    p.cp = cp;
    if (maxKey > 0 && d.isConsonant(cp)) {
      const uint32_t key[2] = {Lipi::KEY_CLASS_CP, cp};
      const Entry e = Lipi::lookupEntry(table, d, key, 2);
      p.preClass = e.preClass;
      p.postClass = e.postClass;
    }
    return p;
  }
  Piece fromHit(const uint32_t cp, const bool half = false) const {
    Piece p;
    p.cp = cp;
    p.preClass = hit_.preClass;
    p.postClass = hit_.postClass;
    p.half = half;
    return p;
  }
  static void push(Piece* pieces, int& n, const Piece& p) {
    if (n < MAX_PIECES) pieces[n++] = p;
  }

  // Key = prefix + rest + suffix, when it fits.
  uint32_t lookupWith(const uint32_t* prefix, const int prefixLen, const uint32_t* rest, const int restLen,
                      const uint32_t* suffix, const int suffixLen) const {
    const int len = prefixLen + restLen + suffixLen;
    if (len < 2 || len > maxKey) return 0;
    if (restLen > 0 && rest[restLen - 1] == d.virama) return 0;
    uint32_t key[MAX_KEY];
    int k = 0;
    for (int i = 0; i < prefixLen; ++i) key[k++] = prefix[i];
    for (int i = 0; i < restLen; ++i) key[k++] = rest[i];
    for (int i = 0; i < suffixLen; ++i) key[k++] = suffix[i];
    return lookup(key, len);
  }

  // Half form of the longest segment at pos that a virama and another
  // consonant follow (क्ष्म: क्ष् then म). Keys carry the virama and a ZWJ,
  // the same request an explicit joiner makes. A consonant with a subjoined
  // form (rakar) attaches to the segment as a mark instead, so no half form
  // is taken in front of it. `next` is the consonant that follows cl[n)
  // when the caller split it off (0 otherwise). Returns the form and sets
  // `cover` to the codepoints it stands for (segment plus virama), 0 when
  // there is none.
  uint32_t halfForm(const uint32_t* cl, const int n, const int pos, const uint32_t next, int& cover) const {
    cover = 0;
    for (int e = n - 1; e > pos; --e) {
      const uint32_t after = e + 1 < n ? cl[e + 1] : next;
      if (cl[e] != d.virama || after == 0 || after == ZWJ || !d.isConsonant(after)) continue;
      const int len = e - pos + 2;
      if (len > maxKey) continue;
      const uint32_t subjoined[2] = {d.virama, after};
      const uint32_t subForm = lookup(subjoined, 2);
      if (subForm && !isComposite(subForm)) continue;
      uint32_t key[MAX_KEY];
      for (int i = 0; i < len - 1; ++i) key[i] = cl[pos + i];
      key[len - 1] = ZWJ;
      const uint32_t hit = lookup(key, len);
      if (hit) {
        cover = len - 1;
        return hit;
      }
    }
    return 0;
  }

  // Row of a half form in the table's pair variants ({KEY_CLASS_CP, half key}:
  // pre class | post class << 4), 0 when the sign before it does not depend on
  // the glyph after it. `half` is the half form's key without the ZWJ.
  uint8_t halfRow(const uint32_t* half, const int len) const {
    if (len + 2 > maxKey) return 0;
    uint32_t key[MAX_KEY];
    key[0] = Lipi::KEY_CLASS_CP;
    for (int i = 0; i < len; ++i) key[i + 1] = half[i];
    key[len + 1] = ZWJ;
    const Entry e = Lipi::lookupEntry(table, d, key, len + 2);
    return e.found ? static_cast<uint8_t>(e.preClass | (e.postClass << 4)) : 0;
  }

  // Longest-match walk over a consonant cluster. Keys never end on a virama:
  // a trailing virama is a visible hasanta mark on the preceding consonant,
  // never the reph key (ra + virama), which only the reph path consumes.
  // In half-form scripts a ligature and a half form compete for the same
  // position. A ligature that ends the cluster wins (क्ष); one that would
  // be followed by another consonant loses to any half form (ह्य्ष is
  // ह् य् ष, not ह्य + virama + ष), unless its own half form covers more
  // (क्ष्म with the font's क्ष्).
  void greedy(const uint32_t* cl, const int n, const uint32_t next, Piece* pieces, int& np) const {
    int pos = 0;
    while (pos < n) {
      uint32_t fullHit = 0;
      int fullLen = 0;
      Entry fullEntry;
      const int maxLen = (n - pos) < maxKey ? (n - pos) : maxKey;
      for (int len = maxLen; len >= 2; --len) {
        if (cl[pos + len - 1] == d.virama) {
          // A key ending on the virama is the composite of a consonant with
          // its visible virama (क्, placed as the font does), usable only
          // when that virama ends the cluster and the entry is a spacing
          // composite: the reph key (ra + virama) is a mark and never matches.
          if (pos + len != n || next != 0) continue;
          const uint32_t hit = lookup(cl + pos, len);
          if (!hit || !isComposite(hit)) continue;
          fullHit = hit;
          fullLen = len;
          fullEntry = hit_;
          break;
        }
        fullHit = lookup(cl + pos, len);
        if (fullHit) {
          fullLen = len;
          fullEntry = hit_;
          break;
        }
      }
      if (halfForms) {
        int cover = 0;
        const uint32_t half = halfForm(cl, n, pos, next, cover);
        const Entry halfEntry = hit_;
        // A ligature followed only by the word's final virama ends the cluster
        // too: the virama is drawn after it (Hind অস্ত্: স্ত + hasanta).
        bool fullEndsCluster = fullHit && next == 0 &&
                               (pos + fullLen == n || (pos + fullLen + 1 == n && cl[pos + fullLen] == d.virama));
        // A ligature followed by more of the cluster only forms when the
        // font does so (the builder flags the ligature as continuing);
        // otherwise the first consonant stands alone with a visible virama
        // and the rest joins on its own (द्व्य: द ् व्य).
        if (fullHit && !fullEndsCluster && fullLen >= 3 && d.isConsonant(cl[pos]) &&
            (pos + fullLen < n ? cl[pos + fullLen] == d.virama : next != 0)) {
          // A consonant that subjoins (rakar) attaches to the last consonant
          // of the ligature instead (ष्ट्र: ष् ट्र), so the ligature yields.
          const uint32_t after = pos + fullLen + 1 < n ? cl[pos + fullLen + 1] : next;
          const uint32_t subjoined[2] = {d.virama, after};
          const uint32_t subForm = after ? lookup(subjoined, 2) : 0;
          // Likewise when the ligature's last consonant forms a ligature with
          // the next one (ष्ट्य: ष् ट्य).
          const uint32_t tail[3] = {cl[pos + fullLen - 1], d.virama, after};
          const uint32_t tailForm = after ? lookup(tail, 3) : 0;
          if (!(subForm && !isComposite(subForm)) && !isComposite(tailForm) && fullEntry.continues) {
            fullEndsCluster = true;
          } else {
            fullHit = 0;
            fullLen = 0;
          }
        }
        if (half && (cover > fullLen || !fullEndsCluster)) {
          hit_ = halfEntry;
          Piece p = fromHit(half, true);
          p.row = halfRow(cl + pos, cover);
          push(pieces, np, p);
          pos += cover;
          continue;
        }
      }
      if (fullHit) {
        hit_ = fullEntry;
        push(pieces, np, fromHit(fullHit));
        pos += fullLen;
      } else {
        if (cl[pos] != ZWJ) push(pieces, np, bare(cl[pos]));
        ++pos;
      }
    }
  }

  // Contextual variant of a vowel sign chosen by the sign class of the glyph
  // it attaches to: ি/ि by the first glyph when it is a half form or the
  // whole cluster, ী/ी by the last glyph. Tried with the first modifier
  // fused (कीं) before the plain sign. Returns 0 when the table has no
  // variant for the class.
  uint32_t classVariant(const uint32_t sign, const uint8_t cls, const uint32_t mod, const bool withReph = false) const {
    if (cls == 0 || maxKey == 0) return 0;
    uint32_t key[6] = {Lipi::KEY_VARIANT_CP};
    int n = 1;
    if (withReph) {
      key[n++] = d.ra;
      key[n++] = d.virama;
    }
    key[n++] = sign;
    if (mod) {
      key[n] = mod;
      key[n + 1] = Lipi::KEY_CLASS_INDEX_CP + cls;
      const uint32_t hit = lookup(key, n + 2);
      if (hit) return hit;
    }
    key[n] = Lipi::KEY_CLASS_INDEX_CP + cls;
    return lookup(key, n + 1);
  }

  // Emits one syllable in visual order, mirroring what an OpenType engine
  // produces for the same font:
  //   pre-base sign, cluster (with its below-base vowel), other below signs,
  //   above sign, reph, candrabindu, post-base sign, anusvara/visarga;
  // with rephAfterPost the reph moves behind the post-base sign and the
  // candrabindu stays with the other modifiers.
  // Every vowel-sign lookup may return a spacing composite (cluster and sign
  // fused), a contextual form of the sign alone (PUA_PRE/PUA_POST), or
  // nothing, in which case the plain sign is drawn. A post-base or above
  // sign, or the reph, may also fuse with the first modifier (कीं, कें,
  // र्कं); the modifier is then consumed.
  void syllable(const Syllable& s) const {
    const uint32_t* rest = s.rest();
    int restLen = s.restLen();
    const uint32_t rephKey[2] = {d.ra, d.virama};
    const uint32_t rephCp = s.rephs ? lookup(rephKey, 2) : 0;
    // With no reph glyph the ra + virama stay in logical order (visible
    // hasanta) and none of the fused forms apply.
    const bool fusable = s.rephs == 0 || rephCp != 0;
    bool rephDone = s.rephs == 0;
    bool restDone = false;
    bool restByFull = false;  // restDone because of the whole-cluster composite
    bool belowDone = s.belowCount == 0;

    // 0. A composite for the whole cluster including its reph (র্ক drawn
    //    as one glyph with exact placement), possibly with the below sign.
    //    A below-sign ligature of the rest (র্দু: দু + reph mark) wins over
    //    the reph composite, as it does in the font's own substitutions.
    uint32_t fullHit = 0;
    uint32_t clusterOut = 0;
    Entry clusterEntry;  // entry of clusterOut / fullHit, for its sign classes
    if (s.rephs > 0 && fusable) {
      if (s.belowCount > 0) {
        fullHit = lookupWith(nullptr, 0, s.cluster, s.n, s.below, 1);
        if (fullHit) {
          belowDone = true;
          clusterEntry = hit_;
        } else {
          clusterOut = lookupWith(nullptr, 0, rest, restLen, s.below, 1);
          if (clusterOut) {
            restDone = true;
            belowDone = true;
            clusterEntry = hit_;
          }
        }
      }
      if (!fullHit && !restDone) {
        fullHit = lookupWith(nullptr, 0, s.cluster, s.n, nullptr, 0);
        if (fullHit) clusterEntry = hit_;
      }
    }

    // A cluster ending in the post-base consonant (ya-phala) at the end of a
    // word may have a final form (composite or the form alone); nothing may
    // follow it.
    const uint32_t postC = d.postBaseConsonant;
    const bool endsInPostC = postC != 0 && restLen >= 3 && rest[restLen - 2] == d.virama && rest[restLen - 1] == postC;
    const bool yaFinal = s.post == 0 && s.modCount == 0 && s.belowCount <= 1 && s.wordEnd && endsInPostC;
    const uint32_t finaKey[1] = {Lipi::KEY_FINA_CP};
    if (yaFinal && !fullHit && !restDone) {
      if (s.belowCount == 0) {
        clusterOut = lookupWith(nullptr, 0, rest, restLen, finaKey, 1);
      } else {
        // The below vowel attaches to the base and the ya-phala still takes
        // its final form (মৃত্যু): the cluster + vowel + FINA composite.
        const uint32_t belowFina[2] = {s.below[0], Lipi::KEY_FINA_CP};
        clusterOut = lookupWith(nullptr, 0, rest, restLen, belowFina, 2);
        if (clusterOut) belowDone = true;
      }
      if (clusterOut) {
        restDone = true;
        clusterEntry = hit_;
      }
    }

    // A trailing ya-phala is a spacing form drawn after the base; below
    // signs and the candrabindu attach to the base, so it is split off and
    // emitted after them (ত্যু, হ্যাঁ).
    uint32_t yaPhala = 0;
    if (!fullHit && !restDone && endsInPostC && !lookupWith(nullptr, 0, rest, restLen, nullptr, 0)) {
      uint32_t form = 0;
      if (yaFinal) form = lookupWith(nullptr, 0, rest + restLen - 2, 2, finaKey, 1);
      if (!form) form = lookupWith(nullptr, 0, rest + restLen - 2, 2, nullptr, 0);
      if (form && isComposite(form)) {
        yaPhala = form;
        restLen -= 2;
      }
    }

    // 1. Pre-base sign. At each level the sign with the first modifier is
    //    tried before the sign alone (हिं: ि fused with the
    //    anusvara).
    uint32_t preOut = s.pre;
    int modFused = -1;      // index of the modifier consumed by a fused form
    bool postInYa = false;  // the ya-phala form also carries the post-base sign
    if (yaPhala && s.modCount > 0) {
      // The ya-phala with its modifier as one form when the font orders them
      // differently from the default emission (Tiro: ঁ after the ya-phala).
      // At the end of a word the font may use the final ya-phala before the
      // modifier (Tiro ব্যঁ, ব্যং), keyed with the FINA marker.
      uint32_t hit = 0;
      if (s.wordEnd && s.post == 0 && s.belowCount == 0) {
        const uint32_t finaKey4[4] = {d.virama, d.postBaseConsonant, s.mods[0], Lipi::KEY_FINA_CP};
        hit = lookup(finaKey4, 4);
      }
      // With a post-base sign the font may order the modifier by it (Noto Sans:
      // ক্যঁ draws ঁ before the ya-phala, ক্যাঁ after it): ya-phala, sign and
      // modifier as one form.
      if (!hit && s.post != 0) {
        const uint32_t key4[4] = {d.virama, d.postBaseConsonant, s.post, s.mods[0]};
        hit = lookup(key4, 4);
        postInYa = hit != 0;
      }
      const uint32_t key[3] = {d.virama, d.postBaseConsonant, s.mods[0]};
      if (!hit) hit = lookup(key, 3);
      if (hit) {
        yaPhala = hit;
        modFused = 0;
      }
    }
    bool preGenericReph = false;   // preOut is the generic ি+reph form
    bool postGenericReph = false;  // postOut is the generic ী+reph form
    bool preGenericMod = false;    // preOut is the generic sign + modifier form
    bool postGenericMod = false;   // postOut is the generic sign + modifier form
    bool preInit = false;          // preOut is the generic word-initial form
    const bool preInitial = s.pre != 0 && s.wordStart && d.in(d.initSigns, s.pre);
    if (s.pre != 0 && !preInitial && d.in(d.preSignsWithForms, s.pre) && fusable) {
      const uint32_t withMod[2] = {s.pre, s.modCount > 0 ? s.mods[0] : 0};
      // The levels: per base with a reph, generic with a reph, per base.
      // Run first with the sign + modifier suffix (a fused form anywhere
      // wins over a plain form), then with the sign alone.
      const auto preLevels = [&](const int signLen) {
        uint32_t hit = 0;
        if (s.rephs == 1) {
          hit = lookupWith(rephKey, 2, rest, restLen, withMod, signLen);  // র্তি as one form
          if (hit) {
            rephDone = true;
            fullHit = 0;
            belowDone = s.belowCount == 0;
          } else if (!fullHit) {
            hit = lookupWith(rephKey, 2, nullptr, 0, withMod, signLen);  // generic ি fused with the reph
            // A key without a base cannot stand for the cluster: a composite
            // here would replace the consonant (builders before 2026-09-19
            // wrote the probe letter's run under this key).
            if (hit && isComposite(hit)) hit = 0;
            if (hit) {
              rephDone = true;
              preGenericReph = true;
            }
          }
        }
        // Forms of ি with the cluster alone (টি, ষ্টি, wide ি); not after a
        // fused ি+reph form, which already stands in for the sign.
        if (!hit && !fullHit && !(s.rephs > 0 && rephDone))
          hit = lookupWith(nullptr, 0, rest, restLen, withMod, signLen);
        if (!hit && signLen == 2) {
          hit = lookup(withMod, 2);  // generic sign + modifier form
          if (hit && isComposite(hit)) hit = 0;  // same rule: no base in the key
          if (hit) preGenericMod = true;
        }
        return hit;
      };
      uint32_t hit = s.modCount > 0 ? preLevels(2) : 0;
      if (hit) {
        modFused = 0;
      } else {
        hit = preLevels(1);
      }
      if (hit) {
        preOut = hit;
        if (isComposite(hit)) restDone = true;
      }
    } else if (preInitial) {
      // The font's own word-initial form for this base first (Noto Sans
      // Bengali ক্মে: ে.long.init; Tiro Bangla খ্রে: a composite), then the
      // generic initial form. A composite stands for the cluster too, so it
      // is not taken when the cluster is already drawn as one glyph.
      const uint32_t initKey[1] = {Lipi::KEY_INIT_CP};
      uint32_t hit = lookupWith(initKey, 1, rest, restLen, &s.pre, 1);
      if (hit && isComposite(hit) && (fullHit || restDone)) hit = 0;
      if (hit) {
        preOut = hit;
        if (isComposite(hit)) restDone = true;
      } else {
        const uint32_t key[2] = {Lipi::KEY_INIT_CP, s.pre};
        const uint32_t generic = lookup(key, 2);
        if (generic) preOut = generic;
        preInit = true;
      }
    }
    if (fullHit) {
      restDone = true;
      rephDone = true;
      restByFull = true;
    }

    // 2. Post-base sign (looked up now, drawn last, because a fused ী+reph
    //    form replaces the reph mark). Suffixes tried at each level: the sign
    //    with the first modifier (कीं), the word-final key, the sign alone.
    uint32_t postOut = postInYa ? 0 : s.post;
    // A modifier other than the candrabindu (anusvara, visarga) is a spacing
    // glyph drawn after the post-base sign, so the sign is not word-final.
    bool spacingModifier = false;
    for (int i = 0; i < s.modCount; ++i) spacingModifier |= s.mods[i] != d.candrabindu;
    if (s.post != 0 && fusable && !postInYa) {
      const uint32_t withMod[2] = {s.post, s.modCount > 0 ? s.mods[0] : 0};
      const uint32_t withFina[2] = {s.post, Lipi::KEY_FINA_CP};
      // A font that stacks the modifier on the reph (Tiro कर्हाँ) has a form for that
      // pair; taking a generic sign + modifier form here would consume the modifier
      // first and leave the reph to be drawn on its own, off the cluster.
      const uint32_t rephMod[3] = {d.ra, d.virama, s.modCount > 0 ? s.mods[0] : 0};
      const bool rephTakesMod = s.rephs == 1 && rephCp != 0 && s.modCount > 0 && lookup(rephMod, 3) != 0;
      const bool tryFina = s.post == d.postSignWithForms && s.wordEnd && !spacingModifier;
      // Looks the sign up at each level: per base with a reph, generic with
      // a reph, per base. The suffix is the sign + modifier on the first
      // pass (a fused form anywhere wins), the word-final key and the sign
      // alone on the second.
      const auto signAt = [&](const uint32_t* prefix, const int prefixLen, const uint32_t* r, const int rLen,
                              const bool modPass) {
        if (modPass) return lookupWith(prefix, prefixLen, r, rLen, withMod, 2);
        uint32_t h = tryFina ? lookupWith(prefix, prefixLen, r, rLen, withFina, 2) : 0;
        if (!h) h = lookupWith(prefix, prefixLen, r, rLen, withFina, 1);
        return h;
      };
      const auto postLevels = [&](const bool modPass) {
        uint32_t hit = 0;
        if (s.rephs == 1 && (!restDone || restByFull)) {
          hit = signAt(rephKey, 2, rest, restLen, modPass);
          if (hit) {
            rephDone = true;
            if (restByFull) {
              fullHit = 0;
              restByFull = false;
              restDone = false;
              belowDone = s.belowCount == 0;
            }
            if (isComposite(hit)) restDone = true;
          } else if (!fullHit) {
            hit = signAt(rephKey, 2, nullptr, 0, modPass);
            if (hit) {
              rephDone = true;
              postGenericReph = true;
            }
          }
        }
        if (!hit && !restDone && !(s.rephs > 0 && rephDone)) {
          hit = signAt(nullptr, 0, rest, restLen, modPass);
          if (hit && isComposite(hit)) restDone = true;
        }
        if (!hit && modPass && s.wordEnd) {
          // The sign's final form before a trailing modifier (Tiro ডাঃ, বাং).
          const uint32_t withModFina[3] = {s.post, s.mods[0], Lipi::KEY_FINA_CP};
          hit = lookup(withModFina, 3);
          if (hit) postGenericMod = true;
        }
        if (!hit && modPass && !rephTakesMod) {
          hit = lookup(withMod, 2);  // generic sign + modifier form (कों)
          if (hit) postGenericMod = true;
        }
        return hit;
      };
      uint32_t hit = (s.modCount > 0 && modFused < 0) ? postLevels(true) : 0;
      if (hit) {
        modFused = 0;
      } else {
        hit = postLevels(false);
      }
      if (hit) postOut = hit;
    }
    // Word-final form of the post-base sign: the font applies it when the
    // next glyph is not a letter or spacing sign of the script. Anusvara and
    // visarga after the sign count as followers; a candrabindu drawn after
    // the ৗ of ৌ does not (it is drawn before া/ী).
    const bool candrabinduFirst = !d.rephAfterPost && (s.post == 0 || d.in(d.candrabinduBeforePost, s.post));
    const bool postIsLast = !spacingModifier && s.wordEnd;
    if (postOut == s.post && s.post != 0 && postIsLast) {
      const uint32_t key[2] = {Lipi::KEY_FINA_CP, s.post};
      const uint32_t hit = lookup(key, 2);
      if (hit) postOut = hit;
    }

    // 3. Cluster with its first below-base sign (রু হু গু ligatures). In a
    //    half-form script the sign belongs to the last consonant, so its
    //    ligature (न्दु: न् + दु) is tried when the whole cluster has none.
    uint32_t tailOut = 0;  // ligature of the last consonant with the sign
    Entry tailEntry;
    int headLen = restLen;
    if (fullHit) clusterOut = fullHit;
    if (!restDone && s.belowCount > 0) {
      clusterOut = lookupWith(nullptr, 0, rest, restLen, s.below, 1);
      if (clusterOut) {
        restDone = true;
        belowDone = true;
        clusterEntry = hit_;
      } else if (halfForms && restLen >= 3 && rest[restLen - 2] == d.virama && d.isConsonant(rest[restLen - 1]) &&
                 !lookup(rest, restLen) && !lookup(rest + restLen - 3, 3)) {
        // Not when the last consonant subjoins to the one before it (rakar)
        // or ends a ligature (द्व्यु: व्य + ु): the sign then follows it.
        const uint32_t subjoined[2] = {d.virama, rest[restLen - 1]};
        const uint32_t subForm = lookup(subjoined, 2);
        if (!subForm || isComposite(subForm)) tailOut = lookupWith(nullptr, 0, rest + restLen - 1, 1, s.below, 1);
        if (tailOut) {
          headLen = restLen - 1;
          belowDone = true;
          tailEntry = hit_;
        }
      }
    }

    // 4. Reph fused with the above sign and/or the first modifier (र्के,
    //    र्कं, र्कें), then an above sign fused with the modifier (कें).
    uint32_t aboveOut = s.above;
    uint32_t rephOut = rephCp;
    if (!rephDone && rephCp && s.rephs == 1) {
      const uint32_t mod0 = (s.modCount > 0 && modFused < 0) ? s.mods[0] : 0;
      uint32_t hit = 0;
      if (s.above && mod0) {
        const uint32_t key[4] = {d.ra, d.virama, s.above, mod0};
        hit = lookup(key, 4);
        if (hit) {
          aboveOut = 0;
          modFused = 0;
        }
      }
      if (!hit && s.above) {
        const uint32_t key[3] = {d.ra, d.virama, s.above};
        hit = lookup(key, 3);
        if (hit) aboveOut = 0;
      }
      if (!hit && mod0) {
        const uint32_t key[3] = {d.ra, d.virama, mod0};
        hit = lookup(key, 3);
        if (hit) modFused = 0;
      }
      if (hit) rephOut = hit;
    }
    if (aboveOut && s.modCount > 0 && modFused < 0) {
      const uint32_t key[2] = {aboveOut, s.mods[0]};
      const uint32_t hit = lookup(key, 2);
      if (hit) {
        aboveOut = hit;
        modFused = 0;
      }
    }
    // A bare base fused with the first modifier (ओं: the font draws आ with
    // a fused e-anusvara).
    if (!restDone && !clusterOut && s.pre == 0 && s.post == 0 && s.above == 0 && s.belowCount == 0 && s.rephs == 0 &&
        s.modCount > 0 && modFused < 0) {
      const uint32_t mod[1] = {s.mods[0]};
      const uint32_t hit = lookupWith(nullptr, 0, rest, restLen, mod, 1);
      if (hit && isComposite(hit)) {
        clusterOut = hit;
        restDone = true;
        modFused = 0;
      }
    }

    // The cluster's glyphs, resolved before anything is emitted so the sign
    // variants can follow their classes.
    Piece pieces[MAX_PIECES];
    int np = 0;
    if (clusterOut) {
      hit_ = clusterEntry;
      push(pieces, np, fromHit(clusterOut));
    } else if (!restDone) {
      greedy(rest, headLen, tailOut ? rest[restLen - 1] : 0, pieces, np);
      if (tailOut) {
        hit_ = tailEntry;
        push(pieces, np, fromHit(tailOut));
      }
    }
    // 5. Sign variants by class, when no per-base form applied: ি/ि from
    //    the first glyph (a half form the sign attaches to, or the whole
    //    cluster as one glyph), ী/ी from the last glyph.
    //    A generic reph-fused form (level 2) gives way to the class variant
    //    of the sign fused with the reph, which is what the per-base forms
    //    folded into.
    if (np > 0 && fusable) {
      const bool rephVariant = s.rephs == 1 && rephCp != 0;
      // Picks the class variant for one sign. `generic` says the current
      // form is a generic one (sign + modifier, or sign + reph) that a
      // variant of the same shape may replace; a plain variant never
      // replaces a fused generic form.
      const auto pick = [&](const uint32_t sign, const uint8_t cls, uint32_t& outSign, const bool genericMod,
                            const bool genericReph) {
        const bool modTaken = modFused == 0 && !genericMod;  // fused by a per-base or reph form: keep it
        const uint32_t mod = (s.modCount > 0 && (modFused < 0 || genericMod)) ? s.mods[0] : 0;
        if (modTaken && outSign != sign) return;
        uint32_t hit = 0;
        bool fused = false;
        if (rephVariant && (genericReph || !rephDone)) {
          const uint32_t plain = classVariant(sign, cls, 0, true);
          const uint32_t withMod = mod ? classVariant(sign, cls, mod, true) : 0;
          if (withMod && withMod != plain) {
            hit = withMod;
            fused = true;
          } else if (plain && !genericMod) {
            hit = plain;
          }
          if (hit) rephDone = true;
        }
        // A reph carried by the whole-cluster composite (র্থ as one glyph) leaves the
        // sign on its own: the class of the letter under the reph applies (অর্থে).
        const bool rephInCluster = restByFull && !genericReph;
        if (!hit && (!(s.rephs > 0 && (rephDone || genericReph)) || rephInCluster)) {
          const uint32_t plain = classVariant(sign, cls, 0);
          const uint32_t withMod = mod ? classVariant(sign, cls, mod) : 0;
          if (withMod && withMod != plain) {
            hit = withMod;
            fused = true;
          } else if (plain) {
            // A base with its own class takes the class variant; a generic
            // sign+modifier form (shaped on the probe letter) then does not
            // apply to it and the modifier is drawn on its own (Noto: a wide
            // ি is never fused with the candrabindu).
            hit = plain;
          }
        }
        if (!hit) return;
        outSign = hit;
        modFused = fused ? 0 : (genericMod ? -1 : modFused);
      };
      if (s.pre != 0 && d.in(d.preSignsWithForms, s.pre)) {
        uint8_t cls = (np == 1 || pieces[0].half) ? pieces[0].preClass : 0;
        // Before a half form the font may size the sign by the glyph after it
        // (Noto Serif Devanagari षि + व): the pair's class from the table's rows.
        if (pieces[0].half && pieces[0].row && np >= 2 && s.pre == d.preSignWithForms) {
          const uint8_t col = pieces[1].half ? HALF_PAIR_FOLLOWS + 1 : pieces[1].preClass + 1;
          const uint32_t key[5] = {Lipi::KEY_VARIANT_CP, ZWJ, s.pre, static_cast<uint32_t>(d.blockBase + pieces[0].row),
                                   Lipi::KEY_CLASS_INDEX_CP + col};
          const Entry e = Lipi::lookupEntry(table, d, key, 5);
          if (e.found) cls = e.preClass;
        }
        if (preInit) {
          // Word-initial variant of the class (Noto Sans Bengali খে: ে.long.init),
          // keyed {VARIANT, INIT, sign, class}; else the generic initial form stays.
          if (cls != 0) {
            const uint32_t key[4] = {Lipi::KEY_VARIANT_CP, Lipi::KEY_INIT_CP, s.pre, Lipi::KEY_CLASS_INDEX_CP + cls};
            const uint32_t hit = lookup(key, 4);
            if (hit) preOut = hit;
          }
        } else if (preOut == s.pre || preGenericReph || preGenericMod) {
          pick(s.pre, cls, preOut, preGenericMod, preGenericReph);
        }
      }
      if (s.post != 0 && s.post == d.postSignWithForms && (postOut == s.post || postGenericReph || postGenericMod)) {
        pick(s.post, pieces[np - 1].postClass, postOut, postGenericMod, postGenericReph);
      }
    }

    // Emit.
    // A modifier drawn differently after the pre-base sign (Noto: ঁ.alt after a
    // wide ি) has its variant keyed modifier + sign; a fused sign+modifier
    // form (modFused == 0) has already consumed it.
    uint32_t modVariant = 0;
    if (s.pre == d.preSignWithForms && s.modCount > 0 && modFused != 0) {
      const uint32_t key[2] = {s.mods[0], s.pre};
      modVariant = lookup(key, 2);
    }
    const auto modGlyph = [&](const int i) { return (i == 0 && modVariant) ? modVariant : s.mods[i]; };

    if (preOut) put(preOut);
    if (!rephDone && !rephCp) {
      for (int i = 0; i < s.rephs; ++i) {
        put(d.ra);
        put(d.virama);
      }
      rephDone = true;
    }
    for (int i = 0; i < np; ++i) put(pieces[i].cp);
    if (!belowDone) put(s.below[0]);
    if (s.belowCount > 1) put(s.below[1]);
    if (aboveOut && !d.rephAfterPost) put(aboveOut);
    if (!rephDone && !d.rephAfterPost) {
      for (int i = 0; i < s.rephs; ++i) put(rephOut);
      rephDone = true;
    }
    // The candrabindu sits on the consonant, before a post-base া/ী; after
    // the ৗ of ৌ it stays in logical order.
    if (candrabinduFirst) {
      for (int i = 0; i < s.modCount; ++i) {
        if (s.mods[i] == d.candrabindu && i != modFused) put(modGlyph(i));
      }
    }
    if (yaPhala) put(yaPhala);
    if (postOut) put(postOut);
    // Order after the post-base sign when rephAfterPost is set: above sign, then the reph.
    if (aboveOut && d.rephAfterPost) put(aboveOut);
    if (!rephDone) {
      for (int i = 0; i < s.rephs; ++i) put(rephOut);
    }
    for (int i = 0; i < s.modCount; ++i) {
      if (i == modFused) continue;
      if (s.mods[i] != d.candrabindu || !candrabinduFirst) put(modGlyph(i));
    }
  }
};

// Collects one syllable starting at the base under the cursor:
//   C (nukta)? (virama (ZWJ|ZWNJ)? C (nukta)?)*  signs and modifiers
void collectSyllable(const ScriptDesc& d, Cursor& in, Syllable& s, const bool dandaEndsWord) {
  uint32_t* cl = s.cluster;
  int& n = s.n;
  cl[n++] = in.cur;
  in.advance();
  // Independent vowels take a ya-phala too (অ্যা), so every base may
  // continue with virama + consonant.
  while (true) {
    if (in.cur == d.nukta) {
      const uint32_t precomposed = d.precomposedNukta(cl[n - 1]);
      if (precomposed) {
        cl[n - 1] = precomposed;
      } else if (n < MAX_CLUSTER) {
        cl[n++] = d.nukta;
      }
      in.advance();
    }
    // A ZWJ before the virama keeps the consonant whole: no reph and no half
    // form (র‍্য is ra + ya-phala; fonts differ for र‍्य). The joiner stays in
    // the cluster so the table can key the font's own form.
    if (in.cur == ZWJ && in.peek() == d.virama && n <= MAX_CLUSTER - 4) {
      cl[n++] = ZWJ;
      in.advance();
    }
    if (in.cur != d.virama || n > MAX_CLUSTER - 3) break;
    const uint32_t after = in.peek();
    if (after == ZWNJ) {
      // Explicit hasanta: the cluster ends here with a visible virama.
      cl[n++] = d.virama;
      in.advance();
      in.advance();
      break;
    }
    if (after == ZWJ) {
      cl[n++] = d.virama;
      cl[n++] = ZWJ;
      in.advance();
      in.advance();
      if (d.isConsonant(in.cur)) {
        cl[n++] = in.cur;
        in.advance();
        continue;
      }
      break;
    }
    if (d.isConsonant(after)) {
      cl[n++] = d.virama;
      cl[n++] = after;
      in.advance();
      in.advance();
      continue;
    }
    // Trailing hasanta at the end of a word.
    cl[n++] = d.virama;
    in.advance();
    break;
  }

  // Reph: ra + virama at the start of a cluster with another consonant
  // after it is drawn as a mark over that consonant, so it moves behind
  // the rest of the cluster. A ZWJ before or after the virama stops it; the
  // forms the font draws for those sequences come from the table (greedy()).
  if (d.rephMode == RephMode::PreBase) {
    while (n - s.start >= 3 && d.isRa(cl[s.start]) && cl[s.start + 1] == d.virama && d.isConsonant(cl[s.start + 2])) {
      s.start += 2;
      ++s.rephs;
    }
  }

  // Vowel signs and modifiers, in any order the source has them. The
  // two-part signs ো/ৌ split into ে before the cluster and া/ৗ after it.
  while (in.cur) {
    const uint32_t cp = in.cur;
    const Lipi::SplitVowel* split = d.inBlock(cp) ? d.splitVowel(cp) : nullptr;
    if (d.isPreBaseVowel(cp) && !s.pre) {
      s.pre = cp;
    } else if (split && !s.pre && !s.post) {
      s.pre = split->pre;
      s.post = split->post;
    } else if (d.isPostBaseVowel(cp) && !s.post) {
      s.post = cp;
    } else if (d.isAboveVowel(cp) && !s.above) {
      s.above = cp;
    } else if (d.isBelowVowel(cp) && s.belowCount < MAX_BELOW) {
      s.below[s.belowCount++] = cp;
    } else if (d.isModifier(cp) && s.modCount < MAX_MODIFIERS) {
      s.mods[s.modCount++] = cp;
    } else {
      break;
    }
    in.advance();
  }
  // Word-final forms apply when nothing from the script follows. Whether a
  // danda counts as part of the script depends on the font (the table says).
  s.wordEnd = in.cur == 0 || (isIndicDanda(in.cur) ? dandaEndsWord : !d.inBlock(in.cur));
}

}  // namespace

namespace Lipi {

bool mayNeedShaping(const char* utf8) {
  if (!utf8) return false;
  for (const auto* p = reinterpret_cast<const unsigned char*>(utf8); *p; ++p) {
    if (p[0] == 0xE0 && p[1] >= 0x80 && ((kShapedContinuationBytes >> (p[1] - 0x80)) & 1u)) return true;
  }
  return false;
}

// The mark queries of LipiMarks.h, defined here so only this file carries the
// provider descriptors.
bool isMark(const uint32_t cp) {
  if (cp >= PUA_BELOW_FIRST && cp <= PUA_BELOW_RIGHT_LAST) return true;  // the four PUA mark classes
  if (!inIndicBlocks(cp)) return false;
  const ScriptDesc* d = scriptFor(cp);
  return d != nullptr && d->in(d->nonSpacing, cp);
}

bool attachesBelow(const uint32_t cp) {
  if ((cp >= PUA_BELOW_FIRST && cp <= PUA_BELOW_LAST) || (cp >= PUA_BELOW_RIGHT_FIRST && cp <= PUA_BELOW_RIGHT_LAST)) {
    return true;
  }
  if (!inIndicBlocks(cp)) return false;
  const ScriptDesc* d = scriptFor(cp);
  return d != nullptr && d->in(d->attachBelow, cp);
}

MarkAnchor anchorClass(const uint32_t cp) {
  if ((cp >= PUA_BELOW_FIRST && cp <= PUA_BELOW_LAST) ||
      (cp >= PUA_ABOVE_CENTER_FIRST && cp <= PUA_ABOVE_CENTER_LAST)) {
    return MarkAnchor::Center;
  }
  if ((cp >= PUA_ABOVE_FIRST && cp <= PUA_ABOVE_LAST) || (cp >= PUA_BELOW_RIGHT_FIRST && cp <= PUA_BELOW_RIGHT_LAST)) {
    return MarkAnchor::Right;
  }
  if (!inIndicBlocks(cp)) return MarkAnchor::None;
  const ScriptDesc* d = scriptFor(cp);
  if (d == nullptr) return MarkAnchor::None;
  if (d->in(d->anchorCenter, cp)) return MarkAnchor::Center;
  if (d->in(d->anchorRight, cp)) return MarkAnchor::Right;
  if (d->in(d->anchorPen, cp)) return MarkAnchor::Pen;
  return MarkAnchor::None;
}

namespace {

inline uint16_t readU16(const uint8_t* p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }

// Directory slot of a key length: entry count and bucket count.
inline void directoryAt(const uint8_t* directory, const uint32_t len, uint32_t& count, uint32_t& buckets) {
  const uint8_t* slot = directory + (len - Lipi::PACKED_MIN_KEY_LEN) * 3;
  count = readU16(slot);
  buckets = slot[2];
}

// Bytes of one length's section: its bucket index plus its entries.
inline uint32_t sectionBytes(const uint32_t len, const uint32_t count, const uint32_t buckets) {
  return buckets * 3 + count * (len + 2);
}

}  // namespace

uint32_t packedTableBytes(const uint8_t* directory, const uint8_t kind, uint32_t* count) {
  const uint32_t keyLen = maxKeyLenForKind(kind);
  if (!directory || keyLen == 0) return 0;
  uint32_t bytes = PACKED_DIRECTORY_BYTES;
  uint32_t total = 0;
  for (uint32_t len = PACKED_MIN_KEY_LEN; len <= PACKED_MAX_KEY_LEN; ++len) {
    uint32_t n = 0;
    uint32_t b = 0;
    directoryAt(directory, len, n, b);
    if ((len > keyLen && (n || b)) || (n == 0) != (b == 0) || b > n) return 0;
    bytes += sectionBytes(len, n, b);
    total += n;
  }
  if (count) *count = total;
  return bytes;
}

Entry lookupEntry(const ClusterTable& table, const ScriptDesc& script, const uint32_t* cps, const uint32_t len) {
  Entry e;
  const uint32_t keyLen = maxKeyLenForKind(table.kind);
  if (!table.entries || table.count == 0 || table.kind != script.shapeKind || len < PACKED_MIN_KEY_LEN || len > keyLen)
    return e;
  uint8_t probe[MAX_KEY_CAP] = {0};
  for (uint32_t i = 0; i < len; ++i) {
    const uint8_t b = keyByte(script, cps[i]);
    if (b == 0) return e;
    probe[i] = b;
  }

  // The section of this key length: skip the shorter ones.
  const uint8_t* directory = table.entries;
  uint32_t offset = PACKED_DIRECTORY_BYTES;
  uint32_t count = 0;
  uint32_t buckets = 0;
  for (uint32_t l = PACKED_MIN_KEY_LEN; l < len; ++l) {
    directoryAt(directory, l, count, buckets);
    offset += sectionBytes(l, count, buckets);
  }
  directoryAt(directory, len, count, buckets);
  if (count == 0) return e;
  const uint8_t* index = table.entries + offset;
  const uint8_t* entries = index + buckets * 3;

  // The bucket of the first key byte (the index is short: a scan).
  uint32_t first = 0;
  uint32_t inBucket = 0;
  for (uint32_t i = 0; i < buckets; ++i) {
    const uint8_t* slot = index + i * 3;
    const uint32_t n = readU16(slot + 1);
    if (slot[0] == probe[0]) {
      inBucket = n;
      break;
    }
    if (slot[0] > probe[0]) return e;
    first += n;
  }
  if (inBucket == 0) return e;

  // Binary search on the remaining key bytes. Keys are prefix-free (0x00
  // never occurs inside one), so the bytes alone identify the entry.
  const uint32_t rowSize = len + 2;
  const uint32_t rest = len - 1;
  uint32_t lo = 0;
  uint32_t hi = inBucket;
  while (lo < hi) {
    const uint32_t mid = lo + (hi - lo) / 2;
    const uint8_t* row = entries + (first + mid) * rowSize;
    const int cmp = memcmp(row, probe + 1, rest);
    if (cmp < 0) {
      lo = mid + 1;
    } else if (cmp > 0) {
      hi = mid;
    } else {
      const uint8_t meta = row[rest];
      const uint16_t value = readU16(row + rest + 1);
      if ((meta & 0x07) != len) return e;
      e.found = true;
      e.continues = (meta & 0x08) != 0;
      e.preClass = meta >> 4;
      e.postClass = value >> 13;
      const uint16_t off = value & VALUE_NO_GLYPH;
      e.cp = off == VALUE_NO_GLYPH ? 0 : PUA_BASE_FIRST + off;
      return e;
    }
  }
  return e;
}

uint32_t lookupCluster(const ClusterTable& table, const ScriptDesc& script, const uint32_t* cps, const uint32_t len) {
  return lookupEntry(table, script, cps, len).cp;
}

namespace {
const ScriptDesc* tableScript(const ClusterTable& table) {
  const ScriptDesc* script = nullptr;
  for (const ScriptDesc* d : kScriptByBlock) {
    if (d && d->shapeKind == table.kind) script = d;
  }
  return script;
}
}  // namespace

uint8_t tableFormat(const ClusterTable& table) {
  const ScriptDesc* script = tableScript(table);
  if (!script) return 0;
  const uint32_t key[2] = {KEY_FORMAT_CP, KEY_FORMAT_CP};
  const Entry e = lookupEntry(table, *script, key, 2);
  return e.found && e.cp ? static_cast<uint8_t>(e.cp - PUA_BASE_FIRST) : 0;
}

uint8_t dandaSpaceShare(const ClusterTable& table, const uint32_t cp) {
  const uint8_t index = indicDandaIndex(cp);
  if (index == 0) return 0;
  const ScriptDesc* script = tableScript(table);
  if (!script) return 0;
  const uint32_t key[3] = {KEY_FORMAT_CP, KEY_INIT_CP, KEY_CLASS_INDEX_CP + index};
  const Entry e = lookupEntry(table, *script, key, 3);
  return e.found && e.cp > PUA_BASE_FIRST && e.cp <= PUA_BASE_FIRST + 0xFF ? static_cast<uint8_t>(e.cp - PUA_BASE_FIRST)
                                                                           : 0;
}

bool shape(const char* utf8, const ClusterTable& table, std::string& out) {
  if (!utf8 || !*utf8) return false;
  // Text that already carries one of this engine's Private Use forms was
  // shaped before and is left alone: shaping it again would move a pre-base
  // sign a second time (জোরে came back with two pre forms and no ে). A caller
  // that measures and draws one string may hand the shaped form back.
  for (const auto* p = reinterpret_cast<const unsigned char*>(utf8); *p;) {
    const uint32_t cp = utf8Next(&p);
    if (cp >= PUA_BASE_FIRST && cp <= PUA_PRECONS_LAST) return false;
  }
  out.clear();
  out.reserve(strlen(utf8) + 16);
  Cursor in(utf8);
  // Block of the previous codepoint when it belongs to a shaped script;
  // a syllable starts a word when the block changes. The dandas are shared
  // punctuation and end a word.
  ScriptBlock prevBlock = ScriptBlock::None;
  // The table's danda and half-form flags, looked up once for the script
  // they belong to.
  const ScriptDesc* flagScript = nullptr;
  bool dandaEndsWord = false;
  bool tableHalfForms = false;

  while (in.cur) {
    const ScriptDesc* d = scriptFor(in.cur);
    if (!d || !d->isSyllableBase(in.cur)) {
      // Joiners outside a cluster have nothing to join and no glyph.
      if (in.cur != ZWJ && in.cur != ZWNJ) put(in.cur, out);
      // Digits are not letters: a sign after them takes its word-initial form (২৩শে).
      prevBlock = (d && !isIndicDanda(in.cur) && !d->isDigit(in.cur)) ? d->block : ScriptBlock::None;
      in.advance();
      continue;
    }

    Syllable s;
    s.wordStart = prevBlock != d->block;
    prevBlock = d->block;
    if (d != flagScript) {
      flagScript = d;
      const uint32_t dandaKey[2] = {KEY_FORMAT_CP, KEY_FINA_CP};
      dandaEndsWord = lookupEntry(table, *d, dandaKey, 2).found;
      const uint32_t halfKey[2] = {KEY_FORMAT_CP, ZWJ};
      tableHalfForms = lookupEntry(table, *d, halfKey, 2).found;
    }
    collectSyllable(*d, in, s, dandaEndsWord);
    const Emitter em(*d, table, out, tableHalfForms);
    em.syllable(s);
  }
  return true;
}

}  // namespace Lipi
