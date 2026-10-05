"""Regression guard for the cluster tables builder/shaping.py writes.

    LIPI_FONT_DIR=/path/with/ttfs python3 -m pytest builder/test_shaping.py

The golden hashes are the SHA-256 of the packed table for the regular style
at 12 pt; any change to the enumeration, the sign-form rules, the PUA
allocation or the table layout shows up here (all goldens moved to table
format 3, the packed layout, on 2026-09-19; the row counts did not). Bengali goldens date from the Devanagari work
(joiner placeholders dropped from HarfBuzz runs, wider PUA sign ranges);
Devanagari goldens from its first release. Skipped when uharfbuzz,
freetype-py or the fonts are missing; the Noto Devanagari fonts are looked
up in the system font directory as well.
"""
import dataclasses
import hashlib
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from builder import shaping as indic_shaping  # noqa: E402

hb = pytest.importorskip("uharfbuzz")
freetype = pytest.importorskip("freetype")

FONT_DIR = os.environ.get("LIPI_FONT_DIR", "")
SYSTEM_FONT_DIRS = ("/usr/share/fonts/truetype/noto",)

# (file name candidates, script spec, table entry count, sha256 of the packed table)
# 2026-09-19: generic reph+sign+modifier composites dropped (1-3 rows per font).
# 2026-09-25 Bengali pass: ৗ per-base forms (Hind), ya-phala + sign + modifier keys,
# per-base sign + modifier forms judged against the engine's generic-first order,
# fused ি+ঁ (Hind): Serif 1002 -> 1025, Tiro 1076 -> 1100, Noto Sans 1710 -> 1735,
# Hind 1004 -> 1100.
# 2026-09-25 Devanagari pass: half-form pair rows/cells, class fused lists, half forms kept
# when C+virama+probe is a ligature: HindSiliguri 1100 -> 1164, NotoSerifDevanagari 1031 -> 1408, NotoSansDevanagari 983 -> 1127.
GOLDEN = {
    # 997 until the lift exceptions (2026-09-24): ট ই ঈ উ ঊ + ঁ keep the font's height.
    "NotoSerifBengali": (("NotoSerifBengali.ttf", "NotoSerifBengali[wdth,wght].ttf"), "bengali", 1025,
                         "825ce37062f27edd419f1d4cd568ca2797c68b0e44a7919e096e86db273664bd"),
    # 1074 until the danda space shares (2026-09-24: two 06 02 1n rows).
    # 1032 rows until the ে/ৈ per-base forms (2026-09-19): 42 headline-connector
    # composites of ্র conjuncts with ে/ৈ joined the ি ones.
    "TiroBangla": (("TiroBangla-Regular.ttf",), "bengali", 1100,
                   "d744b1c05c7f96a523cf60e68c0b2333e19c74a92b46d3cc858fc8ea70601e04"),
    # ে/ৈ class variants (.long on খ গ ণ থ প শ) and their word-initial lists.
    "NotoSansBengali": (("NotoSansBengali.ttf", "NotoSansBengali[wdth,wght].ttf"), "bengali", 1735,
                        "2990408066235cc6ec33dc6e4b82ccf46dfdeeef3618579aee72df00cae994bc"),
    # Joins with half forms: enumerated as a half-form script, table flagged.
    "HindSiliguri": (("HindSiliguri-Regular.ttf",), "bengali", 1164,
                     "96ce5abc4508ef09795af565266cd31ed97023ede090cb92253d6deeace0e7e4"),
    # 2026-09-26: the fused sign+modifier lists the class fold already wrote
    # are no longer written a second time (-9 duplicate rows, -9 orphan glyphs).
    "NotoSerifDevanagari": (("NotoSerifDevanagari[wdth,wght].ttf", "NotoSerifDevanagari.ttf"), "devanagari", 1399,
                            "af4712a44c14aad4baf38f2f52310d53376e90876d2f9589f0dd478fc547f6b3"),
    "NotoSansDevanagari": (("NotoSansDevanagari-Regular.ttf",), "devanagari", 1119,
                           "caedc52f01c13bd2abb8c4a87b4fc25e20e073c1185060b901e816b90ff91194"),
}
SIZE = 12
BUDGET_BYTES = indic_shaping.MAX_TABLE_BYTES


def _font(names):
    for directory in (FONT_DIR,) + SYSTEM_FONT_DIRS:
        for name in names:
            path = os.path.join(directory, name)
            if directory and os.path.exists(path):
                return path
    pytest.skip(f"set LIPI_FONT_DIR to a directory holding {names[0]}")


def _build(path, spec):
    face = freetype.Face(path)
    face.set_char_size(SIZE << 6, SIZE << 6, 150, 150)
    unit_scale = (SIZE * 150.0 / 72.0) / face.units_per_EM
    return indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER, log=lambda m: None)


def test_glyph_anchors_follow_harfbuzz():
    """The v5 glyph anchors put the halant and the anusvara where HarfBuzz does
    for Noto Serif Devanagari at 12 pt: ka's below anchor is its advance plus
    the halant's GPOS offset, the probe marks carry a zero anchor, and the
    consonant + visible virama composite exists. The expected numbers come from
    the Noto project build 2.001 (no Latin); the halant's median lands 2.5 px
    further on ka in the Google Fonts build, whose mark audit is otherwise
    better, so the test stays on the file its numbers describe."""
    spec = indic_shaping.SCRIPTS["devanagari"]
    path = _font(("NotoSerifDevanagari-Regular.ttf",))
    face = freetype.Face(path)
    face.set_char_size(SIZE << 6, SIZE << 6, 150, 150)
    unit_scale = (SIZE * 150.0 / 72.0) / face.units_per_EM
    anchors = {}
    kind, table, forms = indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER,
                                                     anchors_out=anchors)
    ka, halant, anusvara = 0x0915, 0x094D, 0x0902
    base = anchors[ka]  # (above, below, extra)
    u_sign = 0x0941
    # ka: advance 711; GPOS x offsets: u sign -210, anusvara -293, halant -293. Which
    # mark serves as the probe, and which placement mode a mark takes (v6), is the
    # pass's choice; what must hold is where each mark lands: pixels from the base
    # cursor through the same rule the renderer applies, within a pixel of
    # HarfBuzz's position.
    adv_px = int(round(711 * unit_scale))
    assert anchors[anusvara][0] != indic_shaping.ANCHOR_NONE  # an above mark's value sits in its class byte
    assert anchors[halant][1] != indic_shaping.ANCHOR_NONE
    assert abs(indic_shaping.mark_offset_px(False, base, adv_px, anchors[anusvara][:2]) - (711 - 293) * unit_scale) <= 1.0
    assert abs(indic_shaping.mark_offset_px(True, base, adv_px, anchors[u_sign][:2]) - (711 - 210) * unit_scale) <= 1.0
    assert abs(indic_shaping.mark_offset_px(True, base, adv_px, anchors[halant][:2]) - (711 - 293) * unit_scale) <= 1.0
    assert any(f.key == (ka, halant) and f.kind == indic_shaping.KIND_BASE for f in forms.values())
    assert sum(1 for cp, (a, b, _e) in anchors.items() if cp >= 0xE000 and (a or b)) > 400


