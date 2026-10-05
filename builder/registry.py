"""The scripts this builder shapes: one ScriptSpec per provider directory.
Adding a script: providers/<name>/spec.py plus one line here (and the
descriptor entry in engine/Registry.h)."""

from providers.bengali.spec import BENGALI
from providers.devanagari.spec import DEVANAGARI

SCRIPTS = {spec.name: spec for spec in (BENGALI, DEVANAGARI)}

__all__ = ["SCRIPTS"]
