import pdfixsdk
import os

pdfix = pdfixsdk.GetPdfix()
if not pdfix:
    print("PDFix failed to initialize")
    exit(1)

path = os.path.abspath("Test PDF 3.pdf")
print("Path exists:", os.path.exists(path))
doc = pdfix.OpenDoc(path, "")
if not doc:
    print("Error getting open doc:")
    print("Error code:", pdfix.GetErrorType())
    try:
        print("Error detail:", pdfix.GetError())
    except:
        pass
else:
    print("Success!")
    doc.Close()