@pytest.mark.parametrize("family", sorted(GOLDEN))
def test_table_is_golden(family):
    names, script, count, digest = GOLDEN[family]
    spec = indic_shaping.SCRIPTS[script]
    kind, table, forms = _build(_font(names), spec)
    assert kind == spec.shape_kind
    assert indic_shaping.table_entry_count(table) == count
    assert indic_shaping.packed_table_bytes(table[:indic_shaping.PACKED_DIRECTORY_BYTES]) == len(table)
    rows = indic_shaping.unpack_table(table)
    assert len(rows) == count
    # One row per key: a duplicate would leave the engine's binary search on
    # whichever row it lands on and the other row's glyph unreachable.
    keys = [bytes(kb) for kb, _meta, _value in rows]
    assert len(set(keys)) == len(keys), sorted(k.hex() for k in keys if keys.count(k) > 1)
    assert len(forms) < count  # bookkeeping entries carry no glyph
    assert hashlib.sha256(table).hexdigest() == digest
    assert len(table) <= BUDGET_BYTES


@pytest.mark.parametrize("family", sorted(GOLDEN))
def test_no_composite_is_keyed_without_a_base(family):
    """A spacing composite stands for its whole key, so the key must name a
    base (a consonant, an independent vowel, a ZWJ half form) after any
    leading reph. Builders before 2026-09-19 wrote the probe letter's run
    under the generic र्िं / র্িঁ keys and the device drew क in place of
    the real base."""
    names, script, _count, _digest = GOLDEN[family]
    spec = indic_shaping.SCRIPTS[script]
    _kind, table, _forms = _build(_font(names), spec)
    # Bases by block layout: independent vowels (0x04..0x14 and the 0x72..0x77
    # extension), avagraha, khanda ta / om, nukta letters and the vocalic letters.
    base_offsets = {c - spec.block_base for c in spec.consonants} | set(range(0x04, 0x15)) | {0x3D, 0x4E, 0x50} | set(
        range(0x58, 0x62)) | set(range(0x72, 0x78))
    ra, virama = spec.ra - spec.block_base, spec.virama - spec.block_base
    offenders = []
    for kb, _meta, value in indic_shaping.unpack_table(table):
        if (value & 0x1FFF) >= 0x1000 or not kb or (kb[0] < 0x80 and kb[0] != 0x01):
            continue  # not a composite (sign forms and marks), or a bookkeeping row
        body = [b & 0x7F if b >= 0x80 else b for b in kb]
        if body[:2] == [ra, virama] and len(body) > 2:
            body = body[2:]
        if not any(b in base_offsets or b == 0x01 for b in body):
            offenders.append(kb.hex())
    assert offenders == []


def test_placement_modes_follow_the_font():
    """.cpfont v6 placement modes: Noto Sans Bengali attaches its phala marks where
    the above marks go, Hind Siliguri's nukta and hasanta sit on the below anchor of
    the bases the books actually put them on, and Tiro Devanagari Sanskrit's anusvara
    needs a point of its own (the extra anchor). Each mark stores its mode in the byte
    of the other class. (Hind's two took the pen until the fit began weighting each
    pair by how often the provider's word sample shows it, 2026-09-23. The nukta went
    back to the pen once the survey stopped measuring dotted-circle runs, 2026-09-24,
    and to the class anchor with the Bengali pass forms, 2026-09-25: the two land on
    the same pixels in all 7,259 Hind words with ়; the class anchor is the outcome
    this test pins so a change shows up here first.)"""
    cases = (
        ("HindSiliguri", "bengali", {0x09BC: indic_shaping.MODE_CLASS, 0x09CD: indic_shaping.MODE_CLASS}),
        ("NotoSansBengali", "bengali", {0xF103: indic_shaping.MODE_OTHER, 0xF104: indic_shaping.MODE_OTHER}),
    )
    for family, script, expected in cases:
        spec = indic_shaping.SCRIPTS[script]
        path = _font(GOLDEN[family][0])
        face = freetype.Face(path)
        face.set_char_size(SIZE << 6, SIZE << 6, 150, 150)
        unit_scale = (SIZE * 150.0 / 72.0) / face.units_per_EM
        anchors = {}
        indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER, anchors_out=anchors)
        for cp, mode in expected.items():
            below = spec.attaches_below(cp)
            modes = mode if isinstance(mode, tuple) else (mode,)
            assert (anchors[cp][0] if below else anchors[cp][1]) in modes, (family, hex(cp), anchors[cp])
            assert (anchors[cp][1] if below else anchors[cp][0]) != indic_shaping.ANCHOR_NONE
    spec = indic_shaping.SCRIPTS["devanagari"]
    path = _font(("TiroDevanagariSanskrit-Regular.ttf",))
    face, unit_scale = _deva_face(path)
    anchors = {}
    indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER, anchors_out=anchors)
    anusvara, ka = 0x0902, 0x0915
    assert anchors[anusvara][1] == indic_shaping.MODE_EXTRA
    assert anchors[ka][2] != indic_shaping.ANCHOR_NONE  # bases carry the extra point
    # The modifier the font moves after the pre-base sign (मिं) is keyed as its own
    # mark and measured from the base's own points, never from another mark's.
    _kind, _table, cp_to_form = indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER)
    variants = [cp for cp, f in cp_to_form.items()
                if len(f.key) == 2 and f.key[0] in spec.modifiers and f.key[1] == spec.pre_sign_with_forms]
    assert variants
    for cp in variants:
        assert anchors[cp][1] in (indic_shaping.MODE_CLASS, indic_shaping.MODE_PEN), (hex(cp), anchors[cp])
    # And the anusvara lands where HarfBuzz puts it on a few letters.
    plan = indic_shaping.IndicClusterPlan(path, spec)
    for base in (ka, 0x0928, 0x092E):
        run = plan.shape((base, anusvara))
        hb_px = (run.glyphs[0][1] + run.glyphs[1][2]) * unit_scale
        adv_px = int(round(run.glyphs[0][1] * unit_scale))
        assert abs(indic_shaping.mark_offset_px(False, anchors[base], adv_px, anchors[anusvara][:2]) - hb_px) <= 1.0


