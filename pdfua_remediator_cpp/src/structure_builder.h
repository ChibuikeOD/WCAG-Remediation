#ifndef STRUCTURE_BUILDER_H
#define STRUCTURE_BUILDER_H

#include "content_tagger.h"
#include <qpdf/QPDF.hh>
#include <vector>
#include <map>

void build_struct_tree(QPDF& pdf, const std::vector<LayoutBlock>& blocks, const std::map<int, int>& page_mcid_counts);

#endif // STRUCTURE_BUILDER_H
