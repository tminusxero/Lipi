#pragma once

#include <cstdint>

// Unicode script blocks a reader's built-in UI fonts typically cannot draw.
// A host routes strings that contain one to an SD-card font that covers it
// (CrossIndix: GfxRenderer::resolveTextFontId, SdCardFontSystem). The Indic entries are
// the ten consecutive 128-codepoint blocks starting at U+0900; the CJK entries
// group the Han, kana and Hangul ranges the way a CJK font file covers them.
enum class ScriptBlock : uint8_t {
  None = 0,
  Devanagari,
  Bengali,
  Gurmukhi,
  Gujarati,
  Odia,
  Tamil,
  Telugu,
  Kannada,
  Malayalam,
  Sinhala,
  Han,
  Kana,
  Hangul,
  COUNT
};

inline constexpr uint32_t kIndicBlockBase = 0x0900;
inline constexpr uint32_t kIndicBlockSize = 0x80;
inline constexpr uint8_t kIndicBlockCount = 10;  // Devanagari .. Sinhala

// One representative letter per block, used to test whether a font file covers
// the script. KA for every Indic script; a common ideograph, hiragana A and
// the first Hangul syllable for CJK.
inline constexpr uint32_t kScriptProbe[static_cast<uint8_t>(ScriptBlock::COUNT)] = {
    0,       // None
    0x0915,  // Devanagari KA
    0x0995,  // Bengali KA
    0x0A15,  // Gurmukhi KA
    0x0A95,  // Gujarati KA
    0x0B15,  // Odia KA
    0x0B95,  // Tamil KA
    0x0C15,  // Telugu KA
    0x0C95,  // Kannada KA
    0x0D15,  // Malayalam KA
    0x0D9A,  // Sinhala KA
    0x4E00,  // Han
    0x3042,  // Hiragana A
    0xAC00,  // Hangul GA
};

inline constexpr uint32_t scriptProbe(const ScriptBlock s) { return kScriptProbe[static_cast<uint8_t>(s)]; }

// Block of a codepoint, or None for everything the built-in UI fonts handle
// themselves (Latin, Cyrillic, Greek, Hebrew, Arabic, symbols, ...). The
// dandas U+0964/U+0965 belong to Devanagari but are shared by every Indic
// script; they resolve to Devanagari here and are skipped by callers that
// want the script of the surrounding letters (see scriptBlockOfText).
inline ScriptBlock scriptBlockOf(const uint32_t cp) {
  if (cp >= kIndicBlockBase && cp < kIndicBlockBase + kIndicBlockCount * kIndicBlockSize) {
    return static_cast<ScriptBlock>(1 + (cp - kIndicBlockBase) / kIndicBlockSize);
  }
  if (cp < 0x1100) return ScriptBlock::None;
  if (cp <= 0x11FF) return ScriptBlock::Hangul;  // Hangul Jamo
  if (cp < 0x2E80) return ScriptBlock::None;
  if (cp <= 0x2FDF) return ScriptBlock::Han;  // radicals
  if (cp >= 0x3040 && cp <= 0x30FF) return ScriptBlock::Kana;
  if (cp >= 0x31F0 && cp <= 0x31FF) return ScriptBlock::Kana;  // Katakana Phonetic Extensions
  if (cp >= 0x3130 && cp <= 0x318F) return ScriptBlock::Hangul;
  if (cp >= 0x3000 && cp <= 0x33FF) return ScriptBlock::Han;  // CJK punctuation, Bopomofo, enclosed, compat
  if (cp >= 0x3400 && cp <= 0x4DBF) return ScriptBlock::Han;
  if (cp >= 0x4E00 && cp <= 0x9FFF) return ScriptBlock::Han;
  if (cp >= 0xA960 && cp <= 0xA97F) return ScriptBlock::Hangul;
  if (cp >= 0xAC00 && cp <= 0xD7FF) return ScriptBlock::Hangul;
  if (cp >= 0xF900 && cp <= 0xFAFF) return ScriptBlock::Han;
  if (cp >= 0xFE10 && cp <= 0xFE1F) return ScriptBlock::Han;
  if (cp >= 0xFE30 && cp <= 0xFE4F) return ScriptBlock::Han;
  if (cp >= 0xFF01 && cp <= 0xFF60) return ScriptBlock::Han;   // fullwidth forms
  if (cp >= 0xFF65 && cp <= 0xFF9F) return ScriptBlock::Kana;  // halfwidth katakana
  if (cp >= 0xFFA0 && cp <= 0xFFEF) return ScriptBlock::Hangul;
  if (cp >= 0x20000 && cp <= 0x2EBEF) return ScriptBlock::Han;
  if (cp >= 0x2F800 && cp <= 0x2FA1F) return ScriptBlock::Han;
  if (cp >= 0x30000 && cp <= 0x323AF) return ScriptBlock::Han;
  return ScriptBlock::None;
}

inline bool utf8IsUiFallbackScript(const uint32_t cp) { return scriptBlockOf(cp) != ScriptBlock::None; }

// True for the Indic dandas, which do not identify a script on their own.
inline bool isIndicDanda(const uint32_t cp) { return cp == 0x0964 || cp == 0x0965; }
// 1 for the danda, 2 for the double danda, 0 otherwise (index in table keys).
inline uint8_t indicDandaIndex(const uint32_t cp) { return isIndicDanda(cp) ? static_cast<uint8_t>(cp - 0x0963) : 0; }