def test_reph_after_the_post_base_sign_lands_on_the_sign():
    """Devanagari draws the reph after the post-base sign (र्का: ka, aa, reph),
    so the sign is the base the renderer attaches it to. Until 2026-09-19 a
    bare sign was only plausible for the modifiers; its above anchor came from
    the anusvara and the reph landed 3 px past ा's ink in Tiro Devanagari
    Sanskrit (अपर्याप्तं looked reph-less). Both Devanagari fonts, ा and ी or ो
    where the font has no fused form: within a pixel of HarfBuzz."""
    spec = indic_shaping.SCRIPTS["devanagari"]
    ka, aa, ra, virama = 0x0915, 0x093E, 0x0930, 0x094D
    for names in (("TiroDevanagariSanskrit-Regular.ttf",), GOLDEN["NotoSerifDevanagari"][0]):
        path = _font(names)
        face, unit_scale = _deva_face(path)
        anchors = {}
        _kind, _table, forms = indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER,
                                                           anchors_out=anchors)
        reph = next(cp for cp, f in forms.items() if f.key == (ra, virama))
        plan = indic_shaping.IndicClusterPlan(path, spec)
        run = plan.shape((ra, virama, ka, aa))
        # HarfBuzz: reph origin from the ा origin = ा advance + reph x offset (the reph follows ा in the run).
        gids = [g[0] for g in run.glyphs]
        assert gids[:2] == [plan.gid(ka), plan.gid(aa)] and len(gids) == 3, gids
        hb_px = (run.glyphs[1][1] + run.glyphs[2][2]) * unit_scale
        adv_px = int(round(run.glyphs[1][1] * unit_scale))
        device_px = indic_shaping.mark_offset_px(False, anchors[aa], adv_px, anchors[reph][:2])
        assert device_px is not None and abs(device_px - hb_px) <= 1.0, (names[0], device_px, hb_px)


def test_kind1_keys_are_codepoint_minus_0x0900():
    spec = indic_shaping.SCRIPTS["bengali"]
    assert indic_shaping.key_bytes((0x0995, 0x09CD, 0x09B7), spec) == bytes([0x95, 0xCD, 0xB7])
    assert indic_shaping.key_bytes((0x09F0, 0x09CD), spec) == bytes([0xB0, 0xCD])  # Assamese ra keyed as ra
    assert indic_shaping.key_bytes((indic_shaping.INIT_CP, 0x09C7), spec) == bytes([0x02, 0xC7])
    assert indic_shaping.key_bytes((0x09BE, indic_shaping.FINA_CP), spec) == bytes([0xBE, 0x03])
    assert indic_shaping.key_bytes((0x09B0, 0x09CD, indic_shaping.ZWJ, 0x09AF), spec) == bytes([0xB0, 0xCD, 0x01, 0xAF])
    with pytest.raises(ValueError):
        indic_shaping.key_bytes((0x0915,), spec)  # Devanagari letter in a Bengali key


def test_pack_table_rejects_duplicate_keys():
    """Two rows with one key: the packed table would hold both, the device finds one,
    and the other's glyph is allocated but unreachable (the fold of 2026-09-26
    wrote such rows for Noto Serif Bengali)."""
    spec = indic_shaping.SCRIPTS["bengali"]
    ka, virama, ta = 0x0995, 0x09CD, 0x09A4
    with pytest.raises(ValueError, match="duplicate cluster key"):
        indic_shaping.pack_table([((ka, virama, ta), 0xE000, 0, 0, False), ((ka, virama, ta), 0xE001, 0, 0, False)],
                                 spec)


