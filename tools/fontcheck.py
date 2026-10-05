#!/usr/bin/env python3
"""The one place the tools take a font's forms from.

    loaded = fontcheck.load("FONT.ttf", "FONT_12.cpfont")
    print(loaded.header)
    runs = fontcheck.runs(loaded, hb_font)   # {PUA cp: [HarfBuzz glyph names]}

    python3 tools/fontcheck.py FONT.ttf FONT_12.cpfont [more cpfonts]   # prints one header line per file

`load` reads the cluster table out of the .cpfont, rebuilds the table from the
TTF with the builder at the file's size, and refuses to continue unless the two
are byte-identical. Only then do the builder's forms (their keys, PUA
codepoints and HarfBuzz runs) describe what the device draws from this file,
and the tools take every device-side glyph run from those forms instead of
deriving it a second time. A table from another build of the font, a wrong TTF
or a tool out of step with the builder raises TableMismatch naming the first
differing key. `header` names the inputs (SHA-256 of the TTF and of the table)
so a printed number can be traced to exact files.
"""
import hashlib
import os
import struct
import sys

import freetype

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from builder import shaping as indic_shaping  # noqa: E402

PSEUDO = {0x01: "ZWJ", 0x02: "INIT", 0x03: "FINA", 0x04: "CLASS", 0x05: "VARIANT", 0x06: "FORMAT"}


class TableMismatch(Exception):
    """The .cpfont's cluster table is not the one the builder makes for the TTF."""


class Loaded:
    __slots__ = ("ttf", "cpfont", "spec", "size", "face", "unit_scale", "plan", "cp_to_form", "table",
                 "ttf_sha256", "table_sha256", "header")


def size_of(cpfont):
    """Point size from the file name (FONT_12.cpfont), as the converter writes it."""
    return int(os.path.basename(cpfont).rsplit("_", 1)[1].split(".")[0])


def table_of(cpfont):
    """(spec, packed table bytes, entry count) of the file's first style."""
    d = open(cpfont, "rb").read()
    if d[:8] != b"CPFONT\0\0":
        raise TableMismatch(f"{cpfont}: not a .cpfont")
    toc = struct.unpack_from("<BBHIIBhhHHBBBII", d, 32)
    kind, count, off = toc[1] & ~indic_shaping.TOC_KIND_PACKED, toc[2], toc[14]
    if not (toc[1] & indic_shaping.TOC_KIND_PACKED) or not off or not count:
        raise TableMismatch(f"{os.path.basename(cpfont)}: no packed cluster table")
    spec = next((s for s in indic_shaping.SCRIPTS.values() if s.shape_kind == kind), None)
    if spec is None:
        raise TableMismatch(f"{os.path.basename(cpfont)}: table kind {kind} has no provider")
    size = indic_shaping.packed_table_bytes(d[off:off + indic_shaping.PACKED_DIRECTORY_BYTES])
    blob = d[off:off + size]
    if len(blob) != size or indic_shaping.table_entry_count(blob) != count:
        raise TableMismatch(f"{os.path.basename(cpfont)}: cluster table directory does not match the TOC")
    return spec, blob, count


def key_text(kb, spec):
    """A key's bytes as text: letters of the block as U+XXXX, pseudo bytes by name."""
    out = []
    for b in kb:
        if b in PSEUDO:
            out.append(PSEUDO[b])
        elif 0x10 <= b < 0x20:
            out.append(f"class{b & 0x0F}")
        else:
            out.append(f"U+{spec.block_base + (b & 0x7F):04X}")
    return " ".join(out)


def describe_mismatch(file_blob, built_blob, spec):
    rows_f = {kb: (meta, value) for kb, meta, value in indic_shaping.unpack_table(file_blob)}
    rows_b = {kb: (meta, value) for kb, meta, value in indic_shaping.unpack_table(built_blob)}
    only_file = sorted(set(rows_f) - set(rows_b))
    only_built = sorted(set(rows_b) - set(rows_f))
    changed = sorted(kb for kb in rows_f if kb in rows_b and rows_f[kb] != rows_b[kb])
    parts = [f"file {len(rows_f)} rows / {len(file_blob)} B, fresh build {len(rows_b)} rows / {len(built_blob)} B"]
    if only_file:
        parts.append(f"{len(only_file)} only in the file, first {key_text(only_file[0], spec)}")
    if only_built:
        parts.append(f"{len(only_built)} only in the build, first {key_text(only_built[0], spec)}")
    if changed:
        kb = changed[0]
        parts.append(f"{len(changed)} with another value, first {key_text(kb, spec)}: "
                     f"file {rows_f[kb][1]:#06x}/{rows_f[kb][0]:#04x}, build {rows_b[kb][1]:#06x}/{rows_b[kb][0]:#04x}")
    if not (only_file or only_built or changed):
        parts.append("same rows in another order or layout")
    return "; ".join(parts)


def load(ttf, cpfont, log=None):
    """Builder forms for `ttf` at the size of `cpfont`, proven to be the file's own table."""
    spec, blob, count = table_of(cpfont)
    size = size_of(cpfont)
    face = freetype.Face(ttf)
    face.set_char_size(size << 6, size << 6, 150, 150)
    unit_scale = (size * 150.0 / 72.0) / face.units_per_EM
    plans = []
    kind, table, cp_to_form = indic_shaping.build_shaping(
        ttf, spec, face, unit_scale, freetype.FT_LOAD_RENDER, log=log or (lambda m: None), plan_out=plans)
    if kind != spec.shape_kind:
        raise TableMismatch(f"{os.path.basename(ttf)} builds a kind-{kind} table, the file holds kind {spec.shape_kind}")
    if table != blob:
        raise TableMismatch(f"{os.path.basename(cpfont)}: cluster table differs from a fresh build of "
                            f"{os.path.basename(ttf)} at {size} pt: {describe_mismatch(blob, table, spec)}")
    out = Loaded()
    out.ttf, out.cpfont, out.spec, out.size, out.face, out.unit_scale = ttf, cpfont, spec, size, face, unit_scale
    out.plan, out.cp_to_form, out.table = plans[0], cp_to_form, blob
    out.ttf_sha256 = hashlib.sha256(open(ttf, "rb").read()).hexdigest()
    out.table_sha256 = hashlib.sha256(blob).hexdigest()
    out.header = (f"{os.path.basename(ttf)} sha256 {out.ttf_sha256[:12]} | {os.path.basename(cpfont)} "
                  f"table sha256 {out.table_sha256[:12]}, {count} rows, identical to a fresh build at {size} pt")
    return out


def runs(loaded, hb_font):
    """{PUA cp: [HarfBuzz glyph names]}: what each composite, sign form and
    mark form of the table was rasterised from (the builder's run)."""
    return {cp: [hb_font.glyph_to_string(g) for g in form.run.gids]
            for cp, form in loaded.cp_to_form.items() if form.run is not None}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    ttf, status = argv[1], 0
    for cpfont in argv[2:]:
        try:
            print(load(ttf, cpfont).header)
        except TableMismatch as e:
            print(f"MISMATCH {e}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
