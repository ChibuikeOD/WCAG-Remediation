import fitz

doc = fitz.open("test_page_copy.pdf")
for idx, page in enumerate(doc):
    contents = page.read_contents()
    contents_str = contents.decode("utf-8", errors="ignore")
    bdc_count = contents_str.count("BDC")
    emc_count = contents_str.count("EMC")
    print(f"Page {idx + 1}: BDC = {bdc_count}, EMC = {emc_count}")
doc.close()
