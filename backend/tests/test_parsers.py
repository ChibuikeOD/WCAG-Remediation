"""
Unit tests for HTML and PDF parsers.
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.parsers.html_parser import HTMLParser


class TestHTMLParser:
    """Tests for the HTML parser."""
    
    def test_extract_title(self):
        """Test title extraction - WCAG 2.4.2"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>My Page Title</title></head>
        <body></body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        metadata = parser.get_document_metadata()
        
        assert metadata['title'] == 'My Page Title'
    
    def test_extract_language(self):
        """Test language extraction - WCAG 3.1.1"""
        html = """
        <!DOCTYPE html>
        <html lang="es">
        <head><title>Test</title></head>
        <body></body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        metadata = parser.get_document_metadata()
        
        assert metadata['language'] == 'es'
    
    def test_detect_main_landmark(self):
        """Test main landmark detection - WCAG 2.4.1"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <main>
                <h1>Content</h1>
            </main>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        metadata = parser.get_document_metadata()
        
        assert metadata['has_main_landmark'] is True
    
    def test_detect_skip_link(self):
        """Test skip link detection - WCAG 2.4.1"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <a href="#main">Skip to main content</a>
            <nav>Navigation</nav>
            <main id="main">Content</main>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        metadata = parser.get_document_metadata()
        
        assert metadata['has_skip_link'] is True
    
    def test_heading_structure(self):
        """Test heading structure extraction - WCAG 1.3.1"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <h1>Main Title</h1>
            <h2>Section 1</h2>
            <h3>Subsection</h3>
            <h2>Section 2</h2>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        metadata = parser.get_document_metadata()
        
        headings = metadata['heading_structure']
        assert len(headings) == 4
        assert headings[0]['level'] == 1
        assert headings[0]['text'] == 'Main Title'
    
    def test_images_info_missing_alt(self):
        """Test image info extraction - WCAG 1.1.1"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <img src="image1.jpg">
            <img src="image2.jpg" alt="Description">
            <img src="image3.jpg" alt="">
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        images = parser.get_images_info()
        
        assert len(images) == 3
        assert images[0]['has_alt'] is False
        assert images[1]['has_alt'] is True
        assert images[1]['alt'] == 'Description'
        assert images[2]['alt_is_empty'] is True
    
    def test_links_info_generic_text(self):
        """Test link info extraction - WCAG 2.4.4"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <a href="/page1">Click here</a>
            <a href="/page2">Read our documentation</a>
            <a href="/page3">More</a>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        links = parser.get_links_info()
        
        assert len(links) == 3
        assert links[0]['has_generic_text'] is True  # "Click here"
        assert links[1]['has_generic_text'] is False
        assert links[2]['has_generic_text'] is True  # "More"
    
    def test_form_controls_labels(self):
        """Test form control info extraction - WCAG 3.3.2"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <form>
                <label for="name">Name</label>
                <input type="text" id="name">
                
                <input type="email" id="email">
                
                <input type="hidden" name="token" value="abc">
            </form>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        controls = parser.get_form_controls_info()
        
        # Should have 2 controls (hidden is excluded)
        assert len(controls) == 2
        
        # Name input should have label
        name_input = [c for c in controls if c['id'] == 'name'][0]
        assert name_input['has_label'] is True
        assert name_input['label_text'] == 'Name'
        
        # Email input should not have label
        email_input = [c for c in controls if c['id'] == 'email'][0]
        assert email_input['has_label'] is False
    
    def test_tables_info(self):
        """Test table info extraction - WCAG 1.3.1"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <table>
                <caption>User Data</caption>
                <tr><th>Name</th><th>Age</th></tr>
                <tr><td>John</td><td>30</td></tr>
            </table>
            
            <table role="presentation">
                <tr><td>Layout content</td></tr>
            </table>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        tables = parser.get_tables_info()
        
        assert len(tables) == 2
        
        # Data table
        assert tables[0]['has_headers'] is True
        assert tables[0]['has_caption'] is True
        assert tables[0]['is_layout_table'] is False
        
        # Layout table
        assert tables[1]['is_layout_table'] is True
    
    def test_landmarks_info(self):
        """Test landmark extraction - WCAG 1.3.6"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <header>Header</header>
            <nav aria-label="Main">Navigation</nav>
            <nav aria-label="Footer">Footer Nav</nav>
            <main>Content</main>
            <aside>Sidebar</aside>
            <footer>Footer</footer>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        landmarks = parser.get_landmarks_info()
        
        assert len(landmarks['banner']) == 1
        assert len(landmarks['navigation']) == 2
        assert len(landmarks['main']) == 1
        assert len(landmarks['complementary']) == 1
        assert len(landmarks['contentinfo']) == 1
    
    def test_multimedia_video_captions(self):
        """Test video caption detection - WCAG 1.2.2"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <video controls>
                <source src="video.mp4" type="video/mp4">
                <track kind="captions" src="captions.vtt" srclang="en">
            </video>
            
            <video src="no-captions.mp4" controls></video>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        multimedia = parser.get_multimedia_info()
        
        assert len(multimedia['video']) == 2
        assert multimedia['video'][0]['has_captions'] is True
        assert multimedia['video'][1]['has_captions'] is False
    
    def test_interactive_elements(self):
        """Test interactive element detection - WCAG 2.1.1"""
        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body>
            <button>Click me</button>
            <div role="button">Custom button</div>
            <div role="button" tabindex="0">Accessible custom button</div>
            <span onclick="doSomething()">Clickable span</span>
        </body>
        </html>
        """
        parser = HTMLParser(html_content=html)
        interactive = parser.get_interactive_elements_info()
        
        buttons = [i for i in interactive if i['type'] == 'button']
        custom_buttons = [i for i in interactive if i['type'] == 'custom_button']
        clickable = [i for i in interactive if i['type'] == 'clickable']
        
        assert len(buttons) == 1
        assert len(custom_buttons) == 2
        assert len(clickable) == 1
        
        # Check tabindex detection
        accessible_btn = [b for b in custom_buttons if b['has_tabindex']][0]
        assert accessible_btn['tabindex'] == '0'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])





