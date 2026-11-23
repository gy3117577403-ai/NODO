"""Material categories and AE stock defaults used by the sheet design and cost applications."""
import json
from pathlib import Path

MATERIALS = json.loads((Path(__file__).parent / 'data/sheet_materials.json').read_text(encoding='utf-8'))
