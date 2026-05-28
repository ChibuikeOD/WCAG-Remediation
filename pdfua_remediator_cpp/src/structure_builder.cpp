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

    // 1. Create StructTreeRoot as an indirect object
    QPDFObjectHandle struct_root = QPDFObjectHandle::newDictionary();
    struct_root.replaceKey("/Type", QPDFObjectHandle::newName("/StructTreeRoot"));
    QPDFObjectHandle struct_root_indirect = pdf.makeIndirectObject(struct_root);

    // 2. Create the top-level /Document StructElem as an indirect object
    QPDFObjectHandle doc_kids = QPDFObjectHandle::newArray();
    QPDFObjectHandle doc_elem = QPDFObjectHandle::newDictionary();
    doc_elem.replaceKey("/Type", QPDFObjectHandle::newName("/StructElem"));
    doc_elem.replaceKey("/S",    QPDFObjectHandle::newName("/Document"));
    doc_elem.replaceKey("/P",    struct_root_indirect);
    doc_elem.replaceKey("/K",    doc_kids);
    QPDFObjectHandle doc_elem_indirect = pdf.makeIndirectObject(doc_elem);

    QPDFObjectHandle root_kids = QPDFObjectHandle::newArray();
    root_kids.appendItem(doc_elem_indirect);
    struct_root_indirect.replaceKey("/K", root_kids);

    // 3. Group the layout blocks by page index for tag lookup
    std::map<int, std::vector<LayoutBlock>> page_blocks;
    for (auto const& block : blocks) {
        page_blocks[block.page].push_back(block);
    }

    QPDFPageDocumentHelper pdh(pdf);
    std::vector<QPDFPageObjectHelper> pages = pdh.getAllPages();

    // 4. Build ParentTree and StructElems — one StructElem per content-stream MCID
    QPDFObjectHandle parent_tree_nums = QPDFObjectHandle::newArray();

    for (auto const& pair : page_mcid_counts) {
        int page_idx  = pair.first;
        int mcid_count = pair.second;

        if (page_idx >= static_cast<int>(pages.size())) {
            continue;
        }

        QPDFPageObjectHelper page = pages.at(page_idx);
        page.getObjectHandle().replaceKey("/StructParents",
                                          QPDFObjectHandle::newInteger(page_idx));

        QPDFObjectHandle page_structs = QPDFObjectHandle::newArray();
        auto const& blocks_on_page = page_blocks[page_idx];
        int num_blocks = static_cast<int>(blocks_on_page.size());

        for (int mcid = 0; mcid < mcid_count; ++mcid) {
            // Map each content-stream MCID to the closest layout block
            // using proportional distribution (layout blocks are in reading order)
            std::string tag = "P";
            std::vector<double> bbox;

            if (num_blocks > 0) {
                // Proportional assignment: spread layout block tags across MCIDs
                int block_idx = (mcid_count == 1)
                    ? 0
                    : (mcid * (num_blocks - 1)) / (mcid_count - 1);
                if (block_idx >= num_blocks) block_idx = num_blocks - 1;
                tag  = blocks_on_page[block_idx].tag;
                bbox = blocks_on_page[block_idx].bbox;
            }

            // PDF/UA: use standard role names only
            if (tag.empty() || tag == "Text") tag = "P";
            if (tag == "Title")               tag = "H1";
            if (tag == "Section-header")      tag = "H2";

            QPDFObjectHandle se = QPDFObjectHandle::newDictionary();
            se.replaceKey("/Type", QPDFObjectHandle::newName("/StructElem"));
            se.replaceKey("/S",    QPDFObjectHandle::newName("/" + tag));
            se.replaceKey("/P",    doc_elem_indirect);
            se.replaceKey("/Pg",   page.getObjectHandle());
            se.replaceKey("/K",    QPDFObjectHandle::newInteger(mcid));

            // Bounding box layout attribute (PDF/UA recommended)
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

            // PDF/UA: Figures must have alternate text
            if (tag == "Figure") {
                se.replaceKey("/Alt", QPDFObjectHandle::newUnicodeString("[Image requires alt text]"));
            }

            QPDFObjectHandle se_indirect = pdf.makeIndirectObject(se);
            doc_kids.appendItem(se_indirect);
            page_structs.appendItem(se_indirect);
        }

        // ParentTree entry: page_idx -> [SE_for_mcid_0, SE_for_mcid_1, ...]
        parent_tree_nums.appendItem(QPDFObjectHandle::newInteger(page_idx));
        parent_tree_nums.appendItem(pdf.makeIndirectObject(page_structs));
    }

    // 5. Attach ParentTree to StructTreeRoot
    QPDFObjectHandle parent_tree = QPDFObjectHandle::newDictionary();
    parent_tree.replaceKey("/Nums", parent_tree_nums);

    struct_root_indirect.replaceKey("/ParentTree",
                                    pdf.makeIndirectObject(parent_tree));
    struct_root_indirect.replaceKey("/ParentTreeNextKey",
                                    QPDFObjectHandle::newInteger(
                                        static_cast<int>(page_mcid_counts.size())));

    root.replaceKey("/StructTreeRoot", struct_root_indirect);

    // 6. Mark the document as tagged (PDF/UA requirement)
    QPDFObjectHandle mark_info = QPDFObjectHandle::newDictionary();
    mark_info.replaceKey("/Marked", QPDFObjectHandle::newBool(true));
    root.replaceKey("/MarkInfo", mark_info);

    // 7. Set document language — required by PDF/UA and NVDA/JAWS for TTS voice selection
    if (!root.hasKey("/Lang")) {
        root.replaceKey("/Lang", QPDFObjectHandle::newUnicodeString("en-US"));
    }
}
