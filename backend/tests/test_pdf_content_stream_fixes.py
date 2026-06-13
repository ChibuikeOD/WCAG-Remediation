from pathlib import Path

import pikepdf

from backend.pdf_remediator_fixes import fix_content_stream_operator_states


PATH_CONSTRUCTION_OPERATORS = {"m", "l", "c", "v", "y", "h", "re"}
PATH_ENDING_OPERATORS = {
    "S",
    "s",
    "f",
    "F",
    "f*",
    "B",
    "B*",
    "b",
    "b*",
    "sh",
    "n",
}


def _write_pdf_with_bad_path_color_state(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(612, 792))
        content = b"/Artifact BMC 60 682 m 552 682 l /DeviceRGB CS 0 0 0 SC S EMC"
        page.obj["/Contents"] = pdf.make_stream(content)
        pdf.save(path)


def _count_color_space_operators_inside_paths(path: Path) -> int:
    count = 0
    with pikepdf.open(path) as pdf:
        for page in pdf.pages:
            in_path = False
            for instruction in pikepdf.parse_content_stream(page):
                operator = str(instruction.operator)
                if operator in PATH_CONSTRUCTION_OPERATORS:
                    in_path = True
                elif operator in PATH_ENDING_OPERATORS:
                    in_path = False
                elif operator == "CS" and in_path:
                    count += 1
    return count


def test_fix_content_stream_operator_states_moves_color_space_before_open_path(tmp_path):
    pdf_path = tmp_path / "bad-path-state.pdf"
    _write_pdf_with_bad_path_color_state(pdf_path)

    assert _count_color_space_operators_inside_paths(pdf_path) == 1

    result = fix_content_stream_operator_states(pdf_path)

    assert result["success"] is True
    assert "1" in result["new_value"]
    assert _count_color_space_operators_inside_paths(pdf_path) == 0
