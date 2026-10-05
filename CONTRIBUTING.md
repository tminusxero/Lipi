# Contributing

Two kinds of change, with different proof.

## A provider change (one script)

Adding a script, or changing how an existing one is shaped: only files under
`providers/<script>/` change (plus its registry lines). Proof:

1. `cmake -S test -B build && cmake --build build -j && ctest --test-dir build`
   green, including the provider's own test file.
   The same under the sanitizers must pass as well (a host may build the engine that way):
   `cmake -S test -B build-asan -DLIPI_SANITIZE=ON && cmake --build build-asan -j && ctest --test-dir build-asan`.
2. `LIPI_FONT_DIR=<dir with the reference fonts> python3 -m pytest builder/test_shaping.py`
   green; if the change alters the table of an existing provider, update its
   golden hash and entry count and say in the commit message what moved.
3. `tools/hb_parity.py` on the provider's word list: numbers in the commit
   message, before and after; every group of differing words explained. Quote
   the tool's first line with them (TTF and table hashes): every tool loads the
   font through `tools/fontcheck.py`, which refuses a .cpfont whose cluster
   table is not a fresh build of the TTF, so a number without that line cannot
   be traced to its inputs.
4. `tools/mark_audit.py` at 16 pt for the provider's reference font when the
   change touches marks or anchors.

Follow `docs/provider-guide.md`. A provider never needs an engine edit; if it
does, that is an engine change first.

## An engine or builder change (every script)

Anything under `engine/`, `builder/` (except goldens), `tools/` or the table
format. Proof, in addition to the provider proof for every provider:

1. Byte identity where the change claims none: rebuild the reference fonts
   and compare the tables; run `tools/shape_cli` over every word list and
   diff against the previous binary's output.
2. The equivalence tests in `test/ScriptTablesTest.cpp` stay green (they hold
   verbatim copies of earlier rules).
3. Engine purity: `grep -nE '0x09[0-9A-F]{2}|Bengali|Devanagari' engine/*.h engine/*.cpp`
   returns hits only in `Registry.h` (the provider list) and `ScriptBlock.h`
   (the Unicode block enum).
4. A table format change bumps `TABLE_FORMAT` in both `engine/Script.h` and
   `builder/spec.py`, updates `docs/table-format.md`, and keeps kind 1
   readable by existing fonts unless the change says otherwise.

## Conventions

- C++17, no exceptions, no RTTI, no heap in the engine beyond
  `std::string::reserve` on the output; `constexpr` data in descriptors.
- `clang-format` with the repository's `.clang-format`.
- Commit messages carry the measurements the change relies on.
- Fonts are never committed; goldens name the file and version they were
  built from.
