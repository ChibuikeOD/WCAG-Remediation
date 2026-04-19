"""
HTML Parser for WCAG Accessibility Analysis.

This module provides utilities for parsing and extracting accessibility-relevant
information from HTML documents, including support for fetching remote URLs
and using Playwright for computed styles.
"""
import re
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class HTMLParser:
    """
    Parser for HTML documents with accessibility-focused extraction.
    
    Provides methods for:
    - Parsing HTML strings and files
    - Extracting document metadata
    - Preparing DOM for accessibility analysis
    """
    
    def __init__(self, html_content: Optional[str] = None, file_path: Optional[Path] = None):
        """
        Initialize parser with HTML content or file path.
        
        Args:
            html_content: Raw HTML string
            file_path: Path to HTML file
        """
        self.html_content = html_content
        self.file_path = file_path
        self._soup: Optional[BeautifulSoup] = None
        
        if file_path and not html_content:
            self.html_content = file_path.read_text(encoding='utf-8')
    
    @property
    def soup(self) -> BeautifulSoup:
        """Lazy-load parsed BeautifulSoup document."""
        if self._soup is None and self.html_content:
            self._soup = BeautifulSoup(self.html_content, 'html5lib')
        return self._soup
    
    def get_document_metadata(self) -> Dict[str, Any]:
        """
        Extract document metadata relevant for accessibility.
        
        Returns metadata including:
        - title
        - language
        - charset
        - viewport settings
        - meta descriptions
        
        WCAG 2.4.2 Page Titled
        WCAG 3.1.1 Language of Page
        """
        metadata = {
            "title": None,
            "language": None,
            "charset": None,
            "viewport": None,
            "description": None,
            "has_main_landmark": False,
            "has_skip_link": False,
            "heading_structure": [],
        }
        
        if not self.soup:
            return metadata
        
        # Title - WCAG 2.4.2
        title_tag = self.soup.find('title')
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)
        
        # Language - WCAG 3.1.1
        html_tag = self.soup.find('html')
        if html_tag and html_tag.get('lang'):
            metadata["language"] = html_tag.get('lang')
        
        # Charset
        charset_meta = self.soup.find('meta', attrs={'charset': True})
        if charset_meta:
            metadata["charset"] = charset_meta.get('charset')
        else:
            content_type = self.soup.find('meta', attrs={'http-equiv': 'Content-Type'})
            if content_type and content_type.get('content'):
                match = re.search(r'charset=([^\s;]+)', content_type.get('content', ''))
                if match:
                    metadata["charset"] = match.group(1)
        
        # Viewport - WCAG 1.4.4 Resize Text, WCAG 1.4.10 Reflow
        viewport_meta = self.soup.find('meta', attrs={'name': 'viewport'})
        if viewport_meta:
            metadata["viewport"] = viewport_meta.get('content')
        
        # Description
        desc_meta = self.soup.find('meta', attrs={'name': 'description'})
        if desc_meta:
            metadata["description"] = desc_meta.get('content')
        
        # Main landmark - WCAG 2.4.1 Bypass Blocks
        main_element = self.soup.find('main') or self.soup.find(attrs={'role': 'main'})
        metadata["has_main_landmark"] = main_element is not None
        
        # Skip link - WCAG 2.4.1 Bypass Blocks
        skip_links = self.soup.find_all('a', href=re.compile(r'^#(main|content|skip)'))
        metadata["has_skip_link"] = len(skip_links) > 0
        
        # Heading structure - WCAG 1.3.1 Info and Relationships
        for level in range(1, 7):
            headings = self.soup.find_all(f'h{level}')
            for h in headings:
                metadata["heading_structure"].append({
                    "level": level,
                    "text": h.get_text(strip=True)[:100],
                    "id": h.get('id')
                })
        
        return metadata
    
    def get_images_info(self) -> List[Dict[str, Any]]:
        """
        Extract information about all images for accessibility review.
        
        WCAG 1.1.1 Non-text Content
        """
        images = []
        
        if not self.soup:
            return images
        
        for img in self.soup.find_all('img'):
            images.append({
                "src": img.get('src'),
                "alt": img.get('alt'),
                "has_alt": img.has_attr('alt'),
                "alt_is_empty": img.get('alt', None) == '',
                "role": img.get('role'),
                "aria_label": img.get('aria-label'),
                "aria_labelledby": img.get('aria-labelledby'),
                "is_decorative": img.get('role') in ['presentation', 'none'] or img.get('alt') == '',
                "width": img.get('width'),
                "height": img.get('height'),
            })
        
        return images
    
    def get_links_info(self) -> List[Dict[str, Any]]:
        """
        Extract information about all links for accessibility review.
        
        WCAG 2.4.4 Link Purpose (In Context)
        WCAG 2.4.9 Link Purpose (Link Only)
        """
        links = []
        
        if not self.soup:
            return links
        
        generic_link_patterns = [
            'click here', 'here', 'read more', 'more', 'learn more',
            'continue', 'details', 'link', 'this', 'this page'
        ]
        
        for link in self.soup.find_all('a', href=True):
            text = link.get_text(strip=True).lower()
            has_generic_text = any(pattern == text for pattern in generic_link_patterns)
            
            # Check for image-only links
            images = link.find_all('img')
            is_image_only = len(images) > 0 and not link.get_text(strip=True)
            
            links.append({
                "href": link.get('href'),
                "text": link.get_text(strip=True),
                "has_generic_text": has_generic_text,
                "aria_label": link.get('aria-label'),
                "aria_labelledby": link.get('aria-labelledby'),
                "title": link.get('title'),
                "is_image_only": is_image_only,
                "image_alt": images[0].get('alt') if is_image_only and images else None,
                "target": link.get('target'),
                "is_external": link.get('target') == '_blank',
            })
        
        return links
    
    def get_form_controls_info(self) -> List[Dict[str, Any]]:
        """
        Extract information about form controls for accessibility review.
        
        WCAG 1.3.1 Info and Relationships
        WCAG 1.3.5 Identify Input Purpose
        WCAG 3.3.2 Labels or Instructions
        """
        controls = []
        
        if not self.soup:
            return controls
        
        # Get all input, select, textarea elements
        form_elements = self.soup.find_all(['input', 'select', 'textarea'])
        
        for element in form_elements:
            element_id = element.get('id')
            element_name = element.get('name')
            element_type = element.get('type', 'text') if element.name == 'input' else element.name
            
            # Skip hidden and button types for label checks
            if element_type in ['hidden', 'submit', 'reset', 'button', 'image']:
                continue
            
            # Find associated label
            label = None
            if element_id:
                label = self.soup.find('label', attrs={'for': element_id})
            
            # Check for implicit label (input inside label)
            if not label:
                parent_label = element.find_parent('label')
                if parent_label:
                    label = parent_label
            
            controls.append({
                "tag": element.name,
                "type": element_type,
                "id": element_id,
                "name": element_name,
                "has_label": label is not None,
                "label_text": label.get_text(strip=True) if label else None,
                "aria_label": element.get('aria-label'),
                "aria_labelledby": element.get('aria-labelledby'),
                "placeholder": element.get('placeholder'),
                "required": element.has_attr('required'),
                "aria_required": element.get('aria-required'),
                "autocomplete": element.get('autocomplete'),
                "pattern": element.get('pattern'),
                "title": element.get('title'),
            })
        
        return controls
    
    def get_tables_info(self) -> List[Dict[str, Any]]:
        """
        Extract information about tables for accessibility review.
        
        WCAG 1.3.1 Info and Relationships
        """
        tables = []
        
        if not self.soup:
            return tables
        
        for table in self.soup.find_all('table'):
            # Check for headers
            headers = table.find_all('th')
            caption = table.find('caption')
            
            # Count rows and cells
            rows = table.find_all('tr')
            
            # Check if it's a layout table
            is_layout_table = table.get('role') == 'presentation' or table.get('role') == 'none'
            
            tables.append({
                "has_headers": len(headers) > 0,
                "header_count": len(headers),
                "has_caption": caption is not None,
                "caption_text": caption.get_text(strip=True) if caption else None,
                "aria_label": table.get('aria-label'),
                "aria_labelledby": table.get('aria-labelledby'),
                "is_layout_table": is_layout_table,
                "row_count": len(rows),
                "summary": table.get('summary'),  # Deprecated but still seen
            })
        
        return tables
    
    def get_landmarks_info(self) -> Dict[str, Any]:
        """
        Extract landmark region information.
        
        WCAG 1.3.6 Identify Purpose
        WCAG 2.4.1 Bypass Blocks
        """
        landmarks = {
            "banner": [],
            "navigation": [],
            "main": [],
            "complementary": [],
            "contentinfo": [],
            "search": [],
            "form": [],
            "region": [],
        }
        
        if not self.soup:
            return landmarks
        
        # Native HTML5 landmarks
        landmark_mapping = {
            'header': 'banner',
            'nav': 'navigation',
            'main': 'main',
            'aside': 'complementary',
            'footer': 'contentinfo',
        }
        
        for tag, role in landmark_mapping.items():
            elements = self.soup.find_all(tag)
            for el in elements:
                # Header and footer only count if not nested in article/section
                if tag in ['header', 'footer']:
                    parent = el.find_parent(['article', 'section'])
                    if parent:
                        continue
                
                landmarks[role].append({
                    "tag": tag,
                    "aria_label": el.get('aria-label'),
                    "aria_labelledby": el.get('aria-labelledby'),
                })
        
        # ARIA role-based landmarks
        for role in landmarks.keys():
            elements = self.soup.find_all(attrs={'role': role})
            for el in elements:
                landmarks[role].append({
                    "tag": el.name,
                    "aria_label": el.get('aria-label'),
                    "aria_labelledby": el.get('aria-labelledby'),
                })
        
        return landmarks
    
    def get_multimedia_info(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract information about multimedia elements.
        
        WCAG 1.2.1 - 1.2.9 Time-based Media
        WCAG 1.4.2 Audio Control
        """
        multimedia = {
            "audio": [],
            "video": [],
            "iframes": [],
        }
        
        if not self.soup:
            return multimedia
        
        # Audio elements
        for audio in self.soup.find_all('audio'):
            tracks = audio.find_all('track')
            multimedia["audio"].append({
                "src": audio.get('src'),
                "has_controls": audio.has_attr('controls'),
                "autoplay": audio.has_attr('autoplay'),
                "has_tracks": len(tracks) > 0,
                "aria_label": audio.get('aria-label'),
            })
        
        # Video elements - WCAG 1.2.2 Captions, WCAG 1.2.5 Audio Description
        for video in self.soup.find_all('video'):
            tracks = video.find_all('track')
            captions = [t for t in tracks if t.get('kind') in ['captions', 'subtitles']]
            descriptions = [t for t in tracks if t.get('kind') == 'descriptions']
            
            multimedia["video"].append({
                "src": video.get('src'),
                "has_controls": video.has_attr('controls'),
                "autoplay": video.has_attr('autoplay'),
                "muted": video.has_attr('muted'),
                "has_captions": len(captions) > 0,
                "has_descriptions": len(descriptions) > 0,
                "aria_label": video.get('aria-label'),
                "poster": video.get('poster'),
            })
        
        # Iframes - WCAG 4.1.2 Name, Role, Value
        for iframe in self.soup.find_all('iframe'):
            multimedia["iframes"].append({
                "src": iframe.get('src'),
                "title": iframe.get('title'),
                "has_title": iframe.has_attr('title'),
                "aria_label": iframe.get('aria-label'),
            })
        
        return multimedia
    
    def get_interactive_elements_info(self) -> List[Dict[str, Any]]:
        """
        Extract information about interactive elements.
        
        WCAG 2.1.1 Keyboard
        WCAG 2.5.5 Target Size
        """
        interactive = []
        
        if not self.soup:
            return interactive
        
        # Buttons
        for button in self.soup.find_all('button'):
            interactive.append({
                "type": "button",
                "tag": "button",
                "text": button.get_text(strip=True),
                "aria_label": button.get('aria-label'),
                "disabled": button.has_attr('disabled'),
                "tabindex": button.get('tabindex'),
            })
        
        # Elements with button role
        for el in self.soup.find_all(attrs={'role': 'button'}):
            if el.name != 'button':
                interactive.append({
                    "type": "custom_button",
                    "tag": el.name,
                    "text": el.get_text(strip=True),
                    "aria_label": el.get('aria-label'),
                    "tabindex": el.get('tabindex'),
                    "has_tabindex": el.has_attr('tabindex'),
                })
        
        # Elements with click handlers
        for el in self.soup.find_all(attrs={'onclick': True}):
            if el.name not in ['a', 'button', 'input']:
                interactive.append({
                    "type": "clickable",
                    "tag": el.name,
                    "text": el.get_text(strip=True)[:50],
                    "tabindex": el.get('tabindex'),
                    "has_tabindex": el.has_attr('tabindex'),
                    "role": el.get('role'),
                })
        
        return interactive





