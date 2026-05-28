import pikepdf
import shutil

shutil.copy("Test PDF 3.pdf", "test_pike_save.pdf")
pdf = pikepdf.open("test_pike_save.pdf", allow_overwriting_input=True)
pdf.save()
pdf.close()

import os
print("Size of test_pike_save.pdf:", os.path.getsize("test_pike_save.pdf"))
