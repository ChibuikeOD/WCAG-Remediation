import pikepdf

file_path = "test_page_copy.pdf"
try:
    doc = pikepdf.open(file_path)
    print("ViewerPreferences in Root:", "/ViewerPreferences" in doc.Root)
    if "/ViewerPreferences" in doc.Root:
        viewer_prefs = doc.Root.ViewerPreferences
        print("ViewerPreferences values:", viewer_prefs)
        print("DisplayDocTitle is:", viewer_prefs.get("/DisplayDocTitle"))
    doc.close()
except Exception as e:
    print("Error:", e)
