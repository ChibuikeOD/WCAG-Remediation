import fitz
import pdfixsdk
import os

doc = fitz.open("Test PDF 3.pdf")
doc.save("test_fitz.pdf", encryption=0)
doc.close()

pdfix = pdfixsdk.GetPdfix()
doc2 = pdfix.OpenDoc(os.path.abspath("test_fitz.pdf"), "")
if not doc2:
    print("PDFix could not open fitz generated file!")
    print(pdfix.GetErrorType(), pdfix.GetError())
else:
    print("PDFix opened fitz generated file successfully!")
    doc2.Close()
