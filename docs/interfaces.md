# Lipi interfaces

The contracts between the three parts of Lipi and the people who extend it:
a host that embeds the engine, a provider that adds a script, and the
converter that calls the builder. Every statement here was checked against
the code at the paths given; "(unverified)" marks the few that were not.

## 1. Overview

Lipi shapes complex-script text without an OpenType engine on the device by
splitting the work in two. At font-build time the **builder**
(`builder/shaping.py`, Python, HarfBuzz) enumerates every cluster form a font
provides, rasterises the composites into Private Use Area glyphs, and writes
a small packed **cluster table** plus per-glyph mark anchors into the host's
font file. On the device the **engine** (`engine/Lipi.cpp`, C++17, no heap
beyond the output string) splits text into syllables, reorders vowel signs,
resolves clusters through that table and leaves marks for the **host
renderer** to anchor with three queries. A **provider** (`providers/<script>/`)
is the data that drives both halves for one script: a C++ descriptor for the
engine and a Python spec for the builder, which must agree.

| Document | What it covers |
|---|---|
| `docs/interfaces.md` (this file) | the contracts: what a host calls, what a provider declares, what the builder returns |
| `docs/provider-guide.md` | the step-by-step for adding a script, with the targets a provider must reach |
| `docs/table-format.md` | the bytes of the cluster table: kinds, key alphabet, packed layout, bookkeeping entries |
| `docs/pua-classes.md` | the Private Use ranges and the placement rule each one implies |
| `docs/renderer-contract.md` | the obligations of a host that draws Lipi output, with CrossIndix's implementation as pointers |
| `CONTRIBUTING.md` | the proof required for a provider change versus an engine change |

## 2. Host interface (C++)

Headers under `engine/`. A host includes `Lipi.h` where it shapes and
`LipiMarks.h` where it only asks about marks; `Lipi.h` pulls in
`Registry.h`, which pulls in every compiled provider's descriptor, so keep it
out of headers that every translation unit includes
(`engine/LipiMarks.h` lines 7-11).

### 2.1 Pre-check

```cpp
bool Lipi::mayNeedShaping(const char* utf8);           // engine/Lipi.h
```

True when the UTF-8 bytes can contain a codepoint of a block that has a
descriptor: a `0xE0` lead byte followed by one of the block's continuation
bytes (`Lipi.cpp` lines 930-937; the byte mask is computed once at start-up,
lines 34-44). It never decodes the text and never consults a table. A host
calls it before every shape, measure or warm-up so Latin text costs one
scan (CrossIndix: `GfxRenderer.cpp` lines 113 and 1148). False means the
text contains nothing the engine would change.

### 2.2 The cluster table

```cpp
struct Lipi::ClusterTable {              // engine/Lipi.h
  const uint8_t* entries = nullptr;      // the packed blob: directory, then one section per key length
  uint16_t count = 0;                    // entries in the blob (the sum of the directory's counts)
  uint8_t kind = 0;                      // SHAPE_KIND_*; read only by the script of the same kind
};
uint32_t Lipi::packedTableBytes(const uint8_t* directory, uint8_t kind, uint32_t* count = nullptr);
uint8_t  Lipi::tableFormat(const ClusterTable& table);
constexpr uint8_t Lipi::TABLE_FORMAT = 3;          // engine/Script.h
constexpr uint8_t Lipi::TOC_KIND_PACKED = 0x80;    // engine/Script.h
constexpr uint32_t Lipi::MAX_SHAPE_TABLE_BYTES = 16384;
```

The table bytes come from the builder (section 4) and live in the host's
font container; Lipi specifies the bytes, not where they are stored. A host
loads a table like this (CrossIndix: `lib/EpdFont/SdCardFont.cpp` lines
705-742 and 844-890):

1. Read the kind byte the converter stored. The converter sets
   `TOC_KIND_PACKED` on it (`builder/spec.py` line 29); a host that keeps the
   kind in its own field strips the flag before use. A kind for which
   `maxKeyLenForKind(kind)` is 0 is one this build cannot read: ignore the
   table, keep the glyphs.
2. Read `PACKED_DIRECTORY_BYTES` (18) bytes of directory and call
   `packedTableBytes(directory, kind, &count)` to learn how many bytes follow
   and how many entries they hold. 0 means an inconsistent directory. Refuse
   anything over `MAX_SHAPE_TABLE_BYTES`.
3. Load the whole blob, build a `ClusterTable{bytes, count, kind}` and check
   `tableFormat(table) == TABLE_FORMAT`. Any other number (including 0, no
   marker) is a table written by another builder: ignore it rather than
   misread it.
