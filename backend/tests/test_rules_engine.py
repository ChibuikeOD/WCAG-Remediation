"""
Unit tests for the WCAG Rules Engine.

Tests cover:
- Rule loading from JSONC files
- Selector-based checks
- Contrast calculations
- HTML analysis
"""
import pytest
from bs4 import BeautifulSoup
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.rules_engine import RulesEngine, ColorUtils, parse_jsonc
from backend.models import WCAGLevel, WCAGPrinciple, DocumentInfo, IssueStatus, Severity


class TestColorUtils:
    """Tests for color contrast calculations - WCAG 1.4.3"""
    
    def test_hex_to_rgb_6_char(self):
        """Test 6-character hex color conversion."""
        assert ColorUtils.hex_to_rgb('#ffffff') == (255, 255, 255)
        assert ColorUtils.hex_to_rgb('#000000') == (0, 0, 0)
        assert ColorUtils.hex_to_rgb('#ff0000') == (255, 0, 0)
    
    def test_hex_to_rgb_3_char(self):
        """Test 3-character hex color conversion."""
        assert ColorUtils.hex_to_rgb('#fff') == (255, 255, 255)
        assert ColorUtils.hex_to_rgb('#000') == (0, 0, 0)
        assert ColorUtils.hex_to_rgb('#f00') == (255, 0, 0)
    
    def test_relative_luminance_white(self):
        """Test relative luminance of white."""
        luminance = ColorUtils.rgb_to_relative_luminance(255, 255, 255)
        assert abs(luminance - 1.0) < 0.001
    
    def test_relative_luminance_black(self):
        """Test relative luminance of black."""
        luminance = ColorUtils.rgb_to_relative_luminance(0, 0, 0)
        assert abs(luminance - 0.0) < 0.001
    
    def test_contrast_ratio_black_white(self):
        """Test maximum contrast ratio (black on white)."""
        ratio = ColorUtils.calculate_contrast_ratio('#000000', '#ffffff')
        assert abs(ratio - 21.0) < 0.1  # Maximum contrast is 21:1
    
    def test_contrast_ratio_same_color(self):
        """Test minimum contrast ratio (same color)."""
        ratio = ColorUtils.calculate_contrast_ratio('#808080', '#808080')
        assert abs(ratio - 1.0) < 0.1  # Same color has 1:1 ratio
    
    def test_contrast_ratio_aa_pass(self):
        """Test AA-passing contrast ratio (4.5:1 minimum)."""
        # Dark gray on white should pass AA
        ratio = ColorUtils.calculate_contrast_ratio('#595959', '#ffffff')
        assert ratio >= 4.5
    
    def test_contrast_ratio_aa_fail(self):
        """Test AA-failing contrast ratio."""
        # Light gray on white should fail AA
        ratio = ColorUtils.calculate_contrast_ratio('#999999', '#ffffff')
        assert ratio < 4.5
    
    def test_is_large_text_18pt(self):
        """Test large text detection at 18pt."""
        assert ColorUtils.is_large_text(18, is_bold=False) is True
        assert ColorUtils.is_large_text(17, is_bold=False) is False
    
    def test_is_large_text_14pt_bold(self):
        """Test large text detection at 14pt bold."""
        assert ColorUtils.is_large_text(14, is_bold=True) is True
        assert ColorUtils.is_large_text(13, is_bold=True) is False


class TestRulesEngine:
    """Tests for the main Rules Engine functionality."""
    
    @pytest.fixture
    def engine(self):
        """Create a RulesEngine instance with test rules."""
        rules_dir = Path(__file__).parent.parent.parent / 'rules'
        return RulesEngine(rules_dir=rules_dir)
    
    def test_rules_loaded(self, engine):
        """Test that rules are loaded from all principle files."""
        all_rules = engine.get_all_rules()
        assert len(all_rules) > 0
        
        # Check all principles are loaded
        assert 'perceivable' in engine.rules
        assert 'operable' in engine.rules
        assert 'understandable' in engine.rules
        assert 'robust' in engine.rules
    
    def test_get_rules_by_level_a(self, engine):
        """Test filtering rules by Level A."""
        rules = engine.get_rules_by_level(WCAGLevel.A, include_lower=False)
        assert all(r.wcag_level == WCAGLevel.A for r in rules)
    
    def test_get_rules_by_level_aa_includes_a(self, engine):
        """Test that Level AA includes Level A rules."""
        rules = engine.get_rules_by_level(WCAGLevel.AA, include_lower=True)
        levels = {r.wcag_level for r in rules}
        assert WCAGLevel.A in levels
        assert WCAGLevel.AA in levels
    
    def test_get_rule_by_id(self, engine):
        """Test retrieving a specific rule by ID."""
        # WCAG 1.1.1 Non-text Content
        rule = engine.get_rule_by_id('1.1.1')
        assert rule is not None
        assert rule.name == 'Non-text Content'
        assert rule.wcag_level == WCAGLevel.A
    
    def test_get_rule_by_id_not_found(self, engine):
        """Test retrieving a non-existent rule."""
        rule = engine.get_rule_by_id('99.99.99')
        assert rule is None
    
    def test_get_automatable_rules(self, engine):
        """Test filtering for automatable rules."""
        rules = engine.get_automatable_rules()
        assert all(r.automatable for r in rules)
        assert len(rules) > 0
    
    def test_get_rules_by_tag(self, engine):
        """Test filtering rules by tag."""
        rules = engine.get_rules_by_tag('images')
        assert len(rules) > 0
        assert all('images' in r.tags for r in rules)

    def test_selector_check_evaluates_supported_has_selector(self, engine):
        """Supported :has() selectors should run during static analysis."""
        rule = engine.get_rule_by_id("1.3.1")
        check = next(
            item for item in rule.selector_checks
            if item.selector.startswith("table:not(:has(th))")
        )
        soup = BeautifulSoup(
            "<table><tr><td>Name</td></tr></table>",
            "html5lib",
        )

        issues = engine._check_selector(
            soup,
            check,
            rule,
            WCAGPrinciple.PERCEIVABLE,
        )

        assert len(issues) == 1
        assert "header" in issues[0].message.lower()


