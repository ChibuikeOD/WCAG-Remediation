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

// Process content streams of the PDF pages and insert BDC/EMC tags with MCIDs.
// Returns a map of page_index -> number of MCIDs injected on that page.
// page_figure_mcids is populated with, per page, the set of MCIDs that wrap an
// image XObject (a `Do` operator) so the structure builder can restrict the
// /Figure role to genuine images and never apply it to text content.
std::map<int, int> tag_pdf_content_streams(QPDF& pdf,
                                           std::map<int, std::set<int>>& page_figure_mcids);

#endif // CONTENT_TAGGER_H
