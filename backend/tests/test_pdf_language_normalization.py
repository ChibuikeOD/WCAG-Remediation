from backend.pdf_accessibility import normalize_language_code as normalize_pdf_language_code
from backend.remediator import normalize_language_code as normalize_remediator_language_code


def test_remediator_language_normalizer_uses_pac_friendly_english_tag():
    assert normalize_remediator_language_code(None) == "en-US"
    assert normalize_remediator_language_code("English") == "en-US"
    assert normalize_remediator_language_code("en") == "en-US"
    assert normalize_remediator_language_code("en_us") == "en-US"


def test_pdf_accessibility_language_normalizer_matches_remediator_behavior():
    assert normalize_pdf_language_code(None) == "en-US"
    assert normalize_pdf_language_code("English") == "en-US"
    assert normalize_pdf_language_code("en") == "en-US"
    assert normalize_pdf_language_code("en_us") == "en-US"


def test_language_normalizers_preserve_non_english_codes():
    assert normalize_remediator_language_code("fr") == "fr"
    assert normalize_remediator_language_code("pt-br") == "pt-BR"
    assert normalize_pdf_language_code("fr") == "fr"
    assert normalize_pdf_language_code("pt-br") == "pt-BR"
