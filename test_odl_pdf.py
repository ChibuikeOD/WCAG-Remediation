import sys
import os
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
import opendataloader_pdf

# Let's run convert with format="pdf" directly
input_path = "Test PDF 3.pdf"
output_dir = "test_odl_output"
os.makedirs(output_dir, exist_ok=True)

try:
    opendataloader_pdf.convert(
        input_path=input_path,
        output_dir=output_dir,
        format=["pdf"],
        include_header_footer=True,
    )
    print("Successfully converted to PDF format in output directory.")
except Exception as e:
    print(f"Error: {e}")
