import sys
import os

sys.path.append(os.path.dirname(__file__))
from backend.layout_model import DocumentLayoutAnalyzer
from pathlib import Path

analyzer = DocumentLayoutAnalyzer()
layouts = analyzer.analyze_document(Path("test_page_copy.pdf"))
for layout in layouts[:3]:
    print(f"Page {layout.page_number + 1} has {len(layout.blocks)} blocks")
    for block in layout.blocks[:3]:
        print(f"  - {block.tag}: {block.text[:30]}")