4. Keep the bytes resident while the font is loaded; every measure and draw
   of text in that script reads them. Sizes of one family normally carry
   identical tables, so a host may share one copy by content (CrossIndix:
   `lib/EpdFont/ShapeTableCache.h`).

The kind must equal the descriptor's `shapeKind` of the script being shaped.
When it does not, `shape` still runs: the syllable split, the reordering of
pre-base signs and split vowels, and the mark handling happen, but no
cluster lookups do, so conjuncts come out as consonant, visible virama,
consonant (`Lipi.cpp` lines 110-115: `maxKey` is 0 when the kinds differ;
`Lipi.h` lines 27-30). A font with no table is the same case with
`entries == nullptr` and `count == 0`.

### 2.3 Shaping

```cpp
bool Lipi::shape(const char* utf8, const ClusterTable& table, std::string& out);
```

Writes the visual-order codepoint stream of `utf8` into `out` (cleared
first): Unicode letters and signs, Private Use composites and marks, with
pre-base signs moved before their cluster, post-base signs after it, ZWJ and
ZWNJ consumed, and codepoints of scripts without a descriptor copied through
in place (`Lipi.cpp` lines 1112-1162). Returns false and leaves `out`
untouched when the text is null or empty, and also when the text already
contains a codepoint in `U+E000..U+F8FF`: that is a stream this engine
produced earlier, and shaping it again would move a pre-base sign twice
(lines 1114-1121). A host that measures and draws the same string may hand
the shaped form back and get `false`, which it should treat as "use the
text as it is" (CrossIndix: `GfxRenderer.cpp` lines 1146-1160).

Memory and stack: the only allocation is `out.reserve(strlen(utf8) + 16)`
(line 1123); the syllable buffers are fixed arrays (`MAX_CLUSTER` 12 letters,
`MAX_BELOW` 2, `MAX_MODIFIERS` 4, lines 20-22). A cluster longer than
`MAX_CLUSTER` consonants simply starts a new cluster (line 19). The engine
uses no exceptions and no RTTI (`CONTRIBUTING.md`, Conventions).

The host must shape the same text the same way in its measuring pass and its
drawing pass, or word widths will not match the drawn glyphs
(`docs/renderer-contract.md` section 3).

### 2.4 Lookups a host may need

```cpp
uint32_t Lipi::lookupCluster(const ClusterTable&, const ScriptDesc&, const uint32_t* cps, uint32_t len);
Lipi::Entry Lipi::lookupEntry(const ClusterTable&, const ScriptDesc&, const uint32_t* cps, uint32_t len);
uint8_t  Lipi::dandaSpaceShare(const ClusterTable& table, uint32_t cp);
```

`lookupCluster` and `lookupEntry` answer an exact key of 2 to
`maxKeyLenForKind(kind)` codepoints built with the pseudo-codepoints of
`Script.h` (`KEY_INIT_CP`, `KEY_FINA_CP`, `KEY_CLASS_CP`, `KEY_VARIANT_CP`,
`KEY_FORMAT_CP`, `KEY_CLASS_INDEX_CP + n`); they return 0 / `found == false`
when the table is not of the descriptor's kind. Hosts rarely need them; the
tools do (`tools/shape_cli.cpp`).

`dandaSpaceShare` is the one layout query: for a word that starts with a
danda (`U+0964`, `U+0965`), the part of the danda's advance, in 1/256, that
is built-in space the font drops after a space character. A host takes
`advance * share / 256` off the space before such a word; 0 when the table
records nothing or `cp` is not a danda (`Lipi.cpp` lines 1101-1110;
CrossIndix: `GfxRenderer.cpp` lines 2836-2850).

### 2.5 Mark queries

```cpp
bool Lipi::isMark(uint32_t cp);                 // engine/LipiMarks.h, defined in Lipi.cpp
bool Lipi::attachesBelow(uint32_t cp);
Lipi::MarkAnchor Lipi::anchorClass(uint32_t cp);
enum class Lipi::MarkAnchor : uint8_t { None, Center, Right, Pen };   // engine/Script.h
```

Asked per codepoint of the shaped stream (`Lipi.cpp` lines 940-971):

| Query | True / value for | Host action |
|---|---|---|
| `isMark` | `U+F000..U+F3FF`, and a script's `nonSpacing` mask | zero advance, overlay on the preceding base |
| `attachesBelow` | `U+F000..U+F0FF`, `U+F300..U+F3FF`, and the script's `attachBelow` mask | use the base's below anchor, otherwise its above anchor |
| `anchorClass` | `Center` for `U+F000..U+F0FF` and `U+F200..U+F2FF`; `Right` for `U+F100..U+F1FF` and `U+F300..U+F3FF`; a script's `anchorCenter` / `anchorRight` / `anchorPen`; else `None` | the fallback placement when the font pair has no anchors: centred, right edges aligned, at the pen after the base; `None` = the host's own default |

