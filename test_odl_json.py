import sys
import os
import json
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(__file__))

from backend.layout_model import DocumentLayoutAnalyzer

analyzer = DocumentLayoutAnalyzer()
json_path = analyzer._convert_with_opendataloader(Path("Test PDF 3.pdf"))
data = json.loads(json_path.read_text(encoding="utf-8"))

print(f"Num kids: {len(data.get('kids', []))}")
for i, kid in enumerate(data.get('kids', [])[:10]):
    print(i, kid.get('type'), kid.get('bounding box'), kid.get('content')[:100] if kid.get('content') else None)

