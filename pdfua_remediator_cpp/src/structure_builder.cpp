#include "structure_builder.h"
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <iostream>
#include <algorithm>
#include <cmath>
#include <limits>

// Normalize a layout-block tag to a PDF structure type that is valid for a
// flat leaf element (one StructElem per content MCID). Headings are preserved,
// everything textual collapses to /P, and structurally-nested roles
// (List/Table/etc.) are avoided here because they require child elements the
// flat tree does not have. /Figure is intentionally excluded: it is applied
// separately and only to genuine image MCIDs.
static std::string normalize_text_role(const std::string& raw) {
    std::string t = raw;
    if (!t.empty() && t[0] == '/') t = t.substr(1);
    if (t.empty()) return "P";

    if (t == "Title") return "H1";
    if (t == "Section-header" || t == "Sectionheader" || t == "Header" ||
        t == "Heading" || t == "Subtitle") return "H2";
    if (t.size() == 2 && t[0] == 'H' && t[1] >= '1' && t[1] <= '6') return t;
    if (t == "Caption") return "Caption";
    // Text, Paragraph, List, List-item, Table, Picture, Figure-on-text,
    // and anything non-standard collapse to a paragraph so we never emit an
    // invalid role or a Figure over real text.
    return "P";
}

// A layout block is usable for positional assignment only when it carries a
// 4-value bounding box in PDF user space.
static bool block_has_bbox(const LayoutBlock& b) {
    return b.bbox.size() == 4;
}

// Squared distance from a point to an axis-aligned rectangle [left,bottom,right,top]
// (zero when the point is inside). Used to pick the nearest block when a point
// falls outside every block (e.g. glyph baseline just under the block bottom).
static double point_rect_dist2(double x, double y, const std::vector<double>& bbox) {
    const double left = bbox[0], bottom = bbox[1], right = bbox[2], top = bbox[3];
    const double dx = std::max(std::max(left - x, 0.0), x - right);
    const double dy = std::max(std::max(bottom - y, 0.0), y - top);
    return dx * dx + dy * dy;
}

static bool point_in_bbox(double x, double y, const std::vector<double>& bbox, double margin) {
    return x >= bbox[0] - margin && x <= bbox[2] + margin &&
           y >= bbox[1] - margin && y <= bbox[3] + margin;
}

// Choose the layout block (index into blocks_on_page) that best owns the point
// (x, y). Prefers the smallest block that contains the point; otherwise falls
// back to the nearest block. Returns -1 when there are no blocks with bboxes.
static int assign_block_for_point(double x, double y,
                                  const std::vector<LayoutBlock>& blocks_on_page) {
    int best_contain = -1;
    double best_contain_area = std::numeric_limits<double>::max();
    int best_near = -1;
    double best_near_dist = std::numeric_limits<double>::max();

    for (int i = 0; i < static_cast<int>(blocks_on_page.size()); ++i) {
        const LayoutBlock& b = blocks_on_page[i];
        if (!block_has_bbox(b)) continue;

        if (point_in_bbox(x, y, b.bbox, 2.0)) {
            double area = std::max(0.0, (b.bbox[2] - b.bbox[0])) *
                          std::max(0.0, (b.bbox[3] - b.bbox[1]));
            if (area < best_contain_area) {
                best_contain_area = area;
                best_contain = i;
            }
        }

        double d2 = point_rect_dist2(x, y, b.bbox);
        if (d2 < best_near_dist) {
            best_near_dist = d2;
            best_near = i;
        }
    }

    return (best_contain >= 0) ? best_contain : best_near;
}

