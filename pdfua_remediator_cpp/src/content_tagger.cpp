#include "content_tagger.h"
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <qpdf/Pl_Buffer.hh>
#include <iostream>

class MCIDTokenFilter : public QPDFObjectHandle::TokenFilter {
public:
    MCIDTokenFilter() : mcid_counter(0), in_text_object(false), has_last_name(false),
                        marked_content_depth(0), in_path_construction(false) {}
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

        // Flush path construction buffering on marked content or text object boundaries
        if (type == QPDFTokenizer::tt_word && (value == "BDC" || value == "BMC" || value == "EMC" || value == "BT" || value == "ET" || value == "Do")) {
            flush_buffered_path_tokens();
        }

        // 1. Handle untagged path objects outside marked content blocks
        if (!in_text_object && marked_content_depth == 0) {
            if (type == QPDFTokenizer::tt_word && (value == "m" || value == "re")) {
                write_pending_name();
                flush_buffered_path_tokens();
                in_path_construction = true;
                buffered_path_tokens.push_back(token);
                return;
            }

            if (in_path_construction) {
                if (type == QPDFTokenizer::tt_word && 
                    (value == "S" || value == "s" || value == "f" || value == "F" || value == "f*" || 
                     value == "B" || value == "B*" || value == "b" || value == "b*" || value == "sh")) {
                    
                    // Wrap the entire path sequence in an /Artifact BMC block
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_name, "/Artifact"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "BMC"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    
                    for (auto const& t : buffered_path_tokens) {
                        writeToken(t);
                    }
                    writeToken(token); // Write the painting operator itself
                    
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
                    writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));

                    buffered_path_tokens.clear();
                    in_path_construction = false;
                    return;
                } else if (type == QPDFTokenizer::tt_word && value == "n") {
                    // Path ended without painting (no-op or clip path) - flush unwrapped
                    flush_buffered_path_tokens();
                } else {
                    buffered_path_tokens.push_back(token);
                    return;
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
        write_pending_name();
        write_buffered_text_tokens();
        flush_buffered_path_tokens();
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

    void flush_buffered_path_tokens() {
        if (in_path_construction) {
            for (auto const& t : buffered_path_tokens) {
                writeToken(t);
            }
            buffered_path_tokens.clear();
            in_path_construction = false;
        }
    }

    int mcid_counter;
    bool in_text_object;
    QPDFTokenizer::Token last_name_token;
    bool has_last_name;
    std::vector<QPDFTokenizer::Token> spaces_after_name;
    std::vector<QPDFTokenizer::Token> buffered_text_tokens;
    int marked_content_depth;
    bool in_path_construction;
    std::vector<QPDFTokenizer::Token> buffered_path_tokens;
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