def test_pack_table_layout_and_order():
    # Packed layout (format 3): a directory of (u16 entry count, u8 bucket
    # count) per key length 2..7, then per length its bucket index (first
    # key byte, u16 count) and entries (key bytes after the first, meta =
    # length | continues << 3 | pre class << 4, value = post class << 13 |
    # cp - 0xE000). The format marker 06 06 is a length-2 entry.
    spec = indic_shaping.SCRIPTS["bengali"]
    D = indic_shaping.PACKED_DIRECTORY_BYTES
    table = indic_shaping.pack_table({(0x09A8, 0x09CD, 0x09A4): 0xE001, (0x0995, 0x09CD, 0x09B7): 0xE000}, spec)
    assert table[:D] == struct.pack("<HB", 1, 1) + struct.pack("<HB", 2, 2) + bytes(3 * 4)
    assert table[D:D + 3] == bytes([0x06, 1, 0])                                   # length 2: one bucket, 0x06
    assert table[D + 3:D + 7] == bytes([0x06, 2, indic_shaping.TABLE_FORMAT, 0x00])  # 06 06 -> the format
    assert table[D + 7:D + 13] == bytes([0x95, 1, 0, 0xA8, 1, 0])                  # length 3: buckets 0x95, 0xA8
    assert table[D + 13:D + 18] == bytes([0xCD, 0xB7, 3, 0x00, 0x00])              # ক্ষ -> U+E000
    assert table[D + 18:D + 23] == bytes([0xCD, 0xA4, 3, 0x01, 0x00])              # ন্ত -> U+E001
    assert len(table) == D + 23
    assert indic_shaping.table_entry_count(table) == 3
    assert indic_shaping.packed_table_bytes(table[:D]) == len(table)
    assert indic_shaping.unpack_table(table) == [
        (bytes([0x06, 0x06]), 2, indic_shaping.TABLE_FORMAT),
        (bytes([0x95, 0xCD, 0xB7]), 3, 0),
        (bytes([0xA8, 0xCD, 0xA4]), 3, 1),
    ]
    packed = indic_shaping.pack_table([
        ((0x0995, 0x09CD, 0x09B7), 0xF234, 5, 1, True),
        ((indic_shaping.CLASS_CP, 0x0995), None, 2, 3, False),
        ((indic_shaping.VARIANT_CP, 0x09BF, indic_shaping.CLASS_INDEX_CP + 4), 0xF400, 0, 0, False),
    ], spec)
    rows = indic_shaping.unpack_table(packed)
    assert rows[0] == (bytes([0x04, 0x95]), 0x22, 0x7FFF)                # no glyph, pre 2, post 3
    assert rows[1] == (bytes([0x06, 0x06]), 2, indic_shaping.TABLE_FORMAT)
    assert rows[2] == (bytes([0x05, 0xBF, 0x14]), 3, 0x1400)             # variant class 4 -> U+F400
    assert rows[3] == (bytes([0x95, 0xCD, 0xB7]), 0x5B, 0x3234)          # continues, pre 5, post 1, U+F234
    with pytest.raises(ValueError):
        indic_shaping.pack_table({(0x0995,): 0xE000}, spec)
    with pytest.raises(ValueError):
        indic_shaping.pack_table({(0x0995, 0x09CD, 0x0995, 0x09CD, 0x0995, 0x09CD): 0xE000}, spec)
    with pytest.raises(ValueError):
        indic_shaping.pack_table([((0x0995, 0x09CD, 0x09B7), 0xE000, 16, 0, False)], spec)


def test_script_selection_from_intervals():
    assert indic_shaping.script_for_intervals([(0x0980, 0x09FF)]) is indic_shaping.SCRIPTS["bengali"]
    assert indic_shaping.script_for_intervals([(0x0900, 0x097F)]) is indic_shaping.SCRIPTS["devanagari"]
    assert indic_shaping.script_for_intervals([(0x0020, 0x007E)]) is None
    with pytest.raises(ValueError):
        indic_shaping.script_for_intervals([(0x0900, 0x09FF)])  # two shaped scripts in one font
    assert indic_shaping.SCRIPTS["devanagari"].shape_kind == 2 and indic_shaping.SCRIPTS["devanagari"].entry_size == 10
    assert indic_shaping.SCRIPTS["devanagari"].join_style == "half" and indic_shaping.SCRIPTS["devanagari"].reph_after_post
    bengali = indic_shaping.SCRIPTS["bengali"]
    assert indic_shaping.script_for_intervals(bengali.intervals) is bengali
    assert indic_shaping.entry_size_for_kind(bengali.shape_kind) == 8
    assert indic_shaping.entry_size_for_kind(0) == 0
    assert indic_shaping.entry_size_for_kind(99) == 0


def test_table_kind_geometry_matches_the_device():
    # Script.h: kind 1 at key[5] + meta + u16 (unpacked row), kinds 2..10 key[7].
    assert indic_shaping.SCRIPTS["bengali"].shape_kind == 1
    assert indic_shaping.SCRIPTS["devanagari"].shape_kind == 2
    assert indic_shaping.SHAPE_KIND_LAST == 10
    assert indic_shaping.max_key_len_for_kind(1) == 5
    for kind in range(2, 11):
        assert indic_shaping.max_key_len_for_kind(kind) == 7
        assert indic_shaping.entry_size_for_kind(kind) == 10
    assert indic_shaping.max_key_len_for_kind(11) == 0
    assert indic_shaping.entry_size_for_kind(11) == 0
    assert indic_shaping.SCRIPTS["bengali"].max_key_len == 5
    assert indic_shaping.SCRIPTS["bengali"].entry_size == 8
    assert indic_shaping.MAX_TABLE_BYTES == 16384


def test_pack_table_for_a_wide_kind():
    # Bengali letters under kind 2 stand in for the scripts that allow 7-byte
    # keys; a seven-byte key lands in the length-7 section of the packed table.
    spec = dataclasses.replace(indic_shaping.SCRIPTS["bengali"], name="kind2", shape_kind=2)
    assert spec.max_key_len == 7 and spec.entry_size == 10
    seven = (0x0995, 0x09CD, 0x09B7, 0x09CD, 0x09A3, 0x09CD, 0x09AF)
    table = indic_shaping.pack_table({seven: 0xE001, (0x0995, 0x09CD, 0x09B7): 0xE000}, spec)
    D = indic_shaping.PACKED_DIRECTORY_BYTES
    assert table[:D] == struct.pack("<HB", 1, 1) + struct.pack("<HB", 1, 1) + bytes(3 * 3) + struct.pack("<HB", 1, 1)
    assert len(table) == D + (3 + 4) + (3 + 5) + (3 + 9)
    assert indic_shaping.unpack_table(table) == [
        (bytes([0x06, 0x06]), 2, indic_shaping.TABLE_FORMAT),
        (bytes([0x95, 0xCD, 0xB7]), 3, 0),
        (bytes([0x95, 0xCD, 0xB7, 0xCD, 0xA3, 0xCD, 0xAF]), 7, 1),
    ]
    with pytest.raises(ValueError):
        indic_shaping.pack_table({seven + (0x09CD, 0x0995): 0xE000}, spec)


def test_pua_classes_tile_without_overlap():
    ranges = sorted(indic_shaping.PUA_RANGES.values())
    assert ranges[0] == (0xE000, 0xEFFF)
    for (_, prev_end), (start, _) in zip(ranges, ranges[1:]):
        assert start == prev_end + 1
    assert ranges[-1] == (0xF800, 0xF8FF)
    assert set(indic_shaping.MARK_KINDS) == {"below", "above", "above_center", "below_right"}


def _deva_face(path):
    face = freetype.Face(path)
    face.set_char_size(SIZE << 6, SIZE << 6, 150, 150)
    return face, (SIZE * 150.0 / 72.0) / face.units_per_EM


