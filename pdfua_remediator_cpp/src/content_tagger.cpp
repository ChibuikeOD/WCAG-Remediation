#include "content_tagger.h"
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <qpdf/Pl_Buffer.hh>
#include <iostream>

class MCIDTokenFilter : public QPDFObjectHandle::TokenFilter {
public:
    MCIDTokenFilter() : mcid_counter(0), in_text_object(false), has_last_name(false),
                        marked_content_depth(0), in_path(false), inline_dict_depth(0) {}
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

        // Pass inline dictionaries through verbatim (outside text objects).
        // Marked-content property lists such as the "/P <</MCID 0>> BDC"
        // sequences emitted by MuPDF's OCR text layer arrive while
        // in_text_object == false and marked_content_depth == 0, the same state
        // in which numeric operands are buffered for path wrapping and names are
        // held as a pending name. Without this guard the dictionary's value (an
        // integer) is captured by the path-operand buffer and flushed before the
        // pending key name, reordering "<</MCID 0>>" into "<<0 /MCID >>" and
        // producing "name object expected" parse errors in strict readers (PAC).
        if (!in_text_object) {
            if (inline_dict_depth > 0) {
                if (type == QPDFTokenizer::tt_dict_open) {
                    inline_dict_depth++;
                } else if (type == QPDFTokenizer::tt_dict_close) {
                    inline_dict_depth--;
                    if (inline_dict_depth < 0) inline_dict_depth = 0;
                }
                writeToken(token);
                return;
            }
            if (type == QPDFTokenizer::tt_dict_open) {
                // Preserve ordering: emit any buffered path operands and the
                // pending name (e.g. the "/P" tag) before the dictionary opens.
                if (!path_operand_buffer.empty()) {
                    for (auto const& t : path_operand_buffer) {
                        writeToken(t);
                    }
                    path_operand_buffer.clear();
                }
                write_pending_name();
                inline_dict_depth++;
                writeToken(token);
                return;
            }
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

                    // Record that this MCID is an image so the structure builder
                    // tags it (and only it) as a /Figure.
                    figure_mcids.insert(mcid_counter);
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
    const std::set<int>& getFigureMCIDs() const { return figure_mcids; }

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
    int inline_dict_depth;
    std::set<int> figure_mcids;
};

// Removes any pre-existing marked-content operators (BDC/BMC/EMC/DP/MP) and
// their operands from a content stream, leaving the drawing operators intact.
// This makes re-tagging idempotent and, crucially, cleans up the marked content
// MuPDF's OCR layer injects (e.g. an unbalanced "/P <</MCID 0>> BDC" wrapping the
// page image). Without this, re-tagging would emit duplicate MCIDs and unbalanced
// marked-content sequences, which PAC and other strict validators reject.
class StripMarkedContentFilter : public QPDFObjectHandle::TokenFilter {
public:
    StripMarkedContentFilter() : dict_depth(0), array_depth(0) {}
    virtual ~StripMarkedContentFilter() = default;

    virtual void handleToken(QPDFTokenizer::Token const& token) override {
        QPDFTokenizer::token_type_e type = token.getType();
        std::string value = token.getValue();

        // Accumulate the tokens of a compound operand (dict/array) verbatim.
        if (dict_depth > 0 || array_depth > 0) {
            pending.push_back(token);
            if (type == QPDFTokenizer::tt_dict_open)        dict_depth++;
            else if (type == QPDFTokenizer::tt_dict_close)  { if (--dict_depth < 0) dict_depth = 0; }
            else if (type == QPDFTokenizer::tt_array_open)  array_depth++;
            else if (type == QPDFTokenizer::tt_array_close) { if (--array_depth < 0) array_depth = 0; }
            return;
        }

        if (type == QPDFTokenizer::tt_dict_open)  { pending.push_back(token); dict_depth++;  return; }
        if (type == QPDFTokenizer::tt_array_open) { pending.push_back(token); array_depth++; return; }

        if (type == QPDFTokenizer::tt_word) {
            // Marked-content operators: drop the operator and its buffered operands.
            if (value == "BDC" || value == "BMC" || value == "DP" || value == "MP") {
                pending.clear();
                return;
            }
            if (value == "EMC") {
                pending.clear();
                return;
            }
            // Any other operator: commit its operands, then the operator itself.
            flushPending();
            writeToken(token);
            return;
        }

        // Operand token (name, number, string, space, comment, inline image): buffer it.
        pending.push_back(token);
    }

    virtual void handleEOF() override {
        flushPending();
    }

private:
    void flushPending() {
        for (auto const& t : pending) {
            writeToken(t);
        }
        pending.clear();
    }

    std::vector<QPDFTokenizer::Token> pending;
    int dict_depth;
    int array_depth;
};

std::map<int, int> tag_pdf_content_streams(QPDF& pdf,
                                           std::map<int, std::set<int>>& page_figure_mcids) {
    std::map<int, int> page_mcid_counts;
    QPDFPageDocumentHelper pdh(pdf);
    std::vector<QPDFPageObjectHelper> pages = pdh.getAllPages();

    for (size_t i = 0; i < pages.size(); ++i) {
        // Pass 1: strip any pre-existing marked content (e.g. from OCR output or
        // a previously tagged PDF) so the re-tagging pass starts from a clean,
        // unmarked content stream.
        StripMarkedContentFilter strip;
        Pl_Buffer strip_buf("stripped contents");
        pages[i].filterPageContents(&strip, &strip_buf);
        strip_buf.finish();
        Buffer* sb = strip_buf.getBuffer();
        std::string stripped_str(reinterpret_cast<char const*>(sb->getBuffer()), sb->getSize());
        delete sb;
        pages[i].getObjectHandle().replaceKey("/Contents",
                                              QPDFObjectHandle::newStream(&pdf, stripped_str));

        // Pass 2: inject fresh MCIDs and marked content on the cleaned stream.
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
        page_figure_mcids[static_cast<int>(i)] = filter.getFigureMCIDs();
    }

    return page_mcid_counts;
}
