import sys
import os
import zlib

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import fitz

doc = fitz.open("test_page_copy.pdf")
page = doc[0]
contents = page.read_contents()
contents_str = contents.decode("utf-8", errors="ignore")
print("Length of content stream:", len(contents_str))
print("BDC count:", contents_str.count("BDC"))
print("EMC count:", contents_str.count("EMC"))
print("First 1000 chars:\n", contents_str[:1000])

