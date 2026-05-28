import pikepdf

file_path = "test_page_copy.pdf"
try:
    doc = pikepdf.open(file_path)
    if "/StructTreeRoot" in doc.Root:
        struct_root = doc.Root.StructTreeRoot
        print("StructTreeRoot:")
        print(struct_root)
        if "/ParentTree" in struct_root:
            parent_tree = struct_root.ParentTree
            print("\nParentTree dictionary keys:")
            print(parent_tree.keys())
            if "/Nums" in parent_tree:
                nums = parent_tree.Nums
                print(f"\nNums array length: {len(nums)}")
                # Nums is an array of [key1, value1, key2, value2, ...]
                # Let's inspect some elements
                for i in range(0, min(10, len(nums)), 2):
                    page_idx = nums[i]
                    val = nums[i+1]
                    print(f"Page index key: {page_idx}, value type: {type(val)}, length of list: {len(val) if isinstance(val, pikepdf.Array) else 'N/A'}")
                    if isinstance(val, pikepdf.Array):
                        print(f"  First elements: {val[:2]}")
            else:
                print("\nNums DOES NOT exist in ParentTree!")
        else:
            print("\nParentTree DOES NOT exist in StructTreeRoot!")
    else:
        print("StructTreeRoot DOES NOT exist!")
except Exception as e:
    print("Error:", e)
