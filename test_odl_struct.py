import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import fitz

doc = fitz.open(r"test_odl_output\Test PDF 3_annotated.pdf")
catalog = doc.pdf_catalog()
mark_info = doc.xref_get_key(catalog, "MarkInfo")
struct = doc.xref_get_key(catalog, "StructTreeRoot")

print(f"MarkInfo: {mark_info}")
print(f"StructTreeRoot: {struct}")

