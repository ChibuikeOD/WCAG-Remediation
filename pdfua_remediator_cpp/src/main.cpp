#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <regex>
#include <cmath>
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
    std::regex table_id_regex("\"table_id\"\\s*:\\s*\"([^\"]+)\"");
    std::regex table_row_regex("\"table_row\"\\s*:\\s*(-?\\d+)");
    std::regex table_col_regex("\"table_col\"\\s*:\\s*(-?\\d+)");
    std::regex table_header_regex("\"table_header\"\\s*:\\s*(true|false)");
    std::regex table_row_span_regex("\"table_row_span\"\\s*:\\s*(\\d+)");
    std::regex table_col_span_regex("\"table_col_span\"\\s*:\\s*(\\d+)");
    std::regex table_scope_regex("\"table_scope\"\\s*:\\s*\"([^\"]*)\"");
    std::regex alt_hex_regex("\"alt_hex\"\\s*:\\s*\"([0-9a-fA-F]*)\"");
    std::regex figure_alt_hex_regex("\"figure_alt_hex\"\\s*:\\s*\"([0-9a-fA-F]*)\"");
    std::regex inline_order_regex("\"inline_order\"\\s*:\\s*\"([0-9eE.,; +\\-]+)\"");
    std::regex inline_group_regex("\"inline_group_id\"\\s*:\\s*\"([a-zA-Z0-9-]+)\"");
    std::regex inline_parent_regex("\"inline_parent_id\"\\s*:\\s*\"([a-zA-Z0-9-]+)\"");

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
        if (std::regex_search(obj_str, match, table_id_regex)) {
            block.table_id = match[1].str();
        }
        if (std::regex_search(obj_str, match, table_row_regex)) {
            block.table_row = std::stoi(match[1].str());
        }
        if (std::regex_search(obj_str, match, table_col_regex)) {
            block.table_col = std::stoi(match[1].str());
        }
        if (std::regex_search(obj_str, match, table_header_regex)) {
            block.table_header = match[1].str() == "true";
        }
        if (std::regex_search(obj_str, match, table_row_span_regex)) {
            block.table_row_span = std::stoi(match[1].str());
            if (block.table_row_span < 1) throw std::runtime_error("Invalid table row span");
        }
        if (std::regex_search(obj_str, match, table_col_span_regex)) {
            block.table_col_span = std::stoi(match[1].str());
            if (block.table_col_span < 1) throw std::runtime_error("Invalid table column span");
        }
        if (std::regex_search(obj_str, match, table_scope_regex)) {
            block.table_scope_supplied = true;
            block.table_scope = match[1].str();
            if (!block.table_scope.empty() && block.table_scope != "Row" &&
                block.table_scope != "Column" && block.table_scope != "Both")
                throw std::runtime_error("Invalid table header scope");
        }
        if (std::regex_search(obj_str, match, figure_alt_hex_regex)) {
            const std::string hex = match[1].str();
            if (hex.size() % 2 != 0) throw std::runtime_error("Invalid figure_alt_hex length");
            for (size_t i = 0; i < hex.size(); i += 2)
                block.figure_alt_text.push_back(static_cast<char>(std::stoi(hex.substr(i, 2), nullptr, 16)));
        }
        if (std::regex_search(obj_str, match, alt_hex_regex)) {
            const std::string hex = match[1].str();
            if (hex.size() % 2 != 0) throw std::runtime_error("Invalid alt_hex length");
            for (size_t i = 0; i < hex.size(); i += 2) {
                block.alt_text.push_back(static_cast<char>(std::stoi(hex.substr(i, 2), nullptr, 16)));
            }
        }
        if (std::regex_search(obj_str, match, inline_order_regex)) {
            std::istringstream runs(match[1].str());
            std::string run;
            while (std::getline(runs, run, ';')) {
                std::istringstream fields(run);
                std::vector<double> values;
                std::string field;
                while (std::getline(fields, field, ',')) values.push_back(std::stod(field));
                if (values.size() != 6 || values[0] > values[2] || values[1] > values[3]) {
                    throw std::runtime_error("Invalid inline_order coordinates");
                }
                for (double value : values) if (!std::isfinite(value)) throw std::runtime_error("Non-finite inline_order coordinate");
                block.inline_runs.push_back(values);
            }
        }

        blocks.push_back(block);
        if (std::regex_search(obj_str, match, inline_group_regex)) blocks.back().inline_group_id = match[1].str();
        if (std::regex_search(obj_str, match, inline_parent_regex)) blocks.back().inline_parent_id = match[1].str();
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
        std::map<int, std::set<int>> page_figure_mcids;
        std::map<int, std::map<int, MCIDInfo>> page_mcid_info;
        std::map<int, int> page_mcid_counts =
            tag_pdf_content_streams(pdf, blocks, page_figure_mcids, page_mcid_info);
        std::cout << "Content streams tagged successfully." << std::endl;
        for (auto const& pair : page_mcid_counts) {
            std::cout << "  Page " << pair.first + 1 << ": " << pair.second << " MCIDs injected." << std::endl;
        }

        // Step 2: Build the structure tagging tree mapping MCIDs -> tags
        std::cout << "Building PDF/UA structure tree..." << std::endl;
        build_struct_tree(pdf, blocks, page_mcid_counts, page_figure_mcids, page_mcid_info);
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
