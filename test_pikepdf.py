import pikepdf
import sys

file_path = "test_page_copy.pdf"
try:
    doc = pikepdf.open(file_path)
    if "/StructTreeRoot" in doc.Root:
        print("StructTreeRoot exists!")
        print("Root:", doc.Root.StructTreeRoot)
        print("MarkInfo:", doc.Root.get("/MarkInfo"))
    else:
        print("StructTreeRoot DOES NOT exist!")
except Exception as e:
    print(e)
