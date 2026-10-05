"""Lipi cluster pre-shaping for .cpfont generation (the CrossInk SD-card font container).

The reader has no OpenType engine, so conjuncts (ক্ষ, ন্ত্র, क्ष, ...),
reph, ra-phala and the vowel-sign ligatures a font builds through GSUB/GPOS
cannot be resolved on the device. Instead the shaping is done here, once, at
font build time, driven by a ScriptSpec per script (providers/<script>/spec.py;
the device side is engine/ with the matching ScriptDesc):

  * Consonant clusters are enumerated and shaped with HarfBuzz. Every glyph
    run the device could not reproduce from smaller pieces is rasterised as
    ONE composite bitmap (GPOS positioning baked in) and assigned a Private
    Use Area codepoint.
  * Standalone forms the device composes itself (reph, subjoined ra/ya/ba
    forms) get their own PUA codepoints, in ranges that tell the renderer
    whether they are spacing glyphs, below-base marks or above-base marks.
  * A cluster table (logical codepoint sequence -> PUA codepoint) is written
    into the .cpfont. The firmware's Lipi engine splits text into
    orthographic syllables, reorders pre-base vowel signs, and resolves each
    consonant cluster through this table with longest-match lookups.

Table layout (format 3, packed; pack_rows / unpack_table, Lipi Script.h):
an 18-byte directory (per key length 2..7: u16 entry count, u8 bucket
count), then per length its bucket index (first key byte, u16 count) and
its entries, each the key bytes after the first, a meta byte and a u16
value, sorted so the device finds a key by length, first byte and a
binary search on the rest:

  key      cluster codepoints, one byte each: 0x80 | (cp - block base) for
           the script's block, 0x01 for ZWJ, 0x02
           for the word-initial marker, 0x03 for the word-final marker.
           Letters in spec.ra_folds (the Assamese ra U+09F0) are
           keyed as the script's ra: fonts shape them the same way inside a
           conjunct.
  meta     bits 0-2 key length (2..max_key_len), bit 3 continues, bits 4-7
           the pre-sign class
  value    u16: bits 13-15 the post-sign class, bits 0-12 the output
           codepoint minus 0xE000 (0x1FFF = no glyph)

Kind 1 allows 5-byte keys; kinds 2..SHAPE_KIND_LAST 7-byte keys. A table
may not exceed MAX_TABLE_BYTES: the device keeps it resident per style and
ignores anything larger.

Besides consonant clusters, keys cover the vowel-sign forms an OpenType
engine would pick by context, so the device reproduces the desktop rendering:

  cluster + below vowel      রু হু গু ligatures (composite)
  cluster + ি                ি sized to a wide base, or fused (টি, ষ্টি)
  ra virama cluster + ি      ি fused with the reph (র্তি)
  cluster + ী [+ FINA]       ী variants after wide bases, word-final ী
  ra virama + ী [+ FINA]     ী fused with the reph (র্তী)
  INIT + ে / ৈ               word-initial forms of the pre-base signs
  FINA + া / ী               word-final forms of the post-base signs

PUA allocation (mirrors engine/Script.h and Registry.h on the device):

  U+E000..U+EFFF  spacing glyphs (composites, subjoined post-base forms)
  U+F000..U+F0FF  below-base marks centred under the base (ra-phala, ba-phala, ...)
  U+F100..U+F1FF  above-base marks anchored at the base's right edge (reph)
  U+F200..U+F2FF  above-base marks centred on the base (tippi, addak, above vowel forms)
  U+F300..U+F3FF  below-base marks anchored at the base's right edge (subjoined consonants)
  U+F400..U+F5FF  pre-base sign forms: drawn instead of ি/ে/ৈ before the cluster
  U+F600..U+F7FF  post-base sign forms: drawn instead of া/ী after the cluster
  U+F800..U+F8FF  pre-base consonant forms: spacing glyphs drawn before the cluster (Malayalam ്ര)
"""

from __future__ import annotations

import collections
import dataclasses
import functools
import os
import struct
import sys

# --- Script data and table format --------------------------------------------
# The per-script specs live in providers/*/spec.py (collected by
# builder/registry.py) and the table format constants in builder/spec.py; they
# are re-exported here for the converter, the tests and the tools.

from builder.registry import SCRIPTS  # noqa: E402,F401
from builder.spec import (  # noqa: E402,F401
    ScriptSpec,
    CLASS_CP, CLASS_INDEX_CP, FINA_CP, FORMAT_CP, INIT_CP, KEY_CLASS, KEY_CLASS_INDEX, KEY_FINA, KEY_FORMAT, KEY_INIT,
    KEY_VARIANT, KEY_ZWJ, KIND_ABOVE, KIND_BASE, KIND_BELOW, KIND_META, KIND_POST,
    KIND_PRE, MARK_KINDS, MAX_SIGN_CLASS, MAX_TABLE_BYTES, PUA_ABOVE, PUA_BASE,
    PACKED_DIRECTORY_BYTES, PACKED_MAX_KEY_LEN, PACKED_MIN_KEY_LEN, TOC_KIND_PACKED,
    PUA_BELOW, PUA_POST, PUA_PRE, PUA_RANGES, SHAPE_KIND_LAST, TABLE_FORMAT,
    VALUE_NO_GLYPH, VARIANT_CP, ZWJ, entry_size_for_kind, max_key_len_for_kind,
)


def script_for_intervals(intervals):
    """The ScriptSpec whose block the intervals cover, or None. Two shaped
    scripts in one font are an error: each family carries one table."""
    found = [spec for spec in SCRIPTS.values() if any(start <= spec.probe <= end for start, end in intervals)]
    if len(found) > 1:
        raise ValueError("a font can pre-shape one script only, intervals cover "
                         + ", ".join(spec.name for spec in found))
    return found[0] if found else None


def key_bytes(seq, spec):
    """Encode a cluster codepoint sequence as table key bytes (no padding)."""
    out = bytearray()
    for cp in seq:
        if cp == ZWJ:
            out.append(KEY_ZWJ)
        elif cp == INIT_CP:
            out.append(KEY_INIT)
        elif cp == FINA_CP:
            out.append(KEY_FINA)
        elif cp == CLASS_CP:
            out.append(KEY_CLASS)
        elif cp == VARIANT_CP:
            out.append(KEY_VARIANT)
        elif cp == FORMAT_CP:
            out.append(KEY_FORMAT)
        elif CLASS_INDEX_CP < cp <= CLASS_INDEX_CP + MAX_SIGN_CLASS:
            out.append(KEY_CLASS_INDEX | (cp - CLASS_INDEX_CP))
        elif cp in spec.ra_folds:
            out.append(0x80 | (spec.ra - spec.block_base))
        elif spec.in_block(cp):
            out.append(0x80 | (cp - spec.block_base))
        else:
            raise ValueError(f"codepoint U+{cp:04X} cannot appear in a cluster key")
    return bytes(out)


def pack_entry(seq, cp, spec, pre_class=0, post_class=0, continues=False):
    """One table entry as (key bytes, meta byte, value): meta = length,
    continues flag, pre-sign class; value = post-sign class and the output
    codepoint minus 0xE000 (VALUE_NO_GLYPH when `cp` is None)."""
    kb = key_bytes(seq, spec)
    if not PACKED_MIN_KEY_LEN <= len(kb) <= spec.max_key_len:
        raise ValueError(f"cluster key length {len(kb)} out of range")
    if not 0 <= pre_class <= MAX_SIGN_CLASS or not 0 <= post_class <= MAX_POST_SIGN_CLASS:
        raise ValueError(f"sign class out of range for {seq!r}")
    offset = VALUE_NO_GLYPH if cp is None else cp - PUA_BASE[0]
    if not 0 <= offset <= VALUE_NO_GLYPH:
        raise ValueError(f"output U+{cp:04X} outside the PUA")
    meta = len(kb) | (0x08 if continues else 0) | (pre_class << 4)
    return kb, meta, (post_class << 13) | offset


def pack_rows(rows):
    """Serialise (key bytes, meta, value) rows in the packed layout (format
    3, Script.h): an 18-byte directory (per key length 2..7: u16 entry
    count, u8 bucket count), then per length the bucket index (first key
    byte, u16 count) and the entries (key bytes after the first, meta, u16
    value), sorted so the device can binary-search inside a bucket."""
    by_len = {}
    for kb, meta, value in rows:
        by_len.setdefault(len(kb), []).append((kb, meta, value))
    directory = bytearray()
    sections = bytearray()
    for length in range(PACKED_MIN_KEY_LEN, PACKED_MAX_KEY_LEN + 1):
        group = sorted(by_len.get(length, []))
        buckets = []
        for kb, meta, value in group:
            if not buckets or buckets[-1][0] != kb[0]:
                buckets.append([kb[0], []])
            buckets[-1][1].append((kb, meta, value))
        if len(buckets) > 255:
            raise ValueError(f"{len(buckets)} first-byte buckets at key length {length}")
        directory += struct.pack("<HB", len(group), len(buckets))
        for first, members in buckets:
            sections += struct.pack("<BH", first, len(members))
        for _first, members in buckets:
            for kb, meta, value in members:
                sections += kb[1:] + bytes([meta]) + struct.pack("<H", value)
    assert len(directory) == PACKED_DIRECTORY_BYTES
    return bytes(directory) + bytes(sections)


def pack_table(entries, spec, danda_ends_word=False, half_forms=False, space_leads=None):
    """Serialise the table. `entries` is {key_tuple: pua_cp} (cp None for a
    bookkeeping entry) or a list of (key_tuple, pua_cp, pre_class,
    post_class, continues). The format marker is added, the danda flag
    (Script.h) when the font draws final forms before a danda, and the
    half-form flag when the font joins with half forms in a subjoining
    script, and one entry per danda whose built-in space the reader takes off
    a preceding space (`space_leads`, from danda_space_leads)."""
    rows = []
    items = entries.items() if isinstance(entries, dict) else entries
    for item in items:
        if isinstance(entries, dict):
            seq, cp = item
            rows.append(pack_entry(seq, cp, spec))
        else:
            rows.append(pack_entry(*item[:2], spec, *item[2:]))
    rows.append(pack_entry((FORMAT_CP, FORMAT_CP), PUA_BASE[0] + TABLE_FORMAT, spec))
    if danda_ends_word:
        rows.append(pack_entry((FORMAT_CP, FINA_CP), None, spec))
    if half_forms:
        rows.append(pack_entry((FORMAT_CP, ZWJ), None, spec))
    for index, share in sorted((space_leads or {}).items()):
        rows.append(pack_entry((FORMAT_CP, INIT_CP, CLASS_INDEX_CP + index), PUA_BASE[0] + share, spec))
    seen = set()
    for kb, _meta, _value in rows:
        if kb in seen:
            raise ValueError(f"{spec.name}: duplicate cluster key {kb.hex()}: the device would find one row and "
                             f"the other's glyph would be unreachable")
        seen.add(kb)
    return pack_rows(rows)


def unpack_table(data):
    """(key bytes, meta, value) rows of a packed table, in table order; the
    inverse of pack_rows. Raises ValueError on a truncated blob."""
    if len(data) < PACKED_DIRECTORY_BYTES:
        raise ValueError("cluster table shorter than its directory")
    rows = []
    pos = PACKED_DIRECTORY_BYTES
    for length in range(PACKED_MIN_KEY_LEN, PACKED_MAX_KEY_LEN + 1):
        count, buckets = struct.unpack_from("<HB", data, (length - PACKED_MIN_KEY_LEN) * 3)
        index = [struct.unpack_from("<BH", data, pos + 3 * i) for i in range(buckets)]
        pos += 3 * buckets
        if sum(n for _f, n in index) != count:
            raise ValueError(f"bucket counts do not add up at key length {length}")
        for first, n in index:
            for _ in range(n):
                if pos + length + 2 > len(data):
                    raise ValueError("cluster table truncated")
                kb = bytes([first]) + data[pos:pos + length - 1]
                meta = data[pos + length - 1]
                value = struct.unpack_from("<H", data, pos + length)[0]
                rows.append((kb, meta, value))
                pos += length + 2
    if pos != len(data):
        raise ValueError("cluster table has trailing bytes")
    return rows


def table_entry_count(data):
    """Entries in a packed table, from its directory."""
    return sum(struct.unpack_from("<H", data, i * 3)[0]
               for i in range(PACKED_MAX_KEY_LEN - PACKED_MIN_KEY_LEN + 1))


def packed_table_bytes(directory):
    """Bytes of the packed table whose directory these are (mirror of
    Lipi::packedTableBytes, without the kind check)."""
    total = PACKED_DIRECTORY_BYTES
    for i in range(PACKED_MAX_KEY_LEN - PACKED_MIN_KEY_LEN + 1):
        count, buckets = struct.unpack_from("<HB", directory, i * 3)
        total += buckets * 3 + count * (PACKED_MIN_KEY_LEN + i + 2)
    return total


# --- HarfBuzz enumeration ----------------------------------------------------

class GlyphRun:
    """A shaped glyph run in font units."""
    __slots__ = ("glyphs", "keep_y")  # list of (gid, x_advance, x_offset, y_offset)

    def __init__(self, glyphs, keep_y=False):
        self.glyphs = glyphs
        # A mark run normally rasterises at its own height, the device adding the
        # base's anchor; a context variant (ं after ि) keeps the height the font
        # gives it in that context, since it is only ever drawn there.
        self.keep_y = keep_y

    @property
    def gids(self):
        return [g[0] for g in self.glyphs]

    @property
    def advance(self):
        return sum(g[1] for g in self.glyphs)


class ClusterForm:
    __slots__ = ("key", "run", "kind", "pre_class", "post_class", "continues")

    def __init__(self, key, run, kind, pre_class=0, post_class=0, continues=False):
        self.key = key
        self.run = run
        self.kind = kind
        self.pre_class = pre_class    # class of the pre-base sign drawn next to this glyph
        self.post_class = post_class  # class of the post-base sign drawn after it
        self.continues = continues    # the ligature also forms before a further virama + consonant


