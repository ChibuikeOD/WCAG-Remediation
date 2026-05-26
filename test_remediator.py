import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(__file__))
from backend.pdf_accessibility import PDFRemediator
import shutil

# Make a copy of a pdf to test on
test_pdf = Path("test_page_copy.pdf")
shutil.copy("Test PDF 3.pdf", test_pdf)

remediator = PDFRemediator(test_pdf)
print("Testing fix_metadata...")
res1 = remediator.fix_metadata(title="Test Title", language="en")
print(res1)

print("Testing auto_tag_document...")
res3 = remediator.auto_tag_document()
print("Tags created:", res3.get("tags_created"))

print("Testing generate_bookmarks...")
res2 = remediator.generate_bookmarks_from_headings()
print(res2)

print("Done! Open 'test_page_copy.pdf' to review the results.")