def test_mark_runs_are_rasterised_at_their_own_origin():
    """A fused mark (Noto Serif Devanagari's ai sign + anusvara ligature) is shaped after a
    probe consonant. Its bitmap must sit at the glyph's own origin, not carry that
    consonant's GPOS offset: with v5 anchors the device adds the real base's anchor, and the
    doubled offset drew हैं with the sign 10 px left of the letter (2026-09-14)."""
    spec = indic_shaping.SCRIPTS["devanagari"]
    path = _font(GOLDEN["NotoSerifDevanagari"][0])
    face, unit_scale = _deva_face(path)
    anchors = {}
    kind, table, forms = indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER,
                                                     anchors_out=anchors)
    ai, anusvara, ha = 0x0948, 0x0902, 0x0939
    cp, form = next((cp, f) for cp, f in forms.items() if f.key == (ai, anusvara))
    assert form.kind in indic_shaping.MARK_KINDS
    assert len(form.run.glyphs) == 1 and form.run.glyphs[0][2] != 0  # one ligature glyph, probe offset present
    bmp = indic_shaping.render_run(face, form.run, unit_scale, freetype.FT_LOAD_RENDER, mark=True)
    width, height, left, top, rows = indic_shaping._glyph_gray(face, form.run.gids[0], freetype.FT_LOAD_RENDER)
    assert (bmp.left, bmp.top, bmp.width) == (left, top, width)
    # End to end: the ink of the fused mark on ह lands where HarfBuzz + FreeType put it (±1 px).
    plan = indic_shaping.IndicClusterPlan(path, spec)
    run = plan.shape((ha, ai, anusvara))
    assert run.gids[1:] == list(form.run.gids)
    hb_ink_left = round((run.glyphs[0][1] + run.glyphs[1][2]) * unit_scale) + left
    ha_adv_px = int(round(plan.shape((ha,)).glyphs[0][1] * unit_scale))
    device_ink_left = indic_shaping.mark_offset_px(False, anchors[ha], ha_adv_px, anchors[cp][:2]) + bmp.left
    assert abs(device_ink_left - hb_ink_left) <= 1.0


def test_bare_vowel_sign_anchors_the_anusvara_where_harfbuzz_does():
    """Tiro Devanagari Sanskrit does not fuse ों: the anusvara is a mark on the ो glyph, and
    ो never carries the e-sign probe, so its anchor must come from a mark that occurs on it.
    Before the bare-sign rule the dot sat inside the hook of कों."""
    spec = indic_shaping.SCRIPTS["devanagari"]
    path = _font(("TiroDevanagariSanskrit-Regular.ttf",))
    face, unit_scale = _deva_face(path)
    anchors = {}
    indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER, anchors_out=anchors)
    ka, o_sign, anusvara = 0x0915, 0x094B, 0x0902
    plan = indic_shaping.IndicClusterPlan(path, spec)
    run = plan.shape((ka, o_sign, anusvara))
    assert [g[0] for g in run.glyphs] == [plan.gid(ka), plan.gid(o_sign), plan.gid(anusvara)]
    hb_x = (run.glyphs[1][1] + run.glyphs[2][2]) * unit_scale  # from the ो origin
    o_adv_px = int(round(run.glyphs[1][1] * unit_scale))
    device_x = indic_shaping.mark_offset_px(False, anchors[o_sign], o_adv_px, anchors[anusvara][:2])
    assert abs(device_x - hb_x) <= 1.0


def test_zero_metric_letters_take_their_harfbuzz_advance():
    """Tiro Bangla's anusvara and visarga have no hmtx advance and are spaced by a GPOS
    rule; the converter must give them HarfBuzz's advance or the next letter overprints
    them (বাংলা). Noto Serif Bengali needs no override."""
    spec = indic_shaping.SCRIPTS["bengali"]
    tiro = _font(GOLDEN["TiroBangla"][0])
    face, unit_scale = _deva_face(tiro)
    advances = {}
    indic_shaping.build_shaping(tiro, spec, face, unit_scale, freetype.FT_LOAD_RENDER, advances_out=advances)
    anusvara, visarga = 0x0982, 0x0983
    assert set(advances) >= {anusvara, visarga}
    plan = indic_shaping.IndicClusterPlan(tiro, spec)
    run = plan.shape((0x0995, anusvara))
    assert advances[anusvara] == round(run.glyphs[1][1] * unit_scale * 16) > 0
    noto = _font(GOLDEN["NotoSerifBengali"][0])
    face, unit_scale = _deva_face(noto)
    advances = {}
    indic_shaping.build_shaping(noto, spec, face, unit_scale, freetype.FT_LOAD_RENDER, advances_out=advances)
    assert advances == {}


def test_danda_takes_the_fonts_single_adjustment():
    """Tiro Bangla puts space before its danda and double danda through a GPOS single
    adjustment (advance and x offset); the converter gives them HarfBuzz's advance and
    shifts the bitmap right by the offset. Noto Serif Bengali has no such rule."""
    spec = indic_shaping.SCRIPTS["bengali"]
    tiro = _font(GOLDEN["TiroBangla"][0])
    face, unit_scale = _deva_face(tiro)
    advances, lefts = {}, {}
    indic_shaping.build_shaping(tiro, spec, face, unit_scale, freetype.FT_LOAD_RENDER,
                                advances_out=advances, lefts_out=lefts)
    plan = indic_shaping.IndicClusterPlan(tiro, spec)
    for danda in (0x0964, 0x0965):
        run = plan.shape((0x0995, danda))
        advance, x_offset = run.glyphs[1][1], run.glyphs[1][2]
        assert x_offset > 0 and advance > plan.font.get_glyph_h_advance(plan.gid(danda))
        assert advances[danda] == round(advance * unit_scale * 16)
        assert lefts[danda] == round(x_offset * unit_scale) > 0
    assert set(lefts) == {0x0964, 0x0965}
    noto = _font(GOLDEN["NotoSerifBengali"][0])
    face, unit_scale = _deva_face(noto)
    advances, lefts = {}, {}
    indic_shaping.build_shaping(noto, spec, face, unit_scale, freetype.FT_LOAD_RENDER,
                                advances_out=advances, lefts_out=lefts)
    assert advances == {} and lefts == {}


