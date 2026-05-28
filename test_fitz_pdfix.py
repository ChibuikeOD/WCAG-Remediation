import fitz
import pdfixsdk
import os
import pikepdf

# 1. Open with fitz and set toc
doc = fitz.open("Test PDF 3.pdf")
toc = doc.get_toc()
doc.set_toc(toc)
doc.save("test_1.pdf")
doc.close()

# 2. Try to open with pdfix
pdfix = pdfixsdk.GetPdfix()
doc_pdfix = pdfix.OpenDoc(os.path.abspath("test_1.pdf"), "")
if not doc_pdfix:
    print("PDFix could not open fitz output!")
    print(pdfix.GetErrorType(), pdfix.GetError())
else:
    print("PDFix opened fitz output successfully!")
    doc_pdfix.Close()

