import sys
import os
import pikepdf
import fitz

file_path = "test_page_copy.pdf"

try:
    with open(file_path, 'rb') as f:
        header = f.read(10)
        print("Header bytes (first 10):", header)
except Exception as e:
    print("Error reading header:", e)

try:
    doc = pikepdf.open(file_path)
    print("pikepdf opens successfully")
    doc.close()
except Exception as e:
    print("pikepdf error:", e)

try:
    doc = fitz.open(file_path)
    print("fitz opens successfully")
    doc.close()
except Exception as e:
    print("fitz error:", e)
