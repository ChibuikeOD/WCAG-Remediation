import fitz
import pdfixsdk
import pikepdf
import os

doc = fitz.open("Test PDF 3.pdf")
toc = doc.get_toc()
doc.set_toc(toc)
doc.save("test_1.pdf")
doc.close()

# Now clean with pikepdf
pdf = pikepdf.open("test_1.pdf")
pdf.save("test_clean.pdf")
pdf.close()

pdfix = pdfixsdk.GetPdfix()
doc_pdfix = pdfix.OpenDoc(os.path.abspath("test_clean.pdf"), "")
if not doc_pdfix:
    print("PDFix could not open cleaned output!")
    print(pdfix.GetErrorType(), pdfix.GetError())
else:
    print("PDFix opened cleaned output successfully!")
    doc_pdfix.Close()

