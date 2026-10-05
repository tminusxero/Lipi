#pragma once

#include "../../engine/Script.h"

/// Bengali provider: the descriptor the engine registry compiles in for the
/// Bengali block (Bangla, Assamese). Builder mirror: spec.py beside this file.
namespace Lipi {

/// Bengali (Bangla) and Assamese: U+0980..U+09FF.
constexpr ScriptDesc makeBengali() {
  ScriptDesc d{};
  d.shapeKind = SHAPE_KIND_BENGALI;
  d.block = ScriptBlock::Bengali;
  d.blockBase = 0x0980;
  d.rephMode = RephMode::PreBase;
  d.joinStyle = JoinStyle::Subjoined;
  d.virama = 0x09CD;
  d.nukta = 0x09BC;
  d.ra = 0x09B0;
  d.candrabindu = 0x0981;
  d.preSignWithForms = 0x09BF;   // ি
  d.postSignWithForms = 0x09C0;  // ী
  d.postBaseConsonant = 0x09AF;  // য (ya-phala)
  // ক..ন, প..র, ল, শ..হ, ড় ঢ় য়, ৰ ৱ
  d.consonants = blockRange(0x15, 0x28) | blockRange(0x2A, 0x30) | blockBit(0x32) | blockRange(0x36, 0x39) |
                 blockBit(0x5C) | blockBit(0x5D) | blockBit(0x5F) | blockBit(0x70) | blockBit(0x71);
  // অ..ঌ, এ ঐ, ও ঔ, ৠ ৡ, ৼ
  d.independentVowels = blockRange(0x05, 0x0C) | blockBit(0x0F) | blockBit(0x10) | blockBit(0x13) | blockBit(0x14) |
                        blockBit(0x60) | blockBit(0x61) | blockBit(0x7C);
  d.extraBases = blockBit(0x4E) | blockBit(0x3D);                      // খণ্ড ত, avagraha
  d.preBase = blockBit(0x3F) | blockBit(0x47) | blockBit(0x48);        // ি ে ৈ
  d.postBase = blockBit(0x3E) | blockBit(0x40) | blockBit(0x57);       // া ী ৗ
  d.below = blockRange(0x41, 0x44) | blockBit(0x62) | blockBit(0x63);  // ু ূ ৃ ৄ ৢ ৣ
  d.above = BlockMask{};
  d.modifiers = blockBit(0x01) | blockBit(0x02) | blockBit(0x03) | blockBit(0x7E);  // ঁ ং ঃ ৾
  d.nonSpacing = blockBit(0x01) | blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x4D) | blockBit(0x62) |
                 blockBit(0x63) | blockBit(0x7E);
  d.raFolds = blockBit(0x70);                                 // ৰ shapes like র inside a conjunct
  d.initSigns = blockBit(0x47) | blockBit(0x48);              // ে ৈ
  // ি always; ে ৈ have per-base forms in some fonts (Noto Sans Bengali ে.long on খ গ ণ থ প শ).
  d.preSignsWithForms = blockBit(0x3F) | blockBit(0x47) | blockBit(0x48);
  d.candrabinduBeforePost = blockBit(0x3E) | blockBit(0x40);  // া ী (after the ৗ of ৌ it stays in logical order)
  // Mark placement: below signs, nukta and the hasanta hang from the below
  // anchor; below signs, nukta, candrabindu and the sandhi mark sit centred;
  // a visible hasanta hangs at the pen after the base.
  d.attachBelow = blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x4D) | blockBit(0x62) | blockBit(0x63);
  d.anchorCenter =
      blockBit(0x01) | blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x62) | blockBit(0x63) | blockBit(0x7E);
  d.anchorRight = BlockMask{};
  d.anchorPen = blockBit(0x4D);
  d.splitVowels[0] = {0x09CB, 0x09C7, 0x09BE};  // ো = ে + া
  d.splitVowels[1] = {0x09CC, 0x09C7, 0x09D7};  // ৌ = ে + ৗ
  d.splitVowelCount = 2;
  d.nuktaFolds[0] = {0x09A1, 0x09DC};  // ড় rra
  d.nuktaFolds[1] = {0x09A2, 0x09DD};  // ঢ় rha
  d.nuktaFolds[2] = {0x09AF, 0x09DF};  // য় yya
  d.nuktaFoldCount = 3;
  return d;
}

inline constexpr ScriptDesc kBengali = makeBengali();

}  // namespace Lipi
