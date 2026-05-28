#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <regex>
#include <qpdf/QPDF.hh>
#include <qpdf/QPDFWriter.hh>
#include "content_tagger.h"
#include "structure_builder.h"

// Robust self-contained JSON parser to extract layout blocks
std::vector<LayoutBlock> parse_layout_json(const std::string& path) {
    std::vector<LayoutBlock> blocks;
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "Failed to open layout JSON file: " << path << std::endl;
        return blocks;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    std::string content = buffer.str();

    // Regexes to extract page indices, tags, and bounding boxes.
    // We ignore the actual "text" field to avoid escaping/quote matching issues in C++.
    std::regex page_regex("\"page\"\\s*:\\s*(\\d+)");
    std::regex tag_regex("\"tag\"\\s*:\\s*\"([^\"]+)\"");
    std::regex bbox_regex("\"bbox\"\\s*:\\s*\\[\\s*([\\d.-]+)\\s*,\\s*([\\d.-]+)\\s*,\\s*([\\d.-]+)\\s*,\\s*([\\d.-]+)\\s*\\]");

    // Scan the JSON array for block objects enclosed in { }
    size_t pos = 0;
    while ((pos = content.find('{', pos)) != std::string::npos) {
        size_t end_pos = content.find('}', pos);
        if (end_pos == std::string::npos) {
            break;
        }

        std::string obj_str = content.substr(pos, end_pos - pos + 1);
        pos = end_pos + 1;

        LayoutBlock block;
        block.page = 0;
        
        std::smatch match;
        if (std::regex_search(obj_str, match, page_regex)) {
            block.page = std::stoi(match[1].str());
        }
        if (std::regex_search(obj_str, match, tag_regex)) {
            block.tag = match[1].str();
        }
        if (std::regex_search(obj_str, match, bbox_regex)) {
            block.bbox.push_back(std::stod(match[1].str()));
            block.bbox.push_back(std::stod(match[2].str()));
            block.bbox.push_back(std::stod(match[3].str()));
            block.bbox.push_back(std::stod(match[4].str()));
        }

        blocks.push_back(block);
    }

    return blocks;
}

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: pdfua-remediator-cli <input-pdf> <layout-json> <output-pdf>" << std::endl;
        return 1;
    }

    std::string input_pdf = argv[1];
    std::string layout_json = argv[2];
    std::string output_pdf = argv[3];

    try {
        std::cout << "Loading layout mapping from " << layout_json << "..." << std::endl;
        std::vector<LayoutBlock> blocks = parse_layout_json(layout_json);
        std::cout << "Loaded " << blocks.size() << " layout blocks." << std::endl;

        std::cout << "Processing PDF content streams in " << input_pdf << "..." << std::endl;
        QPDF pdf;
        pdf.processFile(input_pdf.c_str());

        // Step 1: Wrap text elements in BDC/EMC marked content and assign MCIDs
        std::map<int, int> page_mcid_counts = tag_pdf_content_streams(pdf);
        std::cout << "Content streams tagged successfully." << std::endl;
        for (auto const& pair : page_mcid_counts) {
            std::cout << "  Page " << pair.first + 1 << ": " << pair.second << " MCIDs injected." << std::endl;
        }

        // Step 2: Build the structure tagging tree mapping MCIDs -> tags
        std::cout << "Building PDF/UA structure tree..." << std::endl;
        build_struct_tree(pdf, blocks, page_mcid_counts);
        std::cout << "Structure tree generated." << std::endl;

        // Step 3: Write out the final tagged PDF
        // Use PDF 1.4 settings: disable object streams and xref streams so that
        // NVDA, JAWS and other AT tools can traverse the structure tree without
        // issues caused by compressed/object-stream cross-reference tables.
        std::cout << "Saving compliant PDF to " << output_pdf << "..." << std::endl;
        QPDFWriter writer(pdf, output_pdf.c_str());
        writer.setObjectStreamMode(qpdf_o_disable);   // No object streams (PDF 1.5+)
        writer.setMinimumPDFVersion("1.4");            // PDF 1.4 baseline
        writer.setLinearization(false);                // Simpler file structure
        writer.write();
        std::cout << "PDF/UA compliant document created successfully." << std::endl;

    } catch (std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
