import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import fitz

doc = fitz.open("test_page_copy.pdf")
print("PyMuPDF can open 'test_page_copy.pdf'!")
doc.close()
