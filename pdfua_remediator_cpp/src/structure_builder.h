#ifndef STRUCTURE_BUILDER_H
#define STRUCTURE_BUILDER_H

#include "content_tagger.h"
#include <qpdf/QPDF.hh>
#include <vector>
#include <map>
#include <set>

void build_struct_tree(QPDF& pdf,
                       const std::vector<LayoutBlock>& blocks,
                       const std::map<int, int>& page_mcid_counts,
                       const std::map<int, std::set<int>>& page_figure_mcids,
                       const std::map<int, std::map<int, MCIDInfo>>& page_mcid_info);

#endif // STRUCTURE_BUILDER_H
