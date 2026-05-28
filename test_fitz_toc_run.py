import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import fitz

doc = fitz.open("Test PDF 3.pdf")
toc = doc.get_toc()
print("original toc:", toc)

# test adding TOC with top margin
new_toc = [
    [1, "First heading at top", 1, 100.0],
    [1, "Second heading at bottom", 1, 500.0],
    [2, "Heading on page 2", 2, 200.0],
]
doc.set_toc(new_toc)
doc.save("test_toc_output.pdf")
print("saved test_toc_output.pdf")
