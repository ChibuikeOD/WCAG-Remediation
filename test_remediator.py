import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from pdf_accessibility import PDFRemediator
import shutil

# Make a copy of a pdf to test on
test_pdf = Path("test_page_copy.pdf")
shutil.copy("Test PDF 3.pdf", test_pdf)

remediator = PDFRemediator(test_pdf)
print("Testing fix_metadata...")
res1 = remediator.fix_metadata(title="Test Title", language="en")
print(res1)

print("Testing generate_bookmarks...")
res2 = remediator.generate_bookmarks_from_headings()
print(res2)
