#pragma once

#include <cstdint>

#include "Script.h"

/// The per-codepoint mark queries a renderer asks the engine, declared without
/// the provider descriptors so a header every translation unit includes (a
/// UTF-8 helper, the font data layout) stays light: the descriptors come in
/// once, through Lipi.cpp. Marks of scripts this build does not shape answer
/// false / None.
namespace Lipi {

/// Zero-advance overlay on the preceding base glyph: a script's non-spacing
/// marks (candrabindu, nukta, below-base vowel signs, virama, ...) and the
/// Private Use ranges the font builder allocates for shaped cluster marks
/// (reph, subjoined consonants).
bool isMark(uint32_t cp);

/// Marks that hang from the base's below anchor; every other mark takes the
/// above anchor.
bool attachesBelow(uint32_t cp);

/// Anchor class of a mark: the PUA classes by range (F000 below centre, F100
/// above right, F200 above centre, F300 below right), a script's marks from
/// its descriptor, None for anything else.
MarkAnchor anchorClass(uint32_t cp);

}  // namespace Lipi
