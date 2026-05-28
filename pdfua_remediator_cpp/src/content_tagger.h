#ifndef CONTENT_TAGGER_H
#define CONTENT_TAGGER_H

#include <string>
#include <vector>
#include <map>
#include <qpdf/QPDF.hh>
#include <qpdf/QPDFObjectHandle.hh>

struct LayoutBlock {
    int page;
    std::string tag;
    std::string text;
    std::vector<double> bbox;
};

// Process content streams of the PDF pages and insert BDC/EMC tags with MCIDs
// Returns a map of page_index -> number of MCIDs injected on that page
std::map<int, int> tag_pdf_content_streams(QPDF& pdf);

#endif // CONTENT_TAGGER_H
