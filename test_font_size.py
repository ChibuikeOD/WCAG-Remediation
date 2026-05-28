import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import fitz

doc = fitz.open("Test PDF 3.pdf")
page = doc[0]
blocks = page.get_text("dict", sort=True)["blocks"]
for block in blocks:
    if "lines" in block:
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    print("size:", span["size"], "text:", span["text"][:30])
