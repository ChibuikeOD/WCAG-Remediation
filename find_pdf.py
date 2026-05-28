import fitz
import os
from pathlib import Path

# Search in the root workspace and in the uploads directory
search_dirs = [Path("."), Path("uploads")]
search_term = "luso-brazilian"

found_files = []

for s_dir in search_dirs:
    if not s_dir.exists():
        continue
    for file_path in s_dir.glob("*.pdf"):
        try:
            doc = fitz.open(file_path)
            title = doc.metadata.get("title", "")
            subject = doc.metadata.get("subject", "")
            
            # Check title / metadata first
            if search_term in title.lower() or search_term in subject.lower() or "centen" in title.lower():
                found_files.append((file_path, "metadata", title))
                doc.close()
                continue
                
            # If not in metadata, search the first page text
            if len(doc) > 0:
                first_page_text = doc[0].get_text("text").lower()
                if search_term in first_page_text or "centen" in first_page_text:
                    found_files.append((file_path, "text", doc.metadata.get("title") or ""))
            doc.close()
        except Exception as e:
            pass

print("Search results:")
for path, match_type, title in found_files:
    print(f"- {path} (matched via {match_type}, title: '{title}')")
