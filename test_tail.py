import os

file_path = "test_page_copy.pdf"
with open(file_path, 'rb') as f:
    f.seek(-50, os.SEEK_END)
    tail = f.read(50)
    print("Tail bytes (last 50):", tail)
