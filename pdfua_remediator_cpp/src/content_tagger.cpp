#include "content_tagger.h"
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <qpdf/Pl_Buffer.hh>
#include <iostream>
#include <cmath>
#include <algorithm>

// A 2x3 affine matrix [a b c d e f] mapping a row-vector point (x, y, 1):
//   x' = a*x + c*y + e
//   y' = b*x + d*y + f
// Matches the PDF coordinate-transform convention used by `cm`/`Tm`/`Td`.
struct AffineMat {
    double a = 1.0, b = 0.0, c = 0.0, d = 1.0, e = 0.0, f = 0.0;
};

// Compose two matrices so that a point is transformed by L first, then R
// (row-vector convention: p' = p * L * R). This is the order PDF uses when
// concatenating the text matrix with the CTM and when `cm` premultiplies.
static AffineMat affine_mul(const AffineMat& L, const AffineMat& R) {
    AffineMat m;
    m.a = L.a * R.a + L.b * R.c;
    m.b = L.a * R.b + L.b * R.d;
    m.c = L.c * R.a + L.d * R.c;
    m.d = L.c * R.b + L.d * R.d;
    m.e = L.e * R.a + L.f * R.c + R.e;
    m.f = L.e * R.b + L.f * R.d + R.f;
    return m;
}

class MCIDTokenFilter : public QPDFObjectHandle::TokenFilter {
public:
    struct Rect {
        double left, bottom, right, top;
    };
    std::vector<Rect> page_link_rects;

    MCIDTokenFilter() : mcid_counter(0), in_text_object(false), has_last_name(false),
                        marked_content_depth(0), in_path(false), inline_dict_depth(0),
                        text_leading(0.0), geo_array_depth(0), geo_dict_depth(0),
                        in_marked_content(false), last_x(0.0), last_y(0.0), last_link_idx(-1) {}

    MCIDTokenFilter(std::vector<QPDFObjectHandle> const& link_rects) 
        : mcid_counter(0), in_text_object(false), has_last_name(false),
          marked_content_depth(0), in_path(false), inline_dict_depth(0),
          text_leading(0.0), geo_array_depth(0), geo_dict_depth(0),
          in_marked_content(false), last_x(0.0), last_y(0.0), last_link_idx(-1) {
        for (auto const& rect : link_rects) {
            if (rect.isArray() && rect.getArrayNItems() == 4) {
                Rect r;
                r.left = rect.getArrayItem(0).getNumericValue();
                r.bottom = rect.getArrayItem(1).getNumericValue();
                r.right = rect.getArrayItem(2).getNumericValue();
                r.top = rect.getArrayItem(3).getNumericValue();
                page_link_rects.push_back(r);
            }
        }
    }
    virtual ~MCIDTokenFilter() = default;

    virtual void handleToken(QPDFTokenizer::Token const& token) override {
        QPDFTokenizer::token_type_e type = token.getType();
        std::string value = token.getValue();

        // Maintain the graphics/text transform state for every token so we can
        // record where each injected MCID lives on the page.
        updateGeometry(token, type, value);

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
                    // tags it (and only it) as a /Figure. The image is drawn into
                    // the unit square transformed by the CTM, so use its centre and calculate its BBox.
                    MCIDInfo info;
                    info.x = ctm.a * 0.5 + ctm.c * 0.5 + ctm.e;
                    info.y = ctm.b * 0.5 + ctm.d * 0.5 + ctm.f;
                    info.is_figure = true;

                    // Calculate transformed corners of [0, 0, 1, 1] unit square
                    double x1 = ctm.e;
                    double y1 = ctm.f;
                    double x2 = ctm.a + ctm.e;
                    double y2 = ctm.b + ctm.f;
                    double x3 = ctm.c + ctm.e;
                    double y3 = ctm.d + ctm.f;
                    double x4 = ctm.a + ctm.c + ctm.e;
                    double y4 = ctm.b + ctm.d + ctm.f;

                    info.bbox = {
                        std::min({x1, x2, x3, x4}),
                        std::min({y1, y2, y3, y4}),
                        std::max({x1, x2, x3, x4}),
                        std::max({y1, y2, y3, y4})
                    };

                    mcid_info[mcid_counter] = info;

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
            in_marked_content = false;
            last_link_idx = -1;
            writeToken(token);
            return;
        }

        if (type == QPDFTokenizer::tt_word && value == "ET") {
            if (in_marked_content) {
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
                writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                in_marked_content = false;
            }
            // Write any remaining buffered tokens
            write_buffered_text_tokens();
            in_text_object = false;
            writeToken(token);
            return;
        }

        if (in_text_object) {
            if (type == QPDFTokenizer::tt_word && (value == "Tj" || value == "TJ" || value == "'" || value == "\"")) {
                AffineMat trm = affine_mul(tm, ctm);

                int current_link_idx = -1;
                for (int j = 0; j < static_cast<int>(page_link_rects.size()); ++j) {
                    const auto& r = page_link_rects[j];
                    if (trm.e >= r.left - 2.0 && trm.e <= r.right + 2.0 &&
                        trm.f >= r.bottom - 5.0 && trm.f <= r.top + 5.0) {
                        current_link_idx = j;
                        break;
                    }
                }

                bool start_new_mcid = false;
                if (!in_marked_content) {
                    start_new_mcid = true;
                } else {
                    double dx = std::abs(trm.e - last_x);
                    double dy = std::abs(trm.f - last_y);
                    if (dy > 3.0 || dx > 150.0 || trm.e < last_x - 5.0) {
                        start_new_mcid = true;
                    } else if (current_link_idx != last_link_idx) {
                        start_new_mcid = true;
                    }
                }

                if (start_new_mcid) {
                    if (in_marked_content) {
                        writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                        writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_word, "EMC"));
                        writeToken(QPDFTokenizer::Token(QPDFTokenizer::tt_space, " "));
                        in_marked_content = false;
                    }

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

                    MCIDInfo info;
                    info.x = trm.e;
                    info.y = trm.f;
                    info.is_figure = false;
                    mcid_info[mcid_counter] = info;

                    mcid_counter++;
                    in_marked_content = true;
                }

