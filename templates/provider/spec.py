"""__Script__ builder spec; device mirror: descriptor.h beside this file.
Every field is documented in builder/spec.py (ScriptSpec)."""

from builder.spec import ScriptSpec

BLOCK = __BLOCK__

__SCRIPT__ = ScriptSpec(
    name="__script__",
    shape_kind=__KIND__,
    block_base=BLOCK,
    hb_script="__HB__",                     # HarfBuzz script tag, e.g. "Taml"
    hb_language="__LANG__",                 # BCP 47 language for HarfBuzz, e.g. "ta"
    intervals=((BLOCK, BLOCK + 0x7F),),     # the host converter's interval preset
    probe=BLOCK + 0x15,                     # KA: shaped after a key to hide word-final forms
    consonants=tuple(range(BLOCK + 0x15, BLOCK + 0x3A)),
    cluster_consonants=tuple(range(BLOCK + 0x15, BLOCK + 0x3A)),  # those that take part in conjuncts
    virama=BLOCK + 0x4D,
    nukta=BLOCK + 0x3C,
    ra=BLOCK + 0x30,
    post_base_consonant=0,
    ra_folds=(),
    below_vowels=(BLOCK + 0x41, BLOCK + 0x42, BLOCK + 0x43, BLOCK + 0x44),
    pre_sign_with_forms=BLOCK + 0x3F,       # the pre-base sign fused with a reph / modifier
    pre_signs_with_forms=(BLOCK + 0x3F,),   # every pre-base sign with per-base forms (mirror: preSignsWithForms)
    post_sign_with_forms=BLOCK + 0x40,
    init_signs=(),
    fina_signs=(),
    form_probe_bases=(BLOCK + 0x15, BLOCK + 0x24, BLOCK + 0x2A),  # bases tried to isolate a subjoined form
    join_style="subjoined",                 # "subjoined" or "half"
    reph_after_post=False,
    mark_fusion=False,                      # enumerate signs/reph fused with modifiers
    post_vowels=(BLOCK + 0x3E, BLOCK + 0x40),
    above_vowels=(),
    modifiers=(BLOCK + 0x01, BLOCK + 0x02, BLOCK + 0x03),
    independent_vowels=tuple(range(BLOCK + 0x05, BLOCK + 0x15)),
    candrabindu_before_post=(),
    # Mark sets, mirroring the descriptor's nonSpacing / attachBelow / anchor masks.
    marks=(BLOCK + 0x01, BLOCK + 0x3C) + tuple(range(BLOCK + 0x41, BLOCK + 0x45)) + (BLOCK + 0x4D,),
    attach_below=(BLOCK + 0x3C,) + tuple(range(BLOCK + 0x41, BLOCK + 0x45)) + (BLOCK + 0x4D,),
    anchor_center=(BLOCK + 0x01, BLOCK + 0x3C) + tuple(range(BLOCK + 0x41, BLOCK + 0x45)),
    anchor_right=(),
    anchor_pen=(BLOCK + 0x4D,),
    below_signs=tuple(range(BLOCK + 0x41, BLOCK + 0x45)) + (BLOCK + 0x4D,),
    rare_marks=(),
    phala_consonants=(BLOCK + 0x30,),       # consonants whose post-virama form is a subjoined mark (rakar)
    dandas=(0x0964, 0x0965),
)
