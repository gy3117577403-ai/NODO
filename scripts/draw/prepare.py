"""Install a standalone private copy of the v0.57.3 engineering inputs for NODO."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / ".nodo-draw"
PATTERNS = (
    "ae-cabinet/build.py", "ae-cabinet/src/*.py", "ae-cabinet/*.json",
    "ae-cabinet/rules/*.json", "ae-cabinet/converted/*.dxf", "ae-cabinet/source/*.dwg",
    "top-panel/core.py", "top-panel/templates/*",
    "ae-cabinet/vendor/freecad-library/fc-plate-t5/*.step",
    "ae-cabinet/vendor/freecad-library/ATTRIBUTION.md",
    "ae-cabinet/vendor/freecad-library/LICENSE-Assets.txt",
)


def prepare(app):
    if json.loads((app / "package.json").read_text("utf-8"))["version"] != "0.57.3":
        raise ValueError("此连接器需要已核对的 0.57.3 工程包")
    engineering = app / "engineering"
    destination = ROOT / "engineering"
    inventory = {}
    for pattern in PATTERNS:
        files = sorted(p for p in engineering.glob(pattern) if p.is_file())
        if not files:
            raise ValueError(f"缺少工程资源 {pattern}")
        for source in files:
            key = source.relative_to(engineering).as_posix()
            target = destination / key
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f"已有 NODO 工程资源与来源不同 {key}")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            inventory[key] = digest
    (ROOT / "exchange").mkdir(exist_ok=True)
    (ROOT / "engine-manifest.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), "utf-8")
    print(f"已核对并准备 {len(inventory)} 个工程资源")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path, help="京能 0.57.3 发行包的 resources/app")
    prepare(parser.parse_args().app.resolve())