class TestHTMLAnalysis:
    """Tests for HTML accessibility analysis."""
    
    @pytest.fixture
    def engine(self):
        """Create a RulesEngine instance."""
        rules_dir = Path(__file__).parent.parent.parent / 'rules'
        return RulesEngine(rules_dir=rules_dir)
    
    @pytest.fixture
    def doc_info(self):
        """Create test document info."""
        return DocumentInfo(
            filename='test.html',
            file_type='html'
        )
    
    def test_missing_alt_attribute(self, engine, doc_info):
        """
        Test detection of missing alt attribute.
        WCAG 1.1.1 Non-text Content
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <img src="image.jpg">
        </body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        # Should detect missing alt
        alt_issues = [i for i in report.all_issues if '1.1.1' in i.rule_id and 'alt' in i.message.lower()]
        assert len(alt_issues) > 0
    
    def test_image_with_alt_passes(self, engine, doc_info):
        """
        Test that images with alt text pass.
        WCAG 1.1.1 Non-text Content
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <img src="image.jpg" alt="A beautiful sunset">
        </body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        # Should not have missing alt issues
        alt_issues = [i for i in report.all_issues 
                      if i.rule_id == '1.1.1' and 'missing alt' in i.message.lower()]
        assert len(alt_issues) == 0
    
    def test_missing_lang_attribute(self, engine, doc_info):
        """
        Test detection of missing lang attribute.
        WCAG 3.1.1 Language of Page
        """
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test</title></head>
        <body><p>Hello</p></body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        lang_issues = [i for i in report.all_issues if '3.1.1' in i.rule_id]
        assert len(lang_issues) > 0
    
    def test_lang_attribute_present(self, engine, doc_info):
        """
        Test that pages with lang attribute pass.
        WCAG 3.1.1 Language of Page
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body><p>Hello</p></body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        # Should extract language
        assert report.document.language == 'en'
    
    def test_empty_title(self, engine, doc_info):
        """
        Test detection of empty page title.
        WCAG 2.4.2 Page Titled
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title></title></head>
        <body><p>Hello</p></body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        title_issues = [i for i in report.all_issues if '2.4.2' in i.rule_id]
        assert len(title_issues) > 0
    
    def test_input_without_label(self, engine, doc_info):
        """
        Test detection of form inputs without labels.
        WCAG 1.3.1 Info and Relationships
        WCAG 3.3.2 Labels or Instructions
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test Form</title></head>
        <body>
            <form>
                <input type="text" name="username">
            </form>
        </body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        # Should detect missing label
        label_issues = [i for i in report.all_issues if 'label' in i.message.lower()]
        assert len(label_issues) > 0
    
    def test_table_without_headers(self, engine, doc_info):
        """
        Test detection of data tables without headers.
        WCAG 1.3.1 Info and Relationships
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test Table</title></head>
        <body>
            <table>
                <tr><td>Name</td><td>Age</td></tr>
                <tr><td>John</td><td>30</td></tr>
            </table>
        </body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        table_issues = [i for i in report.all_issues 
                        if 'table' in i.message.lower() and 'header' in i.message.lower()]
        assert len(table_issues) > 0
    
    def test_positive_tabindex(self, engine, doc_info):
        """
        Test detection of positive tabindex values.
        WCAG 2.4.3 Focus Order
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <button tabindex="5">Click me</button>
        </body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        tabindex_issues = [i for i in report.all_issues if 'tabindex' in i.message.lower()]
        assert len(tabindex_issues) > 0
    
    def test_video_without_captions(self, engine, doc_info):
        """
        Test detection of videos without captions.
        WCAG 1.2.2 Captions (Prerecorded)
        """
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test Video</title></head>
        <body>
            <video src="video.mp4" controls></video>
        </body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        # Should have warning about captions
        caption_issues = [i for i in report.all_issues 
                          if 'caption' in i.message.lower() or 'caption' in i.fix_suggestion.lower()]
        assert len(caption_issues) > 0
    
    def test_report_structure(self, engine, doc_info):
        """Test that report has correct structure."""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body><p>Hello World</p></body>
        </html>
        """
        report = engine.analyze_html(html, doc_info)
        
        # Verify report structure
        assert report.document is not None
        assert report.wcag_version == '2.2'
        assert report.target_level is not None
        assert isinstance(report.all_issues, list)
        assert isinstance(report.issues_by_principle, dict)
        assert report.processing_time_ms is not None
        assert report.processing_time_ms >= 0


class TestJSONCParsing:
    """Tests for JSONC file parsing."""
    
    def test_parse_jsonc_removes_comments(self):
        """Test that JSONC parser removes comments."""
        # Create a temporary JSONC content
        jsonc_content = '''
        {
            // This is a comment
            "key": "value",
            /* Multi-line
               comment */
            "number": 42
        }
        '''
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonc', delete=False) as f:
            f.write(jsonc_content)
            f.flush()
            
            result = parse_jsonc(Path(f.name))
            
            assert result['key'] == 'value'
            assert result['number'] == 42


if __name__ == '__main__':
    pytest.main([__file__, '-v'])





