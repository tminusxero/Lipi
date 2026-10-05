#pragma once

#include "Script.h"

// Providers compiled into this build. Without LIPI_PROVIDERS_SELECTED every
// provider in the repository is included; a host that wants fewer defines
// LIPI_PROVIDERS_SELECTED and one LIPI_WITH_<SCRIPT> per provider it keeps.
#ifndef LIPI_PROVIDERS_SELECTED
#define LIPI_WITH_BENGALI 1
#define LIPI_WITH_DEVANAGARI 1
#endif
#if LIPI_WITH_BENGALI
#include "../providers/bengali/descriptor.h"
#endif
#if LIPI_WITH_DEVANAGARI
#include "../providers/devanagari/descriptor.h"
#endif

/// The scripts this build shapes: the descriptor per block, which pulls every
/// provider's tables into the including translation unit. Renderers that only
/// ask whether a codepoint is a mark and where it sits include LipiMarks.h
/// instead. Adding a script means adding its descriptor include above and its
/// entry in kScriptByBlock; nothing else in the engine changes.
namespace Lipi {

/// Descriptor per ScriptBlock; nullptr for scripts the engine does not
/// handle (their text passes through untouched).
inline constexpr const ScriptDesc* kScriptByBlock[static_cast<uint8_t>(ScriptBlock::COUNT)] = {
    nullptr,  // None
#if LIPI_WITH_DEVANAGARI
    &kDevanagari,
#else
    nullptr,
#endif
#if LIPI_WITH_BENGALI
    &kBengali,
#else
    nullptr,
#endif
    nullptr,  // Gurmukhi
    nullptr,  // Gujarati
    nullptr,  // Odia
    nullptr,  // Tamil
    nullptr,  // Telugu
    nullptr,  // Kannada
    nullptr,  // Malayalam
    nullptr,  // Sinhala
    nullptr,  // Han
    nullptr,  // Kana
    nullptr,  // Hangul
};

inline const ScriptDesc* scriptFor(const uint32_t cp) {
  return kScriptByBlock[static_cast<uint8_t>(scriptBlockOf(cp))];
}

/// True when `cp` is inside one of the Indic blocks the block map covers.
inline constexpr bool inIndicBlocks(const uint32_t cp) {
  return cp >= kIndicBlockBase && cp < kIndicBlockBase + kIndicBlockCount * kIndicBlockSize;
}

}  // namespace Lipi
