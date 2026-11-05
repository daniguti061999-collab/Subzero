"""Validate PBIR/PBIP JSON files against Microsoft's published schemas (fetched from GitHub raw, cached)."""
import json, sys, pathlib, urllib.request, hashlib
from jsonschema import Draft7Validator
from referencing import Registry, Resource
CACHE = pathlib.Path(__file__).parent / "cache"; CACHE.mkdir(exist_ok=True)
MS = "https://developer.microsoft.com/json-schemas/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"
def fetch(uri):
    url = uri.split('#')[0].replace(MS, RAW)
    f = CACHE / hashlib.md5(url.encode()).hexdigest()
    if not f.exists():
        f.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    return json.loads(f.read_text())
def retrieve(uri):
    return Resource.from_contents(fetch(uri))
reg = Registry(retrieve=retrieve)
def validate(path):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or "$schema" not in doc:
        raise KeyError("not a Power BI definition file")
    sch = fetch(doc["$schema"])
    v = Draft7Validator(sch, registry=reg)
    errs = sorted(v.iter_errors(doc), key=lambda e: list(e.path))
    return errs
if __name__ == "__main__":
    bad = 0
    for p in sys.argv[1:]:
        for f in ([p] if p.endswith(".json") or p.endswith(".pbir") or p.endswith(".pbism") or p.endswith(".pbip") else sorted(map(str, pathlib.Path(p).rglob("*")))):
            if not (f.endswith((".json", ".pbir", ".pbism", ".pbip"))) or any(x in f for x in ("RegisteredResources", "SharedResources", "/Data/", "/tools/")):
                continue
            try:
                errs = validate(f)
            except KeyError:
                continue
            if errs:
                bad += 1
                print("FAIL", f)
                for e in errs[:6]:
                    print("   ", "/".join(map(str, e.path)), "->", e.message[:300])
            else:
                print("ok  ", f)
    sys.exit(1 if bad else 0)