Codepoints outside the Indic blocks and the PUA mark ranges answer false /
`None`, as do marks of scripts not compiled into the build. When the font
carries builder anchors (section 4), the host places a mark at
`base cursor + (basePoint - markAnchor)` with the mark's placement mode and
uses the class only as the fallback (`docs/renderer-contract.md` section 4;
CrossIndix: `lib/EpdFont/EpdFontData.h` `glyphAnchor`).

### 2.6 Script blocks

```cpp
enum class ScriptBlock : uint8_t { None, Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil,
                                   Telugu, Kannada, Malayalam, Sinhala, Han, Kana, Hangul, COUNT };
ScriptBlock scriptBlockOf(uint32_t cp);          // engine/ScriptBlock.h, no namespace
constexpr uint32_t scriptProbe(ScriptBlock s);  // KA of an Indic block, a representative CJK character
bool isIndicDanda(uint32_t cp);  uint8_t indicDandaIndex(uint32_t cp);
const Lipi::ScriptDesc* Lipi::scriptFor(uint32_t cp);   // engine/Registry.h; nullptr = not shaped
constexpr bool Lipi::inIndicBlocks(uint32_t cp);
```

`scriptBlockOf` maps a codepoint to a block for UI font routing: the ten
Indic blocks are consecutive 128-codepoint ranges from `U+0900`
(`kIndicBlockBase`, `kIndicBlockSize`, `kIndicBlockCount`), the CJK entries
group Han, kana and Hangul the way a CJK font covers them, and everything a
reader's built-in fonts handle (Latin, Cyrillic, Greek, Hebrew, Arabic) is
`None`. The dandas resolve to Devanagari; callers that want the script of
the surrounding letters skip them (`isIndicDanda`). `scriptProbe` gives one
letter per block to test whether a font file covers the script (CrossIndix:
`src/SdCardFontSystem.cpp` indexes installed families with it).
`scriptFor(cp)` returns the compiled descriptor for the codepoint's block,
or `nullptr`; `Registry.h` line 47.

### 2.7 PUA glyphs the host must provide

The builder allocates every shaped glyph a codepoint in `U+E000..U+F8FF`
and the host's font must carry a glyph for each one it allocated
(`docs/pua-classes.md`); the ranges tell the renderer the placement without
a lookup (`engine/Script.h` lines 160-187):

| Range | Advance | Class |
|---|---|---|
| `E000..EFFF` | spacing | cluster composites, post-base consonant forms |
| `F000..F0FF` | zero | below marks, centred (phalas, rakar) |
| `F100..F1FF` | zero | above marks, right edges aligned (reph) |
| `F200..F2FF` | zero | above marks, centred |
| `F300..F3FF` | zero | below marks, right edges aligned (subjoined consonants) |
| `F400..F5FF` | spacing | pre-base sign forms |
| `F600..F7FF` | spacing | post-base sign forms |
| `F800..F8FF` | spacing | pre-base consonant forms (reserved; no provider emits them yet) |

### 2.8 Warm-up obligation

A host that caches glyph advances per page must feed the shaped forms of a
paragraph's words through the cache before layout, because shaping
introduces codepoints the words do not contain: the PUA composites and the
parts of split vowels. Deduplicate by codepoint; CrossIndix keeps a bitset
over `kIndicBlockBase..` and the PUA and shapes each distinct table once
(`GfxRenderer.cpp` lines 76-130, `appendShapedIndicText`;
`docs/renderer-contract.md` section 5).

### 2.9 Choosing providers at compile time

`engine/Registry.h` lines 5-17: without `LIPI_PROVIDERS_SELECTED` every
provider in the repository is compiled in. A host that wants fewer defines
`LIPI_PROVIDERS_SELECTED` and `LIPI_WITH_<SCRIPT>=1` for each provider it
keeps (`LIPI_WITH_BENGALI`, `LIPI_WITH_DEVANAGARI`). The descriptors are
`constexpr` data; leaving one out drops its block to `nullptr` in
`kScriptByBlock`, and text in that block passes through `shape` untouched.
`Lipi.cpp` is the one translation unit that must see the descriptors;
`LipiMarks.h` lets every other file ask the mark queries without them.

### 2.10 What a host must not assume

- That the output has one glyph per input codepoint, or the same length.
- That `shape` is idempotent on its own output: it refuses (returns false)
  instead.
