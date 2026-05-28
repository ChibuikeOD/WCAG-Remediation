import shutil
import fitz
import sys
import os
from pathlib import Path

sys.path.append(os.path.dirname(__file__))
from backend.pdf_auto_tagging import auto_tag_pdf

test_pdf = Path("test_stream_direct.pdf")
shutil.copy("Test PDF 3.pdf", test_pdf)

print("Running auto_tag_pdf...")
res = auto_tag_pdf(test_pdf, overwrite_tags=True)
print("Result:", res)

# Check content stream
doc = fitz.open(test_pdf)
page = doc[0]
contents = page.read_contents()
contents_str = contents.decode("utf-8", errors="ignore")
print("Length of content stream:", len(contents_str))
print("BDC count:", contents_str.count("BDC"))
print("EMC count:", contents_str.count("EMC"))
doc.close()
