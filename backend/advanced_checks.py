"""
Advanced WCAG Accessibility Checks Module

This module provides enhanced implementations for complex accessibility checks
that require browser automation, computed styles, or advanced analysis:

- Contrast checking (WCAG 1.4.3, 1.4.6, 1.4.11)
- Target size checking (WCAG 2.5.5, 2.5.8)
- Focus appearance checking (WCAG 2.4.7, 2.4.11, 2.4.13)
- Link text quality checking (WCAG 2.4.4, 2.4.9)
- Label in name checking (WCAG 2.5.3)
- Duplicate ID checking (WCAG 4.1.1)
- Reflow checking (WCAG 1.4.10)
- Text spacing checking (WCAG 1.4.12)
- Content on hover/focus (WCAG 1.4.13)

All checks return structured CheckResult objects for integration with
the rules engine and report generation.
"""

import asyncio
import logging
import re
import math
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import Counter

logger = logging.getLogger(__name__)

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Page, Browser, ElementHandle
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.warning("Playwright not available - browser-based checks will be limited")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CheckResult:
    """
    Result of an accessibility check.
    
    Attributes:
        rule_id: WCAG success criterion ID (e.g., "1.4.3")
        check_type: Type of check performed (e.g., "contrast")
        passed: Whether the check passed
        details: Human-readable description of the result
        element_selector: CSS selector for the affected element
        element_html: HTML snippet of the affected element
        evidence: Additional data supporting the result
        automatable: Whether this check can be fully automated
        fix_suggestion: Recommended fix for the issue
        severity: Issue severity (error, warning, info)
    """
    rule_id: str
    check_type: str
    passed: bool
    details: str
    element_selector: Optional[str] = None
    element_html: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    automatable: bool = True
    fix_suggestion: Optional[str] = None
    severity: str = "error"


class ContrastLevel(Enum):
    """WCAG contrast conformance levels."""
    AA_NORMAL = 4.5   # Normal text Level AA
    AA_LARGE = 3.0    # Large text Level AA
    AAA_NORMAL = 7.0  # Normal text Level AAA
    AAA_LARGE = 4.5   # Large text Level AAA
    NON_TEXT = 3.0    # Non-text contrast (UI components)


class TargetSizeLevel(Enum):
    """WCAG target size requirements."""
    AA_MINIMUM = 24   # 2.5.8 Target Size (Minimum)
    AAA_ENHANCED = 44 # 2.5.5 Target Size (Enhanced)


# =============================================================================
# Color Utilities
# =============================================================================

class ColorUtils:
    """
    Utility class for color manipulation and contrast calculations.
    
    Implements WCAG 2.1 relative luminance and contrast ratio formulas:
    https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
    https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
    """
    
    # Extended named colors mapping
    NAMED_COLORS = {
        'black': (0, 0, 0, 1.0),
        'white': (255, 255, 255, 1.0),
        'red': (255, 0, 0, 1.0),
        'green': (0, 128, 0, 1.0),
        'blue': (0, 0, 255, 1.0),
        'yellow': (255, 255, 0, 1.0),
        'cyan': (0, 255, 255, 1.0),
        'magenta': (255, 0, 255, 1.0),
        'gray': (128, 128, 128, 1.0),
        'grey': (128, 128, 128, 1.0),
        'silver': (192, 192, 192, 1.0),
        'maroon': (128, 0, 0, 1.0),
        'olive': (128, 128, 0, 1.0),
        'lime': (0, 255, 0, 1.0),
        'aqua': (0, 255, 255, 1.0),
        'teal': (0, 128, 128, 1.0),
        'navy': (0, 0, 128, 1.0),
        'fuchsia': (255, 0, 255, 1.0),
        'purple': (128, 0, 128, 1.0),
        'orange': (255, 165, 0, 1.0),
        'transparent': (0, 0, 0, 0.0),
    }
    
    @staticmethod
    def parse_color(color_str: str) -> Optional[Tuple[int, int, int, float]]:
        """
        Parse CSS color string to RGBA tuple.
        
        Supports:
        - rgb(r, g, b) and rgba(r, g, b, a)
        - Hex: #RGB, #RRGGBB, #RRGGBBAA
        - Named colors
        
        Args:
            color_str: CSS color value
            
        Returns:
            Tuple of (red, green, blue, alpha) or None if unparseable
        """
        if not color_str:
            return None
        
        color_str = color_str.strip().lower()
        
        # Handle rgb/rgba
        rgba_match = re.match(
            r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)',
            color_str
        )
        if rgba_match:
            r = int(rgba_match.group(1))
            g = int(rgba_match.group(2))
            b = int(rgba_match.group(3))
            a = float(rgba_match.group(4)) if rgba_match.group(4) else 1.0
            return (r, g, b, a)
        
        # Handle hex
        hex_match = re.match(r'#([0-9a-f]{3,8})$', color_str)
        if hex_match:
            hex_val = hex_match.group(1)
            if len(hex_val) == 3:
                r = int(hex_val[0] * 2, 16)
                g = int(hex_val[1] * 2, 16)
                b = int(hex_val[2] * 2, 16)
                return (r, g, b, 1.0)
            elif len(hex_val) == 6:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return (r, g, b, 1.0)
            elif len(hex_val) == 8:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                a = int(hex_val[6:8], 16) / 255
                return (r, g, b, a)
        
        # Handle named colors
        if color_str in ColorUtils.NAMED_COLORS:
            return ColorUtils.NAMED_COLORS[color_str]
        
        return None
    
    @staticmethod
    def get_relative_luminance(r: int, g: int, b: int) -> float:
        """
        Calculate relative luminance per WCAG 2.1.
        
        Formula: L = 0.2126 * R + 0.7152 * G + 0.0722 * B
        where R, G, B are adjusted sRGB values.
        
        https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
        """
        def adjust(c: int) -> float:
            c_srgb = c / 255.0
            if c_srgb <= 0.03928:
                return c_srgb / 12.92
            return ((c_srgb + 0.055) / 1.055) ** 2.4
        
        return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)
    
    @staticmethod
    def calculate_contrast_ratio(
        fg_color: Tuple[int, int, int, float],
        bg_color: Tuple[int, int, int, float]
    ) -> float:
        """
        Calculate contrast ratio between foreground and background colors.
        
        Formula: (L1 + 0.05) / (L2 + 0.05) where L1 > L2
        
        Handles alpha compositing for semi-transparent foregrounds.
        
        https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
        """
        fg_r, fg_g, fg_b, fg_a = fg_color
        bg_r, bg_g, bg_b, bg_a = bg_color
        
        # Alpha composite foreground onto background
        if fg_a < 1.0:
            fg_r = int(fg_r * fg_a + bg_r * (1 - fg_a))
            fg_g = int(fg_g * fg_a + bg_g * (1 - fg_a))
            fg_b = int(fg_b * fg_a + bg_b * (1 - fg_a))
        
        l1 = ColorUtils.get_relative_luminance(fg_r, fg_g, fg_b)
        l2 = ColorUtils.get_relative_luminance(bg_r, bg_g, bg_b)
        
        lighter = max(l1, l2)
        darker = min(l1, l2)
        
        return (lighter + 0.05) / (darker + 0.05)
    
    @staticmethod
    def is_large_text(font_size_px: float, is_bold: bool) -> bool:
        """
        Determine if text qualifies as "large" per WCAG.
        
        Large text is:
        - 18pt (24px) or larger, OR
        - 14pt (18.67px) or larger AND bold
        
        Args:
            font_size_px: Font size in CSS pixels
            is_bold: Whether the text is bold (font-weight >= 700)
        """
        if font_size_px >= 24:
            return True
        if font_size_px >= 18.67 and is_bold:
            return True
        return False
    
    @staticmethod
    def suggest_contrast_fix(
        current_ratio: float,
        required_ratio: float,
        fg_color: Tuple[int, int, int, float],
        bg_color: Tuple[int, int, int, float]
    ) -> str:
        """Generate a suggestion for fixing contrast issues."""
        fg_luminance = ColorUtils.get_relative_luminance(fg_color[0], fg_color[1], fg_color[2])
        bg_luminance = ColorUtils.get_relative_luminance(bg_color[0], bg_color[1], bg_color[2])
        
        if fg_luminance > bg_luminance:
            return f"Darken the text color or lighten the background. Current ratio: {current_ratio:.2f}:1, Required: {required_ratio}:1"
        else:
            return f"Lighten the text color or darken the background. Current ratio: {current_ratio:.2f}:1, Required: {required_ratio}:1"