- That a table of one script helps another: kinds are per script.
- That mark queries are meaningful for codepoints the build does not shape.
- That the engine breaks lines, handles bidi, or reads font files: it does
  none of these (`docs/renderer-contract.md`, last section).

## 3. Provider interface

A provider is one directory, `providers/<script>/`, with the files in 3.3.
Nothing under `engine/` or `builder/` names a script; the purity grep in
`CONTRIBUTING.md` enforces it. The two halves below are mirrors of each
other and must agree on every letter, or the device will look up keys the
table does not hold (`builder/spec.py` lines 72-74).

### 3.1 The C++ descriptor (`descriptor.h`)

One `constexpr ScriptDesc make<Script>()` and `inline constexpr ScriptDesc
k<Script> = make<Script>();` (`providers/bengali/descriptor.h`). Block
offsets are `cp - blockBase`, 0..127; the helpers `blockBit(off)` and
`blockRange(first, last)` build a `BlockMask` (`engine/Script.h` lines
16-37). Field by field (`engine/Script.h` lines 70-147), with the Bengali
value:

| Field | Type | Meaning, and the engine behaviour it drives | Bengali |
|---|---|---|---|
| `shapeKind` | `uint8_t` | the script's table kind; a table is read only when its kind equals this (2.2) | `SHAPE_KIND_BENGALI` (1) |
| `block` | `ScriptBlock` | the block enum value; a syllable starts a word when the block changes (`Lipi.cpp` lines 1125-1140) | `ScriptBlock::Bengali` |
| `blockBase` | `uint16_t` | first codepoint of the block, `kIndicBlockBase + n * kIndicBlockSize`; key bytes are `0x80 | (cp - blockBase)` | `0x0980` |
| `rephMode` | `RephMode` | how a leading (ra, virama) is drawn: `None` (Tamil), `PreBase` (a mark over the following consonant). `PostBase` is reserved: the engine implements only `PreBase` and treats any other value as `None` (`Script.h` lines 39-43) | `PreBase` |
| `joinStyle` | `JoinStyle` | `Subjoined` (the first consonant's form hangs under the base) or `HalfForm` (a half form before the next consonant); a font may override to half forms with the table flag `{KEY_FORMAT_CP, ZWJ}` (`Lipi.cpp` lines 107-115, 1145-1150) | `Subjoined` |
| `rephAfterPost` | `bool` | the reph mark is emitted after the post-base vowel sign (र्का) instead of right after the cluster; modifiers then follow the reph | `false` (Devanagari: `true`) |
| `virama`, `nukta`, `ra`, `candrabindu` | `uint16_t` | the letters handled by name; 0 = the script has none | `09CD`, `09BC`, `09B0`, `0981` |
| `preSignWithForms` | `uint16_t` | the pre-base sign with contextual forms, sized to its base and fused with a reph or modifier | `09BF` ি |
| `postSignWithForms` | `uint16_t` | the post-base sign with contextual forms | `09C0` ী |
| `postBaseConsonant` | `uint16_t` | consonant whose subjoined form is a spacing post-base glyph, split off so below signs and the candrabindu attach to the base | `09AF` য (Devanagari: 0) |
| `consonants` | `BlockMask` | consonants; `isConsonant`, syllable bases | ক..ন, প..র, ল, শ..হ, ড় ঢ় য়, ৰ ৱ |
| `independentVowels` | `BlockMask` | independent vowels; syllable bases that take modifiers | অ..ঌ, এ ঐ, ও ঔ, ৠ ৡ, ৼ |
| `extraBases` | `BlockMask` | other letters signs attach to | khanda ta `4E`, avagraha `3D` |
| `preBase` | `BlockMask` | vowel signs drawn before the cluster (moved in front) | ি ে ৈ |
| `postBase` | `BlockMask` | vowel signs drawn after the cluster | া ী ৗ |
| `below` | `BlockMask` | vowel signs drawn under the base; up to `MAX_BELOW` (2) collected per syllable | ু ূ ৃ ৄ ৢ ৣ |
| `above` | `BlockMask` | vowel signs drawn over the base | none (Devanagari: ॅ ॆ े ै) |
| `modifiers` | `BlockMask` | candrabindu, anusvara, visarga and the like; up to `MAX_MODIFIERS` (4) per syllable | ঁ ং ঃ ৾ |
| `nonSpacing` | `BlockMask` | everything drawn as a zero-advance overlay; this is `isMark` for the block | ঁ ় ু ূ ৃ ৄ ্ ৢ ৣ ৾ |
| `raFolds` | `BlockMask` | letters keyed and treated as ra inside a conjunct | ৰ `70` |
| `initSigns` | `BlockMask` | pre-base signs with a word-initial form (key marker `KEY_INIT_CP`) | ে ৈ |
| `preSignsWithForms` | `BlockMask` | every pre-base sign with per-base forms or sign classes; `preSignWithForms` is the one of them that also fuses with a reph or modifier | ি ে ৈ |
| `candrabinduBeforePost` | `BlockMask` | post-base signs the candrabindu is drawn before | া ী |
| `attachBelow` | `BlockMask` | marks that hang from the base's below anchor (`attachesBelow`) | nukta, below signs, hasanta, ৢ ৣ |
| `anchorCenter`, `anchorRight`, `anchorPen` | `BlockMask` | the `anchorClass` of each mark; a mark in none of them takes the host's default | centre: ঁ ় ু ূ ৃ ৄ ৢ ৣ ৾; right: none; pen: ্ |
| `splitVowels[4]`, `splitVowelCount` | `SplitVowel{sign, pre, post}` | two-part signs: the sign in the text, the part drawn before the cluster and the part after it | ো = ে + া, ৌ = ে + ৗ |
| `nuktaFolds[8]`, `nuktaFoldCount` | `NuktaFold{base, folded}` | consonant + nukta pairs with a precomposed letter the fonts map instead | ড়, ঢ়, য় |

Optional in practice: everything that is `0` or an empty mask for a script
that lacks the feature (`above`, `raFolds`, `initSigns`, `splitVowels`,
`nuktaFolds`, `postBaseConsonant`, `candrabindu`). Reserved:
`RephMode::PostBase`. Capacity limits: `MAX_SPLIT_VOWELS` 4,
`MAX_NUKTA_FOLDS` 8 (`Script.h` lines 66-67); a script with three-part
split vowels (Sinhala ෝ) does not fit the two-part `SplitVowel` (3.5).

The template `templates/provider/descriptor.h` has every field with a
comment; `tools/new_provider.py` fills the names.

### 3.2 The Python spec (`spec.py`)

One `ScriptSpec(...)` instance (`builder/spec.py` lines 69-179), frozen
dataclass. Required fields first, then the optional ones with defaults.
"Read by" names the builder step that uses the field (`builder/shaping.py`):

| Field | Meaning | Read by | Bengali |
|---|---|---|---|
| `name` | provider directory name; the key in `SCRIPTS` and the plan cache | `build_shaping`, `pair_counts` (finds `words.txt`) | `"bengali"` |
| `shape_kind` | the table kind, must equal `shapeKind` | `pack_table`, key geometry | `1` |
| `block_base` | first codepoint of the block | `key_bytes`, `in_block` | `0x0980` |
| `hb_script`, `hb_language` | HarfBuzz script and language tags for every shaping call | `IndicClusterPlan.shape_internal` | `"Beng"`, `"bn"` |
| `intervals` | `(start, end)` pairs the host's interval preset covers | the host converter's preset table (`fontconvert_sdcard.py` line 89), `script_for_intervals` | Bengali block + the dandas |
| `probe` | KA: shaped after a key so word-final forms stay hidden | enumeration | `0x0995` |
| `consonants` | every consonant | enumeration, `pair_counts` | 41 letters |
| `cluster_consonants` | consonants that take part in conjuncts (nukta letters left out: no book uses them) | enumeration of pairs and triples | 33 letters |
| `virama`, `nukta`, `ra` | the named letters | enumeration, `pair_counts` (a virama before a consonant is a join, not a mark) | `09CD`, `09BC`, `09B0` |
| `post_base_consonant` | consonant whose subjoined form is a spacing glyph (ya-phala) | ya-phala split | `09AF` |
| `ra_folds` | letters shaped as ra inside a conjunct | enumeration | `(09F0,)` |
| `below_vowels` | below-base vowel signs | cluster + below-sign forms | ু ূ ৃ ৄ |
| `pre_sign_with_forms`, `post_sign_with_forms` | the signs with contextual forms (ি, ী) | `_sign_forms`, `_sign_classes` | `09BF`, `09C0` |
| `init_signs`, `fina_signs` | signs with word-initial / word-final forms | `_sign_forms` (INIT/FINA keys) | ে ৈ; া ী ৗ |
| `form_probe_bases` | bases tried when isolating a subjoined form (the first that does not ligate exposes it) | enumeration | ক ট প ম ব দ গ |
| `pre_signs_with_forms`, `post_signs_with_forms` | every sign with per-base forms (`()` = the one above) | `_sign_forms`, sign classes | ি ে ৈ; ী ৗ |
| `join_style` | `"subjoined"` or `"half"` | `_half_form`, half-form enumeration | `"subjoined"` |
| `reph_after_post` | reph follows the post-base sign | device simulation, fused forms | `False` |
| `mark_fusion` | enumerate signs and rephs fused with modifiers | `_fused_marks` | `True` |
| `post_vowels`, `above_vowels`, `modifiers`, `independent_vowels` | the sets tried for fused forms | `_fused_marks` | া ী ৗ; none; ঁ ং ঃ; none |
| `candrabindu_before_post` | post signs the device draws the candrabindu before | device simulation | া ী |
| `marks`, `attach_below`, `anchor_center`, `anchor_right`, `anchor_pen` | mirrors of `nonSpacing`, `attachBelow` and the anchor masks | `is_mark`, `attaches_below`, `anchor_class` (used by `compute_anchors`, the tools) | as the descriptor |
| `below_signs` | vowel signs and virama drawn under the base | the mark audit's anchor set | ু ূ ৃ ৄ ্ ৢ ৣ |
| `rare_marks` | marks the mark audit does not report on | `tools/mark_audit.py`, `hb_parity.py` | `(09FE,)` |
| `phala_consonants` | consonants whose post-virama form is a phala glyph | the mark audit | র ব য |
| `dandas` | the shared sentence punctuation | `danda_space_leads`, `spacing_advance_overrides` | `0964`, `0965` |

`builder/test_shaping.py` holds a consistency test for the sets; the
provider's test should add a mirror check against the descriptor once the
numbers are final (`docs/provider-guide.md` section 3).

### 3.3 Files in a provider directory

| File | Purpose |
|---|---|
| `descriptor.h` | the engine data (3.1); included from `engine/Registry.h` under `LIPI_WITH_<SCRIPT>` |
| `spec.py` | the builder data (3.2); imported by `builder/registry.py` |
| `__init__.py` | Python package marker |
| `test/<Script>ShaperTest.cpp` | googletest cases for the script: syllable split, reordering, split vowels, conjuncts and reph, pass-through of other scripts, a table-kind mismatch case; compiled into `LipiTest` (`test/CMakeLists.txt` lines 32-36). `test/PackedTable.h` builds packed test tables |
| `README.md` | what the script needs, the reference fonts, the parity table with every residual group explained, how `words.txt` was made |
| `fonts.yaml` | the recommended Google Fonts families with version and licence |
| `words.txt` | a word sample of a few thousand lines. Two consumers: the parity smoke test (`tools/hb_parity.py` in CI), and the builder's `pair_counts(spec)`, which counts (base, mark) pairs in it to weight the anchor fit (`shaping.py` lines 1963-1995; a pair the sample never shows must not outvote one it is full of, cap `PAIR_WEIGHT_CAP` 30). A missing file is an empty sample. Its provenance matters twice: legally (commit only public-domain text; the Bengali sample is from Manik Bandopadhyay's *Padma Nadir Majhi*, the Devanagari one from Premchand's *Nirmala*, both via Wikisource) and for quality, because the pair weights follow the sample's vocabulary and spelling; see `providers/bengali/README.md` for the measurement |

### 3.4 Registration

Three lines, printed by `tools/new_provider.py` when it creates the directory:

1. `engine/Registry.h`: `#if LIPI_WITH_<SCRIPT>` include of the descriptor,
   and the `&k<Script>` entry at the block's position in `kScriptByBlock`
   (the array is indexed by `ScriptBlock`, so the slot already exists for
   every Indic block). Add `#define LIPI_WITH_<SCRIPT> 1` to the default
   block (lines 7-10).
2. `builder/registry.py`: the import and the `SCRIPTS` entry.
3. `test/CMakeLists.txt`: the test file in `LipiTest`.

Then `docs/table-format.md`: the kind is no longer reserved. The kind numbers
3..10 are assigned per script in that table.

### 3.5 Extension points

What the next scripts need, and whether it is data or engine work. "Data
only" means a provider directory plus registration; "engine change" means
`engine/` or `builder/` changes, with the proof `CONTRIBUTING.md` asks for.

| Need | Scripts | Status |
|---|---|---|
| No reph (`RephMode::None`), pre-base and split two-part vowels, few conjuncts | Tamil | data only |
| Subjoined conjuncts with a limited set, tippi/addak above marks (`PUA_ABOVE_CENTER`) | Gurmukhi | data only |
| Half forms + reph after the post-base sign (as Devanagari) | Gujarati | data only |
| Subjoined conjuncts with two-part vowels (as Bengali) | Odia | data only |
| Reph as a spacing or mark glyph after the cluster (`RephMode::PostBase`) | Kannada, Telugu | engine change: the enum value exists, the emitter does not implement it (`Script.h` lines 39-43) |
| Consonant + vowel ligatures in large numbers, subjoined forms at the right edge (`PUA_BELOW_RIGHT`) | Kannada, Telugu | PUA class exists; whether the table budget (16 KB) holds the forms is per font (unverified) |
| Pre-base consonant forms drawn before the cluster (`PUA_PRECONS`, F800) | Malayalam ്ര | the range and the builder kind `KIND_PRECONS` exist; no emitter path produces them (engine change) |
| Chillu letters (atomic codepoints and `C + virama + ZWJ` sequences) | Malayalam | engine change: the syllable collector keeps a ZWJ only when a virama follows it inside a cluster (`Lipi.cpp` lines 846-852) and the emitter keys ZWJ only in half-form keys (lines 188-214); a trailing `virama + ZWJ` has no path |
| Three-part split vowels (ෝ = ෙ + ො + ා style) | Sinhala | engine change: `SplitVowel` has two parts (`Script.h` line 50) |
| Conjuncts only with an explicit ZWJ, plain virama otherwise visible | Sinhala | engine change: today a virama between cluster consonants always joins (`Lipi.cpp` lines 849-853) |
| Mark on mark (a tone mark above a vowel sign) | Thai, Lao | engine and host change: marks anchor to the preceding spacing base only (2.5) |
| Dictionary line breaking | Thai, Lao, Burmese, Khmer | out of scope for the engine (`docs/renderer-contract.md`, last section); a host feature |
| A block outside `U+0900..U+0DFF` | Thai, Burmese, Tibetan, Khmer | engine change: `ScriptBlock.h` lists only the ten Indic blocks and CJK; `inIndicBlocks`, the key byte scheme (`0x80 | offset`, one 128-codepoint block per script) and `mayNeedShaping`'s `0xE0` lead-byte mask all assume it |

## 4. Builder interface (Python)

Entry point `builder/shaping.py`; the host imports it with the repository
root on `sys.path` (`from builder import shaping`). Requirements:
`builder/requirements.txt` (uharfbuzz, fontTools, freetype-py; Pillow for
the tools).

### 4.1 `build_shaping`

```python
build_shaping(font_path, spec, face, unit_scale, load_flags, log=None, anchors_out=None,
              advances_out=None, lefts_out=None, tops_out=None, plan_out=None)
    -> (shape_kind, table_bytes, {pua_cp: ClusterForm})
```

(`shaping.py` lines 2551-2630.) Inputs: the TTF path, the `ScriptSpec`, a
FreeType `face` already set to the target size, `unit_scale` (pixels per font
unit at that size), the FreeType load flags the host rasterises with, and an
optional `log(msg)`.

Outputs:

- `shape_kind`: `spec.shape_kind`, or 0 with an empty table and mapping
  when the font has nothing to shape.
- `table_bytes`: the packed table (`docs/table-format.md`), already carrying
  the format marker, the danda flag, the half-form flag and the danda
  space-lead entries. Raises `ValueError` when it exceeds
  `MAX_TABLE_BYTES` (16384) (lines 2611-2613).
- `{pua_cp: ClusterForm}`: every allocated Private Use codepoint with its
  `ClusterForm` (`key`, `run`, `kind`, `pre_class`, `post_class`,
  `continues`, lines 272-282). `run` is a `GlyphRun` of
  `(gid, x_advance, x_offset, y_offset)` in font units; `kind` is one of
  `KIND_BASE`, `KIND_BELOW`, `KIND_ABOVE`, `KIND_ABOVE_CENTER`,
  `KIND_BELOW_RIGHT`, `KIND_PRE`, `KIND_POST`, `KIND_PRECONS` (`spec.py`
  lines 47-60). The host rasterises each form with
  `render_run(face, form.run, unit_scale, load_flags, mark=form.kind in MARK_KINDS)`
  and stores the bitmap under the PUA codepoint; `pua_intervals(mapping)`
  gives the intervals to add to the font's coverage.
- `anchors_out` (dict): `{codepoint: (above, below, extra)}` anchor bytes,
  from `compute_anchors`, for the script's letters, signs and the PUA forms;
  the host stores them in its glyph records (three bytes per entry, the
  assignments in `shaping.py` lines 2420-2450; the function's docstring still
  says `(above, below)`).
- `advances_out` (dict): `{codepoint: advance in 12.4 px}` for spacing
  glyphs whose HarfBuzz position differs from their metrics (zero-advance
  letters spaced by GPOS, dandas with a single adjustment), from
  `spacing_advance_overrides`; `lefts_out`: the extra left shift in whole
  pixels for the same glyphs.
- `tops_out` (dict): `{mark codepoint: px}` added to a mark bitmap's top,
  from `mark_lifts`, so a mark sits at the height the font gives it on its
  usual bases.
- `plan_out` (list): receives the `IndicClusterPlan`, which the tools read
  glyph ids and runs from.

How CrossIndix consumes all of this: `lib/EpdFont/scripts/fontconvert_sdcard.py`
lines 786-830 (one call per style and size, intervals extended with the PUA,
each form rendered and packed, anchors and overrides written into the glyph
record) and 1147-1155 (table kind with `TOC_KIND_PACKED`, entry count from
`table_entry_count`, table bytes appended after the style's sections).

### 4.2 The plan cache

`_PLAN_CACHE` (lines 2523-2540) keeps the size-independent half of a build
per `(absolute font path, spec.name, id(spec))`: the enumerated plan, the
mark lifts with their exceptions, and the last `MarkSurvey` with the PUA
mapping it was built on. A conversion of eight sizes enumerates once; a
later size only re-classifies the mark forms from its own rendered ink
(`_classify_mark_kinds`), re-allocates the PUA, packs the table and scales
the anchors. The survey is rebuilt when a size's classification moves a form
to another range (the mapping differs, lines 2597-2603). `clear_plan_cache()`
empties it; a new `ScriptSpec` object (different `id`) or a different path
also misses. The cache lives for the process: a long-running host must call
`clear_plan_cache()` between fonts of the same path that changed on disk.

### 4.3 Other entry points a host or tool may call

| Function | Use |
|---|---|
| `script_for_intervals(intervals)` (line 92) | the single spec whose block the intervals cover, for a `--shape auto` option; two scripts in one font is an error |
| `allocate_pua(forms, spec)` (1885) | `({key: cp}, {cp: form})`; raises when a kind has more forms than its range holds |
| `pack_table(entries, spec, danda_ends_word, half_forms, space_leads)` (175) | serialises rows `(key, cp, pre_class, post_class, continues)`; `table_entries(forms, key_to_cp)` makes the rows |
| `unpack_table(data)`, `table_entry_count(data)`, `packed_table_bytes(directory)` (207-250) | read a packed table back (the tools, the converter's TOC count) |
| `compute_anchors(plan, cp_to_form, unit_scale, log, survey)` (2244) | the anchor bytes (4.1) |
| `mark_lifts(survey, cp_to_form, log)` (2481) | the vertical lifts (4.1) |
| `pair_counts(spec)` (1967) | the (base, mark) counts from `words.txt` (3.3) |
| `render_run(face, run, scale, load_flags, mark)` (1834) | rasterise a form's glyph run into a `CompositeBitmap` (width, height, rows, left, top, advance_fp4) |
| `mark_offset_px(below, base_bytes, adv_px, mark_bytes)` (1935) | the host's reference placement rule, mirrored by CrossIndix's `glyphAnchor::markOffsetWithMode` |
| `SCRIPTS` (`builder/registry.py`) | `{name: ScriptSpec}` for every provider |

### 4.4 Checking a build

Each tool loads the font through `tools/fontcheck.py`, which refuses a
`.cpfont` whose cluster table is not a fresh build of the TTF, so every
number is traceable to its inputs (`CONTRIBUTING.md`, provider proof 3).

| Tool | One line |
|---|---|
| `tools/fontcheck.py FONT.ttf FONT_12.cpfont` | the `.cpfont`'s table is the builder's own for this TTF; the loader every other tool uses |
| `tools/hb_parity.py FONT.ttf FONT_12.cpfont WORDS.txt [--show N]` | percentage of words whose device glyph sequence equals HarfBuzz's, with the differing words grouped |
| `tools/word_parity.py` | whole-word placement: where the device puts every glyph of a word against HarfBuzz, including mark contact |
| `tools/mark_audit.py FONT.ttf FONT_16.cpfont [--strict] [--tolerance PX]` | every base x mark pair: device position against HarfBuzz |
| `tools/space_parity.py` | the gap before a word that starts with a danda, device against HarfBuzz |
| `tools/render.py` | host emulation of the renderer: shaped streams from `shape_cli` drawn to a PNG |
| `tools/shape_cli.cpp` | the engine on the host: reads a `.cpfont`'s table and prints the shaped codepoint stream per input line; `g++ -std=c++17 -O2 -Iengine tools/shape_cli.cpp engine/Lipi.cpp -o tools/shape_cli` |
| `builder/test_shaping.py` | pytest goldens: entry count and table hash per reference font (`LIPI_FONT_DIR`) |
