#include "structure_builder.h"
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <iostream>

void build_struct_tree(QPDF& pdf, const std::vector<LayoutBlock>& blocks, const std::map<int, int>& page_mcid_counts) {
    QPDFObjectHandle root = pdf.getRoot();

    // Clean up any existing structure tree metadata to avoid duplicates
    if (root.hasKey("/StructTreeRoot")) {
        root.removeKey("/StructTreeRoot");
    }
    if (root.hasKey("/MarkInfo")) {
        root.removeKey("/MarkInfo");
    }

    // 1. Create StructTreeRoot
    QPDFObjectHandle struct_root = QPDFObjectHandle::newDictionary();
    struct_root.replaceKey("/Type", QPDFObjectHandle::newName("/StructTreeRoot"));

    QPDFObjectHandle doc_kids = QPDFObjectHandle::newArray();
    QPDFObjectHandle doc_elem = QPDFObjectHandle::newDictionary();
    doc_elem.replaceKey("/Type", QPDFObjectHandle::newName("/StructElem"));
    doc_elem.replaceKey("/S", QPDFObjectHandle::newName("/Document"));
    doc_elem.replaceKey("/P", struct_root);
    doc_elem.replaceKey("/K", doc_kids);

    QPDFObjectHandle root_kids = QPDFObjectHandle::newArray();
    root_kids.appendItem(pdf.makeIndirectObject(doc_elem));
    struct_root.replaceKey("/K", root_kids);

    // 2. Group the layout blocks from JSON by page index
    std::map<int, std::vector<LayoutBlock>> page_blocks;
    for (auto const& block : blocks) {
        page_blocks[block.page].push_back(block);
    }

    QPDFPageDocumentHelper pdh(pdf);
    std::vector<QPDFPageObjectHelper> pages = pdh.getAllPages();

    // 3. Build ParentTree Nums array
    QPDFObjectHandle parent_tree_nums = QPDFObjectHandle::newArray();

    for (auto const& pair : page_mcid_counts) {
        int page_idx = pair.first;
        int mcid_count = pair.second;

        if (page_idx >= static_cast<int>(pages.size())) {
            continue;
        }

        QPDFPageObjectHelper page = pages.at(page_idx);
        page.getObjectHandle().replaceKey("/StructParents", QPDFObjectHandle::newInteger(page_idx));

        QPDFObjectHandle page_structs = QPDFObjectHandle::newArray();
        auto const& blocks_on_page = page_blocks[page_idx];

        for (int mcid = 0; mcid < mcid_count; ++mcid) {
            std::string tag = "P"; // Default tag if JSON has fewer blocks than stream text runs
            std::vector<double> bbox;

            if (mcid < static_cast<int>(blocks_on_page.size())) {
                tag = blocks_on_page[mcid].tag;
                bbox = blocks_on_page[mcid].bbox;
            }

            // Create Structure Element (StructElem)
            QPDFObjectHandle se = QPDFObjectHandle::newDictionary();
            se.replaceKey("/Type", QPDFObjectHandle::newName("/StructElem"));
            se.replaceKey("/S", QPDFObjectHandle::newName("/" + tag));
            se.replaceKey("/P", doc_elem);
            se.replaceKey("/Pg", page.getObjectHandle());
            se.replaceKey("/K", QPDFObjectHandle::newInteger(mcid));

            // Set Bounding Box Layout Attribute if available
            if (bbox.size() == 4) {
                QPDFObjectHandle attr = QPDFObjectHandle::newDictionary();
                attr.replaceKey("/O", QPDFObjectHandle::newName("/Layout"));
                QPDFObjectHandle bbox_array = QPDFObjectHandle::newArray();
                for (double val : bbox) {
                    bbox_array.appendItem(QPDFObjectHandle::newReal(val));
                }
                attr.replaceKey("/BBox", bbox_array);
                se.replaceKey("/A", attr);
            }

            // PDF/UA requirement: Alternate Text for Figures
            if (tag == "Figure") {
                se.replaceKey("/Alt", QPDFObjectHandle::newUnicodeString("[Image requires alt text]"));
            }

            QPDFObjectHandle se_indirect = pdf.makeIndirectObject(se);
            doc_kids.appendItem(se_indirect);
            page_structs.appendItem(se_indirect);
        }

        // Add to ParentTree number list
        parent_tree_nums.appendItem(QPDFObjectHandle::newInteger(page_idx));
        parent_tree_nums.appendItem(pdf.makeIndirectObject(page_structs));
    }

    // 4. Create ParentTree and attach it to the StructTreeRoot
    QPDFObjectHandle parent_tree = QPDFObjectHandle::newDictionary();
    parent_tree.replaceKey("/Nums", parent_tree_nums);

    struct_root.replaceKey("/ParentTree", pdf.makeIndirectObject(parent_tree));
    struct_root.replaceKey("/ParentTreeNextKey", QPDFObjectHandle::newInteger(page_mcid_counts.size()));

    root.replaceKey("/StructTreeRoot", pdf.makeIndirectObject(struct_root));

    // Set MarkInfo
    QPDFObjectHandle mark_info = QPDFObjectHandle::newDictionary();
    mark_info.replaceKey("/Marked", QPDFObjectHandle::newBool(true));
    root.replaceKey("/MarkInfo", mark_info);
}