def test_danda_space_share_follows_the_font():
    """Tiro drops the danda's built-in space after a space character ("X ।" and
    "X।" put the danda in the same place); the table records that space as a
    share of the danda's advance, the same at every size. Noto has none."""
    spec = indic_shaping.SCRIPTS["bengali"]
    tiro = _font(GOLDEN["TiroBangla"][0])
    plan = indic_shaping.IndicClusterPlan(tiro, spec)
    leads = indic_shaping.danda_space_leads(plan)
    assert set(leads) == {1, 2}
    for index, danda in ((1, 0x0964), (2, 0x0965)):
        after_letter = plan.shape((0x0995, danda)).glyphs[1]
        after_space = plan.shape((0x0020, danda)).glyphs[1]
        assert after_space[2] == 0 < after_letter[2]
        assert leads[index] == round((after_letter[2] - after_space[2]) * 256 / after_letter[1])
    _kind, table, _forms = _build(tiro, spec)
    rows = {kb: value for kb, _meta, value in indic_shaping.unpack_table(table)}
    assert rows[bytes([0x06, 0x02, 0x11])] == leads[1] and rows[bytes([0x06, 0x02, 0x12])] == leads[2]
    noto = _font(GOLDEN["NotoSerifBengali"][0])
    assert indic_shaping.danda_space_leads(indic_shaping.IndicClusterPlan(noto, spec)) == {}


def test_danda_flag_follows_the_font():
    """Tiro Bangla draws word-final forms before a danda (বা।), Noto Serif Bengali
    does not; the table carries the flag only for the first."""
    spec = indic_shaping.SCRIPTS["bengali"]
    flag = bytes([0x06, 0x03])
    for names, expected in ((GOLDEN["TiroBangla"][0], True), (GOLDEN["NotoSerifBengali"][0], False)):
        _kind, table, _forms = _build(_font(names), spec)
        rows = indic_shaping.unpack_table(table)
        assert any(kb == flag for kb, _meta, _value in rows) == expected


def test_pack_table_danda_flag_row():
    spec = indic_shaping.SCRIPTS["bengali"]
    plain = indic_shaping.pack_table({(0x0995, 0x09CD, 0x09B7): 0xE000}, spec)
    flagged = indic_shaping.pack_table({(0x0995, 0x09CD, 0x09B7): 0xE000}, spec, danda_ends_word=True)
    assert len(flagged) == len(plain) + 4  # one more length-2 entry in the 0x06 bucket the marker already opened
    row = next(r for r in indic_shaping.unpack_table(flagged) if r[0] == bytes([0x06, 0x03]))
    assert row[1] & 0x07 == 2 and row[2] == 0x1FFF


def test_half_form_flag_follows_the_font():
    """Hind Siliguri joins Bengali conjuncts with half forms (29 of 32
    consonants at the 2026-09-18 build), Noto Serif Bengali subjoins; the
    builder switches the strategy and flags the table only for the first."""
    spec = indic_shaping.SCRIPTS["bengali"]
    flag = bytes([0x06, 0x01])
    for names, expected in ((GOLDEN["HindSiliguri"][0], True), (GOLDEN["NotoSerifBengali"][0], False)):
        path = _font(names)
        plan = indic_shaping.IndicClusterPlan(path, spec)
        assert bool(plan.half_forms_from_font) == expected
        assert (plan.spec.join_style == "half") == expected
        _kind, table, _forms = _build(path, spec)
        rows = indic_shaping.unpack_table(table)
        assert any(kb == flag for kb, _meta, _value in rows) == expected
        half_keys = sum(1 for kb, _meta, _value in rows
                        if len(kb) == 3 and kb[1] == 0x80 | (0x09CD - spec.block_base) and kb[2] == 0x01)
        assert (half_keys > 0) == expected


def test_below_anchor_probe_is_chosen_by_outcome():
    """Noto Sans Bengali draws the ba-phala mark on a homogeneous few conjuncts;
    scored only where it exists it beat ু as the below probe and left every
    rakar conjunct 7 px off (2026-09-18). The probe is now chosen by the
    residual over every base and mark pair: ু lands within a pixel of HarfBuzz
    both on ka and on ক্ম্র, whose ু hangs from the ra-phala."""
    spec = indic_shaping.SCRIPTS["bengali"]
    path = _font(GOLDEN["NotoSansBengali"][0])
    face = freetype.Face(path)
    face.set_char_size(SIZE << 6, SIZE << 6, 150, 150)
    unit_scale = (SIZE * 150.0 / 72.0) / face.units_per_EM
    anchors = {}
    _kind, _table, forms = indic_shaping.build_shaping(path, spec, face, unit_scale, freetype.FT_LOAD_RENDER,
                                                       anchors_out=anchors)
    plan = indic_shaping.IndicClusterPlan(path, spec)
    u_sign = 0x09C1
    kmra = next(cp for cp, f in forms.items() if f.key == (0x0995, 0x09CD, 0x09AE, 0x09CD, 0x09B0))
    for base, text in ((0x0995, (0x0995,)), (kmra, (0x0995, 0x09CD, 0x09AE, 0x09CD, 0x09B0))):
        run = plan.shape(text + (u_sign,))
        hb_px = (sum(g[1] for g in run.glyphs[:-1]) + run.glyphs[-1][2]) * unit_scale
        adv_px = int(round(sum(g[1] for g in run.glyphs[:-1]) * unit_scale))
        device_px = indic_shaping.mark_offset_px(True, anchors[base], adv_px, anchors[u_sign][:2])
        assert abs(device_px - hb_px) <= 1.0, (hex(base), device_px, hb_px)