                // Write all buffered tokens
                write_buffered_text_tokens();

                // Write the text showing operator itself
                writeToken(token);

                last_x = trm.e;
                last_y = trm.f;
                last_link_idx = current_link_idx;
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
    const std::map<int, MCIDInfo>& getMCIDInfo() const { return mcid_info; }

private:
    // Track the current transformation matrix (CTM) and text matrices so that
    // the page-space position of each shown text run / image can be computed.
    // Numeric operands are buffered until their operator arrives; operands that
    // live inside an array (e.g. the TJ array) or a dictionary are ignored.
    void updateGeometry(QPDFTokenizer::Token const& token,
                        QPDFTokenizer::token_type_e type,
                        std::string const& value) {
        if (type == QPDFTokenizer::tt_array_open)  { geo_array_depth++; return; }
        if (type == QPDFTokenizer::tt_array_close) { if (--geo_array_depth < 0) geo_array_depth = 0; return; }
        if (type == QPDFTokenizer::tt_dict_open)   { geo_dict_depth++; return; }
        if (type == QPDFTokenizer::tt_dict_close)  { if (--geo_dict_depth < 0) geo_dict_depth = 0; return; }

        if (type == QPDFTokenizer::tt_integer || type == QPDFTokenizer::tt_real) {
            if (geo_array_depth == 0 && geo_dict_depth == 0) {
                try { geo_numbers.push_back(std::stod(value)); } catch (...) {}
            }
            return;
        }

        if (type != QPDFTokenizer::tt_word) {
            // Names, strings, comments, etc. do not move the cursor and must not
            // discard the operands accumulated for the operator that follows.
            return;
        }

        const size_t n = geo_numbers.size();
        if (value == "q") {
            ctm_stack.push_back(ctm);
        } else if (value == "Q") {
            if (!ctm_stack.empty()) { ctm = ctm_stack.back(); ctm_stack.pop_back(); }
        } else if (value == "cm" && n >= 6) {
            AffineMat m;
            m.a = geo_numbers[n-6]; m.b = geo_numbers[n-5]; m.c = geo_numbers[n-4];
            m.d = geo_numbers[n-3]; m.e = geo_numbers[n-2]; m.f = geo_numbers[n-1];
            ctm = affine_mul(m, ctm);
        } else if (value == "BT") {
            tm = AffineMat();
            tlm = AffineMat();
        } else if (value == "Tm" && n >= 6) {
            AffineMat m;
            m.a = geo_numbers[n-6]; m.b = geo_numbers[n-5]; m.c = geo_numbers[n-4];
            m.d = geo_numbers[n-3]; m.e = geo_numbers[n-2]; m.f = geo_numbers[n-1];
            tm = m;
            tlm = m;
        } else if (value == "Td" && n >= 2) {
            AffineMat t;
            t.e = geo_numbers[n-2];
            t.f = geo_numbers[n-1];
            tlm = affine_mul(t, tlm);
            tm = tlm;
        } else if (value == "TD" && n >= 2) {
            double ty = geo_numbers[n-1];
            text_leading = -ty;
            AffineMat t;
            t.e = geo_numbers[n-2];
            t.f = ty;
            tlm = affine_mul(t, tlm);
            tm = tlm;
        } else if (value == "TL" && n >= 1) {
            text_leading = geo_numbers[n-1];
        } else if (value == "T*" || value == "'" || value == "\"") {
            // Move to the start of the next line by the current leading. For the
            // ' and " show operators this line move happens before the glyphs are
            // painted, so the recorded origin reflects the new line.
            AffineMat t;
            t.e = 0.0;
            t.f = -text_leading;
            tlm = affine_mul(t, tlm);
            tm = tlm;
        }

        geo_numbers.clear();
    }

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

    // Geometry tracking state (see updateGeometry).
    AffineMat ctm;                    // current transformation matrix
    std::vector<AffineMat> ctm_stack; // q/Q save-restore stack
    AffineMat tm;                     // text matrix
    AffineMat tlm;                    // text line matrix
    double text_leading;              // current leading (TL), used by T*/'/"
    std::vector<double> geo_numbers;  // numeric operands pending an operator
    int geo_array_depth;              // depth inside [...] arrays (e.g. TJ)
    int geo_dict_depth;               // depth inside <<...>> dictionaries
    std::map<int, MCIDInfo> mcid_info;

    bool in_marked_content;
    double last_x;
    double last_y;
    int last_link_idx;
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
                                           std::map<int, std::set<int>>& page_figure_mcids,
                                           std::map<int, std::map<int, MCIDInfo>>& page_mcid_info) {
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
        std::vector<QPDFObjectHandle> link_rects;
        for (auto& annot : pages[i].getAnnotations()) {
            QPDFObjectHandle annot_obj = annot.getObjectHandle();
            if (annot_obj.getKey("/Subtype").isName() && annot_obj.getKey("/Subtype").getName() == "/Link") {
                QPDFObjectHandle rect = annot_obj.getKey("/Rect");
                if (rect.isArray() && rect.getArrayNItems() == 4) {
                    link_rects.push_back(rect);
                }
            }
        }

        MCIDTokenFilter filter(link_rects);
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
        page_mcid_info[static_cast<int>(i)] = filter.getMCIDInfo();
    }

    return page_mcid_counts;
}