# =============================================================================
# Link Text Analysis
# =============================================================================

class LinkTextAnalyzer:
    """
    Analyzes link text for accessibility issues.
    
    Detects vague, non-descriptive, or ambiguous link text that fails
    WCAG 2.4.4 (Link Purpose in Context) and 2.4.9 (Link Purpose - Link Only).
    """
    
    # Vague/non-informative link texts to flag
    VAGUE_PHRASES: Set[str] = {
        'click here', 'click', 'here', 'more', 'read more', 'learn more',
        'info', 'information', 'details', 'more details', 'link', 'this link',
        'this', 'that', 'go', 'continue', 'next', 'previous', 'back', 'forward',
        'page', 'see more', 'view more', 'view', 'find out more', 'find out',
        'download', 'open', 'start', 'begin', 'press here', 'tap here',
        'continue reading', 'read on', 'show more', 'see all', 'view all',
        'pdf', 'document', 'file', 'attachment',
    }
    
    # Regex patterns for potentially vague links
    VAGUE_PATTERNS = [
        r'^click\s*(here)?$',
        r'^read\s*more$',
        r'^learn\s*more$',
        r'^more\s*$',
        r'^here\s*$',
        r'^link\s*$',
        r'^\d+$',           # Just a number
        r'^[→←↑↓▶◀►◄]+$',  # Just arrows
        r'^\.{2,}$',        # Just dots
    ]
    
    # Minimum meaningful length
    MIN_LENGTH = 3
    
    @classmethod
    def is_vague(cls, link_text: str) -> Tuple[bool, str]:
        """
        Check if link text is vague or non-informative.
        
        Args:
            link_text: The text content of the link
            
        Returns:
            Tuple of (is_vague, reason)
        """
        if not link_text:
            return True, "Empty link text"
        
        text = link_text.strip().lower()
        
        # Too short
        if len(text) < cls.MIN_LENGTH:
            return True, f"Link text too short ({len(text)} characters)"
        
        # Exact match to vague phrase
        if text in cls.VAGUE_PHRASES:
            return True, f"Vague phrase: '{text}'"
        
        # Remove punctuation and check again
        cleaned = re.sub(r'[^\w\s]', '', text)
        if cleaned in cls.VAGUE_PHRASES:
            return True, f"Vague phrase: '{cleaned}'"
        
        # Check regex patterns
        for pattern in cls.VAGUE_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                return True, f"Matches vague pattern"
        
        # URL as link text (not descriptive)
        if re.match(r'^https?://', text) or re.match(r'^www\.', text):
            return True, "URL used as link text (not descriptive)"
        
        # Email as sole link text
        if re.match(r'^[\w.+-]+@[\w.-]+\.\w+$', text):
            return True, "Email address as link text (consider adding context)"
        
        return False, "Link text appears descriptive"
    
    @classmethod
    def get_quality_score(cls, link_text: str) -> float:
        """
        Calculate a quality score for link text (0.0 to 1.0).
        
        Higher scores indicate better link text quality.
        """
        if not link_text:
            return 0.0
        
        text = link_text.strip().lower()
        score = 1.0
        
        # Penalize short text
        if len(text) < 10:
            score -= 0.2
        if len(text) < 5:
            score -= 0.3
        
        # Penalize vague phrases
        for phrase in cls.VAGUE_PHRASES:
            if phrase in text:
                score -= 0.4
                break
        
        # Penalize all caps (accessibility concern)
        if link_text.isupper() and len(link_text) > 4:
            score -= 0.1
        
        # Bonus for verb + noun pattern (action-oriented)
        if re.search(r'\b(view|see|read|download|get|learn|explore)\s+\w+', text):
            score += 0.1
        
        return max(0.0, min(1.0, score))
    
    @classmethod
    def suggest_improvement(cls, link_text: str, href: str = "") -> str:
        """Suggest an improved link text based on context."""
        if not link_text or link_text.lower() in cls.VAGUE_PHRASES:
            # Try to infer from href
            if href:
                # Extract meaningful part from URL
                path = href.split('/')[-1].split('?')[0].split('#')[0]
                path = re.sub(r'[-_]', ' ', path)
                path = re.sub(r'\.\w+$', '', path)  # Remove extension
                if path and len(path) > 2:
                    return f"Consider: '{path.title()}' or describe the destination"
            return "Use descriptive text indicating the link's destination or purpose"
        return "Link text is acceptable"


