"""Paquete pequeno de inventario: no incluye los KMZ ni conversiones previas."""
from pathlib import Path
import hashlib
import json
import zipfile

BASE = Path(__file__).resolve().parents[1]
report = json.loads((BASE / "VALIDACION.json").read_text(encoding="utf-8"))
assert report["status"] == "PASS"
files = [BASE / "01_inventariar_kmz.py", BASE / "LEEME.md", BASE / "REVISION_HERRAMIENTA.md", BASE / "VALIDACION.json"]
files += sorted((BASE / "inventario").glob("*"))
assert all(p.is_file() and BASE in p.resolve().parents for p in files)
target = BASE.parent / "Mapline_KMZ_Inventario_EFT.zip"
assert target.resolve().parent == BASE.parent.resolve()
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for path in files:
        z.write(path, str(Path(BASE.name) / path.relative_to(BASE)))
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None and len(z.infolist()) == len(files)
    for path in files:
        assert z.read(str(Path(BASE.name) / path.relative_to(BASE)).replace("\\", "/")) == path.read_bytes()
print(json.dumps({"zip": str(target), "files": len(files), "bytes": target.stat().st_size,
                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "crc_ok": True}))
