#!/usr/bin/env python3
"""Create providers/<name>/ from templates/provider/.

    tools/new_provider.py <name> <Script> <blockBase> <kind>
    tools/new_provider.py tamil Tamil 0x0B80 3

Fills the placeholders (__script__, __Script__, __SCRIPT__, __BLOCK__, __KIND__,
__HB__, __LANG__) and reminds you of the two registry lines to add."""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    name, script, block, kind = sys.argv[1], sys.argv[2], int(sys.argv[3], 0), int(sys.argv[4])
    dst = os.path.join(ROOT, "providers", name)
    if os.path.exists(dst):
        sys.exit(f"{dst} exists")
    subst = {
        "__script__": name, "__Script__": script, "__SCRIPT__": name.upper(),
        "__BLOCK__": f"0x{block:04X}", "__KIND__": str(kind),
        "__BLOCKHEX__": f"{block:04X}", "__BLOCKENDHEX__": f"{block + 0x7F:04X}",
        "__HB__": script[:4], "__LANG__": name[:2],
    }
    src = os.path.join(ROOT, "templates", "provider")
    for base, _, files in os.walk(src):
        rel = os.path.relpath(base, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            text = open(os.path.join(base, f), encoding="utf-8").read()
            for k, v in subst.items():
                text = text.replace(k, v)
            out = f
            for k, v in subst.items():
                out = out.replace(k, v)
            open(os.path.join(dst, rel, out), "w", encoding="utf-8").write(text)
    open(os.path.join(dst, "words.txt"), "w").close()
    print(f"created {dst}")
    print("now add:")
    print(f"  engine/Registry.h:   #if LIPI_WITH_{name.upper()}  #include \"../providers/{name}/descriptor.h\"  and the kScriptByBlock entry")
    print(f"  builder/registry.py: from providers.{name}.spec import {name.upper()}  and the SCRIPTS entry")
    print(f"  test/CMakeLists.txt: providers/{name}/test/{script}ShaperTest.cpp")
    print(f"  docs/table-format.md: kind {kind} is no longer reserved")


if __name__ == "__main__":
    main()
