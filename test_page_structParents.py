import pikepdf

file_path = "test_page_copy.pdf"
try:
    doc = pikepdf.open(file_path)
    for idx, page in enumerate(doc.pages):
        struct_parents = page.get("/StructParents")
        print(f"Page {idx + 1}: /StructParents = {struct_parents}")
except Exception as e:
    print("Error:", e)
