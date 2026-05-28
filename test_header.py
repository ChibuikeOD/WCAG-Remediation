file_path = "test_page_copy.pdf"
with open(file_path, 'rb') as f:
    header = f.read(25)
    print("Header bytes (first 25):", header)