def test_second_pre_sign_classes_follow_the_font():
    """Noto Sans Bengali draws ে.long on six letters and ে.long.init at the
    start of a word: the builder folds both into the classes ি already uses
    (variant lists keyed sign + class and INIT + sign + class); Noto Serif
    Bengali has no such variants and gets no ে lists at all."""
    spec = indic_shaping.SCRIPTS["bengali"]
    for names, expected in ((GOLDEN["NotoSansBengali"][0], True), (GOLDEN["NotoSerifBengali"][0], False)):
        _kind, _table, forms = _build(_font(names), spec)
        e_lists = [f for f in forms.values() if f.key[0] == indic_shaping.VARIANT_CP and 0x09C7 in f.key]
        init_lists = [f for f in e_lists if f.key[1] == indic_shaping.INIT_CP]
        assert bool(e_lists) == expected and bool(init_lists) == expected
        if expected:
            classes = {f.key[-1] for f in e_lists}
            assert classes <= {indic_shaping.CLASS_INDEX_CP + n for n in range(1, indic_shaping.MAX_SIGN_CLASS + 1)}
            i_lists = [f for f in forms.values() if f.key[0] == indic_shaping.VARIANT_CP and f.key[1] == 0x09BF]
            assert i_lists, "ি keeps its own lists on the shared classes"


def test_pack_table_half_form_flag_row():
    spec = indic_shaping.SCRIPTS["bengali"]
    plain = indic_shaping.pack_table({(0x0995, 0x09CD, 0x09B7): 0xE000}, spec)
    flagged = indic_shaping.pack_table({(0x0995, 0x09CD, 0x09B7): 0xE000}, spec, half_forms=True)
    assert len(flagged) == len(plain) + 4  # one more length-2 entry in the marker's 0x06 bucket
    row = next(r for r in indic_shaping.unpack_table(flagged) if r[0] == bytes([0x06, 0x01]))
    assert row[1] & 0x07 == 2 and row[2] == 0x1FFF


def test_spec_mark_sets_are_consistent():
    # Every anchored or below-attached mark is non-spacing, no mark is in two
    # anchor classes, and the below-sign audit set is drawn below.
    for spec in indic_shaping.SCRIPTS.values():
        marks = set(spec.marks)
        assert set(spec.attach_below) <= marks
        classes = [set(spec.anchor_center), set(spec.anchor_right), set(spec.anchor_pen)]
        for i, a in enumerate(classes):
            assert a <= marks
            for b in classes[i + 1:]:
                assert not (a & b)
        assert set(spec.below_signs) <= set(spec.attach_below)
        assert all(spec.in_block(cp) for cp in marks)
        assert spec.is_mark(indic_shaping.PUA_ABOVE[0]) and not spec.is_mark(indic_shaping.PUA_PRE[0])


def test_sign_variants_are_surveyed_after_a_letter_of_their_class():
    """A width-class variant of ी only appears after a consonant of its class; shaped
    alone, ी comes out behind a dotted circle, and the marks measured on it carried the
    circle's width (Tiro Sanskrit's anusvara on ी.class1 drawn ~25 px right of लीं). The
    survey measures the variant after a class letter and never accepts a dotted-circle
    run as a base."""
    spec = indic_shaping.SCRIPTS["devanagari"]
    path = _font(("TiroDevanagariSanskrit-Regular.ttf",))
    plan = indic_shaping.IndicClusterPlan(path, spec)
    forms = plan.build(lambda m: None)
    _k2c, c2f = indic_shaping.allocate_pua(forms, spec)
    survey = indic_shaping.MarkSurvey(plan, c2f)
    plain = survey.origins[0x0902][0x0940]
    variants = [cp for cp, f in c2f.items() if f.key[0] == indic_shaping.VARIANT_CP and f.key[1] == 0x0940]
    measured = [survey.origins[0x0902][cp] for cp in variants if survey.origins[0x0902][cp] is not None]
    assert measured, "no ी variant measured"
    upem = plan.font.face.upem
    assert all(abs(x - plain) < 0.1 * upem for x in measured), (plain, measured)


def test_mark_lifts_follow_the_font_where_one_height_fits():
    """Noto Serif Bengali lowers ঁ on nearly every letter: the lift moves the glyph
    down, and the tall independent vowels the font keeps it high on get base +
    candrabindu composites (ইঁদুর would otherwise touch). Noto Sans ু follows the base
    (under conjuncts it sits lower), so no constant is applied to it."""
    spec = indic_shaping.SCRIPTS["bengali"]
    serif = _font(GOLDEN["NotoSerifBengali"][0])
    plan = indic_shaping.IndicClusterPlan(serif, spec)
    forms = plan.build(lambda m: None)
    _k2c, c2f = indic_shaping.allocate_pua(forms, spec)
    lifts = indic_shaping.mark_lifts(indic_shaping.MarkSurvey(plan, c2f), c2f, lambda m: None)
    assert lifts[(0x0981,)] < -0.03 * plan.font.face.upem
    assert plan.add_lift_exceptions(lifts, lambda m: None) >= 2
    assert (0x0987, 0x0981) in plan._table and (0x0995, 0x0981) not in plan._table
    face, unit_scale = _deva_face(serif)
    tops = {}
    indic_shaping.build_shaping(serif, spec, face, unit_scale, freetype.FT_LOAD_RENDER, log=lambda m: None,
                                tops_out=tops)
    assert tops[0x0981] == round(lifts[(0x0981,)] * unit_scale) < 0
    sans = _font(GOLDEN["NotoSansBengali"][0])
    plan = indic_shaping.IndicClusterPlan(sans, spec)
    forms = plan.build(lambda m: None)
    _k2c, c2f = indic_shaping.allocate_pua(forms, spec)
    lifts = indic_shaping.mark_lifts(indic_shaping.MarkSurvey(plan, c2f), c2f, lambda m: None)
    assert (0x09C1,) not in lifts


