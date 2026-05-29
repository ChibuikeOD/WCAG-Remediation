#include "content_tagger.h"
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <qpdf/Pl_Buffer.hh>
#include <iostream>

class MCIDTokenFilter : public QPDFObjectHandle::TokenFilter {
public:
    MCIDTokenFilter() : mcid_counter(0), in_text_object(false), has_last_name(false),
                        marked_content_depth(0), in_path(false) {}
    virtual ~MCIDTokenFilter() = default;

    virtual void handleToken(QPDFTokenizer::Token const& token) override {
        QPDFTokenizer::token_type_e type = token.getType();
        std::string value = token.getValue();

        // Track marked content depth to avoid nesting artifacts inside structural elements
        if (type == QPDFTokenizer::tt_word) {
            if (value == "BDC" || value == "BMC") {
                marked_content_depth++;
            } else if (value == "EMC") {
                marked_content_depth--;
                if (marked_content_depth < 0) marked_content_depth = 0;
            }
        }

        // If we are currently inside a path, we write everything directly.
        // If we hit a path painting/terminating operator, we write it, then write EMC, and set in_path = false.
        if (in_path) {
            writeToken(token);
            if (type == QPDFTokenizer::tt_word && 
                (value == "S" || value == "s" || value == "f" || value == "F" || value == "f*" || 
                 value == "B" || value == "B*" || value == "b" || value == "b*" || value == "sh" || value == "n")) {
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                in_path = false;
            }
            return;
        }

        // If we are not inside a path, and we are outside text objects, and not inside marked content:
        if (!in_text_object && marked_content_depth == 0) {
            // Check if this token is a path-starting operator
            bool is_path_start = (type == QPDFTokenizer::tt_word &&
                                  (value == "m" || value == "re" || value == "l" || value == "c" || 
                                   value == "v" || value == "y" || value == "h"));
            
            if (is_path_start) {
                // Wrap the path in /Artifact BMC ... EMC
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_name, "/Artifact"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "BMC"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));

                // Write the buffered operands
                for (auto const& t : path_operand_buffer) {
                    writeToken(t);
                }
                path_operand_buffer.clear();

                // Write the path starting operator itself
                writeToken(token);
                
                in_path = true;
                return;
            }

            // If it is not a path-starting operator, check if it's a bufferable token (numeric, or space/comment when buffer is not empty)
            bool is_numeric = (type == QPDFTokenizer::tt_integer || type == QPDFTokenizer::tt_real);
            bool is_space_comment = (type == QPDFTokenizer::tt_space || type == QPDFTokenizer::tt_comment);

            if (is_numeric) {
                path_operand_buffer.push_back(token);
                return;
            } else if (is_space_comment && !path_operand_buffer.empty()) {
                path_operand_buffer.push_back(token);
                return;
            } else {
                // Not a path-starting operator and not a bufferable token.
                // Flush path operand buffer before processing this token.
                if (!path_operand_buffer.empty()) {
                    for (auto const& t : path_operand_buffer) {
                        writeToken(t);
                    }
                    path_operand_buffer.clear();
                }
            }
        }

        // 2. Handle name token buffering for Do (which only occurs outside text objects)
        if (!in_text_object) {
            if (type == QPDFTokenizer::tt_space || type == QPDFTokenizer::tt_comment) {
                if (has_last_name) {
                    spaces_after_name.push_back(token);
                } else {
                    writeToken(token);
                }
                return;
            }

            if (type == QPDFTokenizer::tt_name) {
                write_pending_name();
                last_name_token = token;
                has_last_name = true;
                spaces_after_name.clear();
                return;
            }

            if (type == QPDFTokenizer::tt_word && value == "Do") {
                if (has_last_name) {
                    // Wrap the Do operator in a BDC/EMC block representing a Figure
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_name, "/Figure"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_dict_open, "<<"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_name, "/MCID"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_integer, std::to_string(mcid_counter)));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_dict_close, ">>"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "BDC"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));

                    // Write the buffered name token (e.g. /Im0) and spaces
                    writeToken(last_name_token);
                    for (auto const& s : spaces_after_name) {
                        writeToken(s);
                    }
                    has_last_name = false;
                    spaces_after_name.clear();

                    // Write Do
                    writeToken(token);

                    // Write EMC
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));

                    mcid_counter++;
                    return;
                }
            }

            write_pending_name();
        }

        // 3. Handle text object BT...ET and its buffering
        if (type == QPDFTokenizer::tt_word && value == "BT") {
            in_text_object = true;
            writeToken(token);
            return;
        }

        if (type == QPDFTokenizer::tt_word && value == "ET") {
            // Write any remaining buffered tokens
            write_buffered_text_tokens();
            in_text_object = false;
            writeToken(token);
            return;
        }

        if (in_text_object) {
            if (type == QPDFTokenizer::tt_word && (value == "Tj" || value == "TJ" || value == "'" || value == "\"")) {
                // Write BDC
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_name, "/P"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_dict_open, "<<"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_name, "/MCID"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_integer, std::to_string(mcid_counter)));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_dict_close, ">>"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "BDC"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));

                // Write all buffered tokens
                write_buffered_text_tokens();

                // Write the text showing operator itself
                writeToken(token);

                // Write EMC
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));

                mcid_counter++;
                return;
            } else {
                // Buffer the token
                buffered_text_tokens.push_back(token);
                return;
            }
        }

        // Pass through the original token
        writeToken(token);
    }

    virtual void handleEOF() override {
        if (!path_operand_buffer.empty()) {
            for (auto const& t : path_operand_buffer) {
                writeToken(t);
            }
            path_operand_buffer.clear();
        }
        write_pending_name();
        write_buffered_text_tokens();
        if (in_path) {
            writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
            writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
            writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
            in_path = false;
        }
    }

    int getMCIDCount() const { return mcid_counter; }

private:
    void write_pending_name() {
        if (has_last_name) {
            writeToken(last_name_token);
            for (auto const& s : spaces_after_name) {
                writeToken(s);
            }
            has_last_name = false;
            spaces_after_name.clear();
        }
    }

    void write_buffered_text_tokens() {
        for (auto const& t : buffered_text_tokens) {
            writeToken(t);
        }
        buffered_text_tokens.clear();
    }

    int mcid_counter;
    bool in_text_object;
    QPDFTokenizer::Token last_name_token;
    bool has_last_name;
    std::vector<QPDFTokenizer::Token> spaces_after_name;
    std::vector<QPDFTokenizer::Token> buffered_text_tokens;
    int marked_content_depth;
    bool in_path;
    std::vector<QPDFTokenizer::Token> path_operand_buffer;
};

std::map<int, int> tag_pdf_content_streams(QPDF& pdf) {
    std::map<int, int> page_mcid_counts;
    QPDFPageDocumentHelper pdh(pdf);
    std::vector<QPDFPageObjectHelper> pages = pdh.getAllPages();

    for (size_t i = 0; i < pages.size(); ++i) {
        MCIDTokenFilter filter;
        Pl_Buffer buf("filtered contents");
        
        pages[i].filterPageContents(&filter, &buf);
        buf.finish();
        
        Buffer* b = buf.getBuffer();
        std::string new_content_str(reinterpret_cast<char const*>(b->getBuffer()), b->getSize());
        delete b;
        QPDFObjectHandle new_contents = QPDFObjectHandle::newStream(&pdf, new_content_str);
        
        pages[i].getObjectHandle().replaceKey("/Contents", new_contents);
        page_mcid_counts[static_cast<int>(i)] = filter.getMCIDCount();
    }

    return page_mcid_counts;
}