# =============================================================================
# Browser-Based Checks
# =============================================================================

class AdvancedBrowserChecker:
    """
    Performs advanced accessibility checks using Playwright browser automation.
    
    These checks require actual browser rendering to compute styles,
    measure elements, and interact with focus states.
    """
    
    def __init__(self):
        self._browser: Optional[Browser] = None
        self._playwright = None
        self._page: Optional[Page] = None
    
    async def initialize(self, headless: bool = True):
        """Initialize Playwright browser instance."""
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install")
        
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        logger.info("Advanced browser checker initialized")
    
    async def close(self):
        """Clean up browser resources."""
        if self._page:
            await self._page.close()
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Advanced browser checker closed")
    
    async def _get_page(self) -> Page:
        """Get or create a page instance."""
        if not self._browser:
            await self.initialize()
        if not self._page:
            self._page = await self._browser.new_page()
        return self._page
    
    async def load_html(self, html_content: str):
        """Load HTML content into the browser page."""
        page = await self._get_page()
        await page.set_content(html_content, wait_until='domcontentloaded')
    
    async def load_url(self, url: str, timeout: int = 30000):
        """Navigate to a URL."""
        page = await self._get_page()
        await page.goto(url, timeout=timeout, wait_until='domcontentloaded')
    
    # =========================================================================
    # Contrast Check (WCAG 1.4.3, 1.4.6)
    # =========================================================================
    
    async def check_contrast(
        self,
        level: str = "AA",
        max_elements: int = 100
    ) -> List[CheckResult]:
        """
        Check text contrast ratios against WCAG requirements.
        
        Args:
            level: "AA" (4.5:1/3:1) or "AAA" (7:1/4.5:1)
            max_elements: Maximum elements to check (for performance)
            
        Returns:
            List of CheckResult objects for failing elements
        """
        results = []
        page = await self._get_page()
        
        # JavaScript to extract text elements with computed styles
        js_code = """
        (maxElements) => {
            const results = [];
            const seen = new Set();
            
            // Walk text nodes
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );
            
            let node;
            while ((node = walker.nextNode()) && results.length < maxElements) {
                const text = node.textContent.trim();
                if (text.length < 2) continue;
                
                const element = node.parentElement;
                if (!element || seen.has(element)) continue;
                seen.add(element);
                
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                
                // Skip hidden/invisible elements
                if (rect.width === 0 || rect.height === 0) continue;
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                if (parseFloat(style.opacity) === 0) continue;
                
                // Get background color (traverse up if transparent)
                let bgColor = style.backgroundColor;
                let bgElement = element;
                while ((bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') && bgElement.parentElement) {
                    bgElement = bgElement.parentElement;
                    bgColor = window.getComputedStyle(bgElement).backgroundColor;
                }
                if (bgColor === 'rgba(0, 0, 0, 0)') bgColor = 'rgb(255, 255, 255)';
                
                // Build selector
                let selector = element.tagName.toLowerCase();
                if (element.id) selector += '#' + element.id;
                else if (element.className && typeof element.className === 'string') {
                    selector += '.' + element.className.split(' ')[0];
                }
                
                results.push({
                    text: text.substring(0, 50),
                    selector: selector,
                    color: style.color,
                    backgroundColor: bgColor,
                    fontSize: parseFloat(style.fontSize),
                    fontWeight: style.fontWeight,
                    html: element.outerHTML.substring(0, 200)
                });
            }
            return results;
        }
        """
        
        try:
            elements = await page.evaluate(js_code, max_elements)
            
            # Determine thresholds based on level
            normal_ratio = ContrastLevel.AAA_NORMAL.value if level == "AAA" else ContrastLevel.AA_NORMAL.value
            large_ratio = ContrastLevel.AAA_LARGE.value if level == "AAA" else ContrastLevel.AA_LARGE.value
            
            for elem in elements:
                fg = ColorUtils.parse_color(elem.get('color', ''))
                bg = ColorUtils.parse_color(elem.get('backgroundColor', ''))
                
                if not fg or not bg:
                    continue
                
                ratio = ColorUtils.calculate_contrast_ratio(fg, bg)
                font_size = elem.get('fontSize', 16)
                font_weight = elem.get('fontWeight', '400')
                is_bold = font_weight in ['bold', '700', '800', '900'] or (
                    font_weight.isdigit() and int(font_weight) >= 700
                )
                is_large = ColorUtils.is_large_text(font_size, is_bold)
                
                required_ratio = large_ratio if is_large else normal_ratio
                passed = ratio >= required_ratio
                
                if not passed:
                    results.append(CheckResult(
                        rule_id="1.4.3" if level == "AA" else "1.4.6",
                        check_type="contrast",
                        passed=False,
                        details=f"Contrast ratio {ratio:.2f}:1 is below {required_ratio}:1 required for {'large' if is_large else 'normal'} text",
                        element_selector=elem.get('selector', ''),
                        element_html=elem.get('html', ''),
                        evidence={
                            'contrast_ratio': round(ratio, 2),
                            'required_ratio': required_ratio,
                            'foreground': elem.get('color'),
                            'background': elem.get('backgroundColor'),
                            'font_size': font_size,
                            'is_bold': is_bold,
                            'is_large_text': is_large,
                            'text_sample': elem.get('text', '')
                        },
                        fix_suggestion=ColorUtils.suggest_contrast_fix(ratio, required_ratio, fg, bg)
                    ))
            
            # Add passing result if no failures
            if not any(not r.passed for r in results):
                results.append(CheckResult(
                    rule_id="1.4.3" if level == "AA" else "1.4.6",
                    check_type="contrast",
                    passed=True,
                    details=f"All text meets Level {level} contrast requirements ({normal_ratio}:1 normal, {large_ratio}:1 large)"
                ))
                
        except Exception as e:
            logger.error(f"Contrast check failed: {e}")
            results.append(CheckResult(
                rule_id="1.4.3",
                check_type="contrast",
                passed=False,
                details=f"Contrast check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Target Size Check (WCAG 2.5.5, 2.5.8)
    # =========================================================================
    
    async def check_target_size(
        self,
        min_size: int = 24,
        max_elements: int = 50
    ) -> List[CheckResult]:
        """
        Check that interactive elements meet minimum target size requirements.
        
        Args:
            min_size: Minimum size in CSS pixels (24 for AA, 44 for AAA)
            max_elements: Maximum elements to check
            
        Returns:
            List of CheckResult objects for undersized elements
        """
        results = []
        page = await self._get_page()
        
        js_code = """
        (args) => {
            const { minSize, maxElements } = args;
            const selectors = 'a, button, input:not([type="hidden"]), select, textarea, ' +
                            '[role="button"], [role="link"], [role="checkbox"], [role="radio"], ' +
                            '[role="tab"], [role="menuitem"], [tabindex]:not([tabindex="-1"])';
            
            const elements = document.querySelectorAll(selectors);
            const issues = [];
            
            for (let i = 0; i < elements.length && issues.length < maxElements; i++) {
                const el = elements[i];
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                
                // Skip hidden elements
                if (rect.width === 0 || rect.height === 0) continue;
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                
                const width = rect.width;
                const height = rect.height;
                
                if (width < minSize || height < minSize) {
                    let selector = el.tagName.toLowerCase();
                    if (el.id) selector += '#' + el.id;
                    else if (el.className && typeof el.className === 'string') {
                        selector += '.' + el.className.split(' ')[0];
                    }
                    
                    issues.push({
                        selector: selector,
                        text: (el.textContent || el.getAttribute('aria-label') || '').trim().substring(0, 30),
                        width: Math.round(width),
                        height: Math.round(height),
                        tagName: el.tagName.toLowerCase(),
                        type: el.getAttribute('type') || el.getAttribute('role') || 'interactive',
                        html: el.outerHTML.substring(0, 200)
                    });
                }
            }
            
            return issues;
        }
        """
        
        try:
            issues = await page.evaluate(js_code, {'minSize': min_size, 'maxElements': max_elements})
            
            rule_id = "2.5.8" if min_size == 24 else "2.5.5"
            
            for issue in issues:
                results.append(CheckResult(
                    rule_id=rule_id,
                    check_type="target_size",
                    passed=False,
                    details=f"Target size {issue['width']}x{issue['height']}px is below minimum {min_size}x{min_size}px",
                    element_selector=issue.get('selector', ''),
                    element_html=issue.get('html', ''),
                    evidence={
                        'width': issue['width'],
                        'height': issue['height'],
                        'minimum_required': min_size,
                        'element_type': issue.get('type', ''),
                        'text': issue.get('text', '')
                    },
                    fix_suggestion=f"Increase element size to at least {min_size}x{min_size}px using padding, min-width/min-height, or larger touch targets"
                ))
            
            if not issues:
                results.append(CheckResult(
                    rule_id=rule_id,
                    check_type="target_size",
                    passed=True,
                    details=f"All interactive elements meet the {min_size}x{min_size}px minimum target size"
                ))
                
        except Exception as e:
            logger.error(f"Target size check failed: {e}")
            results.append(CheckResult(
                rule_id="2.5.8",
                check_type="target_size",
                passed=False,
                details=f"Target size check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Focus Appearance Check (WCAG 2.4.7, 2.4.11)
    # =========================================================================
    
    async def check_focus_appearance(
        self,
        min_outline_width: int = 2,
        max_elements: int = 30
    ) -> List[CheckResult]:
        """
        Check that focused elements have visible focus indicators.
        
        Args:
            min_outline_width: Minimum outline width in pixels
            max_elements: Maximum elements to check
            
        Returns:
            List of CheckResult objects for elements with insufficient focus indicators
        """
        results = []
        page = await self._get_page()
        
        js_code = """
        async (args) => {
            const { maxElements, minOutlineWidth } = args;
            const selectors = 'a[href], button, input:not([type="hidden"]), select, textarea, ' +
                            '[tabindex]:not([tabindex="-1"])';
            
            const elements = Array.from(document.querySelectorAll(selectors)).slice(0, maxElements);
            const issues = [];
            
            for (const el of elements) {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                
                // Get unfocused styles
                const unfocusedStyle = window.getComputedStyle(el);
                const unfocusedOutline = unfocusedStyle.outline;
                const unfocusedOutlineWidth = parseFloat(unfocusedStyle.outlineWidth) || 0;
                const unfocusedBoxShadow = unfocusedStyle.boxShadow;
                const unfocusedBorder = unfocusedStyle.border;
                const unfocusedBackground = unfocusedStyle.backgroundColor;
                
                // Focus the element
                el.focus();
                await new Promise(r => setTimeout(r, 50));
                
                // Get focused styles
                const focusedStyle = window.getComputedStyle(el);
                const focusedOutline = focusedStyle.outline;
                const focusedOutlineWidth = parseFloat(focusedStyle.outlineWidth) || 0;
                const focusedOutlineStyle = focusedStyle.outlineStyle;
                const focusedOutlineColor = focusedStyle.outlineColor;
                const focusedBoxShadow = focusedStyle.boxShadow;
                const focusedBorder = focusedStyle.border;
                const focusedBackground = focusedStyle.backgroundColor;
                
                // Check for visible changes
                const hasOutlineChange = focusedOutline !== unfocusedOutline && 
                                        focusedOutlineStyle !== 'none' && 
                                        focusedOutlineWidth > 0;
                const hasShadowChange = focusedBoxShadow !== unfocusedBoxShadow && 
                                       focusedBoxShadow !== 'none';
                const hasBorderChange = focusedBorder !== unfocusedBorder;
                const hasBackgroundChange = focusedBackground !== unfocusedBackground;
                
                const hasFocusIndicator = hasOutlineChange || hasShadowChange || hasBorderChange || hasBackgroundChange;
                const meetsMinWidth = focusedOutlineWidth >= minOutlineWidth;
                
                if (!hasFocusIndicator || (hasOutlineChange && !meetsMinWidth)) {
                    let selector = el.tagName.toLowerCase();
                    if (el.id) selector += '#' + el.id;
                    else if (el.className && typeof el.className === 'string') {
                        selector += '.' + el.className.split(' ')[0];
                    }
                    
                    issues.push({
                        selector: selector,
                        text: (el.textContent || el.getAttribute('aria-label') || '').trim().substring(0, 30),
                        hasFocusIndicator: hasFocusIndicator,
                        outlineWidth: focusedOutlineWidth,
                        outlineStyle: focusedOutlineStyle,
                        outlineColor: focusedOutlineColor,
                        html: el.outerHTML.substring(0, 200)
                    });
                }
                
                // Blur to reset
                el.blur();
            }
            
            return issues;
        }
        """
        
        try:
            issues = await page.evaluate(js_code, {'maxElements': max_elements, 'minOutlineWidth': min_outline_width})
            
            for issue in issues:
                has_indicator = issue.get('hasFocusIndicator', False)
                outline_width = issue.get('outlineWidth', 0)
                
                if not has_indicator:
                    detail = "Element has no visible focus indicator"
                else:
                    detail = f"Focus outline ({outline_width}px) is below minimum {min_outline_width}px"
                
                results.append(CheckResult(
                    rule_id="2.4.7",
                    check_type="focus_appearance",
                    passed=False,
                    details=detail,
                    element_selector=issue.get('selector', ''),
                    element_html=issue.get('html', ''),
                    evidence={
                        'has_focus_indicator': has_indicator,
                        'outline_width': outline_width,
                        'outline_style': issue.get('outlineStyle', ''),
                        'outline_color': issue.get('outlineColor', ''),
                        'text': issue.get('text', '')
                    },
                    fix_suggestion="Add visible focus styles: outline: 2px solid currentColor; or use :focus-visible with custom styles"
                ))
            
            if not issues:
                results.append(CheckResult(
                    rule_id="2.4.7",
                    check_type="focus_appearance",
                    passed=True,
                    details="All focusable elements have visible focus indicators"
                ))
                
        except Exception as e:
            logger.error(f"Focus appearance check failed: {e}")
            results.append(CheckResult(
                rule_id="2.4.7",
                check_type="focus_appearance",
                passed=False,
                details=f"Focus appearance check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Link Text Quality Check (WCAG 2.4.4, 2.4.9)
    # =========================================================================
    
    async def check_link_text_quality(
        self,
        max_links: int = 50
    ) -> List[CheckResult]:
        """
        Check link text for vague or non-informative content.
        
        Args:
            max_links: Maximum links to check
            
        Returns:
            List of CheckResult objects for links with poor text
        """
        results = []
        page = await self._get_page()
        
        js_code = """
        (maxLinks) => {
            const links = document.querySelectorAll('a[href]');
            const linkData = [];
            
            for (let i = 0; i < links.length && linkData.length < maxLinks; i++) {
                const link = links[i];
                const rect = link.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                
                // Get link text
                let linkText = link.textContent?.trim() || '';
                
                // Check aria-label
                const ariaLabel = link.getAttribute('aria-label') || '';
                const title = link.getAttribute('title') || '';
                
                // Check for image alt
                const img = link.querySelector('img');
                if (img && img.alt && !linkText) {
                    linkText = img.alt;
                }
                
                // Get context
                const parent = link.parentElement;
                const context = parent?.textContent?.substring(0, 100) || '';
                
                let selector = 'a';
                if (link.id) selector += '#' + link.id;
                else if (link.className && typeof link.className === 'string') {
                    selector += '.' + link.className.split(' ')[0];
                }
                
                linkData.push({
                    selector: selector,
                    text: linkText,
                    ariaLabel: ariaLabel,
                    title: title,
                    href: link.href,
                    context: context,
                    html: link.outerHTML.substring(0, 200),
                    hasImage: !!img
                });
            }
            
            return linkData;
        }
        """
        
        try:
            links = await page.evaluate(js_code, max_links)
            
            for link in links:
                # Use aria-label if present, otherwise link text
                effective_text = link.get('ariaLabel') or link.get('text', '')
                
                is_vague, reason = LinkTextAnalyzer.is_vague(effective_text)
                
                if is_vague:
                    results.append(CheckResult(
                        rule_id="2.4.4",
                        check_type="link_text_quality",
                        passed=False,
                        details=f"Link text issue: {reason}",
                        element_selector=link.get('selector', ''),
                        element_html=link.get('html', ''),
                        evidence={
                            'link_text': link.get('text', ''),
                            'aria_label': link.get('ariaLabel', ''),
                            'href': (link.get('href', '') or '')[:50],
                            'reason': reason,
                            'quality_score': LinkTextAnalyzer.get_quality_score(effective_text)
                        },
                        fix_suggestion=LinkTextAnalyzer.suggest_improvement(
                            effective_text, link.get('href', '')
                        )
                    ))
            
            if not any(not r.passed for r in results):
                results.append(CheckResult(
                    rule_id="2.4.4",
                    check_type="link_text_quality",
                    passed=True,
                    details="All link texts are descriptive"
                ))
                
        except Exception as e:
            logger.error(f"Link text quality check failed: {e}")
            results.append(CheckResult(
                rule_id="2.4.4",
                check_type="link_text_quality",
                passed=False,
                details=f"Link text quality check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Label in Name Check (WCAG 2.5.3)
    # =========================================================================
    
    async def check_label_in_name(
        self,
        max_elements: int = 30
    ) -> List[CheckResult]:
        """
        Check that accessible names contain visible label text.
        
        Args:
            max_elements: Maximum elements to check
            
        Returns:
            List of CheckResult objects for mismatched labels
        """
        results = []
        page = await self._get_page()
        
        js_code = """
        (maxElements) => {
            const selectors = 'button, [role="button"], a, input:not([type="hidden"]), ' +
                            '[role="link"], [role="tab"], [role="menuitem"]';
            const elements = document.querySelectorAll(selectors);
            const issues = [];
            
            for (let i = 0; i < elements.length && issues.length < maxElements; i++) {
                const el = elements[i];
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                
                // Get visible text
                let visibleText = '';
                if (el.tagName === 'INPUT') {
                    visibleText = el.value || el.placeholder || '';
                } else {
                    visibleText = el.textContent || '';
                }
                visibleText = visibleText.trim();
                
                // Get accessible name
                let accessibleName = '';
                
                if (el.getAttribute('aria-label')) {
                    accessibleName = el.getAttribute('aria-label');
                } else if (el.getAttribute('aria-labelledby')) {
                    const ids = el.getAttribute('aria-labelledby').split(' ');
                    accessibleName = ids.map(id => {
                        const labelEl = document.getElementById(id);
                        return labelEl?.textContent?.trim() || '';
                    }).join(' ');
                } else if (el.id) {
                    const label = document.querySelector(`label[for="${el.id}"]`);
                    if (label) {
                        accessibleName = label.textContent?.trim() || '';
                    }
                }
                
                // Only check if there's both visible text and a different accessible name
                if (visibleText && accessibleName && 
                    visibleText.toLowerCase() !== accessibleName.toLowerCase()) {
                    
                    // Check if visible text is contained in accessible name
                    const normalizedVisible = visibleText.toLowerCase().replace(/[^a-z0-9\\s]/g, '');
                    const normalizedAccessible = accessibleName.toLowerCase().replace(/[^a-z0-9\\s]/g, '');
                    
                    if (!normalizedAccessible.includes(normalizedVisible) && normalizedVisible.length > 2) {
                        let selector = el.tagName.toLowerCase();
                        if (el.id) selector += '#' + el.id;
                        else if (el.className && typeof el.className === 'string') {
                            selector += '.' + el.className.split(' ')[0];
                        }
                        
                        issues.push({
                            selector: selector,
                            visibleText: visibleText.substring(0, 50),
                            accessibleName: accessibleName.substring(0, 50),
                            tagName: el.tagName.toLowerCase(),
                            html: el.outerHTML.substring(0, 200)
                        });
                    }
                }
            }
            
            return issues;
        }
        """
        
        try:
            issues = await page.evaluate(js_code, max_elements)
            
            for issue in issues:
                results.append(CheckResult(
                    rule_id="2.5.3",
                    check_type="label_in_name",
                    passed=False,
                    details=f"Accessible name '{issue.get('accessibleName', '')}' does not contain visible text '{issue.get('visibleText', '')}'",
                    element_selector=issue.get('selector', ''),
                    element_html=issue.get('html', ''),
                    evidence={
                        'visible_text': issue.get('visibleText', ''),
                        'accessible_name': issue.get('accessibleName', ''),
                        'element_type': issue.get('tagName', '')
                    },
                    fix_suggestion="Ensure aria-label or aria-labelledby includes the visible label text verbatim"
                ))
            
            if not issues:
                results.append(CheckResult(
                    rule_id="2.5.3",
                    check_type="label_in_name",
                    passed=True,
                    details="All accessible names include their visible labels"
                ))
                
        except Exception as e:
            logger.error(f"Label in name check failed: {e}")
            results.append(CheckResult(
                rule_id="2.5.3",
                check_type="label_in_name",
                passed=False,
                details=f"Label in name check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Non-Text Contrast Check (WCAG 1.4.11)
    # =========================================================================
    
    async def check_non_text_contrast(
        self,
        min_ratio: float = 3.0,
        max_elements: int = 30
    ) -> List[CheckResult]:
        """
        Check contrast for UI components and graphical objects.
        
        Args:
            min_ratio: Minimum contrast ratio (3.0 for WCAG 1.4.11)
            max_elements: Maximum elements to check
            
        Returns:
            List of CheckResult objects for low contrast UI elements
        """
        results = []
        page = await self._get_page()
        
        js_code = """
        (maxElements) => {
            const selectors = 'input, select, textarea, button, [role="button"], ' +
                            '[role="checkbox"], [role="radio"], [role="slider"], [role="switch"]';
            const elements = document.querySelectorAll(selectors);
            const data = [];
            
            for (let i = 0; i < elements.length && data.length < maxElements; i++) {
                const el = elements[i];
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                
                const style = window.getComputedStyle(el);
                const borderColor = style.borderColor;
                const borderWidth = parseFloat(style.borderWidth) || 0;
                const backgroundColor = style.backgroundColor;
                
                // Get parent background
                let parentBg = 'rgb(255, 255, 255)';
                let parent = el.parentElement;
                while (parent) {
                    const pStyle = window.getComputedStyle(parent);
                    if (pStyle.backgroundColor !== 'rgba(0, 0, 0, 0)' && 
                        pStyle.backgroundColor !== 'transparent') {
                        parentBg = pStyle.backgroundColor;
                        break;
                    }
                    parent = parent.parentElement;
                }
                
                let selector = el.tagName.toLowerCase();
                if (el.id) selector += '#' + el.id;
                
                data.push({
                    selector: selector,
                    borderColor: borderColor,
                    borderWidth: borderWidth,
                    backgroundColor: backgroundColor,
                    parentBackground: parentBg,
                    html: el.outerHTML.substring(0, 200)
                });
            }
            
            return data;
        }
        """
        
        try:
            elements = await page.evaluate(js_code, max_elements)
            
            for elem in elements:
                border_color = ColorUtils.parse_color(elem.get('borderColor', ''))
                parent_bg = ColorUtils.parse_color(elem.get('parentBackground', ''))
                border_width = elem.get('borderWidth', 0)
                
                if not border_color or not parent_bg or border_width < 1:
                    continue
                
                # Check border alpha - skip if fully transparent
                if border_color[3] == 0:
                    continue
                
                ratio = ColorUtils.calculate_contrast_ratio(border_color, parent_bg)
                
                if ratio < min_ratio:
                    results.append(CheckResult(
                        rule_id="1.4.11",
                        check_type="non_text_contrast",
                        passed=False,
                        details=f"UI component border contrast {ratio:.2f}:1 is below {min_ratio}:1",
                        element_selector=elem.get('selector', ''),
                        element_html=elem.get('html', ''),
                        evidence={
                            'contrast_ratio': round(ratio, 2),
                            'required_ratio': min_ratio,
                            'border_color': elem.get('borderColor'),
                            'background': elem.get('parentBackground')
                        },
                        fix_suggestion=f"Increase border/boundary contrast to at least {min_ratio}:1"
                    ))
            
            if not any(not r.passed for r in results):
                results.append(CheckResult(
                    rule_id="1.4.11",
                    check_type="non_text_contrast",
                    passed=True,
                    details=f"All UI components meet {min_ratio}:1 contrast requirement"
                ))
                
        except Exception as e:
            logger.error(f"Non-text contrast check failed: {e}")
            results.append(CheckResult(
                rule_id="1.4.11",
                check_type="non_text_contrast",
                passed=False,
                details=f"Non-text contrast check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Duplicate ID Check (WCAG 4.1.1)
    # =========================================================================
    
    async def check_duplicate_ids(self) -> List[CheckResult]:
        """
        Check for duplicate ID attributes in the document.
        
        Returns:
            List of CheckResult objects for duplicate IDs
        """
        results = []
        page = await self._get_page()
        
        js_code = """
        () => {
            const ids = {};
            const elements = document.querySelectorAll('[id]');
            
            for (const el of elements) {
                const id = el.id;
                if (!id) continue;
                
                if (!ids[id]) {
                    ids[id] = [];
                }
                ids[id].push({
                    tag: el.tagName.toLowerCase(),
                    html: el.outerHTML.substring(0, 100)
                });
            }
            
            // Return only duplicates
            const duplicates = [];
            for (const [id, elements] of Object.entries(ids)) {
                if (elements.length > 1) {
                    duplicates.push({
                        id: id,
                        count: elements.length,
                        elements: elements
                    });
                }
            }
            
            return duplicates;
        }
        """
        
        try:
            duplicates = await page.evaluate(js_code)
            
            for dup in duplicates:
                results.append(CheckResult(
                    rule_id="4.1.1",
                    check_type="duplicate_id",
                    passed=False,
                    details=f"ID '{dup['id']}' is used {dup['count']} times (must be unique)",
                    evidence={
                        'id': dup['id'],
                        'count': dup['count'],
                        'elements': dup['elements']
                    },
                    fix_suggestion=f"Ensure ID '{dup['id']}' is unique - use different IDs or classes for multiple elements"
                ))
            
            if not duplicates:
                results.append(CheckResult(
                    rule_id="4.1.1",
                    check_type="duplicate_id",
                    passed=True,
                    details="All ID attributes are unique"
                ))
                
        except Exception as e:
            logger.error(f"Duplicate ID check failed: {e}")
            results.append(CheckResult(
                rule_id="4.1.1",
                check_type="duplicate_id",
                passed=False,
                details=f"Duplicate ID check could not complete: {str(e)}",
                automatable=False
            ))
        
        return results
    
    # =========================================================================
    # Run All Checks
    # =========================================================================
    
    async def run_all_checks(
        self,
        level: str = "AA"
    ) -> Dict[str, List[CheckResult]]:
        """
        Run all advanced accessibility checks.
        
        Args:
            level: WCAG conformance level ("A", "AA", or "AAA")
            
        Returns:
            Dictionary mapping check_type to list of results
        """
        all_results = {}
        
        # Contrast check
        all_results['contrast'] = await self.check_contrast(level=level)
        
        # Non-text contrast
        all_results['non_text_contrast'] = await self.check_non_text_contrast()
        
        # Target size (use 24px for AA, 44px for AAA)
        min_size = 44 if level == "AAA" else 24
        all_results['target_size'] = await self.check_target_size(min_size=min_size)
        
        # Focus appearance
        all_results['focus_appearance'] = await self.check_focus_appearance()
        
        # Link text quality
        all_results['link_text_quality'] = await self.check_link_text_quality()
        
        # Label in name
        all_results['label_in_name'] = await self.check_label_in_name()
        
        # Duplicate IDs
        all_results['duplicate_id'] = await self.check_duplicate_ids()
        
        return all_results


# =============================================================================
# Static Checks (No Browser Required)
# =============================================================================

def check_link_text_quality_static(html_content: str) -> List[CheckResult]:
    """
    Static analysis of link text quality without browser.
    
    Args:
        html_content: HTML string to analyze
        
    Returns:
        List of CheckResult objects
    """
    from bs4 import BeautifulSoup
    
    results = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    for link in soup.find_all('a'):
        link_text = link.get_text(strip=True)
        aria_label = link.get('aria-label', '')
        
        effective_text = aria_label or link_text
        
        is_vague, reason = LinkTextAnalyzer.is_vague(effective_text)
        
        if is_vague:
            selector = 'a'
            if link.get('id'):
                selector += f"#{link.get('id')}"
            elif link.get('class'):
                selector += f".{link.get('class')[0]}"
            
            results.append(CheckResult(
                rule_id="2.4.4",
                check_type="link_text_quality",
                passed=False,
                details=f"Link text issue: {reason}",
                element_selector=selector,
                element_html=str(link)[:200],
                evidence={
                    'link_text': link_text[:50],
                    'aria_label': aria_label[:50] if aria_label else '',
                    'href': (link.get('href', '') or '')[:50],
                    'reason': reason
                },
                fix_suggestion=LinkTextAnalyzer.suggest_improvement(effective_text, link.get('href', ''))
            ))
    
    if not any(not r.passed for r in results):
        results.append(CheckResult(
            rule_id="2.4.4",
            check_type="link_text_quality",
            passed=True,
            details="All link texts appear descriptive"
        ))
    
    return results


def check_duplicate_ids_static(html_content: str) -> List[CheckResult]:
    """
    Static analysis for duplicate IDs without browser.
    
    Args:
        html_content: HTML string to analyze
        
    Returns:
        List of CheckResult objects
    """
    from bs4 import BeautifulSoup
    
    results = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    id_counter = Counter()
    for elem in soup.find_all(id=True):
        elem_id = elem.get('id')
        if elem_id:
            id_counter[elem_id] += 1
    
    for elem_id, count in id_counter.items():
        if count > 1:
            results.append(CheckResult(
                rule_id="4.1.1",
                check_type="duplicate_id",
                passed=False,
                details=f"ID '{elem_id}' is used {count} times (must be unique)",
                evidence={
                    'id': elem_id,
                    'count': count
                },
                fix_suggestion=f"Make ID '{elem_id}' unique by using different values or classes"
            ))
    
    if not any(not r.passed for r in results):
        results.append(CheckResult(
            rule_id="4.1.1",
            check_type="duplicate_id",
            passed=True,
            details="All ID attributes are unique"
        ))
    
    return results


# =============================================================================
# Check Dispatcher
# =============================================================================

# Map check_type names to static check functions
STATIC_CHECK_FUNCTIONS = {
    'link_text_quality': check_link_text_quality_static,
    'link_text_standalone': check_link_text_quality_static,
    'duplicate_id': check_duplicate_ids_static,
}

# Check types requiring browser
BROWSER_CHECK_TYPES = {
    'contrast',
    'non_text_contrast',
    'target_size',
    'focus_appearance',
    'focus_visible',
    'label_in_name',
}

# All implemented check types
ALL_CHECK_TYPES = set(STATIC_CHECK_FUNCTIONS.keys()) | BROWSER_CHECK_TYPES


def run_static_check(check_type: str, html_content: str) -> List[CheckResult]:
    """
    Run a static check on HTML content.
    
    Args:
        check_type: The type of check to run
        html_content: HTML string to analyze
        
    Returns:
        List of CheckResult objects
    """
    if check_type in STATIC_CHECK_FUNCTIONS:
        return STATIC_CHECK_FUNCTIONS[check_type](html_content)
    
    return [CheckResult(
        rule_id="unknown",
        check_type=check_type,
        passed=False,
        details=f"Check type '{check_type}' requires browser automation",
        automatable=False
    )]


async def run_browser_checks(
    html_content: str = None,
    url: str = None,
    check_types: List[str] = None,
    level: str = "AA"
) -> Dict[str, List[CheckResult]]:
    """
    Run browser-based checks on HTML content or URL.
    
    Args:
        html_content: HTML string to check
        url: URL to check (alternative to html_content)
        check_types: Specific checks to run (None = all)
        level: WCAG conformance level
        
    Returns:
        Dictionary mapping check_type to list of results
    """
    if not HAS_PLAYWRIGHT:
        return {ct: [CheckResult(
            rule_id="unknown",
            check_type=ct,
            passed=False,
            details="Playwright not installed - browser checks unavailable",
            automatable=False
        )] for ct in (check_types or BROWSER_CHECK_TYPES)}
    
    checker = AdvancedBrowserChecker()
    results = {}
    
    try:
        await checker.initialize()
        
        if html_content:
            await checker.load_html(html_content)
        elif url:
            await checker.load_url(url)
        else:
            raise ValueError("Either html_content or url must be provided")
        
        # Run requested checks
        checks_to_run = check_types or list(BROWSER_CHECK_TYPES)
        
        if 'contrast' in checks_to_run:
            results['contrast'] = await checker.check_contrast(level=level)
        
        if 'non_text_contrast' in checks_to_run:
            results['non_text_contrast'] = await checker.check_non_text_contrast()
        
        if 'target_size' in checks_to_run:
            min_size = 44 if level == "AAA" else 24
            results['target_size'] = await checker.check_target_size(min_size=min_size)
        
        if 'focus_appearance' in checks_to_run or 'focus_visible' in checks_to_run:
            results['focus_appearance'] = await checker.check_focus_appearance()
        
        if 'link_text_quality' in checks_to_run or 'link_text_standalone' in checks_to_run:
            results['link_text_quality'] = await checker.check_link_text_quality()
        
        if 'label_in_name' in checks_to_run:
            results['label_in_name'] = await checker.check_label_in_name()
        
        if 'duplicate_id' in checks_to_run:
            results['duplicate_id'] = await checker.check_duplicate_ids()
        
    except Exception as e:
        logger.error(f"Browser checks failed: {e}")
        for ct in (check_types or BROWSER_CHECK_TYPES):
            if ct not in results:
                results[ct] = [CheckResult(
                    rule_id="unknown",
                    check_type=ct,
                    passed=False,
                    details=f"Check failed: {str(e)}",
                    automatable=False
                )]
    finally:
        await checker.close()
    
    return results


def run_browser_checks_sync(
    html_content: str = None,
    url: str = None,
    check_types: List[str] = None,
    level: str = "AA"
) -> Dict[str, List[CheckResult]]:
    """Synchronous wrapper for run_browser_checks."""
    return asyncio.run(run_browser_checks(
        html_content=html_content,
        url=url,
        check_types=check_types,
        level=level
    ))


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Data classes
    'CheckResult',
    'ContrastLevel',
    'TargetSizeLevel',
    
    # Utilities
    'ColorUtils',
    'LinkTextAnalyzer',
    
    # Browser checker
    'AdvancedBrowserChecker',
    
    # Static checks
    'check_link_text_quality_static',
    'check_duplicate_ids_static',
    
    # Dispatchers
    'STATIC_CHECK_FUNCTIONS',
    'BROWSER_CHECK_TYPES',
    'ALL_CHECK_TYPES',
    'run_static_check',
    'run_browser_checks',
    'run_browser_checks_sync',
    
    # Flags
    'HAS_PLAYWRIGHT',
]