class IndicClusterPlan:
    """Enumerates the cluster forms a font needs for `spec` and the table that
    maps to them."""

    def __init__(self, font_path, spec):
        import uharfbuzz as hb
        self.hb = hb
        self.spec = spec
        blob = hb.Blob.from_file_path(font_path)
        self.face = hb.Face(blob)
        self.font = hb.Font(self.face)
        self.upem = self.face.upem
        self.font.scale = (self.upem, self.upem)
        self._nominal = {}
        self.forms = []          # ClusterForm in enumeration order
        self._table = {}         # key tuple -> gid list (device simulation)
        self.aliases = {}        # extra key -> key of the form it maps to
        self._dotted_circle = self.gid(0x25CC)
        self._generic_dropped = 0   # generic sign forms whose run spans the probe base (not keyable)
        self._ignorable_gids = set()
        for cp in (ZWJ, 0x200C, 0x200B, 0x00AD):
            gid = self.gid(cp)
            if gid:
                self._ignorable_gids.add(gid)
        # Placeholder marks some fonts leave where a reph was fused into a
        # vowel sign (Noto Devanagari NullMark / dummymark): no ink, no width.
        for gid in range(self.face.glyph_count):
            name = self.font.glyph_to_string(gid).lower()
            if name in ("nullmark", "dummymarkdeva", "dummymark"):
                self._ignorable_gids.add(gid)
        # A font may join conjuncts with half forms although its script
        # subjoins (Hind Siliguri writes Bengali that way): enumerate it as a
        # half-form script and flag the table so the device does the same.
        self.half_forms_from_font = 0
        if spec.join_style == "subjoined":
            self.half_forms_from_font = self._count_half_forms()
            if self.half_forms_from_font:
                self.spec = dataclasses.replace(spec, join_style="half")

    def pre_signs_with_forms(self):
        """Pre-base signs with per-base forms in this font's script, the one
        fused with a reph / modifier first; only those the font has."""
        spec = self.spec
        signs = spec.pre_signs_with_forms or (spec.pre_sign_with_forms,)
        return tuple(s for s in signs if s and self.has(s))

    def _count_half_forms(self):
        """Consonants the font writes as a half form before another consonant
        (C + virama + ZWJ is one glyph, and C + virama + probe starts with it);
        0 unless at least half the consonants do, so a stray joiner form does
        not switch the strategy."""
        spec = self.spec
        consonants = [c for c in spec.consonants if self.has(c) and c != spec.ra]
        halves = 0
        for c in consonants:
            run = self.shape_internal((c, spec.virama, ZWJ))
            if not self._valid_run(run) or len(run.glyphs) != 1 or run.gids[0] in (self.gid(c), self.gid(spec.virama)):
                continue
            implicit = self.shape_internal((c, spec.virama, spec.probe))
            if self._valid_run(implicit) and implicit.gids[:1] == run.gids:
                halves += 1
        return halves if consonants and halves * 2 >= len(consonants) else 0

    def gid(self, cp):
        gid = self._nominal.get(cp)
        if gid is None:
            gid = self.font.get_nominal_glyph(cp) or 0
            self._nominal[cp] = gid
        return gid

    def has(self, cp):
        return self.gid(cp) != 0

    def shape_internal(self, seq):
        """Shape `seq` as it appears inside a word: the probe letter (spec.probe)
        follows it so no word-final variant is selected, and its glyph is dropped."""
        spec = self.spec
        run = self.shape(tuple(seq) + (spec.probe,))
        ka = self.gid(spec.probe)
        if run.glyphs and run.glyphs[-1][0] == ka:
            return GlyphRun(run.glyphs[:-1])
        return self.shape(seq)

    def shape(self, seq):
        spec = self.spec
        buf = self.hb.Buffer()
        buf.add_codepoints(list(seq))
        buf.direction = "ltr"
        buf.script = spec.hb_script
        buf.language = spec.hb_language
        # Joiners draw nothing; fonts without a ZWJ glyph would otherwise show
        # a zero-width space glyph in their place.
        buf.flags = self.hb.BufferFlags.REMOVE_DEFAULT_IGNORABLES
        self.hb.shape(self.font, buf)
        glyphs = []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            if info.codepoint in self._ignorable_gids and pos.x_advance == 0:
                continue  # ZWJ/ZWNJ placeholder glyphs draw nothing
            glyphs.append((info.codepoint, pos.x_advance, pos.x_offset, pos.y_offset))
        return GlyphRun(glyphs)

    # -- Device simulation ---------------------------------------------------
    # Mirrors Lipi's Emitter on the firmware so a form is only
    # added when the device could not assemble the same glyph sequence from
    # forms already in the table. (Positions are ignored: what the device
    # composes itself is placed by its mark-anchoring heuristics.)

    def _simulate(self, seq):
        spec = self.spec
        n = len(seq)
        if 2 <= n <= spec.max_key_len and seq[-1] != spec.virama and seq in self._table:
            return list(self._table[seq])
        i = 0
        rephs = 0
        while n - i >= 3 and seq[i] == spec.ra and seq[i + 1] == spec.virama and seq[i + 2] in spec.consonant_set:
            i += 2
            rephs += 1
        if rephs:
            rest = self._simulate(seq[i:])
            reph = self._table.get((spec.ra, spec.virama))
            if reph:
                return rest + list(reph) * rephs
            return [self.gid(spec.ra), self.gid(spec.virama)] * rephs + rest
        out = []
        pos = 0
        while pos < n:
            full, full_len = None, 0
            for length in range(min(spec.max_key_len, n - pos), 1, -1):
                sub = seq[pos:pos + length]
                if sub[-1] == spec.virama:
                    # Lipi: only the composite of a consonant with its
                    # visible, cluster-final virama (क्); never the reph mark.
                    if pos + length == n and sub in self._table and self._kind_of(sub) == KIND_BASE:
                        full, full_len = self._table[sub], length
                        break
                    continue
                if sub in self._table:
                    full, full_len = self._table[sub], length
                    break
            if spec.join_style == "half":
                half = self._half_form(seq, pos)
                full_ends_cluster = full is not None and pos + full_len == n
                if (full is not None and not full_ends_cluster and full_len >= 3
                        and seq[pos] in spec.consonant_set and seq[pos + full_len] == spec.virama):
                    # Lipi: a ligature continues only when the builder recorded
                    # its pair + virama key (the entry's continues flag), and
                    # yields before a subjoining consonant (rakar).
                    after = seq[pos + full_len + 1] if pos + full_len + 1 < n else None
                    sub_mark = after is not None and self._kind_of((spec.virama, after)) in MARK_KINDS
                    tail_lig = after is not None and self._kind_of((seq[pos + full_len - 1], spec.virama, after)) == KIND_BASE
                    if (not sub_mark and not tail_lig and full_len + 1 <= spec.max_key_len
                            and tuple(seq[pos:pos + full_len]) + (spec.virama,) in self._table):
                        full_ends_cluster = True
                    else:
                        full, full_len = None, 0
                if half and (half[1] - pos > full_len or not full_ends_cluster):
                    out.extend(half[0])
                    pos = half[1]
                    continue
            if full is not None:
                out.extend(full)
                pos += full_len
            else:
                if seq[pos] != ZWJ:
                    out.append(self.gid(seq[pos]))
                pos += 1
        return out

    def _half_form(self, seq, pos):
        """Lipi::Emitter::halfForm: the half form of the longest segment
        at pos that a virama and another consonant follow, unless that
        consonant takes a subjoined mark form (rakar). Returns (gids, next
        pos) or None."""
        spec = self.spec
        n = len(seq)
        for e in range(n - 2, pos, -1):
            if seq[e] != spec.virama or seq[e + 1] == ZWJ or seq[e + 1] not in spec.consonant_set:
                continue
            if e - pos + 2 > spec.max_key_len:
                continue
            sub = self._table.get((spec.virama, seq[e + 1]))
            if sub is not None and self._kind_of((spec.virama, seq[e + 1])) in MARK_KINDS:
                continue
            key = tuple(seq[pos:e + 1]) + (ZWJ,)
            if key in self._table:
                return list(self._table[key]), e + 1
        return None

    def danda_ends_word(self):
        """True when the font draws word-final forms before a danda (Tiro
        Bangla বা।) rather than the ordinary ones (Noto): votes over the
        table's word-final keys on the probe letter."""
        spec = self.spec
        danda = spec.dandas[0]
        if not self.has(danda):
            return False
        yes = no = 0
        for form in self.forms:
            key = form.key
            if len(key) < 2 or key[-1] != FINA_CP or FINA_CP in key[:-1] or INIT_CP in key:
                continue
            seq = (spec.probe,) + tuple(key[:-1]) if key[0] not in spec.consonant_set else tuple(key[:-1])
            final = self.shape(seq).gids
            internal = self.shape_internal(seq).gids
            if final == internal:
                continue
            run = self.shape(seq + (danda,)).gids
            before = run[:-1] if run and run[-1] == self.gid(danda) else run
            if before == final:
                yes += 1
            elif before == internal:
                no += 1
        return yes > no

    def _final_phala_with_modifier(self, consonants, m, default):
        """(virama, post-base consonant, modifier, FINA): the tail most bases share
        when the word ends there (Tiro ব্যঁ: ya-phala.fina + ঁ) and it differs from
        what the device draws otherwise. Returns the number of forms added."""
        spec = self.spec
        tails = collections.Counter()
        example = {}
        for c in consonants:
            run = self.shape((c, spec.virama, spec.post_base_consonant, m))
            if not self._valid_run(run) or run.gids[:1] != [self.gid(c)] or len(run.gids) < 2:
                continue
            tail = tuple(run.gids[1:])
            if list(tail) == default:
                continue
            tails[tail] += 1
            example.setdefault(tail, run)
        if not tails:
            return 0
        gids, n = tails.most_common(1)[0]
        if n < len(consonants) // 3:
            return 0
        tail = GlyphRun(example[gids].glyphs[1:])
        self._add((spec.virama, spec.post_base_consonant, m, FINA_CP), tail, KIND_POST if tail.advance > 0 else KIND_BELOW)
        return 1

    def _shaped_right(self, seq):
        """True when the device simulation of `seq` draws what HarfBuzz does (or
        HarfBuzz rejects the sequence, so there is nothing to get wrong)."""
        run = self.shape_internal(seq)
        return not self._valid_run(run) or run.gids == self._simulate(seq)

    def _remove(self, key):
        self.forms = [f for f in self.forms if f.key != key]
        self._table.pop(key, None)

    def _kind_of(self, key):
        return next((f.kind for f in self.forms if f.key == key), None)

    def _add(self, key, run, kind):
        self.forms.append(ClusterForm(key, run, kind))
        self._table[key] = run.gids

    def add_lift_exceptions(self, lifts, log=None):
        """Composites (base, modifier) for the bare letters and independent
        vowels on which a lifted modifier (mark_lifts, font units) would sit
        LIFT_EXCEPTION_EM or more away from where the font puts it: the engine
        looks a bare base plus its first modifier up as one form (ओं). Returns
        the number of forms added."""
        spec = self.spec
        limit = LIFT_EXCEPTION_EM * self.font.face.upem
        added = []
        for key, units in sorted(lifts.items()):
            if len(key) != 1 or key[0] not in spec.modifiers:
                continue
            m = key[0]
            # Consonants and the independent vowels (block offsets 0x05..0x14; not every
            # spec lists the latter).
            vowels = [spec.block_base + o for o in range(0x05, 0x15)]
            for b in list(spec.consonants) + vowels:
                if not self.has(b) or (b, m) in self._table:
                    continue
                run = self.shape((b, m))
                if (not self._valid_run(run) or len(run.glyphs) != 2 or run.gids[0] != self.gid(b)
                        or run.gids[1] != self.gid(m)):
                    continue
                if abs(run.glyphs[1][3] - units) >= limit:
                    self._add((b, m), run, KIND_BASE)
                    added.append(b)
            if added and log:
                log(f"  {spec.name}: U+{m:04X} keeps its own height on " + " ".join(chr(b) for b in added)
                    + " (base + modifier composites)")
        return len(added)

    def _alias(self, key, target):
        self.aliases[key] = target
        self._table[key] = self._table[target]

    def _pair_plus_rakar(self, seq, run):
        """True when `run` draws C1+C2+RA as the C1C2 ligature glyph with the
        rakar mark under it. The device would split it as C1 + C2RA (the
        ligature yields before a rakar), so the font's choice needs an entry."""
        spec = self.spec
        if len(run.glyphs) != 2 or seq[-1] != spec.ra or seq[-3] == spec.ra:
            return False  # a rakar never doubles (क्र्र)
        rakar = self._table.get((spec.virama, spec.ra))
        pair = self._table.get(seq[:-2])
        return (rakar is not None and self._kind_of((spec.virama, spec.ra)) in MARK_KINDS
                and list(run.gids[1:]) == list(rakar) and pair is not None and list(run.gids[:1]) == list(pair))

    def _has_ink(self, gid):
        extents = self.font.get_glyph_extents(gid)
        return bool(extents and extents.width and extents.height)

    def _valid_run(self, run):
        # A dotted circle means HarfBuzz saw an invalid sequence; such a run
        # is never a form.
        return run.glyphs and all(g[0] != 0 and g[0] != self._dotted_circle for g in run.glyphs)

    # -- Enumeration ---------------------------------------------------------

    def build(self, log=None):
        spec = self.spec
        log = log or (lambda msg: print(msg, file=sys.stderr))
        consonants = [c for c in spec.cluster_consonants if self.has(c)]
        if not consonants or not self.has(spec.virama):
            log(f"  {spec.name}: font has no {spec.name} consonants, skipping cluster shaping")
            return self.forms
        if self.half_forms_from_font:
            log(f"  {spec.name}: the font joins conjuncts with half forms ({self.half_forms_from_font} of "
                f"{len(consonants)} consonants); enumerated as a half-form script, table flagged")

        def mark_kind(run):
            # A zero-advance single glyph is a mark; where it sits is decided
            # at raster time from its bitmap (see classify_mark_kind).
            return KIND_BELOW if run.advance == 0 else KIND_BASE

        # 1. Subjoined / post-base forms of each consonant (virama + C).
        #    HarfBuzz shapes a bare virama+consonant as dotted circle + the
        #    subjoined form, which isolates the form for any consonant that
        #    has one; fonts without a dotted circle fall back to probing
        #    against bases that do not ligate with it.
        dotted_circle = self.gid(0x25CC)
        for c in consonants:
            form = None
            run = self.shape_internal((spec.virama, c))
            glyphs = [g for g in run.glyphs if g[0] != dotted_circle] if dotted_circle else []
            if (glyphs and len(glyphs) == 1 and glyphs[0][0] not in (0, self.gid(spec.virama), self.gid(c))):
                form = glyphs
            if form is None:
                for base in spec.form_probe_bases:
                    if base == c or not self.has(base):
                        continue
                    run = self.shape_internal((base, spec.virama, c))
                    if (self._valid_run(run) and len(run.glyphs) == 2 and run.glyphs[0][0] == self.gid(base)
                            and run.glyphs[1][0] not in (self.gid(spec.virama), self.gid(c))):
                        form = run.glyphs[1:]
                        break
            if form is not None:
                form_run = GlyphRun(form)
                self._add((spec.virama, c), form_run, mark_kind(form_run))

        # 1b. Half forms (C + virama + ZWJ), for scripts that join that way.
        #     The same keys serve an explicit joiner in the text. Every
        #     consonant including the nukta letters; ra's half form is the
        #     eyelash ra.
        halves = 0
        if spec.join_style == "half":
            for c in spec.consonants:
                if not self.has(c):
                    continue
                seq = (c, spec.virama, ZWJ)
                run = self.shape_internal(seq)
                if not self._valid_run(run) or len(run.glyphs) != 1 or run.gids[0] in (self.gid(c), self.gid(spec.virama)):
                    continue
                # Some fonts have a half form only for an explicit joiner and
                # write C + virama + C with a visible virama otherwise (Noto
                # ङ); the device uses one key for both, so those are left
                # out. Ra's is the eyelash ra, always explicit.
                if c in spec.ra_folds:
                    continue  # keyed as ra: its half is the eyelash ra's key
                if c != spec.ra:
                    # Left out only when the font draws the consonant with a visible
                    # virama there; a ligature with the probe (Tiro स्क) is no such
                    # sign, and the font still joins the half form before others
                    # (अन्तस्स्थानि: स् + स्थ).
                    implicit = self.shape_internal((c, spec.virama, spec.probe))
                    alone = self.shape((c, spec.virama))
                    visible = (self._valid_run(implicit) and self._valid_run(alone)
                               and implicit.gids[:len(alone.gids)] == alone.gids)
                    if not self._valid_run(implicit) or (implicit.gids[:1] != run.gids and visible):
                        continue
                self._add(seq, run, KIND_BASE)
                halves += 1

        # 2. Reph (ra + virama before a consonant).
        run = self.shape_internal((spec.ra, spec.virama, spec.probe))
        if self._valid_run(run) and len(run.glyphs) == 2 and run.glyphs[0][0] == self.gid(spec.probe):
            self._add((spec.ra, spec.virama), GlyphRun(run.glyphs[1:]), KIND_ABOVE)

        # 3. Two-consonant clusters. Kept whenever the font joins them (any
        #    output other than C1 + visible virama + C2); the composite bakes
        #    in the GPOS placement even when the run is two glyphs.
        naive_virama = self.gid(spec.virama)
        pairs = []
        for c1 in consonants:
            if c1 == spec.ra and spec.reph_after_post:
                continue  # the reph is a mark on the sign, never baked into the base
            for c2 in consonants:
                seq = (c1, spec.virama, c2)
                run = self.shape_internal(seq)
                if not self._valid_run(run):
                    continue
                if run.gids == [self.gid(c1), naive_virama, self.gid(c2)]:
                    continue
                # A pair the device assembles from the base plus a spacing
                # post-base form (ta + ya-phala) needs no composite: keeping
                # them apart lets below signs and the candrabindu attach to
                # the base, as the font does. Mark forms keep the composite
                # for its exact placement.
                post_form = self._table.get((spec.virama, c2))
                post_kind = next((f.kind for f in self.forms if f.key == (spec.virama, c2)), None)
                if post_form and post_kind == KIND_BASE and run.gids == [self.gid(c1)] + post_form:
                    continue
                # Half form of C1 followed by the full C2 is what the device
                # assembles on its own.
                half = self._table.get((c1, spec.virama, ZWJ))
                if half and run.gids == half + [self.gid(c2)]:
                    continue
                self._add(seq, run, KIND_BASE)
                pairs.append(seq)
        # Ligatures that still form when the cluster continues (ष्ट्वा keeps
        # ष्ट; द्व्य does not keep द्व): recorded here as the pair key plus a
        # virama so the device simulation sees the continuation, and written
        # to the table as the pair entry's `continues` flag (build()). Fonts
        # decide this per pair by the order of their lookups.
        aliases = 0
        if spec.join_style == "half":
            for pair in pairs:
                run = self.shape_internal(pair + (spec.virama,))
                if self._valid_run(run) and run.gids == self._table[pair] + [naive_virama]:
                    self._alias(pair + (spec.virama,), pair)
                    aliases += 1

        # A ZWJ next to the virama blocks reph formation. After the virama
        # (র্‍য, र्‍य) fonts draw a visible virama or the eyelash ra; before it
        # (র‍্য, र‍्य) ra + the subjoined or post-base form, or a ligature.
        # Only what the device cannot assemble is kept.
        for c in consonants:
            for seq in ((spec.ra, spec.virama, ZWJ, c), (spec.ra, ZWJ, spec.virama, c)):
                run = self.shape_internal(seq)
                if not self._valid_run(run):
                    continue
                if run.gids == self._simulate(seq):
                    continue
                self._add(seq, run, KIND_BASE)

        # 3b. Half forms of the ligature pairs (क्ष् त्र् श्र्), where the font
        #     has one that the device cannot build from the single half forms.
        if spec.join_style == "half":
            for pair in list(pairs):
                seq = pair + (spec.virama, ZWJ)
                run = self.shape_internal(seq)
                # Only a single glyph is a half form of the ligature; anything
                # else is the device's own decomposition or a visible virama.
                if not self._valid_run(run) or len(run.glyphs) != 1 or run.gids == self._simulate(seq):
                    continue
                self._add(seq, run, KIND_BASE)
                halves += 1

        # 3c. Half forms that change with the consonant after them (Noto Serif
        #     Devanagari 2.006: त्.alt before स and य, also when those are half
        #     forms or start a ligature: त्स्न, त्क्ष). The device builds those
        #     clusters from the plain half form, so the font's pair is kept as
        #     one form, keyed as the half pair (त्स्) or the half + ligature
        #     (त्क्ष), and only when the rest of the run is what the device
        #     draws anyway.
        contextual = 0
        if spec.join_style == "half":
            for c1 in consonants:
                half = self._table.get((c1, spec.virama, ZWJ))
                if half is None or len(half) != 1:
                    continue
                rests = [(c2, spec.virama, ZWJ) for c2 in consonants]
                rests += [p for p in pairs if p in self._table and len(self._table[p]) == 1]
                for rest in rests:
                    seq = (c1, spec.virama) + rest
                    if len(seq) > spec.max_key_len or seq in self._table:
                        continue
                    run = self.shape_internal(seq)
                    if not self._valid_run(run) or len(run.glyphs) < 2 or run.gids[:1] == list(half):
                        continue
                    if run.gids[1:] != self._simulate(rest) or run.gids == self._simulate(seq):
                        continue
                    # The device takes the longest half form, so the entry must
                    # not break a cluster it drew right before (ज्ज्ञ: the ज्ञ
                    # ligature wins over the ज्ज् half pair): every consonant
                    # after it is checked before and after adding it.
                    longer = [seq[:-1] + (c,) if seq[-1] == ZWJ else seq + (spec.virama, c) for c in consonants]
                    longer = [t for t in longer if len(t) <= spec.max_key_len]
                    right_before = {t for t in longer if self._shaped_right(t)}
                    self._add(seq, run, KIND_BASE)
                    added = [seq]
                    # A cluster the half pair would break (त्स्म: स्म is a
                    # ligature and the font keeps the plain त्) gets its own
                    # entry, which the device prefers as the longer match.
                    for t in sorted(right_before):
                        if not self._shaped_right(t):
                            self._add(t, self.shape_internal(t), KIND_BASE)
                            added.append(t)
                    fixed = sum(1 for t in longer if t not in right_before and self._shaped_right(t))
                    if seq[-1] != ZWJ:
                        fixed += 1  # a whole cluster (त्क्ष) is itself text the entry fixes
                    if fixed == 0 or any(not self._shaped_right(t) for t in right_before):
                        for key in added:
                            self._remove(key)
                        continue
                    contextual += len(added)

        # 4. Three-consonant clusters: only those the device cannot assemble
        #    from a pair plus a subjoined or half form.
        triples = 0
        pair_set = set(pairs)
        candidates = []
        for c1, _, c2 in pairs:
            for c3 in consonants:
                # Only clusters whose tail also conjoins are real Bengali;
                # ya-phala is always final and a reph never doubles.
                if spec.join_style == "subjoined" and (
                        (c2, spec.virama, c3) not in pair_set or c2 == spec.post_base_consonant
                        or (c1 == spec.ra and c2 == spec.ra)):
                    continue
                candidates.append((c1, spec.virama, c2, spec.virama, c3))
        if spec.join_style == "half":
            # Any consonant before a ligature pair (स्त्र = स् + त्र unless the
            # font has a dedicated form).
            for c1 in consonants:
                for c2, _, c3 in pairs:
                    seq = (c1, spec.virama, c2, spec.virama, c3)
                    if seq not in candidates:
                        candidates.append(seq)
        for seq in candidates:
            run = self.shape_internal(seq)
            if not self._valid_run(run):
                continue
            sim = self._simulate(seq)
            if run.gids == sim:
                continue
            if spec.join_style == "half" and len(run.glyphs) != 1 and not self._pair_plus_rakar(seq, run):
                # Only a dedicated three-consonant ligature (क्ष्र, द्ध्य), or
                # a pair ligature the font keeps under a rakar (Tiro ष्ट्र),
                # is kept; other differences are the font's contextual
                # choices in clusters no word uses.
                continue
            self._add(seq, run, KIND_BASE)
            triples += 1

        # 4b. A consonant with its visible virama (word-final क्, or before a
        #     ZWNJ) as one composite, so the halant sits where the font's
        #     mark positioning puts it. Ra is left out: its key is the reph.
        halants = 0
        for c in consonants:
            if c == spec.ra:
                continue
            seq = (c, spec.virama)
            run = self.shape(seq)
            if (not self._valid_run(run) or len(run.glyphs) != 2 or run.glyphs[0][0] != self.gid(c)
                    or run.glyphs[1][1] != 0):
                continue
            self._add(seq, run, KIND_BASE)
            halants += 1

        # 5. Reph over a single consonant (exact GPOS placement for the
        #    common case; longer clusters use the standalone reph mark).
        #    Not for scripts that draw the reph after the post-base sign:
        #    there the mark is placed on the sign, never baked into the base.
        rephs = 0
        for c in consonants:
            if c == spec.ra or spec.reph_after_post:
                continue
            seq = (spec.ra, spec.virama, c)
            if seq in self._table:
                continue
            run = self.shape_internal(seq)
            if not self._valid_run(run):
                continue
            self._add(seq, run, KIND_BASE)
            rephs += 1

        # 6. Below-base vowel signs: every single consonant (GPOS placement),
        #    and pairs only where the font has a dedicated ligature.
        vowels = 0
        # Every letter including the nukta ones (ড়ু has its own u form); the
        # ra folds (Assamese ৰ) are keyed as ra and would only duplicate রু.
        vowel_bases = [c for c in spec.consonants if self.has(c) and c not in spec.ra_folds]
        for v in spec.below_vowels:
            if not self.has(v):
                continue
            for c in vowel_bases:
                seq = (c, v)
                run = self.shape_internal(seq)
                if not self._valid_run(run):
                    continue
                self._add(seq, run, KIND_BASE)
                vowels += 1
            for pair in pairs:
                seq = pair + (v,)
                run = self.shape_internal(seq)
                if not self._valid_run(run):
                    continue
                # Kept for a ligature or for a variant of the sign (ম্পূ);
                # the plain sign after the composite needs no entry.
                if run.gids == self._table[pair] + [self.gid(v)]:
                    continue
                self._add(seq, run, KIND_BASE)
                vowels += 1

        # 7-9. Vowel-sign forms chosen by context on the desktop (see the
        #      module docstring). Bases are every single consonant and every
        #      consonant-only cluster key added above.
        bases = [(c,) for c in spec.consonants if self.has(c) and c not in spec.ra_folds]
        bases += [f.key for f in self.forms
                  if f.kind == KIND_BASE and f.key[0] != spec.virama and f.key[-1] != ZWJ
                  and not (f.key[0] == spec.ra and f.key[1] == spec.virama)
                  and all(cp == spec.virama or cp == ZWJ or cp in spec.consonant_set for cp in f.key)]
        signs = self._sign_forms(bases, consonants, log)
        fused = self._fused_marks(bases, log) if spec.mark_fusion else 0
        classed = self._sign_classes(consonants, log)
        over = [f for f in self.forms if f.kind != KIND_META and len(f.key) > spec.max_key_len]
        if over:
            dropped = set(id(f) for f in over)
            self.forms = [f for f in self.forms if id(f) not in dropped]
            for f in over:
                self._table.pop(f.key, None)
            log(f"  {spec.name}: {len(over)} sign forms of long clusters do not fold into a class and are dropped "
                f"(e.g. {' '.join('U+%04X' % c for c in over[0].key)})")
        for key, target in self.aliases.items():
            form = self._form_of(target)
            if form is not None:
                form.continues = True

        log(f"  {spec.name}: {halves} half forms, {contextual} contextual half forms, {halants} consonant+virama, {len(pairs)} conjunct pairs ({aliases} continuing), "
            f"{triples} triples, {rephs} reph forms, {vowels} vowel forms, {signs} sign forms, "
            f"{fused} fused marks, {classed} folded into sign classes, {len(self.forms)} cluster forms total")
        if self._generic_dropped:
            log(f"  {spec.name}: {self._generic_dropped} generic sign+modifier forms span the probe base and are "
                f"dropped (the device draws the sign, the base and the marks itself)")
        return self.forms

    def _form_of(self, key):
        return next((f for f in self.forms if f.key == key), None)

    # -- Sign classes ----------------------------------------------------------

    def _right_edge(self, run):
        x = 0
        edge = 0
        for gid, adv, _, _ in run.glyphs:
            ext = self.font.get_glyph_extents(gid)
            edge = max(edge, x + ext.x_bearing + ext.width)
            x += adv
        return edge

    def _sign_classes(self, consonants, log):
        """Fold the per-base forms of the pre-base sign (ि) and post-base
        sign (ी) into sign classes: every glyph the sign attaches to gets a
        class in its own entry (or a {CLASS_CP, consonant} entry for a bare
        consonant), and one entry per class maps to the variant glyph. The
        device picks the ि variant from the first glyph of the cluster when
        that glyph is a half form or the whole cluster, and the ी variant
        from the last glyph. Fused sign + modifier forms fold too when they
        follow the same classes. Per-base forms the classes cannot express
        keep their entries. Returns the number of forms folded."""
        spec = self.spec
        folded = 0
        cons_class = {}  # consonant -> [pre, post]
        # The pre-base signs share one class per glyph (a base's class stands
        # for its ি variant AND its ে variant: Noto Sans Bengali draws ে.long
        # on খ but not on ক), so they fold together; the post-base sign has its
        # own class field.
        jobs = []
        pre_signs = self.pre_signs_with_forms()
        if pre_signs:
            jobs.append((pre_signs, KIND_PRE, True))
        if spec.post_sign_with_forms and self.has(spec.post_sign_with_forms):
            jobs.append(((spec.post_sign_with_forms,), KIND_POST, False))
        for signs, kind, is_pre in jobs:
            # Per sign: per-base forms of the sign, of the sign + one modifier,
            # of the sign fused with a reph, and of the sign at the start of a word.
            groups_of = {}  # sign -> {sign key (sign,) / (sign, mod) / (ra, virama, sign..) / (INIT, sign) -> {base: form}}
            for sign in signs:
                groups = {}
                for f in self.forms:
                    k = f.key
                    if f.kind != kind or len(k) < 2 or VARIANT_CP in k or CLASS_CP in k:
                        continue
                    if FINA_CP in k:
                        continue
                    # Reph-fused forms (র্তি) and word-initial forms (INIT খে) fold
                    # by the same base classes under the sign key with that prefix.
                    prefix = ()
                    if len(k) >= 4 and k[0] == spec.ra and k[1] == spec.virama:
                        prefix, k = k[:2], k[2:]
                    elif len(k) >= 3 and k[0] == INIT_CP:
                        prefix, k = k[:1], k[1:]
                    if INIT_CP in k:
                        continue
                    if k[-1] == sign:
                        base, sk = k[:-1], prefix + (sign,)
                    elif len(k) >= 3 and k[-2] == sign and k[-1] in spec.modifiers:
                        base, sk = k[:-2], prefix + (sign, k[-1])
                    else:
                        continue
                    if not base:
                        continue  # generic form, kept as the fallback
                    if all(cp == spec.virama or cp == ZWJ or cp in spec.consonant_set for cp in base):
                        groups.setdefault(sk, {})[base] = f
                if groups.get((sign,)):
                    groups_of[sign] = groups
            if not groups_of:
                continue
            signs = tuple(s for s in signs if s in groups_of)
            # One class per distinct tuple of variants over the signs (None =
            # the sign's plain glyph), in the order of the first sign's reach,
            # then the next sign's: with one sign this is the variant list in
            # the order of its reach, class 1..15.
            runs_of = {s: {} for s in signs}  # sign -> gids -> run
            for s in signs:
                for f in groups_of[s][(s,)].values():
                    runs_of[s].setdefault(tuple(f.run.gids), f.run)
            tuple_of = {}
            for s in signs:
                for base in groups_of[s][(s,)]:
                    if base not in tuple_of:
                        tuple_of[base] = tuple(
                            tuple(groups_of[t][(t,)][base].run.gids) if base in groups_of[t][(t,)] else None
                            for t in signs)

            def reach(s, g):
                return self._right_edge(runs_of[s][g]) if is_pre else runs_of[s][g].advance

            order = sorted(set(tuple_of.values()),
                           key=lambda tup: tuple((reach(s, g), g) if g is not None else (-1, ())
                                                 for s, g in zip(signs, tup)))
            # Pre-sign classes fill the meta byte's high nibble (1..MAX_SIGN_CLASS),
            # post-sign classes the value's top three bits (1..MAX_POST_SIGN_CLASS).
            cap = MAX_SIGN_CLASS if is_pre else MAX_POST_SIGN_CLASS
            if len(order) > cap:
                log(f"  {spec.name}: {len(order)} variant classes of " + " ".join(f"U+{s:04X}" for s in signs)
                    + f", keeping per-base forms beyond {cap}")
                order = order[:cap]
            cls_of_tuple = {tup: i + 1 for i, tup in enumerate(order)}
            base_class = {}
            drop = []
            for base, tup in tuple_of.items():
                cls = cls_of_tuple.get(tup)
                if cls is None:
                    continue
                if len(base) == 1:
                    cons_class.setdefault(base[0], [0, 0])[0 if is_pre else 1] = cls
                else:
                    owner = self._form_of(base)
                    if owner is None or owner.kind != KIND_BASE:
                        continue  # the device assembles this base from pieces
                    if is_pre:
                        owner.pre_class = cls
                    else:
                        owner.post_class = cls
                base_class[base] = cls
                drop.extend(groups_of[s][(s,)][base] for s in signs if base in groups_of[s][(s,)])
            for i, tup in enumerate(order):
                for s, g in zip(signs, tup):
                    if g is not None:
                        self.forms.append(ClusterForm((VARIANT_CP, s, CLASS_INDEX_CP + i + 1), runs_of[s][g], kind))
            # Sign + modifier, reph-fused and word-initial forms: fold a class
            # only when every base of that class has the same fused form. A base
            # without one draws the plain variant plus the modifier (or the
            # generic reph / initial form), and the device applies a class
            # variant to the whole class.
            # A pair ligature kept under a rakar (Tiro ष्ट्र) takes the
            # fused forms of its class: the font stops fusing across the
            # rakar mark, so counting it would only break the fold for the
            # class's real members.
            rakar = self._table.get((spec.virama, spec.ra))
            members = {}
            for base, cls in base_class.items():
                owner = self._form_of(base) if len(base) > 1 else None
                if owner is not None and rakar and list(owner.run.gids[-len(rakar):]) == list(rakar):
                    continue
                members.setdefault(cls, set()).add(base)
            for sign in signs:
                for sk, per_base in groups_of[sign].items():
                    if sk == (sign,):
                        continue
                    by_class = {}
                    for base, f in per_base.items():
                        cls = base_class.get(base)
                        if cls:
                            by_class.setdefault(cls, {}).setdefault(tuple(f.run.gids), []).append(f)
                    for cls, variants in by_class.items():
                        if len(variants) != 1:
                            continue
                        gids, fs = next(iter(variants.items()))
                        # (ra, virama) prefix of a reph-fused key, INIT of a word-initial one.
                        head = 2 if sk[0] == spec.ra else (1 if sk[0] == INIT_CP else 0)
                        tail = len(sk) - head  # sign (+ modifier) suffix
                        if {f.key[head:len(f.key) - tail] for f in fs} != members.get(cls):
                            continue
                        drop.extend(fs)
                        self.forms.append(ClusterForm((VARIANT_CP,) + sk + (CLASS_INDEX_CP + cls,), fs[0].run, kind))
                # Half forms: the ि a half form attaches to is fixed when the font
                # draws the same variant whatever consonant follows. A variant
                # names a class only when it belongs to exactly one.
                if is_pre and spec.join_style == "half":
                    varying = []  # half forms whose ি follows the consonant after them
                    at = signs.index(sign)
                    cls_of = {}
                    for tup, cls in cls_of_tuple.items():
                        if tup[at] is not None:
                            cls_of[tup[at]] = 0 if tup[at] in cls_of else cls
                    cls_of = {g: c for g, c in cls_of.items() if c}
                    gid_sign = self.gid(sign)
                    for f in list(self.forms):
                        k = f.key
                        if f.kind != KIND_BASE or k[-1] != ZWJ or VARIANT_CP in k:
                            continue
                        half = list(f.run.gids)
                        seen = set()
                        count = 0
                        for c2 in consonants:
                            seq = k[:-1] + (c2,)
                            if seq in self._table:
                                continue
                            sim = self._simulate(seq)
                            if sim[:len(half)] != half or len(sim) != len(half) + 1:
                                continue
                            run = self.shape_internal(seq + (sign,))
                            if not self._valid_run(run) or run.gids[-len(sim):] != sim:
                                continue
                            seen.add(tuple(run.gids[:-len(sim)]))
                            count += 1
                            if len(seen) > 1:
                                break
                        if count >= 3 and len(seen) == 1:
                            variant = next(iter(seen))
                            if variant != (gid_sign,) and variant in cls_of:
                                f.pre_class = cls_of[variant]
                        elif len(seen) > 1 and sign == spec.pre_sign_with_forms:
                            varying.append(f)
                    if varying:
                        pair_rows = self._half_pair_variants(varying, sign, consonants, cons_class, cls_of, log)
                        if pair_rows:
                            log(f"  {spec.name}: {pair_rows} half-form pair entries for U+{sign:04X}")
            dropped = set(id(f) for f in drop)
            self.forms = [f for f in self.forms if id(f) not in dropped]
            for f in drop:
                self._table.pop(f.key, None)
            folded += len(drop)
        # A reph + base composite (র্থ drawn as one glyph) takes its base's
        # pre-base class: the font sizes ে/ি by the letter under the reph
        # (Noto Sans অর্থে: ে.long as for থ), and the device reads the class from
        # the glyph the cluster resolved to.
        R = (spec.ra, spec.virama)
        for f in self.forms:
            if f.kind != KIND_BASE or f.pre_class or len(f.key) < 3 or tuple(f.key[:2]) != R:
                continue
            base = tuple(f.key[2:])
            if len(base) == 1:
                cls = cons_class.get(base[0], [0, 0])[0]
            else:
                owner = self._form_of(base)
                cls = owner.pre_class if owner is not None else 0
            if cls:
                f.pre_class = cls
        for c, (pre, post) in cons_class.items():
            self.forms.append(ClusterForm((CLASS_CP, c), None, KIND_META, pre_class=pre, post_class=post))
        return folded

    def _half_pair_variants(self, halves, sign, consonants, cons_class, cls_of, log):
        """The pre-base sign before a half form whose variant depends on the
        glyph after the half form (Noto Serif Devanagari: षि + व -> ি.12, ति + क्त
        -> ি.15, by a class-pair rule in its GSUB). Per half form and the column of
        the next glyph (its own sign class + 1, or HALF_PAIR_FOLLOWS + 1 when
        another half form follows), HarfBuzz's variant is recorded as the sign
        class whose variant it is, so the device picks it (and the sign fused with
        a modifier, ि+ं) through the class lists it already has. Half forms with
        the same outcomes share a row: {CLASS, half key} carries the row (pre class
        | post class << 4), {VARIANT, ZWJ, sign, row letter, column} the class (pre
        class, no glyph). Returns the number of entries added."""
        spec = self.spec
        gid_sign = self.gid(sign)
        halves_by_first = {f.key[0]: f for f in halves if len(f.key) == 3}
        cells = {}  # half key -> {column: sign class}
        clash = set()
        unclassed = 0
        for f in halves:
            half = list(f.run.gids)
            got = {}
            for c2 in consonants:
                seq = f.key[:-1] + (c2,)
                if seq in self._table:
                    continue
                sim = self._simulate(seq)
                if sim[:len(half)] != half or len(sim) != len(half) + 1:
                    continue
                cols = [cons_class.get(c2, [0, 0])[0] + 1]
                texts = [seq]
                # Another half form after this one (षि + ट् + ...): its own column.
                if c2 in halves_by_first:
                    seq2 = f.key[:-1] + (c2, spec.virama, spec.probe)
                    sim2 = self._simulate(seq2)
                    if len(sim2) == len(half) + 2 and sim2[:len(half)] == half:
                        cols.append(HALF_PAIR_FOLLOWS + 1)
                        texts.append(seq2)
                for col, text in zip(cols, texts):
                    sim_t = self._simulate(text)
                    run = self.shape_internal(text + (sign,))
                    if not self._valid_run(run) or run.gids[-len(sim_t):] != sim_t:
                        continue
                    variant = tuple(run.gids[:-len(sim_t)])
                    cls = 0 if variant == (gid_sign,) else cls_of.get(variant)
                    if cls is None:
                        unclassed += 1
                        continue
                    if col in got and got[col] != cls:
                        clash.add((f.key, col))
                    got[col] = cls
            cells[f.key] = {c: v for c, v in got.items() if (f.key, c) not in clash}
        # Rows: half forms whose outcomes agree wherever both have one.
        rows = []
        for key in sorted(cells, key=lambda k: -len(cells[k])):
            for row in rows:
                if all(row["cells"].get(c, v) == v for c, v in cells[key].items()):
                    row["cells"].update(cells[key])
                    row["members"].append(key)
                    break
            else:
                rows.append({"cells": dict(cells[key]), "members": [key]})
        if len(rows) > 127:
            log(f"  {spec.name}: {len(rows)} half-form pair rows for U+{sign:04X}, more than the 127 the row "
                f"byte holds: pairs keep the plain sign")
            return 0
        added = 0
        for i, row in enumerate(rows, start=1):
            if not any(row["cells"].values()):
                continue  # the plain sign everywhere: nothing to store
            for key in row["members"]:
                self.forms.append(ClusterForm((CLASS_CP,) + key, None, KIND_META, pre_class=i & 0x0F,
                                              post_class=i >> 4))
                added += 1
            for col, cls in sorted(row["cells"].items()):
                if cls == 0:
                    continue  # the plain sign is what the device draws anyway
                self.forms.append(ClusterForm((VARIANT_CP, ZWJ, sign, spec.block_base + i, CLASS_INDEX_CP + col),
                                              None, KIND_META, pre_class=cls))
                added += 1
        # The sign fused with a modifier (ि+ं) takes the same class through the
        # class's modifier list, which the fold writes only when every member
        # fuses alike and was left out for some (Noto Serif Devanagari classes 8,
        # 11-14): add it for every class whose members all agree (a pair cell
        # may name any class, so none is skipped). The fold's own lists live in
        # self.forms only, so they are checked there as well as in the table;
        # a second list under the same key would give the packed table a
        # duplicate row and the font an unreachable glyph.
        used = set(range(1, MAX_SIGN_CLASS + 1))
        listed = {tuple(f.key) for f in self.forms}
        members = {}
        for c, (pre, _post) in cons_class.items():
            members.setdefault(pre, []).append((c,))
        for f in self.forms:
            if f.kind == KIND_BASE and f.pre_class and f.key[0] not in (CLASS_CP, VARIANT_CP) and f.key[-1] != ZWJ:
                members.setdefault(f.pre_class, []).append(tuple(f.key))
        # The reph fused with the sign (कीर्त्ति: ि+reph as one glyph) likewise.
        R = (spec.ra, spec.virama)
        for cls in sorted(used):
            if not members.get(cls):
                continue
            for prefix, suffix in [((), (m,)) for m in spec.modifiers if self.has(m)] + [(R, ())]:
                key = (VARIANT_CP,) + prefix + (sign,) + suffix + (CLASS_INDEX_CP + cls,)
                if key in self._table or key in listed:
                    continue
                firsts = set()
                example = None
                for base in members[cls]:
                    if prefix and base[0] == spec.ra:
                        continue
                    run = self.shape_internal(prefix + base + (sign,) + suffix)
                    sim = self._simulate(base)
                    if not self._valid_run(run) or run.gids[-len(sim):] != sim or len(run.gids) != len(sim) + 1:
                        firsts.add(None)
                        break
                    firsts.add(run.gids[0])
                    example = example or run
                if len(firsts) == 1 and None not in firsts:
                    self._add(key, GlyphRun(example.glyphs[:1]), KIND_PRE)
                    added += 1
        if log:
            log(f"  {spec.name}: U+{sign:04X} before {len(cells)} half forms follows the next glyph: {len(rows)} rows, "
                f"{added} entries" + (f", {len(clash)} inconsistent cells dropped" if clash else "")
                + (f", {unclassed} outcomes without a class" if unclassed else ""))
        return added

    # -- Vowel-sign forms ----------------------------------------------------

    def _gids_of(self, seq):
        run = self.shape(seq)
        return (run.gids, run) if self._valid_run(run) else (None, None)

    def _add_sign_form(self, key, run, default_gids, prefix_len, base_sim, generic=False):
        """Add the form for `key` when HarfBuzz's `run` differs from what the
        device assembles on its own (`default_gids`). A run that only swaps
        the sign glyph (the base glyphs unchanged) becomes a pre/post form of
        the sign; anything else becomes a composite of the whole run, except
        for a `generic` key (no base of its own, shaped on the probe letter):
        its run contains the probe glyph, so a composite would draw the probe
        in place of the real base. Such a form is dropped and the device
        assembles the sign, the base and the marks itself.
        Returns 1 when a form was added."""
        if run is None or run.gids == default_gids:
            return 0
        if generic and not (len(run.gids) == len(base_sim) + 1 and (
                (prefix_len == 1 and run.gids[1:] == base_sim) or (prefix_len == 0 and run.gids[:-1] == base_sim))):
            self._generic_dropped += 1
            return 0
        n = len(base_sim)
        # Devanagari-style fonts leave the reph on the sign (र्का: ka, aa,
        # reph), so a form may be several glyphs around the unchanged base.
        multi = self.spec.reph_after_post
        if prefix_len == 1 and len(run.gids) == n + 1 and run.gids[1:] == base_sim:
            self._add(key, GlyphRun(run.glyphs[:1]), KIND_PRE)
        elif prefix_len == 0 and len(run.gids) == n + 1 and run.gids[:n] == base_sim:
            self._add(key, GlyphRun(run.glyphs[n:]), KIND_POST)
        elif multi and prefix_len == 1 and len(run.gids) > n and run.gids[-n:] == base_sim:
            self._add(key, GlyphRun(run.glyphs[:-n]), KIND_PRE)
        elif multi and prefix_len == 0 and len(run.gids) > n and run.gids[:n] == base_sim:
            self._add(key, GlyphRun(run.glyphs[n:]), KIND_POST)
        else:
            self._add(key, run, KIND_BASE)
        return 1

    def _sign_forms(self, bases, consonants, log):
        spec = self.spec
        added = 0
        gid_i, gid_ii = self.gid(spec.pre_sign_with_forms), self.gid(spec.post_sign_with_forms)
        if not (gid_i and gid_ii):
            return 0
        ka = self.gid(spec.probe)

        def strip_context(seq):
            # Shape with the probe letter after it so word-final forms do not
            # apply, then drop the probe glyph.
            run = self.shape(seq + (spec.probe,))
            if not self._valid_run(run) or run.gids[-1] != ka:
                return None
            return GlyphRun(run.glyphs[:-1])

        # With a reph the device draws base + reph, or base + sign + reph
        # when the reph follows the post-base sign.
        reph = self._table.get((spec.ra, spec.virama), [])
        # Bases the reph forms are enumerated for: single consonants. A reph
        # over a conjunct uses the generic fused form (width variants of the
        # sign per conjunct would double the table).
        reph_bases = [(c,) for c in consonants]

        def reph_default(base_sim, sign_gids):
            if spec.reph_after_post:
                return base_sim + sign_gids + reph
            return base_sim + reph + sign_gids

        # 7. ি (and any other pre-base sign with per-base forms: Noto Sans
        #    Bengali ে ৈ) with every base, then ি with a reph over every consonant.
        for sign in self.pre_signs_with_forms():
            gid_sign = self.gid(sign)
            # A sign with a word-initial form (ে ৈ) is shaped behind a probe
            # letter as well, so the internal form is what comes out.
            word_internal = sign in spec.init_signs
            for base in bases:
                key = base + (sign,)
                # A key too long for the table is still enumerated when the base is
                # one glyph: its variant folds into that glyph's sign class. What does
                # not fold is dropped after the fold (see build()).
                if len(key) > spec.max_key_len and (base not in self._table or len(self._table[base]) != 1):
                    continue
                sim = self._simulate(base)
                if word_internal:
                    run = self.shape((spec.probe,) + key + (spec.probe,))
                    run = (GlyphRun(run.glyphs[1:-1]) if self._valid_run(run) and len(run.gids) > 2
                           and run.gids[0] == ka and run.gids[-1] == ka else None)
                else:
                    run = self.shape_internal(key)
                    run = run if self._valid_run(run) else None
                added += self._add_sign_form(key, run, [gid_sign] + sim, 1, sim)
        for base in reph_bases:
            key = (spec.ra, spec.virama) + base + (spec.pre_sign_with_forms,)
            reph_sim = self._simulate((spec.ra, spec.virama) + base)
            base_sim = self._simulate(base)
            run = self.shape_internal(key)
            run = run if self._valid_run(run) else None
            added += self._add_sign_form(key, run, [gid_i] + reph_sim, 1, base_sim)
        added += self._generic_reph_sign(consonants, spec.pre_sign_with_forms, 1, log)

        # 8. ী with every base (word-internal and word-final), then with a reph.
        fina_ii = self.shape((spec.probe, spec.post_sign_with_forms))
        fina_ii_gid = fina_ii.gids[-1] if self._valid_run(fina_ii) and len(fina_ii.gids) == 2 else gid_ii
        for base in bases:
            key = base + (spec.post_sign_with_forms,)
            if len(key) > spec.max_key_len:
                continue
            sim = self._simulate(base)
            run = strip_context(key)
            added += self._add_sign_form(key, run, sim + [gid_ii], 0, sim)
            if len(key) + 1 > spec.max_key_len or not spec.fina_signs:
                continue
            # Word-final: what the device would draw is the internal form if
            # one was just added, else the generic final ী.
            # Compared with the table's own run for the key (a post form holds
            # the sign glyph alone), so a base whose internal form is a class
            # variant gets a FINA row naming that variant: the class fold later
            # drops the per-base row, and at a word end the engine takes the
            # generic final form over a class variant (Noto Serif Bengali ঠী
            # keeps ী.long there). The rows look redundant; they are not.
            internal = self._table.get(key)
            default_final = internal if internal is not None else sim + [fina_ii_gid]
            gids, run_final = self._gids_of(key)
            if run_final is not None and run_final.gids != default_final:
                added += self._add_sign_form(key + (FINA_CP,), run_final, default_final, 0, sim)
        for base in reph_bases:
            key = (spec.ra, spec.virama) + base + (spec.post_sign_with_forms,)
            base_sim = self._simulate(base)
            run = strip_context(key)
            added += self._add_sign_form(key, run, reph_default(base_sim, [gid_ii]), 0, base_sim)
            if not spec.fina_signs:
                continue
            internal = self._table.get(key)
            default_final = internal if internal is not None else reph_default(base_sim, [fina_ii_gid])
            gids, run_final = self._gids_of(key)
            if run_final is not None and run_final.gids != default_final:
                added += self._add_sign_form(key + (FINA_CP,), run_final, default_final, 0, base_sim)
        added += self._generic_reph_sign(consonants, spec.post_sign_with_forms, 0, log)

        # 8a. The other post-base signs with per-base forms (Hind's taller ৗ in
        #     ৌ after খ গ ঝ ণ থ প শ). Kept per base: the sign classes belong to ী.
        for sign in spec.post_signs_with_forms:
            if sign == spec.post_sign_with_forms or not self.has(sign):
                continue
            gid_sign = self.gid(sign)
            for base in bases:
                key = base + (sign,)
                if len(key) > spec.max_key_len:
                    continue
                sim = self._simulate(base)
                added += self._add_sign_form(key, strip_context(key), sim + [gid_sign], 0, sim)

        # 8b. Word-final ya-phala: the form alone and the clusters ending in it.
        ya_form = self._table.get((spec.virama, spec.post_base_consonant))
        if ya_form:
            run = self.shape((spec.probe, spec.virama, spec.post_base_consonant))
            if self._valid_run(run) and run.gids[:1] == [ka] and run.gids[1:] != ya_form:
                self._add((spec.virama, spec.post_base_consonant, FINA_CP), GlyphRun(run.glyphs[1:]), KIND_BASE)
                added += 1
            for base in bases:
                if (len(base) < 3 or base[-1] != spec.post_base_consonant or base[-2] != spec.virama
                        or len(base) + 1 > spec.max_key_len):
                    continue
                run = self.shape(base)
                if self._valid_run(run) and run.gids != self._table[base]:
                    self._add(base + (FINA_CP,), run, KIND_BASE)
                    added += 1
                # The same cluster with a below vowel at the end of a word
                # (মৃত্যু): the vowel attaches to the base, the ya-phala takes
                # its final form.
                for v in spec.below_vowels:
                    own = self._table.get(base + (v,))
                    if own is None or len(base) + 2 > spec.max_key_len:
                        continue
                    run = self.shape(base + (v,))
                    if self._valid_run(run) and run.gids != list(own):
                        self._add(base + (v, FINA_CP), run, KIND_BASE)
                        added += 1

        # 9. Word-initial ে ৈ and word-final া ী.
        for sign in spec.init_signs:
            if not self.has(sign):
                continue
            initial = self.shape((spec.probe, sign))
            internal = self.shape((spec.probe, spec.probe, sign))
            if (self._valid_run(initial) and self._valid_run(internal) and len(initial.gids) == 2
                    and len(internal.gids) == 3 and initial.gids[0] != internal.gids[1]):
                self._add((INIT_CP, sign), GlyphRun(initial.glyphs[:1]), KIND_PRE)
                added += 1
            if sign not in self.pre_signs_with_forms():
                continue
            # Per-base word-initial forms (Noto Sans Bengali খে: ে.long.init),
            # keyed INIT + base + sign; they fold into the sign classes as the
            # class's initial variant. The default is the generic initial form.
            init_default = list(self._table.get((INIT_CP, sign), [self.gid(sign)]))
            for base in bases:
                key = (INIT_CP,) + base + (sign,)
                if len(key) > spec.max_key_len and (base not in self._table or len(self._table[base]) != 1):
                    continue
                sim = self._simulate(base)
                run = self.shape(base + (sign,))  # at the start of a word
                run = run if self._valid_run(run) else None
                added += self._add_sign_form(key, run, init_default + sim, 1, sim)
        for sign in spec.fina_signs:
            if not self.has(sign):
                continue
            final = self.shape((spec.probe, sign))
            internal = self.shape((spec.probe, sign, spec.probe))
            if (self._valid_run(final) and self._valid_run(internal) and len(final.gids) == 2
                    and len(internal.gids) == 3 and final.gids[1] != internal.gids[1]):
                self._add((FINA_CP, sign), GlyphRun(final.glyphs[1:]), KIND_POST)
                added += 1
            # Some fonts (Tiro Bangla) still take the final form when only a
            # modifier follows: ডাঃ, বাং. Keyed sign + modifier + FINA, the
            # form carries both glyphs.
            candrabindu = spec.candrabindu
            own_final = self._table.get((FINA_CP, sign))
            for m in spec.modifiers:
                if not self.has(m):
                    continue
                final = self.shape((spec.probe, sign, m))
                # What the device draws at the end of a word on its own: the
                # candrabindu (drawn before the sign) still lets the sign take
                # its final form; a spacing modifier (ং ঃ) keeps it plain.
                if m == candrabindu and sign in spec.candrabindu_before_post:
                    default = [self.gid(m)] + (list(own_final) if own_final else [self.gid(sign)])
                elif m == candrabindu:
                    default = (list(own_final) if own_final else [self.gid(sign)]) + [self.gid(m)]
                else:
                    default = [self.gid(sign), self.gid(m)]
                if (self._valid_run(final) and len(final.gids) == 3 and final.gids[1:] != default
                        and (sign, m, FINA_CP) not in self._table):
                    self._add((sign, m, FINA_CP), GlyphRun(final.glyphs[1:]), KIND_POST)
                    added += 1
        return added

    def _fused_marks(self, bases, log):
        """Forms of the reph, the above signs and the post-base signs fused
        with the first modifier, and of the reph fused with the signs
        (कें कों कीं र्कं र्के र्को र्कें). Generic keys stand for
        any base; ी + modifier also gets per-base keys since its width
        variants follow the base."""
        spec = self.spec
        ka = self.gid(spec.probe)
        R = (spec.ra, spec.virama)
        reph = self._table.get(R)
        added = 0

        consonants = [c for c in spec.consonants if self.has(c) and c not in spec.ra_folds]

        def sign_gids(c, sign):
            form = self._table.get((c, sign))
            return list(form) if form else [self.gid(sign)]

        def modifier_moved(c, run, m):
            # HarfBuzz puts the modifier on the mark before it (mark-to-mark: पूर्णँ
            # on the reph, मैँ on the ai sign), where the device would anchor both on
            # the base and overlap them. The glyphs are the ones the device draws
            # anyway, so only the place differs, and the pair must be one form.
            plain = self.shape_internal((c, m))
            if not self._valid_run(plain) or not plain.glyphs or plain.gids[-1] != self.gid(m):
                return False
            if run.glyphs[-1][1] != 0 or plain.glyphs[-1][1] != 0:
                return False  # a spacing modifier (ः, ং) keeps its own place in the line
            here = sum(g[1] for g in run.glyphs[:-1]) + run.glyphs[-1][2]
            there = sum(g[1] for g in plain.glyphs[:-1]) + plain.glyphs[-1][2]
            return abs(here - there) > self.upem // 32  # about a pixel at 16 pt

        def form_after(key, default_tail, stacked=None):
            # The generic form of `key` (a reph and/or signs after any base):
            # shaped on every consonant (after a leading reph the consonant is
            # its base), keeping the tail most bases share when it differs
            # from what the device draws unfused (`default_tail(c)`).
            tails = collections.Counter()
            example = {}
            for c in consonants:
                text = R + (c,) + key[2:] if key[:2] == R else (c,) + key
                # Word-internal context: a fused form is not a word-final one
                # (Noto Bengali's া.fina would otherwise ride along with ঁ).
                run = self.shape_internal(text)
                if not self._valid_run(run) or run.gids[:1] != [self.gid(c)] or len(run.gids) < 2:
                    continue
                tail = tuple(run.gids[1:])
                if list(tail) == default_tail(c) and not (stacked is not None and stacked(c, run)):
                    continue
                tails[tail] += 1
                example.setdefault(tail, run)
            if not tails:
                return 0
            gids, n = tails.most_common(1)[0]
            if n < len(consonants) // 3:
                return 0
            tail = GlyphRun(example[gids].glyphs[1:])
            kind = KIND_POST if tail.advance > 0 else KIND_BELOW  # marks are placed at raster time
            self._add(key, tail, kind)
            return 1

        if reph:
            for m in spec.modifiers:
                if self.has(m):
                    added += form_after(R + (m,), lambda c, m=m: reph + [self.gid(m)],
                                        stacked=lambda c, run, m=m: modifier_moved(c, run, m))
            for a in spec.above_vowels:
                if not self.has(a):
                    continue
                added += form_after(R + (a,), lambda c, a=a: [self.gid(a)] + reph)
                for m in spec.modifiers:
                    if self.has(m):
                        added += form_after(R + (a, m), lambda c, a=a, m=m: [self.gid(a)] + reph + [self.gid(m)])
            for v in spec.post_vowels:
                if not self.has(v):
                    continue
                if v != spec.post_sign_with_forms:  # ी + reph came from _sign_forms
                    added += form_after(R + (v,), lambda c, v=v: sign_gids(c, v) + reph)
                for m in spec.modifiers:
                    if self.has(m):
                        added += form_after(R + (v, m), lambda c, v=v, m=m: sign_gids(c, v) + reph + [self.gid(m)])
        for a in spec.above_vowels:
            for m in spec.modifiers:
                if self.has(a) and self.has(m):
                    added += form_after((a, m), lambda c, a=a, m=m: [self.gid(a), self.gid(m)],
                                        stacked=lambda c, run, m=m: modifier_moved(c, run, m))
        # The spacing post-base consonant (ya-phala) with a modifier: the
        # device draws the candrabindu before it and the spacing modifiers
        # after; a font that orders them otherwise (Tiro: ্যঁ) gets the pair.
        ya = self._table.get((spec.virama, spec.post_base_consonant)) if spec.post_base_consonant else None
        if ya:
            candrabindu = spec.candrabindu
            for m in spec.modifiers:
                if not self.has(m):
                    continue
                order = ([self.gid(m)] + list(ya)) if m == candrabindu else (list(ya) + [self.gid(m)])
                added += form_after((spec.virama, spec.post_base_consonant, m), lambda c, o=order: o)
                # At the end of a word: what the device draws without a final
                # key is the pair above (when the font has one) or that order.
                fused = self._table.get((spec.virama, spec.post_base_consonant, m))
                default = list(fused) if fused else order
                added += self._final_phala_with_modifier(consonants, m, default)
            # With a post-base sign the font may order the modifier by that sign
            # (Noto Sans ক্যঁ: ঁ before the ya-phala; ক্যাঁ: after it): the
            # ya-phala, sign and modifier as one form, keyed with the sign.
            for m in spec.modifiers:
                if not self.has(m):
                    continue
                for v in spec.post_vowels:
                    if not self.has(v):
                        continue

                    def device(c, v=v, m=m):
                        # What the engine draws without the form (Lipi.cpp, ya-phala).
                        fused = self._table.get((spec.virama, spec.post_base_consonant, m))
                        if fused:
                            return list(fused) + sign_gids(c, v)
                        if m == candrabindu and v in spec.candrabindu_before_post:
                            return [self.gid(m)] + list(ya) + sign_gids(c, v)
                        return list(ya) + sign_gids(c, v) + [self.gid(m)]
                    added += form_after((spec.virama, spec.post_base_consonant, v, m), device)
        candrabindu = spec.candrabindu
        for v in spec.post_vowels:
            for m in spec.modifiers:
                if self.has(v) and self.has(m):
                    if m == candrabindu and v in spec.candrabindu_before_post:
                        # The device draws this one before the sign, so a pair that only
                        # sits differently needs no form: its own anchor still applies.
                        added += form_after((v, m), lambda c, v=v, m=m: [self.gid(m)] + sign_gids(c, v))
                    else:
                        added += form_after((v, m), lambda c, v=v, m=m: sign_gids(c, v) + [self.gid(m)],
                                            stacked=lambda c, run, m=m: modifier_moved(c, run, m))
        for iv in spec.independent_vowels:
            for m in spec.modifiers:
                if not (self.has(iv) and self.has(m)):
                    continue
                run = self.shape((iv, m))
                if self._valid_run(run) and run.gids != [self.gid(iv), self.gid(m)]:
                    self._add((iv, m), run, KIND_BASE)
                    added += 1
        # ि + modifier (हिं): per base, with a reph, and generic. The fused
        # glyph replaces the sign; the base is unchanged.
        i_sign = spec.pre_sign_with_forms
        gid_i = self.gid(i_sign) if i_sign else 0
        if gid_i:
            for m in spec.modifiers:
                if not self.has(m):
                    continue
                alt_marks = collections.Counter()
                moved = collections.Counter()
                moved_example = {}
                skipped = 0
                fused_signs = collections.Counter()
                fused_example = {}
                for base in [b for b in bases if len(b) <= 3]:
                    key = base + (i_sign, m)
                    if len(key) > spec.max_key_len:
                        continue
                    sim = self._simulate(base)
                    own = self._table.get(base + (i_sign,))
                    own_sign = own[0] if own else gid_i
                    default = (list(own) if own else [gid_i]) + sim + [self.gid(m)]
                    run = self.shape_internal(key)
                    if (self._valid_run(run) and len(run.gids) == len(sim) + 2 and run.gids[1:-1] == sim
                            and run.gids[-1] == self.gid(m)):
                        # Same glyph, different place: fonts move the modifier onto the
                        # end of the sign's flag (Tiro Sanskrit मिं, by a chained
                        # contextual lookup). The device places a mark from the base's
                        # anchor and cannot see the sign, so the modifier becomes its own
                        # mark, keyed modifier + sign, anchored in this context.
                        plain = self.shape_internal(base + (m,))
                        if (self._valid_run(plain) and plain.gids[-1] == self.gid(m)
                                and len(plain.gids) == len(sim) + 1):
                            here = sum(g[1] for g in run.glyphs[1:-1]) + run.glyphs[-1][2]
                            there = sum(g[1] for g in plain.glyphs[:-1]) + plain.glyphs[-1][2]
                            if abs(here - there) > self.upem // 32:  # about a pixel at 16 pt
                                moved[True] += 1
                                moved_example.setdefault(True, run)
                            else:
                                moved[False] += 1
                    if (self._valid_run(run) and len(run.gids) == len(sim) + 2 and run.gids[1:-1] == sim
                            and run.gids[-1] != self.gid(m)):
                        # The sign keeps its form and only the modifier changes
                        # (Noto: ঁ.alt after a wide ি): one mark variant for all
                        # bases, keyed modifier + sign, instead of a composite per base.
                        alt_marks[(run.gids[-1], run.gids[0] == own_sign)] += 1
                        if run.gids[0] != own_sign:
                            skipped += 1
                            # The sign fuses with the modifier and the modifier's slot
                            # holds an empty glyph (Hind কিঁ: ি+ঁ as one glyph, then
                            # bnNull): the fused sign is the form, generic for all bases.
                            if not self._has_ink(run.gids[-1]):
                                fused_signs[run.gids[0]] += 1
                                fused_example.setdefault(run.gids[0], run)
                        continue
                    added += self._add_sign_form(key, run if self._valid_run(run) else None, default, 1, sim)
                # One anchor cannot serve both contexts once a tenth of the bases move
                # (Tiro Sanskrit: 196 of 546 for ँ). The variant is anchored per base in
                # this context, so the bases that do not move keep their placement.
                total_bases = moved[True] + moved[False]
                if moved[True] >= max(20, total_bases // 10) and (m, i_sign) not in self._table:
                    # The lift the font gives it in this context is part of the variant.
                    self._add((m, i_sign), GlyphRun(moved_example[True].glyphs[-1:], keep_y=True), KIND_ABOVE)
                    added += 1
                    if log:
                        log(f"  {spec.name}: U+{m:04X} moves after the pre-base sign on {moved[True]} of "
                            f"{total_bases} bases; keyed as its own mark")
                if fused_signs and (i_sign, m) not in self._table:
                    gid_fused, n = fused_signs.most_common(1)[0]
                    if n >= max(20, skipped // 2):
                        self._add((i_sign, m), GlyphRun(fused_example[gid_fused].glyphs[:1]), KIND_PRE)
                        added += 1
                        if log:
                            log(f"  {spec.name}: ি+U+{m:04X} fuse into one glyph on {n} bases; generic form added")
                # The modifier's own variant comes from the bases whose sign stays
                # plain; where the sign fused, the fused form above stands in.
                alt_marks = collections.Counter({k: v for k, v in alt_marks.items() if k[1]})
                if alt_marks:
                    (alt, _), n = alt_marks.most_common(1)[0]
                    if (m, i_sign) not in self._table:
                        example = next((r for r in (self.shape_internal(b + (i_sign, m)) for b in bases if len(b) <= 3)
                                        if self._valid_run(r) and r.gids[-1] == alt), None)
                        if example is not None:
                            self._add((m, i_sign), GlyphRun(example.glyphs[-1:]), KIND_ABOVE)
                            added += 1
                    if skipped and log:
                        log(f"  {spec.name}: {skipped} bases change both the sign and the modifier after ি+U+{m:04X}; "
                            f"kept the modifier variant only")
                if reph:
                    key = R + (i_sign, m)
                    own = self._table.get(R + (i_sign,))
                    sim = [ka]
                    default = (list(own) if own else [gid_i]) + sim + [self.gid(m)]
                    run = self.shape_internal(R + (spec.probe, i_sign, m))
                    added += self._add_sign_form(key, run if self._valid_run(run) else None, default, 1, sim,
                                                 generic=True)
                run = self.shape_internal((spec.probe, i_sign, m))
                if self._valid_run(run) and run.gids[-1:] == [ka] and len(run.gids) == 2:
                    generic = (i_sign, m)
                    if generic not in self._table and run.gids[0] != gid_i:
                        self._add(generic, GlyphRun(run.glyphs[:1]), KIND_PRE)
                        added += 1

        # ी + modifier per base (कीं, नहीं), where the fused glyph differs
        # from the base's own ी form plus the modifier; the same for the other
        # post-base signs with per-base forms (Hind পৌঁ: the taller ৗ, which a
        # generic ৗ + ঁ form would otherwise replace).
        for ii in (spec.post_signs_with_forms or (spec.post_sign_with_forms,)):
            if not ii or not self.has(ii):
                continue
            for base in [b for b in bases if len(b) == 1]:
                for m in spec.modifiers:
                    key = base + (ii, m)
                    if len(key) > spec.max_key_len or not self.has(m):
                        continue
                    sim = self._simulate(base)
                    own = self._table.get(base + (ii,))
                    default = sim + (list(own) if own else [self.gid(ii)]) + [self.gid(m)]
                    # What the device draws without a per-base entry: the engine tries
                    # the generic sign + modifier form before the base's own sign form.
                    generic = self._table.get((ii, m))
                    device = sim + list(generic) if generic is not None else default
                    run = self.shape_internal(base + (ii, m))  # not the word-final form (Tiro ীং)
                    if not self._valid_run(run) or run.gids == device:
                        continue
                    if run.gids[:len(sim)] != sim or len(run.gids) <= len(sim):
                        continue
                    self._add(key, GlyphRun(run.glyphs[len(sim):]), KIND_POST)
                    added += 1
        return added

    def _generic_reph_sign(self, consonants, sign, prefix_len, log):
        """(spec.ra, spec.virama, sign): the sign fused with a reph for clusters that have
        no exact entry. Taken from the form most consonants share."""
        spec = self.spec
        counts = {}
        for c in consonants:
            form = next((f for f in self.forms if f.key == (spec.ra, spec.virama, c, sign)), None)
            if form is None or form.kind not in (KIND_PRE, KIND_POST):
                continue
            counts.setdefault(tuple(form.run.gids), []).append(form)
        if not counts:
            return 0
        gids, forms = max(counts.items(), key=lambda kv: len(kv[1]))
        if len(forms) < len(consonants) // 2:
            return 0
        self._add((spec.ra, spec.virama, sign), forms[0].run, forms[0].kind)
        return 1





# --- Rasterisation -----------------------------------------------------------

class CompositeBitmap:
    """8-bit greyscale raster of a shaped run with EpdGlyph-style metrics."""
    __slots__ = ("width", "height", "left", "top", "advance_fp4", "rows")

    def __init__(self, width, height, left, top, advance_fp4, rows):
        self.width = width
        self.height = height
        self.left = left
        self.top = top
        self.advance_fp4 = advance_fp4
        self.rows = rows  # list of bytearray, one per row, top-down


def _glyph_gray(face, gid, load_flags):
    face.load_glyph(gid, load_flags)
    bitmap = face.glyph.bitmap
    buf = bitmap.buffer
    abs_pitch = abs(bitmap.pitch)
    rows = []
    for y in range(bitmap.rows):
        row_offset = y * abs_pitch if bitmap.pitch >= 0 else (bitmap.rows - 1 - y) * abs_pitch
        rows.append(bytearray(buf[row_offset:row_offset + bitmap.width]))
    return bitmap.width, bitmap.rows, face.glyph.bitmap_left, face.glyph.bitmap_top, rows


def render_run(face, run, scale, load_flags, mark=False):
    """Rasterise a GlyphRun at the face's current size.

    scale: pixels per font unit at the target ppem. For marks (mark=True)
    the run's advance is forced to zero and the bitmap is placed relative
    to the first glyph's own origin: the run was shaped after a probe
    consonant, so its offsets carry that base's mark anchor, which the
    device adds again from the real base's glyph anchor (v5 fonts). The
    later glyphs keep their offsets relative to the first one (mark-to-mark).
    """
    placed = []
    pen = 0.0
    origin_x = run.glyphs[0][2] if mark and run.glyphs else 0
    origin_y = 0 if getattr(run, "keep_y", False) else (run.glyphs[0][3] if mark and run.glyphs else 0)
    for gid, x_adv, x_off, y_off in run.glyphs:
        width, height, left, top, rows = _glyph_gray(face, gid, load_flags)
        if width and height:
            x = int(round(pen + (x_off - origin_x) * scale)) + left
            y = int(round((y_off - origin_y) * scale)) + top
            placed.append((x, y, width, height, rows))
        pen += x_adv * scale
    advance_fp4 = 0 if mark else max(0, int(round(run.advance * scale * 16)))
    if not placed:
        return CompositeBitmap(0, 0, 0, 0, advance_fp4, [])
    min_x = min(p[0] for p in placed)
    max_x = max(p[0] + p[2] for p in placed)
    top = max(p[1] for p in placed)
    bottom = min(p[1] - p[3] for p in placed)
    width = max_x - min_x
    height = top - bottom
    canvas = [bytearray(width) for _ in range(height)]
    for x, y, w, h, rows in placed:
        for r in range(h):
            dst = canvas[top - y + r]
            src = rows[r]
            base = x - min_x
            for c in range(w):
                v = src[c]
                if v > dst[base + c]:
                    dst[base + c] = v
    return CompositeBitmap(width, height, min_x, top, advance_fp4, canvas)


def classify_mark_kind(bitmap):
    """Above- or below-base placement for a zero-advance form, from its ink."""
    if bitmap.height == 0:
        return KIND_BELOW
    center = bitmap.top - bitmap.height / 2.0
    return KIND_ABOVE if center > 0 else KIND_BELOW


def allocate_pua(forms, spec):
    """Assign PUA codepoints per kind. Returns ({key: cp}, {cp: form}) or
    raises when a kind has more forms than its PUA range holds (the table
    would otherwise carry rows whose glyph was never allocated)."""
    by_kind = {kind: [] for kind in PUA_RANGES}
    for form in forms:
        if form.kind == KIND_META:
            continue
        by_kind[form.kind].append(form)
    key_to_cp = {}
    cp_to_form = {}
    for kind, items in by_kind.items():
        start, end = PUA_RANGES[kind]
        capacity = end - start + 1
        if len(items) > capacity:
            raise ValueError(f"{spec.name}: {len(items)} {kind} forms exceed the {capacity}-codepoint PUA range")
        items.sort(key=lambda f: key_bytes(f.key, spec))
        for i, form in enumerate(items):
            cp = start + i
            key_to_cp[form.key] = cp
            cp_to_form[cp] = form
    return key_to_cp, cp_to_form


# -- Mark attachment anchors (.cpfont v5 glyph record bytes 10-11) -----------

ANCHOR_NONE = 0
ANCHOR_BIAS = 128


def anchor_byte(units, unit_scale, clamped=None):
    """Half pixels at the target size, biased so 0 means none. A value past
    +-127 (63.5 px) is clamped and, when `clamped` is given, recorded there:
    the mark then lands short of the font's point (wide sign-fused composites
    at 18-20 pt)."""
    v = int(round(units * unit_scale * 2))
    if clamped is not None and abs(v) > 127:
        clamped.append(v)
    return max(-127, min(127, v)) + ANCHOR_BIAS


# Mark placement modes (.cpfont v6): the byte of the mark's other class.
MODE_CLASS, MODE_PEN, MODE_OTHER, MODE_EXTRA = 0, 1, 2, 3
MODE_NAMES = {MODE_CLASS: "class anchor", MODE_PEN: "pen", MODE_OTHER: "other-class anchor", MODE_EXTRA: "extra anchor"}


def half_to_px(half):
    return (half + 1) // 2 if half >= 0 else -((-half + 1) // 2)


def mark_offset_px(below, base_bytes, adv_px, mark_bytes):
    """Mirror of glyphAnchor::markOffsetWithMode: pixels from the base cursor
    to the mark cursor for a mark of class `below` with record bytes
    `mark_bytes` = (anchorAbove, anchorBelow) over a base with
    `base_bytes` = (above, below, extra) and advance `adv_px`; None when
    the needed point is missing."""
    value = mark_bytes[1] if below else mark_bytes[0]
    mode = mark_bytes[0] if below else mark_bytes[1]
    if mode == MODE_PEN:
        return None if value == ANCHOR_NONE else adv_px + half_to_px(value - ANCHOR_BIAS)
    if mode == MODE_OTHER:
        base = base_bytes[0] if below else base_bytes[1]
    elif mode == MODE_EXTRA:
        base = base_bytes[2] if len(base_bytes) > 2 else ANCHOR_NONE
    else:
        base = base_bytes[1] if below else base_bytes[0]
    return anchor_offset_px(base, value)


def anchor_offset_px(base_byte, mark_byte):
    """Mirror of glyphAnchor::markOffset: pixels from the base cursor to the
    mark cursor, or None without anchors."""
    if base_byte == ANCHOR_NONE or mark_byte == ANCHOR_NONE:
        return None
    half = (base_byte - ANCHOR_BIAS) - (mark_byte - ANCHOR_BIAS)
    return (half + 1) // 2 if half >= 0 else -((-half + 1) // 2)


PAIR_WEIGHT_CAP = 30  # how far a pair's count in the sample may lift its weight
_PAIR_COUNTS = {}


def pair_counts(spec):
    """{(base cp, mark cp): occurrences} and {mark cp: occurrences} in the provider's
    word sample (providers/<script>/words.txt), the base being the spacing letter or
    post-base sign the renderer would attach the mark to. Used to weight the anchor
    fit: a pair the books never show must not outvote one they are full of (ाँ)."""
    if spec.name in _PAIR_COUNTS:
        return _PAIR_COUNTS[spec.name]
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "providers", spec.name, "words.txt")
    pairs, seen = collections.Counter(), collections.Counter()
    spacing = set(spec.consonants) | set(spec.post_vowels) | set(spec.independent_vowels)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    prev = None
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp == spec.virama and i + 1 < len(text) and ord(text[i + 1]) in spec.consonant_set:
            prev = None  # a virama inside a conjunct joins letters, it is not drawn as a mark
            continue
        if spec.is_mark(cp):
            seen[cp] += 1
            if prev is not None:
                pairs[(prev, cp)] += 1
        elif cp in spacing:
            prev = cp
        elif not ch.isspace():
            prev = None
    _PAIR_COUNTS[spec.name] = (pairs, seen)
    return _PAIR_COUNTS[spec.name]


class MarkSurvey:
    """Where the font puts every mark over every base: the data the anchor
    pass and its diagnostics share. `origins[m][b]` is the mark's origin in
    font units from the base's origin, or None when the font does not draw
    the pair as base run + mark run; `plausible(b, m)` says whether the pair
    occurs in text; `weight(m)` how common the mark is."""

    def __init__(self, plan, cp_to_form):
        self.plan, self.cp_to_form = plan, cp_to_form
        spec = plan.spec
        block = range(spec.block_base, spec.block_base + 0x80)
        lead = plan.gid(spec.probe)

        # The per-codepoint and per-pair predicates below are pure functions of
        # the survey's inputs and are asked millions of times by the anchor fit
        # (2.3 M plausible() calls for Noto Serif Devanagari), so they memoise.
        @functools.lru_cache(maxsize=None)
        def text_of(cp):
            form = cp_to_form.get(cp)
            if form is None:
                return (cp,)
            return tuple(c for c in form.key if c < 0x2000 or c == ZWJ)

        def run_of(cp):
            form = cp_to_form.get(cp)
            return [plan.gid(cp)] if form is None else list(form.run.gids)

        def is_mark(cp):
            form = cp_to_form.get(cp)
            if form is not None:
                return form.kind in MARK_KINDS
            run = plan.shape((spec.probe, cp))
            return len(run.glyphs) == 2 and run.glyphs[0][0] == plan.gid(spec.probe) and run.glyphs[1][1] == 0

        candidates = [cp for cp in block if plan.has(cp)] + sorted(cp_to_form)
        marks = [cp for cp in candidates if is_mark(cp)]
        bases = [cp for cp in candidates if not is_mark(cp) and run_of(cp)]
        reph_before = {m for m in marks if m >= 0xE000 and cp_to_form[m].key[:2] == (spec.ra, spec.virama)}

        below_signs_early = set(spec.below_signs)
        candrabindu_context = ({spec.candrabindu} if spec.candrabindu_before_post else set())
        sign_cps = (set(spec.post_vowels) | set(spec.above_vowels) | below_signs_early
                    | set(spec.pre_signs_with_forms) | set(spec.init_signs)
                    | ({spec.pre_sign_with_forms} if spec.pre_sign_with_forms else set())
                    | ({spec.post_sign_with_forms} if spec.post_sign_with_forms else set()))
        modifier_cps = set(spec.modifiers)

        dotted = plan.gid(0x25CC) if plan.has(0x25CC) else None

        def base_runs(b):
            # The glyph runs the font may draw this base with: its own, and the
            # word-final / word-internal shaping of the same text (Tiro Bangla's
            # হ্য has a .fina form; the device draws the form either way). A run
            # with a dotted circle is the font complaining that a sign has no
            # consonant (ी alone), not a way it draws the base.
            runs = {tuple(run_of(b))}
            for r in (plan.shape(text_of(b)), plan.shape_internal(text_of(b))):
                if r.gids and dotted not in r.gids:
                    runs.add(tuple(r.gids))
            return runs

        # A sign's width-class variant (ी.class1) only appears after a letter of
        # its class: the survey shapes it after one, so the marks it carries are
        # measured on the variant glyph rather than on the plain sign.
        class_lead = {}
        for f in plan.forms:
            for cls, sign in ((f.post_class, spec.post_sign_with_forms), (f.pre_class, spec.pre_sign_with_forms)):
                if not cls or not sign or (sign, cls) in class_lead and len(class_lead[(sign, cls)]) == 1:
                    continue
                text = tuple(c for c in f.key if c < 0x2000 or c == ZWJ)
                if text and all(c in spec.consonants or c in (spec.virama, ZWJ) for c in text):
                    if (sign, cls) not in class_lead or len(text) < len(class_lead[(sign, cls)]):
                        class_lead[(sign, cls)] = text

        def variant_lead(b):
            form = cp_to_form.get(b)
            if form is None or form.key[0] != VARIANT_CP or len(form.key) < 3:
                return None
            return class_lead.get((form.key[1], form.key[2] - CLASS_INDEX_CP))

        base_runs_cache = {}

        def find_run(gids, sub):
            for i in range(len(gids) - len(sub) + 1):
                if gids[i:i + len(sub)] == sub:
                    return i
            return None

        def origin(b, m):
            # Where the font puts the origin of mark m over base b, in units from
            # the base's origin, or None when it does not draw the pair as the base
            # run plus the mark run (fused, or the sign needs a consonant first, in
            # which case the probe letter leads and is skipped). The mark run may
            # sit anywhere in the output: fonts reorder a mark around a post-base
            # form (Noto Sans draws ছ্যঁ as ছ, ঁ, ya-phala). A fused reph mark is
            # shaped as its reph head, the base, then its tail (र् + क + ं): its
            # own text order (र्ं + क) is not one the font can shape.
            btext, mtext, mrun = text_of(b), text_of(m), run_of(m)
            if len(mtext) == 2 and mtext[0] in modifier_cps and mtext[1] in sign_cps:
                mtext = (mtext[1], mtext[0])  # a modifier fused with a sign is keyed modifier first (ঁি)
            runs = base_runs_cache.get(b)
            if runs is None:
                runs = base_runs_cache[b] = base_runs(b)
            # The candrabindu is written after a post-base sign the device draws it
            # before (ছ্যাঁ, কাঁ): shaped without that sign, a font may place it
            # somewhere else entirely (Noto Sans moves it ahead of the ya-phala).
            tails = [()]
            if m in candrabindu_context and cp_to_form.get(b) is not None:
                tails = [(spec.candrabindu_before_post[0],), ()]
            leads = [((), 0), ((spec.probe,), 1)]
            vlead = variant_lead(b)
            if vlead is not None:
                leads = [(vlead, 2)]  # the variant glyph needs its class letter first
            for tail in tails:
                for lead_text, skip in leads:
                    if m in reph_before:
                        seq = tuple(mtext[:2]) + lead_text + tuple(btext) + tuple(mtext[2:]) + tail
                    else:
                        seq = lead_text + tuple(btext) + tail + tuple(mtext)
                    out = plan.shape(seq)
                    j = find_run(out.gids, mrun)
                    if j is None or out.glyphs[j][1] != 0:
                        continue
                    rest_gids = out.gids[:j] + out.gids[j + len(mrun):]
                    # The base's run must stand in what is left; around it only the probe
                    # letter and the spacing glyphs of the context (the ি of a modifier +
                    # sign variant, which the font moves ahead of the base, or the tail).
                    hit = next(((r, i) for r in runs for i in [find_run(rest_gids, list(r))] if i is not None), None)
                    if hit is None or (skip == 1 and rest_gids[0] != lead) or (skip == 2 and hit[1] == 0):
                        continue
                    run, i = hit
                    start = i + (len(mrun) if j <= i else 0)  # index in the full output
                    heights[(b, m)] = out.glyphs[j][3] - out.glyphs[start][3]
                    return sum(g[1] for g in out.glyphs[:j]) + out.glyphs[j][2] - sum(g[1] for g in out.glyphs[:start])
            return None

        heights = {}  # (base, mark) -> the mark's y offset over the base, font units, up positive
        origins = {m: {b: origin(b, m) for b in bases} for m in marks}
        # Signs outside the block's 0x3E..0x4C sign range (Bengali ৗ) are bases the
        # renderer attaches modifiers to just the same (sign_cps, set above).
        below_signs = below_signs_early

        @functools.lru_cache(maxsize=None)
        def text_mark(m):
            # The Unicode mark a form stands for: its key's last mark (ं for र्ं, ं for
            # the ি-context variant), used for the corpus counts and the rules below.
            key = cp_to_form[m].key if m >= 0xE000 else (m,)
            return next((c for c in reversed(key) if c < 0x2000 and spec.is_mark(c)), None)

        @functools.lru_cache(maxsize=None)
        def plausible(b, m):
            # Pairs that occur in text: no second mark of a class a cluster
            # already carries, nothing on digits or half forms, modifiers only
            # after a post-base sign, and no repeated rakar / phala.
            bf, mf = cp_to_form.get(b), cp_to_form.get(m)
            key = tuple(bf.key) if bf is not None else (b,)
            if bf is None and b not in spec.consonants and b not in sign_cps and not spec.block_base + 0x04 <= b <= spec.block_base + 0x4C:
                return False
            if key[-1] == ZWJ:
                return False
            if bf is None and spec.block_base + 0x04 <= b <= spec.block_base + 0x14:
                # An independent vowel carries the modifiers (एँ, ঐং) and the nukta,
                # never a vowel sign: a probe that shapes on it anyway (ए + े) would
                # anchor it wherever the font parks an impossible pair.
                return m in (spec.block_base + 0x01, spec.block_base + 0x02, spec.block_base + 0x03,
                             spec.block_base + 0x3C)
            if bf is None and (spec.block_base + 0x3E <= b <= spec.block_base + 0x4C or b in sign_cps):
                # A bare vowel sign carries the modifiers, and, where the reph
                # is drawn after the post-base sign (Devanagari र्का: ka, aa,
                # reph), the reph marks as well: the sign is the base the
                # renderer attaches them to.
                if m in (spec.block_base + 1, spec.block_base + 2, spec.block_base + 3):
                    return True
                return spec.reph_after_post and m in reph_before and not spec.attaches_below(b)
            if spec.attaches_below(m):
                # A below sign the cluster already carries, or a trailing visible
                # virama; the viramas inside a conjunct (ক্ম্র) are not marks.
                if any(c in below_signs and c != spec.virama for c in key) or key[-1] == spec.virama:
                    return False
                if mf is not None and any(key[i] == spec.virama and key[i + 1] not in spec.consonants for i in range(len(key) - 1)):
                    return False
                if mf is not None and len(mf.key) >= 2 and mf.key[0] == spec.virama and any(
                        key[i] == spec.virama and key[i + 1] == mf.key[1] for i in range(len(key) - 1)):
                    return False
            else:
                if any(spec.block_base + 0x45 <= c <= spec.block_base + 0x48 for c in key):
                    return False
                # One modifier per syllable: a form that already fused one (া + ঃ)
                # never carries a second (কাঃঁ is not text).
                tm = text_mark(m)
                if (tm is not None and spec.block_base + 0x01 <= tm <= spec.block_base + 0x03
                        and any(spec.block_base + 0x01 <= c <= spec.block_base + 0x03 for c in key)):
                    return False
            return tuple(btext_cache.setdefault(b, text_of(b))) + tuple(text_of(m)) not in plan._table

        btext_cache = {}

        pairs_seen, marks_seen = pair_counts(spec)

        @functools.lru_cache(maxsize=None)
        def text_base(b):
            # The letter or post-base sign a base ends in (ম of ক্ম), which is what
            # the sample's counts are keyed by.
            return next((c for c in reversed(text_of(b)) if c in spacing_cps), None)

        spacing_cps = set(spec.consonants) | set(spec.post_vowels) | set(spec.independent_vowels)

        def weight(m):
            off = m - spec.block_base if m < 0xE000 else None
            if off == 0x02 or off == 0x47 or off == 0x41:
                return 3.0  # anusvara, e sign, u sign
            if off == 0x48 or off == 0x42 or off == 0x4D:
                return 2.0  # ai sign, uu sign, virama
            if off == 0x01 or off == 0x43:
                return 1.5  # candrabindu, vocalic r
            if m in reph_before or PUA_BELOW[0] <= m <= PUA_BELOW[1]:
                return 2.0  # reph, rakar / phala marks
            return 0.5

        @functools.lru_cache(maxsize=None)
        def pair_weight(b, m):
            # How much this pair counts when anchors are fitted: the mark's own weight,
            # a tenth for a mark the sample never shows (Vedic accents, which the
            # relaxed survey pairs with hundreds of bases), times how often the books
            # put this mark on this base, capped so one pair cannot decide alone.
            tm = text_mark(m)
            w = weight(m) * (1.0 if tm is not None and marks_seen[tm] else 0.1)
            tb = text_base(b)
            if tm is None or tb is None:
                return w
            return w * (1 + min(pairs_seen[(tb, tm)], PAIR_WEIGHT_CAP))

        def mark_weight(m):
            tm = text_mark(m)
            return weight(m) * (1.0 if tm is not None and marks_seen[tm] else 0.1)

        self.spec, self.bases, self.marks, self.origins = spec, bases, marks, origins
        self.heights = heights
        self.reph_before, self.plausible, self.weight = reph_before, plausible, weight
        self.pair_weight, self.mark_weight = pair_weight, mark_weight
        self.is_mark, self.text_of, self.run_of = is_mark, text_of, run_of


def compute_anchors(plan, cp_to_form, unit_scale, log=None, survey=None):
    """{cp: (above, below)} anchor bytes for the script's glyphs. `survey` is
    a MarkSurvey of the same plan and cp_to_form when the caller has one.

    A base (any spacing glyph: letters, signs, PUA composites) stores where
    HarfBuzz puts the origin of an above / below mark, as an x offset from
    the base cursor; a mark stores its own anchor, so that base anchor - mark
    anchor is the mark cursor. Fonts attach different marks at different
    points, and one byte per class can carry one of them exactly: the probe.
    Every base x mark pair is shaped once; each candidate probe (anusvara or
    candrabindu, e sign, reph above; u sign, virama below) is scored by the
    residual it leaves on the other marks of its class, weighted by how
    common they are, and the best one wins for this font. The other marks
    take the median offset over the bases the device draws them on (the
    pair is not a cluster-table composite), so they sit within their class
    spread. Fused pairs need no anchor: the cluster table carries them."""
    if survey is None:
        survey = MarkSurvey(plan, cp_to_form)
    spec, bases, marks, origins = survey.spec, survey.bases, survey.marks, survey.origins
    reph_before, plausible, weight = survey.reph_before, survey.plausible, survey.mark_weight
    pair_weight = survey.pair_weight

    weighted = weighted_median

    def score(probe, members):
        total = 0.0
        for m in members:
            if m == probe:
                continue
            vals = [(origins[probe][b] - origins[m][b], pair_weight(b, m)) for b in bases
                    if origins[probe][b] is not None and origins[m][b] is not None and plausible(b, m)]
            if not vals:
                continue
            med, _, _ = weighted(vals)
            dev = sorted(abs(v - med) for v, _ in vals)
            total += weight(m) * dev[len(dev) // 2]  # median deviation: the bulk, not the odd conjunct
        return total

    classes = {"above": [m for m in marks if not spec.attaches_below(m)], "below": [m for m in marks if spec.attaches_below(m)]}
    options = {"above": [], "below": []}
    for off in (0x02, 0x01, 0x47):
        cp = spec.block_base + off
        if cp in marks and cp not in options["above"]:
            options["above"].append(cp)
    options["above"] += [m for m in marks if m in reph_before and cp_to_form[m].key == (spec.ra, spec.virama)]
    for off in (0x41, 0x4D):
        cp = spec.block_base + off
        if cp in marks:
            options["below"].append(cp)
    # Subjoined consonant marks (rakar, Bengali ra-/ba-phala) attach at their
    # own point in some fonts and sit under many conjuncts: candidates too.
    options["below"] += [m for m in marks if m >= 0xE000 and len(cp_to_form[m].key) == 2
                         and cp_to_form[m].key[0] == spec.virama and cp_to_form[m].key[1] in spec.consonants]
    # A base's anchor is where the first probe lands on it. When that probe
    # does not shape on a base, the next one that does is used, its origin
    # moved into the first probe's frame by that probe's median offset, so
    # the mark offsets stored below apply to every base alike. A bare vowel
    # sign (ो, ে) only ever carries modifiers, and fonts place them on it
    # independently of the vowel probes: it is probed with a plausible mark.
    def assign(probes):
        shift = {probes[0]: 0}
        for p in probes[1:]:
            vals = [(origins[probes[0]][b] - origins[p][b], pair_weight(b, p)) for b in bases
                    if origins[probes[0]][b] is not None and origins[p][b] is not None
                    and plausible(b, probes[0]) and plausible(b, p)]
            shift[p] = weighted(vals)[0] or 0
        out = {}
        for b in bases:
            found = [p for p in probes if origins[p][b] is not None]
            if not found:
                continue
            # The probe must be one that occurs on this base: a sign shapes on an
            # independent vowel (ए + े) or on another sign, and the font parks such a
            # pair wherever it likes, which is no anchor for the marks that do occur.
            pick = next((p for p in found if plausible(b, p)), found[0])
            out[b] = origins[pick][b] + shift[pick]
        return out

    # The first probe is chosen by outcome: anchors are assigned with each
    # candidate first (the others follow in score order), and the residual
    # left on every (base, mark) pair of the class, weighted by how common
    # the mark is, decides; a mark drawn on many bases therefore counts for
    # more than one drawn on a few. Scoring the candidates only where they
    # exist would favour a mark that shapes on a homogeneous few bases (Noto
    # Sans Bengali: the ba-phala mark on a handful of conjuncts beat ু and
    # left every rakar conjunct 7 px off).
    def residual(cls, base_anchor):
        total = 0.0
        for m in classes[cls]:
            vals = [(base_anchor[b] - origins[m][b], pair_weight(b, m)) for b in bases
                    if b in base_anchor and origins[m][b] is not None and plausible(b, m)]
            if not vals:
                continue
            _, resid, _ = weighted(vals)
            total += resid
        return total

    order = {}
    base_anchor = {"above": {}, "below": {}}
    for cls, opts in options.items():
        if not opts:
            continue
        by_score = sorted(opts, key=lambda p: score(p, classes[cls]))
        outcomes = {}
        for p in by_score:
            probes = [p] + [q for q in by_score if q != p]
            outcomes[p] = residual(cls, assign(probes))
        first = min(by_score, key=lambda p: outcomes[p])
        order[cls] = [first] + [q for q in by_score if q != first]
        base_anchor[cls] = assign(order[cls])
        if log:
            log(f"  {spec.name}: {cls} probes by residual " + ", ".join(
                f"U+{p:04X} {outcomes[p]:.0f}" for p in sorted(by_score, key=lambda p: outcomes[p])))
    # Placement modes (.cpfont v6). Each mark's value can be measured from
    # one of four base points: the anchor of its class (the v5 rule), the
    # anchor of the other class, the base's advance (pen), or a third point
    # stored per base (anchorExtra) for the one mark per font that fits none
    # of the others (Tiro Sanskrit's anusvara). Per mark the frame with the
    # smallest weighted residual wins, ties to the class anchor; the extra
    # probe is the mark whose frame lowers the total residual the most.
    adv = {b: sum(g[1] for g in plan.shape(survey.text_of(b)).glyphs) for b in bases}

    def pairs_of(m):
        return [b for b in bases if origins[m][b] is not None and plausible(b, m)]

    def fit(m, frame, sign=1):
        vals = [(sign * (frame[b] - origins[m][b]), pair_weight(b, m)) for b in pairs_of(m) if b in frame]
        if not vals:
            return None, float("inf"), 0.0
        med, resid, total = weighted(vals)
        return med, resid, total

    def extra_frame(p):
        cls = "below" if spec.attaches_below(p) else "above"
        ref = base_anchor[cls]
        shifts = sorted(origins[p][b] - ref[b] for b in pairs_of(p) if b in ref)
        shift = shifts[len(shifts) // 2] if shifts else 0
        return {b: (origins[p][b] if origins[p][b] is not None else ref[b] + shift)
                for b in bases if origins[p][b] is not None or b in ref}

    frames = {}
    for m in marks:
        cls = "below" if spec.attaches_below(m) else "above"
        other = "above" if cls == "below" else "below"
        frames[m] = {MODE_CLASS: fit(m, base_anchor[cls]), MODE_OTHER: fit(m, base_anchor[other]),
                     MODE_PEN: fit(m, adv, sign=-1)}  # pen: mark origin minus the advance
    scored = [m for m in marks if min(f[1] for f in frames[m].values()) < float("inf")]  # marks with pairs
    best_without = sum(min(f[1] for f in frames[m].values()) for m in scored)
    extra_probe, extra, best_total = None, {}, best_without
    candidates = {}
    for p in scored:
        if len(pairs_of(p)) < 20:
            continue
        frame = extra_frame(p)
        total = sum(min(min(f[1] for f in frames[m].values()), fit(m, frame)[1]) for m in scored)
        candidates[p] = total
        if total < best_total:
            extra_probe, extra, best_total = p, frame, total
    if log and candidates:
        log(f"  {spec.name}: extra anchor candidates by total residual (without one: {best_without:.0f}): " + ", ".join(
            f"U+{p:04X} {t:.0f}" for p, t in sorted(candidates.items(), key=lambda kv: kv[1])[:4]))
    if extra_probe is not None:
        for m in marks:
            frames[m][MODE_EXTRA] = fit(m, extra)

    anchors = {}
    clamped = []  # anchor values past the byte's range, for the log
    for b in bases:
        a, d, e = base_anchor["above"].get(b), base_anchor["below"].get(b), extra.get(b)
        if a is not None or d is not None or e is not None:
            anchors[b] = (anchor_byte(a, unit_scale, clamped) if a is not None else ANCHOR_NONE,
                          anchor_byte(d, unit_scale, clamped) if d is not None else ANCHOR_NONE,
                          anchor_byte(e, unit_scale, clamped) if e is not None else ANCHOR_NONE)
    # A modifier keyed with the pre-base sign is drawn only in that context, where the
    # font hangs it off the sign's flag: that point follows the base's width, so it is
    # measured from the class anchor or the pen, never from another mark's point.
    context_variants = {cp for cp, f in cp_to_form.items()
                        if len(f.key) == 2 and f.key[0] in spec.modifiers and f.key[1] == spec.pre_sign_with_forms}
    marks_done = 0
    chosen = collections.Counter()
    for m in marks:
        cls = "below" if spec.attaches_below(m) else "above"
        # The class anchor (the v5 rule) stays unless another point is clearly
        # better: a near tie in the builder's sample is noise in the audit's.
        allowed = {MODE_CLASS, MODE_PEN} if m in context_variants else set(frames[m])
        mode = min((k for k in frames[m] if k in allowed), key=lambda k: (frames[m][k][1], k))
        if mode != MODE_CLASS and frames[m][mode][1] > 0.9 * frames[m][MODE_CLASS][1]:
            mode = MODE_CLASS
        med, resid, n = frames[m][mode]
        if med is None:
            continue
        byte = anchor_byte(med, unit_scale, clamped)
        anchors[m] = (byte, mode, ANCHOR_NONE) if cls == "above" else (mode, byte, ANCHOR_NONE)
        marks_done += 1
        chosen[mode] += 1
        if log and mode != MODE_CLASS:
            cls_med, cls_resid, cls_total = frames[m][MODE_CLASS]
            log(f"  {spec.name}: U+{m:04X} placed by {MODE_NAMES[mode]} (residual {resid / max(n, 1e-9) * unit_scale:.2f} px "
                f"vs {cls_resid / max(cls_total, 1e-9) * unit_scale:.2f} px from the class anchor)")
    if log:
        log(f"  {spec.name}: mark anchors for {len(anchors) - marks_done} bases and {marks_done} marks "
            f"(probes above {' '.join('U+%04X' % p for p in order.get('above', []))}, "
            f"below {' '.join('U+%04X' % p for p in order.get('below', []))}"
            + (f", extra U+{extra_probe:04X}" if extra_probe is not None else "") + "); modes: "
            + ", ".join(f"{MODE_NAMES[k]} {v}" for k, v in sorted(chosen.items())))
        if clamped:
            log(f"  {spec.name}: {len(clamped)} anchor bytes clamped at 63.5 px (largest "
                f"{max(abs(v) for v in clamped) / 2:.1f} px): marks on those bases land short of the font's point")
    return anchors


def weighted_median(items):
    """(median, weighted sum of deviations, total weight) of [(value, weight)]."""
    if not items:
        return None, 0.0, 0.0
    items = sorted(items)
    total = sum(w for _, w in items)
    acc = 0.0
    med = items[-1][0]
    for v, w in items:
        acc += w
        if acc >= total / 2:
            med = v
            break
    return med, sum(w * abs(v - med) for v, w in items), total


# Column of a half-form pair variant when another half form follows (ि before
# ष्ट्र...): past the sign classes, which take columns class + 1.
HALF_PAIR_FOLLOWS = 14
# A post-sign class is stored in the three high bits of an entry's value.
MAX_POST_SIGN_CLASS = 7

MAX_LIFT_SPREAD_EM = 0.06  # 2 px at 16 pt: more spread left after a lift means the height follows the base
LIFT_EXCEPTION_EM = 0.045  # 1.5 px at 16 pt: a bare base the lifted mark would miss by more gets a composite


def mark_lifts(survey, cp_to_form, log=None):
    """{mark key: font units} to add to a mark glyph's height so it sits where
    the font puts it on its usual bases; the key is (cp,) for a Unicode mark,
    the form's key for a PUA mark (codepoints move when forms are added). The
    device draws a mark at the height its bitmap carries (the glyph's own, or
    the context lift a keep_y form bakes in) and has no per-base vertical
    anchor; HarfBuzz moves marks up or down with GPOS (Noto Serif Bengali lowers
    ঁ ~1.7 px on most letters). The lift is the weighted median, over the pairs
    the anchor fit uses (same corpus weights), of HarfBuzz's y minus the drawn
    one. A mark whose height depends on the base (ু under conjuncts), or one the
    book sample never shows (the Vedic accents, fitted on guessed pairs), is left
    alone: a constant made as many words worse as better there (Noto Sans ু,
    Tiro ॒; 2026-09-24). Everything is in font units, so every size lifts the same
    marks and the cluster table stays the same across sizes."""
    spec = survey.spec
    upem = survey.plan.font.face.upem
    out = {}
    for m in survey.marks:
        if survey.mark_weight(m) < survey.weight(m):
            continue  # not in the sample
        form = cp_to_form.get(m)
        drawn = form.run.glyphs[0][3] if form is not None and getattr(form.run, "keep_y", False) and form.run.glyphs else 0
        vals = [(survey.heights[(b, m)] - drawn, survey.pair_weight(b, m)) for b in survey.bases
                if (b, m) in survey.heights and survey.origins[m][b] is not None and survey.plausible(b, m)]
        if not vals:
            continue
        med, resid, total = weighted_median(vals)
        if total <= 0 or abs(med) < 0.5 / 33.3 * upem:
            continue  # under half a pixel at 16 pt
        if resid / total > MAX_LIFT_SPREAD_EM * upem:
            if log:
                log(f"  {spec.name}: U+{m:04X} not lifted: its height follows the base "
                    f"(spread {resid / total / upem:.3f} em around the median)")
            continue
        out[tuple(form.key) if form is not None else (m,)] = med
        if log:
            before = sum(w * abs(v) for v, w in vals) / total / upem
            log(f"  {spec.name}: U+{m:04X} lifted {med / upem:+.3f} em (weighted |dy| {before:.3f} -> "
                f"{resid / total / upem:.3f} em)")
    return out


_PLAN_CACHE = {}  # (font path, script, spec id) -> _PlanCache: the size-independent half of build_shaping


class _PlanCache:
    """What build_shaping computes in font units, kept across the point sizes
    of one conversion: the plan (forms, half-form joins, the font's shaping
    tables), the mark lifts with their base + modifier exceptions already
    added, and the last MarkSurvey with the PUA mapping it was built on."""
    __slots__ = ("spec", "plan", "lifts", "survey", "mapping")

    def __init__(self, spec, plan, lifts):
        self.spec, self.plan, self.lifts = spec, plan, lifts
        self.survey, self.mapping = None, None


def clear_plan_cache():
    _PLAN_CACHE.clear()


def _classify_mark_kinds(forms, face, unit_scale, load_flags):
    # Marks are classified from their rendered ink (above/below the
    # baseline) so the device picks the right anchor; the ink is the size's.
    for form in forms:
        if form.kind in MARK_KINDS:
            bmp = render_run(face, form.run, unit_scale, load_flags, mark=True)
            form.kind = classify_mark_kind(bmp)


def build_shaping(font_path, spec, face, unit_scale, load_flags, log=None, anchors_out=None,
                  advances_out=None, lefts_out=None, tops_out=None, plan_out=None):
    """Enumerate, classify and pack the cluster table of `font_path` for
    `spec`, rasterising the mark forms with the FreeType `face` (already set
    to the target size) to decide their placement. Returns
    (shape_kind, table_bytes, {pua_cp: ClusterForm}); shape_kind is 0 and the
    table empty when the font has nothing to shape. `plan_out`, a list, receives
    the IndicClusterPlan the table was packed from (the tools read glyph ids and
    runs off it).

    The enumeration, the mark lifts and the survey are in font units and are
    kept in _PLAN_CACHE across calls for the same font and spec (a conversion
    builds eight sizes): a later size only re-classifies the marks from its
    own ink, re-allocates the PUA, packs, and scales the anchors. The survey is
    rebuilt when that size's classification moves a form to another PUA range."""
    say = log or (lambda msg: print(msg, file=sys.stderr))
    cache_key = (os.path.abspath(font_path), spec.name, id(spec))
    cached = _PLAN_CACHE.get(cache_key)
    survey = None
    if cached is None:
        plan = IndicClusterPlan(font_path, spec)
        forms = plan.build(log)
        if plan_out is not None:
            plan_out.append(plan)
        if not forms:
            return 0, b"", {}
        _classify_mark_kinds(forms, face, unit_scale, load_flags)
        key_to_cp, cp_to_form = allocate_pua(forms, spec)
        # Mark heights (whole font, font units), then composites for the bare bases a
        # lifted modifier would miss (ইঁ keeps its candrabindu high where the font
        # lowers it on every other letter); adding forms moves the PUA numbers.
        survey = MarkSurvey(plan, cp_to_form)
        lifts = mark_lifts(survey, cp_to_form, say)
        if plan.add_lift_exceptions(lifts, say):
            forms = plan.forms
            key_to_cp, cp_to_form = allocate_pua(forms, spec)
            survey = None
        cached = _PLAN_CACHE[cache_key] = _PlanCache(spec, plan, lifts)
    else:
        plan, lifts = cached.plan, cached.lifts
        if plan_out is not None:
            plan_out.append(plan)
        forms = plan.forms
        if not forms:
            return 0, b"", {}
        _classify_mark_kinds(forms, face, unit_scale, load_flags)
        key_to_cp, cp_to_form = allocate_pua(forms, spec)
    mapping = tuple(sorted((cp, tuple(f.key)) for cp, f in cp_to_form.items()))
    if survey is None and cached.survey is not None and cached.mapping == mapping:
        survey = cached.survey
    if survey is None:
        survey = MarkSurvey(plan, cp_to_form)
    cached.survey, cached.mapping = survey, mapping
    danda = plan.danda_ends_word()
    if log:
        log(f"  {spec.name}: final forms before a danda: {'yes' if danda else 'no'}")
    leads = danda_space_leads(plan)
    if log and leads:
        log(f"  {spec.name}: danda space taken off a preceding space: "
            + " ".join(f"U+{spec.dandas[i - 1]:04X} {share}/256" for i, share in sorted(leads.items())))
    table = pack_table(table_entries(forms, key_to_cp), spec, danda_ends_word=danda,
                       half_forms=bool(plan.half_forms_from_font), space_leads=leads)
    if len(table) > MAX_TABLE_BYTES:
        raise ValueError(f"{spec.name}: cluster table of {len(forms)} entries ({len(table)} bytes) exceeds "
                         f"the {MAX_TABLE_BYTES}-byte device budget")
    if anchors_out is not None:
        # Same default logger as plan.build: the anchor decisions (probes,
        # placement modes, extra point) belong in every build log.
        anchors_out.update(compute_anchors(plan, cp_to_form, unit_scale,
                                           log or (lambda msg: print(msg, file=sys.stderr)), survey=survey))
    if tops_out is not None:
        for key, units in lifts.items():
            cp = key[0] if len(key) == 1 and key[0] < 0xE000 else key_to_cp.get(key)
            px = int(round(units * unit_scale))
            if cp is not None and px:
                tops_out[cp] = px
    if advances_out is not None:
        advances_out.update(spacing_advance_overrides(plan, face, unit_scale, load_flags, log, lefts_out))
    return spec.shape_kind, table, cp_to_form


def spacing_advance_overrides(plan, face, unit_scale, load_flags, log=None, lefts_out=None):
    """Advances (12.4 px) for spacing glyphs whose HarfBuzz position differs from
    their plain metrics:
    - letters of the script whose hmtx advance is zero but which HarfBuzz spaces
      through GPOS (Tiro Bangla's anusvara and visarga had no metric advance, so the
      device drew the following letter on top of them);
    - glyphs with a context-free GPOS single adjustment (Tiro's danda and double
      danda: space before the stroke). Their advance is HarfBuzz's, and the extra
      left shift (whole pixels) goes to `lefts_out` {codepoint: px}.
    Returns {codepoint: advance_fp4}."""
    spec = plan.spec
    out = {}
    shifted = {}
    candidates = list(range(spec.block_base, spec.block_base + 0x80)) + list(spec.dandas)
    for cp in dict.fromkeys(candidates):
        if not plan.has(cp):
            continue
        gid = plan.gid(cp)
        face.load_glyph(gid, load_flags)
        if face.glyph.linearHoriAdvance == 0:
            for seq in ((cp,), (spec.probe, cp)):
                run = plan.shape(seq)
                if len(run.glyphs) == len(seq) and run.gids[-1] == gid and run.glyphs[-1][1] > 0:
                    out[cp] = max(0, int(round(run.glyphs[-1][1] * unit_scale * 16)))
                    break
            continue
        shift = _fixed_right_shift(plan, cp)
        if shift is None:
            continue
        advance, x_offset = shift
        out[cp] = int(round(advance * unit_scale * 16))
        shifted[cp] = int(round(x_offset * unit_scale))
    if lefts_out is not None:
        lefts_out.update(shifted)
    if log and out:
        log(f"  {spec.name}: {len(out)} glyphs take their HarfBuzz advance: "
            + " ".join("U+%04X" % cp for cp in sorted(out))
            + (f" ({len(shifted)} shifted right)" if shifted else ""))
    return out


def _fixed_right_shift(plan, cp):
    """(advance, x_offset) in font units when HarfBuzz moves `cp` right by the
    same amount after a letter, after the probe and at the start of the text
    (a single adjustment such as Tiro's space before the danda), else None.
    Anything that varies (kerning, contextual positioning) is left to the
    device's own rules."""
    spec = plan.spec
    gid = plan.gid(cp)
    positions = set()
    for seq in ((cp,), (spec.probe, cp), (spec.block_base + 0x28, cp)):
        run = plan.shape(seq)
        positions.add((run.glyphs[-1][1], run.glyphs[-1][2]) if run.glyphs and run.gids[-1] == gid else None)
    if len(positions) != 1 or None in positions:
        return None
    advance, x_offset = next(iter(positions))
    if x_offset <= 0 or advance <= 0 or advance == plan.font.get_glyph_h_advance(gid):
        return None
    return advance, x_offset


def danda_space_leads(plan):
    """{danda index (1 = U+0964, 2 = U+0965): share} for the dandas whose
    built-in space (see spacing_advance_overrides) HarfBuzz drops after a
    space character: Tiro's chained lookup keeps "X ।" and "X।" in the same
    place. The device bakes the space into the glyph, so the reader takes it
    off the space before a word that starts with the danda. The share is the
    shift as a fraction of the danda's advance in 1/256, which is the same at
    every size, so the table stays identical across sizes."""
    spec = plan.spec
    out = {}
    for index, cp in enumerate(spec.dandas, start=1):
        if not plan.has(cp):
            continue
        shift = _fixed_right_shift(plan, cp)
        if shift is None:
            continue
        advance, x_offset = shift
        run = plan.shape((0x0020, cp))
        if not run.glyphs or run.gids[-1] != plan.gid(cp):
            continue
        dropped = x_offset - run.glyphs[-1][2]
        if dropped <= 0:
            continue
        out[index] = max(1, min(255, int(round(dropped * 256 / advance))))
    return out


def table_entries(forms, key_to_cp):
    """(key, cp, pre_class, post_class, continues) rows for pack_table."""
    return [(f.key, key_to_cp.get(f.key), f.pre_class, f.post_class, f.continues) for f in forms]


def pua_intervals(cp_to_form):
    """Sorted, merged intervals covering the allocated PUA codepoints."""
    cps = sorted(cp_to_form)
    intervals = []
    for cp in cps:
        if intervals and cp == intervals[-1][1] + 1:
            intervals[-1] = (intervals[-1][0], cp)
        else:
            intervals.append((cp, cp))
    return intervals
