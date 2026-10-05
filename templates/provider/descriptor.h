#pragma once

#include "../../engine/Script.h"

/// __Script__ provider: the descriptor the engine registry compiles in for the
/// __Script__ block. Builder mirror: spec.py beside this file. Every field is
/// data; see docs/provider-guide.md for what each one means.
namespace Lipi {

constexpr ScriptDesc make__Script__() {
  ScriptDesc d{};
  d.shapeKind = __KIND__;                   // reserved kind number, docs/table-format.md
  d.block = ScriptBlock::__Script__;        // ScriptBlock.h enum value
  d.blockBase = __BLOCK__;                  // first codepoint of the block
  d.rephMode = RephMode::PreBase;           // None / PreBase (PostBase reserved, not implemented)
  d.joinStyle = JoinStyle::Subjoined;       // Subjoined / HalfForm
  d.rephAfterPost = false;                  // reph drawn after the post-base sign (Devanagari)
  // Named letters, as codepoints (0 = the script has none).
  d.virama = __BLOCK__ + 0x4D;
  d.nukta = __BLOCK__ + 0x3C;
  d.ra = __BLOCK__ + 0x30;
  d.candrabindu = __BLOCK__ + 0x01;
  d.preSignWithForms = __BLOCK__ + 0x3F;   // the pre-base sign with width variants (ি ि), or 0
  d.postSignWithForms = __BLOCK__ + 0x40;  // the post-base sign with width variants (ী ी), or 0
  d.postBaseConsonant = 0;                 // consonant whose subjoined form is a spacing glyph (Bengali য), or 0
  // Letter classes as block-offset sets (offset = cp - blockBase). Fill from
  // the Unicode chart of the block.
  d.consonants = blockRange(0x15, 0x39);
  d.independentVowels = blockRange(0x05, 0x14);
  d.extraBases = BlockMask{};                                     // other letters signs attach to
  d.preBase = blockBit(0x3F);                                     // vowel signs drawn before the cluster
  d.postBase = blockBit(0x3E) | blockBit(0x40);                   // drawn after it
  d.below = blockRange(0x41, 0x44);                               // drawn under the base
  d.above = BlockMask{};                                          // drawn over the base
  d.modifiers = blockRange(0x01, 0x03);                           // candrabindu, anusvara, visarga
  d.nonSpacing = blockBit(0x01) | blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x4D);
  d.raFolds = BlockMask{};                                        // letters keyed as ra inside conjuncts
  d.initSigns = BlockMask{};                                      // pre-base signs with a word-initial form
  d.preSignsWithForms = blockBit(0x3F);                           // pre-base signs with per-base forms / classes
  d.candrabinduBeforePost = BlockMask{};                          // post signs the candrabindu precedes
  // Mark placement (subsets of nonSpacing): below anchor, and the anchor class.
  d.attachBelow = blockBit(0x3C) | blockRange(0x41, 0x44) | blockBit(0x4D);
  d.anchorCenter = blockBit(0x01) | blockBit(0x3C) | blockRange(0x41, 0x44);
  d.anchorRight = BlockMask{};
  d.anchorPen = blockBit(0x4D);
  // Two-part vowel signs: sign, part before the cluster, part after it.
  d.splitVowelCount = 0;
  // Consonant + nukta pairs with a precomposed letter.
  d.nuktaFoldCount = 0;
  return d;
}

inline constexpr ScriptDesc k__Script__ = make__Script__();

}  // namespace Lipi
