"""Devanagari (Hindi, Marathi, Nepali, Sanskrit) builder spec; device mirror:
descriptor.h beside this file."""

from builder.spec import ScriptSpec

DEVANAGARI = ScriptSpec(
    name="devanagari",
    shape_kind=2,
    block_base=0x0900,
    hb_script="Deva",
    hb_language="hi",
    intervals=((0x0900, 0x097F),),
    probe=0x0915,
    # क..ह, the nukta letters क़..य़ and the extended letters ॹ..ॿ.
    consonants=tuple(list(range(0x0915, 0x093A)) + list(range(0x0958, 0x0960)) + list(range(0x0979, 0x0980))),
    cluster_consonants=tuple(range(0x0915, 0x093A)),
    virama=0x094D,
    nukta=0x093C,
    ra=0x0930,
    post_base_consonant=0,
    ra_folds=(),
    below_vowels=(0x0941, 0x0942, 0x0943, 0x0944),  # u, uu, vocalic r, vocalic rr
    pre_sign_with_forms=0x093F,   # ि
    post_sign_with_forms=0x0940,  # ी
    init_signs=(),
    fina_signs=(),
    form_probe_bases=(0x0915, 0x0924, 0x092A, 0x092E, 0x0928, 0x0917, 0x0938),
    join_style="half",
    reph_after_post=True,
    mark_fusion=True,
    post_vowels=(0x093E, 0x0940, 0x0949, 0x094A, 0x094B, 0x094C),  # ा ी ॉ ॊ ो ौ
    above_vowels=(0x0945, 0x0946, 0x0947, 0x0948),                  # ॅ ॆ े ै
    modifiers=(0x0901, 0x0902, 0x0903),                             # ँ ं ः
    independent_vowels=tuple(range(0x0904, 0x0915)) + (0x0960, 0x0961) + tuple(range(0x0972, 0x0978)),
    # Marks (ऀ ँ ं ऺ ़ ु..ै ् ॑..ॗ ॢ ॣ): below signs, nukta, anudatta and the
    # halant hang from the below anchor; the candrabindus, udatta/svarita and
    # the below marks sit centred; the anusvara and the above vowel signs
    # attach at the stem on the right; the halant at the pen.
    marks=(0x0900, 0x0901, 0x0902, 0x093A, 0x093C) + tuple(range(0x0941, 0x0949)) + (0x094D,)
          + tuple(range(0x0951, 0x0958)) + (0x0962, 0x0963),
    attach_below=(0x093C, 0x0941, 0x0942, 0x0943, 0x0944, 0x094D, 0x0952, 0x0956, 0x0957, 0x0962, 0x0963),
    anchor_center=(0x0900, 0x0901, 0x093C, 0x0941, 0x0942, 0x0943, 0x0944, 0x0951, 0x0952, 0x0953, 0x0954,
                   0x0956, 0x0957, 0x0962, 0x0963),
    anchor_right=(0x0902, 0x093A, 0x0945, 0x0946, 0x0947, 0x0948, 0x0955),
    anchor_pen=(0x094D,),
    below_signs=(0x0941, 0x0942, 0x0943, 0x0944, 0x094D, 0x0962, 0x0963),
    rare_marks=(0x0900, 0x093A) + tuple(range(0x0951, 0x0958)),
    phala_consonants=(0x0930,),  # rakar
    dandas=(0x0964, 0x0965),
)
