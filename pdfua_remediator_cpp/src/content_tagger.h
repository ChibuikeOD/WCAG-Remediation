#ifndef CONTENT_TAGGER_H
#define CONTENT_TAGGER_H

#include <string>
#include <vector>
#include <map>
#include <set>
#include <qpdf/QPDF.hh>
#include <qpdf/QPDFObjectHandle.hh>

struct LayoutBlock {
    int page;
    std::string tag;
    std::string text;
    std::vector<double> bbox;
};

// Geometry of a single injected MCID, expressed in PDF default user space
// (points, bottom-left origin) so it can be matched against the layout-block
// bounding boxes produced by OpenDataLoader (which use the same space).
struct MCIDInfo {
    double x = 0.0;        // text/image origin X in page user space
    double y = 0.0;        // text/image origin Y in page user space
    bool is_figure = false; // true when the MCID wraps an image XObject
    std::vector<double> bbox; // exact page bounding box [left, bottom, right, top] for figures
};

// Process content streams of the PDF pages and insert BDC/EMC tags with MCIDs.
// Returns a map of page_index -> number of MCIDs injected on that page.
// page_figure_mcids is populated with, per page, the set of MCIDs that wrap an
// image XObject (a `Do` operator) so the structure builder can restrict the
// /Figure role to genuine images and never apply it to text content.
// page_mcid_info is populated with, per page, a map of MCID -> MCIDInfo giving
// the on-page position of each MCID. The structure builder uses these positions
// to assign every MCID to its containing layout block and to group the
// word/run-level MCIDs back into proper paragraph and heading elements.
std::map<int, int> tag_pdf_content_streams(QPDF& pdf,
                                           std::map<int, std::set<int>>& page_figure_mcids,
                                           std::map<int, std::map<int, MCIDInfo>>& page_mcid_info);

#endif // CONTENT_TAGGER_H
