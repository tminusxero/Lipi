"""Bengali (Bangla, Assamese) builder spec; device mirror: descriptor.h beside this file."""

from builder.spec import ScriptSpec

BENGALI = ScriptSpec(
    name="bengali",
    shape_kind=1,
    block_base=0x0980,
    hb_script="Beng",
    hb_language="bn",
    # Bengali block plus the danda punctuation it shares with Devanagari.
    intervals=((0x0964, 0x0965), (0x0980, 0x09FF)),
    probe=0x0995,
    consonants=tuple(list(range(0x0995, 0x09A9)) + list(range(0x09AA, 0x09B1)) + [0x09B2]
                     + list(range(0x09B6, 0x09BA)) + [0x09DC, 0x09DD, 0x09DF, 0x09F0, 0x09F1]),
    # The nukta letters (ড় ঢ় য়) and the Assamese ra/wa never conjoin in
    # Bengali orthography; enumerating them would double every ra-form for
    # glyphs no book uses.
    cluster_consonants=tuple(list(range(0x0995, 0x09A9)) + list(range(0x09AA, 0x09B1)) + [0x09B2]
                             + list(range(0x09B6, 0x09BA))),
    virama=0x09CD,
    nukta=0x09BC,
    ra=0x09B0,
    post_base_consonant=0x09AF,   # য: ya-phala
    ra_folds=(0x09F0,),           # ৰ
    below_vowels=(0x09C1, 0x09C2, 0x09C3, 0x09C4),  # u, uu, vocalic r, vocalic rr
    pre_sign_with_forms=0x09BF,   # ি (also the sign fused with a reph or modifier)
    # ে ৈ have per-base forms in some fonts (Noto Sans Bengali: ে.long on খ গ ণ থ প শ).
    pre_signs_with_forms=(0x09BF, 0x09C7, 0x09C8),
    post_sign_with_forms=0x09C0,  # ী
    post_signs_with_forms=(0x09C0, 0x09D7),  # ী, and ৗ (Hind: taller after খ গ ঝ ণ থ প শ)
    init_signs=(0x09C7, 0x09C8),  # ে ৈ
    fina_signs=(0x09BE, 0x09C0, 0x09D7),  # া ী ৗ
    # The first base that does not ligate with a consonant exposes its
    # subjoined form as a separate glyph.
    form_probe_bases=(0x0995, 0x099F, 0x09AA, 0x09AE, 0x09AC, 0x09A6, 0x0997),
    # Fonts differ on the modifiers: Noto fuses ি+ঁ and keeps ৗ.fina before ঁ,
    # Tiro draws ঁ after the ya-phala and applies the final forms before a
    # trailing ং/ঃ; all of it is enumerated rather than coded per font.
    mark_fusion=True,
    post_vowels=(0x09BE, 0x09C0, 0x09D7),
    modifiers=(0x0981, 0x0982, 0x0983),
    candrabindu_before_post=(0x09BE, 0x09C0),
    # Marks (ঁ ় ু ূ ৃ ৄ ্ ৢ ৣ ৾): below signs, nukta and the hasanta hang from
    # the below anchor; all but the hasanta sit centred; the hasanta at the pen.
    marks=(0x0981, 0x09BC, 0x09C1, 0x09C2, 0x09C3, 0x09C4, 0x09CD, 0x09E2, 0x09E3, 0x09FE),
    attach_below=(0x09BC, 0x09C1, 0x09C2, 0x09C3, 0x09C4, 0x09CD, 0x09E2, 0x09E3),
    anchor_center=(0x0981, 0x09BC, 0x09C1, 0x09C2, 0x09C3, 0x09C4, 0x09E2, 0x09E3, 0x09FE),
    anchor_right=(),
    anchor_pen=(0x09CD,),
    below_signs=(0x09C1, 0x09C2, 0x09C3, 0x09C4, 0x09CD, 0x09E2, 0x09E3),
    rare_marks=(0x09FE,),
    phala_consonants=(0x09B0, 0x09AC, 0x09AF),  # ra-phala, ba-phala, ya-phala
    dandas=(0x0964, 0x0965),
)
