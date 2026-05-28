import pikepdf
import pdfixsdk
import os

pdf = pikepdf.open("Test PDF 3.pdf")
pdf.save("test_pike.pdf")
pdf.close()

pdfix = pdfixsdk.GetPdfix()
doc = pdfix.OpenDoc(os.path.abspath("test_pike.pdf"), "")
if not doc:
    print("PDFix could not open pikepdf generated file!")
    print(pdfix.GetErrorType(), pdfix.GetError())
else:
    print("PDFix opened pikepdf generated file successfully!")
    doc.Close()