def test_bengali_pass_forms_follow_the_font():
    """Bengali pass (2026-09-25). Hind Siliguri: the taller ৗ after খ গ ঝ ণ থ প শ is a
    per-base form (also with ঁ, which a generic ৗ+ঁ form would otherwise replace), and
    ি+ঁ fuse into one glyph, so the fused sign is a generic form rather than an empty
    ঁ variant (the candrabindu vanished from কিঁউ). Noto Sans Bengali: ঁ follows the
    ya-phala when া does (ক্যাঁ), keyed with the sign; a reph composite (র্থ) carries
    its letter's class, since the font sizes ে by the letter under the reph."""
    spec = indic_shaping.SCRIPTS["bengali"]
    hind = indic_shaping.IndicClusterPlan(_font(GOLDEN["HindSiliguri"][0]), spec)
    hind.build(lambda m: None)
    name = hind.font.glyph_to_string
    assert name(hind._table[(0x09B6, 0x09D7)][0]).endswith(".taller")
    assert name(hind._table[(0x09AA, 0x09D7, 0x0981)][0]).endswith(".taller")
    assert (0x0995, 0x09D7) not in hind._table  # ক keeps the plain ৗ
    assert [name(g) for g in hind._table[(0x09BF, 0x0981)]] == ["bnmI_Candrabindu"]
    assert (0x0981, 0x09BF) not in hind._table
    sans = indic_shaping.IndicClusterPlan(_font(GOLDEN["NotoSansBengali"][0]), spec)
    sans.build(lambda m: None)
    name = sans.font.glyph_to_string
    assert [name(g) for g in sans._table[(0x09CD, 0x09AF, 0x09BE, 0x0981)]] == ["uni09AF.pstf", "uni0981", "uni09BE"]
    rtha = next(f for f in sans.forms if f.key == (0x09B0, 0x09CD, 0x09A5))
    tha = next(f for f in sans.forms if f.key == (indic_shaping.CLASS_CP, 0x09A5))
    assert rtha.pre_class == tha.pre_class != 0


def test_devanagari_pass_forms_follow_the_font():
    """Devanagari pass (2026-09-25). Noto Serif Devanagari sizes ि before a half form by
    the glyph after it (a class-pair rule in its GSUB, षि + व -> ि.12): half forms get
    rows and the table cells name the class, which the device resolves through its
    class lists. Tiro Devanagari Sanskrit keeps its half forms although स्+क is a
    ligature (अन्तस्स्थानि draws स् before स्थ)."""
    spec = indic_shaping.SCRIPTS["devanagari"]
    noto = indic_shaping.IndicClusterPlan(_font(GOLDEN["NotoSerifDevanagari"][0]), spec)
    forms = noto.build(lambda m: None)
    rows = {f.key: f.pre_class | (f.post_class << 4) for f in forms
            if f.key[0] == indic_shaping.CLASS_CP and f.key[-1] == indic_shaping.ZWJ}
    ssa_row = rows[(indic_shaping.CLASS_CP, 0x0937, 0x094D, indic_shaping.ZWJ)]
    va_class = next(f.pre_class for f in forms if f.key == (indic_shaping.CLASS_CP, 0x0935))
    cell = next(f for f in forms if f.key == (indic_shaping.VARIANT_CP, indic_shaping.ZWJ, 0x093F,
                                               spec.block_base + ssa_row, indic_shaping.CLASS_INDEX_CP + va_class + 1))
    variant = next(f for f in forms if f.key == (indic_shaping.VARIANT_CP, 0x093F, indic_shaping.CLASS_INDEX_CP + cell.pre_class))
    assert noto.font.glyph_to_string(variant.run.gids[0]) == "uni093F.12"
    tiro = indic_shaping.IndicClusterPlan(_font(("TiroDevanagariSanskrit-Regular.ttf",)), spec)
    tiro.build(lambda m: None)
    assert (0x0938, 0x094D, indic_shaping.ZWJ) in tiro._table


# --- tools/fontcheck.py: the tools only trust a table that is the font's own build ---

def _fake_cpfont(path, spec, table):
    """A .cpfont with just the header, one style TOC entry and the packed table."""
    header = bytearray(32)
    header[:8] = b"CPFONT\0\0"
    header[12] = 1  # style count
    toc = struct.pack("<BBHIIBhhHHBBBII", 0, spec.shape_kind | indic_shaping.TOC_KIND_PACKED,
                      indic_shaping.table_entry_count(table), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 64, 64)
    with open(path, "wb") as f:
        f.write(bytes(header) + toc + table)


def _first_value_offset(table):
    """Byte offset of the first row's value in a packed table (mirror of unpack_table)."""
    pos = indic_shaping.PACKED_DIRECTORY_BYTES
    for length in range(indic_shaping.PACKED_MIN_KEY_LEN, indic_shaping.PACKED_MAX_KEY_LEN + 1):
        count, buckets = struct.unpack_from("<HB", table, (length - indic_shaping.PACKED_MIN_KEY_LEN) * 3)
        pos += 3 * buckets
        if count:
            return pos + length  # key bytes (length - 1) + meta, then the value
    raise AssertionError("empty table")


def test_tools_trust_only_the_fonts_own_table(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import fontcheck
    names, script, count, _digest = GOLDEN["TiroBangla"]
    spec = indic_shaping.SCRIPTS[script]
    ttf = _font(names)
    _kind, table, forms = _build(ttf, spec)
    good = tmp_path / "TiroBangla_12.cpfont"
    _fake_cpfont(good, spec, table)
    loaded = fontcheck.load(ttf, str(good))
    assert loaded.table == table and loaded.size == SIZE and loaded.spec is spec
    assert f"{count} rows, identical to a fresh build at 12 pt" in loaded.header
    assert set(loaded.cp_to_form) == set(forms)
    # Every form with a run maps to HarfBuzz glyph names, the device-side truth for the tools.
    runs = fontcheck.runs(loaded, hb.Font(hb.Face(hb.Blob.from_file_path(ttf))))
    assert len(runs) == sum(1 for f in forms.values() if f.run is not None) > 900
    assert all(names_ and all(isinstance(n, str) and n for n in names_) for names_ in runs.values())
    # The same table with one glyph value changed (a table from another build) is refused, key named.
    other = bytearray(table)
    off = _first_value_offset(table)
    other[off] ^= 0x01
    bad = tmp_path / "Other_12.cpfont"
    _fake_cpfont(bad, spec, bytes(other))
    with pytest.raises(fontcheck.TableMismatch, match="1 with another value, first "):
        fontcheck.load(ttf, str(bad))
    # A table with a row missing is refused too.
    rows = indic_shaping.unpack_table(table)
    fewer = indic_shaping.pack_rows([r for r in rows[:-1]]) if hasattr(indic_shaping, "pack_rows") else None
    if fewer is not None:
        shorter = tmp_path / "Short_12.cpfont"
        _fake_cpfont(shorter, spec, fewer)
        with pytest.raises(fontcheck.TableMismatch, match="only in the build"):
            fontcheck.load(ttf, str(shorter))