void build_struct_tree(QPDF& pdf,
                       const std::vector<LayoutBlock>& blocks,
                       const std::map<int, int>& page_mcid_counts,
                       const std::map<int, std::set<int>>& page_figure_mcids,
                       const std::map<int, std::map<int, MCIDInfo>>& page_mcid_info) {
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

    // 4. Build ParentTree and StructElems.
    //
    // The content tagger emits one MCID per text-showing operator, which in
    // OCR/MuPDF output is typically one per *word*. Emitting a StructElem per
    // MCID would therefore tag every word as its own paragraph/heading. Instead
    // we assign each MCID to the layout block that geometrically contains it and
    // then group every run of consecutive MCIDs belonging to the same block into
    // a single StructElem (a real paragraph, heading, etc.) whose /K references
    // all of that block's MCIDs.
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

        auto const& blocks_on_page = page_blocks[page_idx];
        int num_blocks = static_cast<int>(blocks_on_page.size());

        // MCIDs that wrap an image XObject on this page (from the content tagger).
        std::set<int> figure_mcids;
        auto fig_it = page_figure_mcids.find(page_idx);
        if (fig_it != page_figure_mcids.end()) {
            figure_mcids = fig_it->second;
        }

        // Per-MCID page positions recorded by the content tagger.
        const std::map<int, MCIDInfo>* info_map = nullptr;
        auto info_it = page_mcid_info.find(page_idx);
        if (info_it != page_mcid_info.end()) {
            info_map = &info_it->second;
        }

        // Positional assignment requires both layout-block bboxes and recorded
        // MCID positions. When either is missing we fall back to proportional
        // distribution (which still benefits from the grouping pass below).
        bool any_bbox = false;
        for (auto const& b : blocks_on_page) {
            if (block_has_bbox(b)) { any_bbox = true; break; }
        }
        const bool position_mode = any_bbox && info_map && !info_map->empty();

        // 4a. Resolve the owning layout-block index for every MCID.
        std::vector<int> mcid_block(mcid_count, -1);
        int prev_block = (num_blocks > 0) ? 0 : -1;
        for (int mcid = 0; mcid < mcid_count; ++mcid) {
            int block_idx = -1;
            if (num_blocks > 0) {
                if (position_mode) {
                    auto pit = info_map->find(mcid);
                    if (pit != info_map->end()) {
                        block_idx = assign_block_for_point(pit->second.x, pit->second.y,
                                                           blocks_on_page);
                    }
                    if (block_idx < 0) block_idx = prev_block; // inherit on miss
                } else {
                    block_idx = (mcid_count == 1)
                        ? 0
                        : (mcid * (num_blocks - 1)) / (mcid_count - 1);
                    if (block_idx >= num_blocks) block_idx = num_blocks - 1;
                }
            }
            mcid_block[mcid] = block_idx;
            if (block_idx >= 0) prev_block = block_idx;
        }

        // 4b. Walk the MCIDs in reading order and group consecutive MCIDs that
        // share the same block (figures always stand alone) into one StructElem.
        std::vector<QPDFObjectHandle> mcid_parent(mcid_count);

        auto emit_group = [&](int block_idx, bool is_figure,
                              const std::vector<int>& group_mcids) {
            if (group_mcids.empty()) return;

            std::string tag;
            std::vector<double> bbox;
            if (block_idx >= 0 && block_idx < num_blocks) {
                bbox = blocks_on_page[block_idx].bbox;
            }
            if (is_figure) {
                tag = "Figure";
            } else {
                std::string raw_tag = (block_idx >= 0 && block_idx < num_blocks)
                    ? blocks_on_page[block_idx].tag
                    : std::string("P");
                tag = normalize_text_role(raw_tag);
            }

            QPDFObjectHandle se = QPDFObjectHandle::newDictionary();
            se.replaceKey("/Type", QPDFObjectHandle::newName("/StructElem"));
            se.replaceKey("/S",    QPDFObjectHandle::newName("/" + tag));
            se.replaceKey("/P",    doc_elem_indirect);
            se.replaceKey("/Pg",   page.getObjectHandle());

            if (group_mcids.size() == 1) {
                se.replaceKey("/K", QPDFObjectHandle::newInteger(group_mcids[0]));
            } else {
                QPDFObjectHandle kids = QPDFObjectHandle::newArray();
                for (int m : group_mcids) {
                    kids.appendItem(QPDFObjectHandle::newInteger(m));
                }
                se.replaceKey("/K", kids);
            }

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

            if (tag == "Figure") {
                se.replaceKey("/Alt", QPDFObjectHandle::newUnicodeString("[Image requires alt text]"));
            }

            QPDFObjectHandle se_indirect = pdf.makeIndirectObject(se);
            doc_kids.appendItem(se_indirect);
            for (int m : group_mcids) {
                mcid_parent[m] = se_indirect;
            }
        };

        std::vector<int> group_mcids;
        int group_block = -2;     // sentinel distinct from any real index
        bool group_is_figure = false;

        for (int mcid = 0; mcid < mcid_count; ++mcid) {
            const bool is_figure = figure_mcids.count(mcid) > 0;
            const int block_idx = mcid_block[mcid];

            // A new StructElem begins whenever the figure status changes, the
            // block changes, or the current MCID is a (standalone) figure.
            const bool start_new = group_mcids.empty() || is_figure ||
                                   group_is_figure ||
                                   block_idx != group_block;
            if (start_new && !group_mcids.empty()) {
                emit_group(group_block, group_is_figure, group_mcids);
                group_mcids.clear();
            }
            if (group_mcids.empty()) {
                group_block = block_idx;
                group_is_figure = is_figure;
            }
            group_mcids.push_back(mcid);

            // Figures never absorb following MCIDs.
            if (is_figure) {
                emit_group(group_block, group_is_figure, group_mcids);
                group_mcids.clear();
                group_block = -2;
                group_is_figure = false;
            }
        }
        if (!group_mcids.empty()) {
            emit_group(group_block, group_is_figure, group_mcids);
        }

        // 4c. ParentTree entry: page_idx -> [SE owning mcid 0, SE owning mcid 1, ...]
        QPDFObjectHandle page_structs = QPDFObjectHandle::newArray();
        for (int mcid = 0; mcid < mcid_count; ++mcid) {
            if (mcid_parent[mcid].isInitialized()) {
                page_structs.appendItem(mcid_parent[mcid]);
            } else {
                // Should not happen, but keep the array index aligned with MCIDs.
                page_structs.appendItem(QPDFObjectHandle::newNull());
            }
        }
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
