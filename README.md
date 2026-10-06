# Lipi

Complex-script text shaping for readers that cannot run an OpenType engine.
Lipi moves the shaping to font-build time: a builder enumerates the cluster
forms a font provides with HarfBuzz, rasterises the composites and writes a
small cluster table; a device-side engine splits text into syllables,
reorders vowel signs and resolves clusters through that table. The host
draws the result with its ordinary glyph loop plus three mark-placement
queries.

Lipi grew out of Bengali and Devanagari support for the CrossInk e-paper
reader on ESP32-C3 hardware (about 200 KB of heap, no room for HarfBuzz).
Everything script-specific is data in a provider; the engine names no script.

## Layout

```
engine/       the C++ engine: Lipi.h/.cpp (shape), Script.h (descriptor type,
              table format), Registry.h (compiled-in providers, mark queries),
              ScriptBlock.h (block map), LipiUtf8.h
providers/    one directory per script: descriptor.h, spec.py, test/, README,
              fonts.yaml, words.txt
builder/      Python: shaping.py (HarfBuzz enumeration, table packing,
              anchors), spec.py (ScriptSpec, format constants), registry.py
tools/        fontcheck.py (a .cpfont's table is the builder's own for its TTF),
              hb_parity.py (device output vs HarfBuzz), mark_audit.py,
              render.py (host renderer emulation), shape_cli.cpp
docs/         interfaces.md (host, provider and builder contracts), table-format.md,
              pua-classes.md, renderer-contract.md, provider-guide.md
templates/    a provider skeleton; tools/new_provider.py copies it
test/         CMake project for the engine and every provider's tests
```

## Status

| Provider | Languages | Table kind | Reference fonts | Parity (identical glyph sequences vs HarfBuzz) |
|---|---|---|---|---|
| bengali | Bangla, Assamese | 1 | Noto Serif Bengali, Tiro Bangla, Hind Siliguri, Noto Sans Bengali | 99.8 to 100.0% (Noto Serif), 98.9 to 99.0% (Tiro), 99.4 to 99.6% (Hind), 99.3 to 99.5% (Noto Sans) on three novels |
| devanagari | Hindi, Marathi, Nepali, Sanskrit | 2 | Noto Serif Devanagari, Tiro Devanagari Sanskrit | Hindi prose 100.0% / 99.9%; Sanskrit 98.3 to 99.7% / 98.1 to 99.8% (2026-09-26) |

Numbers from `providers/*/README.md`, measured with `tools/hb_parity.py` at
12 pt on real-book word lists.

## Build and test

```sh
cmake -S test -B build && cmake --build build -j && ctest --test-dir build
pip install -r builder/requirements.txt
LIPI_FONT_DIR=/path/to/reference/ttfs python3 -m pytest builder/test_shaping.py
g++ -std=c++17 -O2 -Iengine tools/shape_cli.cpp engine/Lipi.cpp -o tools/shape_cli
```

## Embedding in a reader

- PlatformIO: add the repository as a submodule and `Lipi=symlink://<path>`
  to `lib_deps`; `library.json` exposes `engine/` as the include and source
  directory. Any build system: compile `engine/Lipi.cpp`, include `engine/`.
- Select providers with `-DLIPI_PROVIDERS_SELECTED -DLIPI_WITH_BENGALI=1 ...`;
  without the first macro every provider is compiled in.
- Follow `docs/renderer-contract.md`: shape before measuring and drawing,
  keep the table resident, place marks through `Lipi::isMark`,
  `attachesBelow` and `anchorClass`, store the builder's anchors in your font
  file.
- Build fonts by calling `builder.shaping.build_shaping` from your font
  converter (CrossInk: `fontconvert_sdcard.py --shape auto`).

## Adding a script

`docs/provider-guide.md`. Start with `python3 tools/new_provider.py`.

## Licence

MIT. Reference fonts are not part of the repository; the recommended
families are on Google Fonts under the OFL.
