#pragma once

#include "../../engine/Script.h"

/// Devanagari provider: the descriptor the engine registry compiles in for the
/// Devanagari block (Hindi, Marathi, Nepali, Sanskrit). Builder mirror:
/// spec.py beside this file.
namespace Lipi {

/// Devanagari (Hindi, Marathi, Nepali, Sanskrit): U+0900..U+097F. Conjuncts
/// are half forms before a full consonant, the reph follows the post-base
/// sign, and there are no two-part vowel signs (ो ौ are single glyphs whose
/// fused forms with the reph and anusvara the table provides).
constexpr ScriptDesc makeDevanagari() {
  ScriptDesc d{};
  d.shapeKind = SHAPE_KIND_DEVANAGARI;
  d.block = ScriptBlock::Devanagari;
  d.blockBase = 0x0900;
  d.rephMode = RephMode::PreBase;
  d.joinStyle = JoinStyle::HalfForm;
  d.rephAfterPost = true;
  d.virama = 0x094D;
  d.nukta = 0x093C;
  d.ra = 0x0930;
  d.candrabindu = 0x0901;
  d.preSignWithForms = 0x093F;   // ि
  d.postSignWithForms = 0x0940;  // ी
  d.postBaseConsonant = 0;
  // क..ह, क़..य़, ॹ..ॿ
  d.consonants = blockRange(0x15, 0x39) | blockRange(0x58, 0x5F) | blockRange(0x79, 0x7F);
  // ऄ..औ, ॠ ॡ, ॲ..ॷ
  d.independentVowels = blockRange(0x04, 0x14) | blockBit(0x60) | blockBit(0x61) | blockRange(0x72, 0x77);
  d.extraBases = blockBit(0x3D) | blockBit(0x50);  // avagraha, om
  d.preBase = blockBit(0x3F) | blockBit(0x4E);     // ि ॎ
  d.postBase =
      blockBit(0x3B) | blockBit(0x3E) | blockBit(0x40) | blockRange(0x49, 0x4C) | blockBit(0x4F);  // ऻ ा ी ॉ ॊ ो ौ ॏ
  d.below = blockRange(0x41, 0x44) | blockBit(0x56) | blockBit(0x57) | blockBit(0x62) | blockBit(0x63);  // ु ू ृ ॄ ॖ ॗ ॢ ॣ
  d.above = blockBit(0x3A) | blockRange(0x45, 0x48) | blockBit(0x55);                                    // ऺ ॅ ॆ े ै ॕ
  d.modifiers = blockRange(0x00, 0x03) | blockRange(0x51, 0x54);  // ऀ ँ ं ः, vedic tone marks
  d.nonSpacing = blockRange(0x00, 0x02) | blockBit(0x3A) | blockBit(0x3C) | blockRange(0x41, 0x48) | blockBit(0x4D) |
                 blockRange(0x51, 0x57) | blockBit(0x62) | blockBit(0x63);
  d.raFolds = BlockMask{};
  d.initSigns = BlockMask{};
  d.preSignsWithForms = blockBit(0x3F);  // ि only
  d.candrabinduBeforePost = BlockMask{};
  d.splitVowelCount = 0;
  // Mark placement: below signs, nukta, anudatta and the halant hang from the
  // below anchor; below signs, nukta, anudatta, the candrabindus and the
  // udatta/svarita marks sit centred; the anusvara and the above vowel signs
  // attach at the stem on the right; a visible halant hangs at the pen.
  d.attachBelow = blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x4D) | blockBit(0x52) | blockBit(0x56) |
                  blockBit(0x57) | blockBit(0x62) | blockBit(0x63);
  d.anchorCenter = blockBit(0x00) | blockBit(0x01) | blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x51) |
                   blockBit(0x52) | blockBit(0x53) | blockBit(0x54) | blockBit(0x56) | blockBit(0x57) | blockBit(0x62) |
                   blockBit(0x63);
  d.anchorRight = blockBit(0x02) | blockBit(0x3A) | blockRange(0x45, 0x48) | blockBit(0x55);
  d.anchorPen = blockBit(0x4D);
  d.nuktaFolds[0] = {0x0915, 0x0958};  // क़ qa
  d.nuktaFolds[1] = {0x0916, 0x0959};  // ख़ khha
  d.nuktaFolds[2] = {0x0917, 0x095A};  // ग़ ghha
  d.nuktaFolds[3] = {0x091C, 0x095B};  // ज़ za
  d.nuktaFolds[4] = {0x0921, 0x095C};  // ड़ dddha
  d.nuktaFolds[5] = {0x0922, 0x095D};  // ढ़ rha
  d.nuktaFolds[6] = {0x092B, 0x095E};  // फ़ fa
  d.nuktaFolds[7] = {0x092F, 0x095F};  // य़ yya
  d.nuktaFoldCount = 8;
  return d;
}

inline constexpr ScriptDesc kDevanagari = makeDevanagari();

}  // namespace Lipi
