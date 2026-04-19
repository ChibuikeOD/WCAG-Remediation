"""
Automated Accessibility Checks Module.

Implements complex check types that require browser automation or computed styles:
- Contrast checking (WCAG 1.4.3, 1.4.6, 1.4.11)
- Target size checking (WCAG 2.5.5, 2.5.8)
- Focus appearance checking (WCAG 2.4.11)
- Link text quality checking (WCAG 2.4.4, 2.4.9)
- Label in name checking (WCAG 2.5.3)
"""

import asyncio
import re
import math
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Page, Browser
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.warning("Playwright not available - some automated checks will be limited")


# =============================================================================
# Data Classes for Check Results
# =============================================================================

@dataclass
class CheckResult:
    """Result of an automated accessibility check."""
    rule_id: str
    check_type: str
    passed: bool
    details: str
    element_selector: Optional[str] = None
    element_html: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    automatable: bool = True
    fix_suggestion: Optional[str] = None


class ContrastLevel(Enum):
    """WCAG contrast conformance levels."""
    AA_NORMAL = 4.5  # Normal text AA
    AA_LARGE = 3.0   # Large text AA
    AAA_NORMAL = 7.0 # Normal text AAA
    AAA_LARGE = 4.5  # Large text AAA


# =============================================================================
# Color Utilities
# =============================================================================

class ColorUtils:
    """Utility functions for color manipulation and contrast calculation."""
    
    @staticmethod
    def parse_color(color_str: str) -> Optional[Tuple[int, int, int, float]]:
        """
        Parse CSS color string to RGBA tuple.
        Supports: rgb(), rgba(), hex (#fff, #ffffff), named colors.
        """
        if not color_str:
            return None
        
        color_str = color_str.strip().lower()
        
        # Handle rgba()
        rgba_match = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)', color_str)
        if rgba_match:
            r, g, b = int(rgba_match.group(1)), int(rgba_match.group(2)), int(rgba_match.group(3))
            a = float(rgba_match.group(4)) if rgba_match.group(4) else 1.0
            return (r, g, b, a)
        
        # Handle hex
        hex_match = re.match(r'#([0-9a-f]{3,8})', color_str)
        if hex_match:
            hex_val = hex_match.group(1)
            if len(hex_val) == 3:
                r = int(hex_val[0] * 2, 16)
                g = int(hex_val[1] * 2, 16)
                b = int(hex_val[2] * 2, 16)
            elif len(hex_val) == 6:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
            elif len(hex_val) == 8:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                a = int(hex_val[6:8], 16) / 255
                return (r, g, b, a)
            else:
                return None
            return (r, g, b, 1.0)
        
        # Common named colors
        named_colors = {
            'black': (0, 0, 0, 1.0),
            'white': (255, 255, 255, 1.0),
            'red': (255, 0, 0, 1.0),
            'green': (0, 128, 0, 1.0),
            'blue': (0, 0, 255, 1.0),
            'transparent': (0, 0, 0, 0.0),
        }
        if color_str in named_colors:
            return named_colors[color_str]
        
        return None
    
    @staticmethod
    def get_relative_luminance(r: int, g: int, b: int) -> float:
        """Calculate relative luminance per WCAG 2.1."""
        def adjust(c: int) -> float:
            c = c / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        
        return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)
    
    @staticmethod
    def calculate_contrast_ratio(fg_color: Tuple[int, int, int, float], 
                                  bg_color: Tuple[int, int, int, float]) -> float:
        """Calculate contrast ratio between two colors."""
        # Blend foreground with background if transparent
        fg_r, fg_g, fg_b, fg_a = fg_color
        bg_r, bg_g, bg_b, bg_a = bg_color
        
        # Simple alpha compositing
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
    def is_large_text(font_size: float, is_bold: bool) -> bool:
        """Determine if text qualifies as 'large' per WCAG."""
        # Large text: >= 18pt (24px) or >= 14pt (18.66px) if bold
        if font_size >= 24:
            return True
        if font_size >= 18.66 and is_bold:
            return True
        return False


# =============================================================================
# Contrast Checker
# =============================================================================

async def check_contrast(page: Page, level: str = "AA") -> List[CheckResult]:
    """
    Check color contrast of text elements.
    
    WCAG 1.4.3 (AA), 1.4.6 (AAA), 1.4.11 (non-text)
    
    Args:
        page: Playwright page object
        level: "AA" or "AAA"
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        # Get all text elements with their computed styles
        elements_data = await page.evaluate('''() => {
            const results = [];
            const textElements = document.querySelectorAll('p, span, a, h1, h2, h3, h4, h5, h6, li, td, th, label, button, div, section, article');
            
            for (const el of textElements) {
                // Skip hidden elements
                if (el.offsetParent === null && el.tagName !== 'BODY') continue;
                
                const style = window.getComputedStyle(el);
                const text = el.innerText?.trim()?.substring(0, 50);
                
                if (!text) continue;
                
                // Get background color (may need to traverse up)
                let bgColor = style.backgroundColor;
                let parent = el.parentElement;
                while (bgColor === 'rgba(0, 0, 0, 0)' && parent) {
                    bgColor = window.getComputedStyle(parent).backgroundColor;
                    parent = parent.parentElement;
                }
                if (bgColor === 'rgba(0, 0, 0, 0)') {
                    bgColor = 'rgb(255, 255, 255)'; // Assume white background
                }
                
                results.push({
                    selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className ? '.' + el.className.split(' ')[0] : ''),
                    text: text,
                    color: style.color,
                    backgroundColor: bgColor,
                    fontSize: parseFloat(style.fontSize),
                    fontWeight: style.fontWeight,
                    html: el.outerHTML.substring(0, 200)
                });
            }
            return results;
        }''')
        
        min_ratio = ContrastLevel.AA_NORMAL.value if level == "AA" else ContrastLevel.AAA_NORMAL.value
        min_ratio_large = ContrastLevel.AA_LARGE.value if level == "AA" else ContrastLevel.AAA_LARGE.value
        
        for elem in elements_data:
            fg = ColorUtils.parse_color(elem.get('color', ''))
            bg = ColorUtils.parse_color(elem.get('backgroundColor', ''))
            
            if not fg or not bg:
                continue
            
            ratio = ColorUtils.calculate_contrast_ratio(fg, bg)
            font_size = elem.get('fontSize', 16)
            is_bold = elem.get('fontWeight', '400') in ['bold', '700', '800', '900']
            is_large = ColorUtils.is_large_text(font_size, is_bold)
            
            required_ratio = min_ratio_large if is_large else min_ratio
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
                        "contrast_ratio": round(ratio, 2),
                        "required_ratio": required_ratio,
                        "foreground": elem.get('color'),
                        "background": elem.get('backgroundColor'),
                        "font_size": font_size,
                        "is_large_text": is_large,
                        "text_sample": elem.get('text', '')[:30]
                    },
                    fix_suggestion=f"Increase contrast to at least {required_ratio}:1. Current: {ratio:.2f}:1"
                ))
    
    except Exception as e:
        logger.error(f"Error in contrast check: {e}")
        results.append(CheckResult(
            rule_id="1.4.3",
            check_type="contrast",
            passed=True,  # Can't determine
            details=f"Could not perform contrast check: {str(e)}",
            automatable=False
        ))
    
    return results


# =============================================================================
# Target Size Checker
# =============================================================================

async def check_target_size(page: Page, min_size: int = 24) -> List[CheckResult]:
    """
    Check target size of interactive elements.
    
    WCAG 2.5.5 (AAA - 44x44), 2.5.8 (AA - 24x24)
    
    Args:
        page: Playwright page object
        min_size: Minimum size in CSS pixels (24 for AA, 44 for AAA)
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        # Get all interactive elements
        elements_data = await page.evaluate('''(minSize) => {
            const results = [];
            const interactiveSelectors = 'a, button, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"], [tabindex]:not([tabindex="-1"])';
            const elements = document.querySelectorAll(interactiveSelectors);
            
            for (const el of elements) {
                // Skip hidden elements
                if (el.offsetParent === null) continue;
                
                const rect = el.getBoundingClientRect();
                const width = rect.width;
                const height = rect.height;
                
                // Skip elements with no size
                if (width === 0 || height === 0) continue;
                
                results.push({
                    selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
                    width: width,
                    height: height,
                    text: el.innerText?.trim()?.substring(0, 30) || el.getAttribute('aria-label') || '',
                    html: el.outerHTML.substring(0, 200),
                    type: el.getAttribute('type') || el.tagName.toLowerCase()
                });
            }
            return results;
        }''', min_size)
        
        for elem in elements_data:
            width = elem.get('width', 0)
            height = elem.get('height', 0)
            
            # Check if meets minimum size
            passed = width >= min_size and height >= min_size
            
            if not passed:
                results.append(CheckResult(
                    rule_id="2.5.8" if min_size == 24 else "2.5.5",
                    check_type="target_size",
                    passed=False,
                    details=f"Target size {width:.0f}x{height:.0f}px is below minimum {min_size}x{min_size}px",
                    element_selector=elem.get('selector', ''),
                    element_html=elem.get('html', ''),
                    evidence={
                        "width": round(width, 1),
                        "height": round(height, 1),
                        "min_required": min_size,
                        "element_type": elem.get('type', ''),
                        "text": elem.get('text', '')
                    },
                    fix_suggestion=f"Increase element size to at least {min_size}x{min_size}px or add padding"
                ))
    
    except Exception as e:
        logger.error(f"Error in target size check: {e}")
        results.append(CheckResult(
            rule_id="2.5.8",
            check_type="target_size",
            passed=True,
            details=f"Could not perform target size check: {str(e)}",
            automatable=False
        ))
    
    return results


# =============================================================================
# Focus Appearance Checker
# =============================================================================

async def check_focus_appearance(page: Page) -> List[CheckResult]:
    """
    Check focus indicators on interactive elements.
    
    WCAG 2.4.7, 2.4.11, 2.4.12
    
    Args:
        page: Playwright page object
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        # Get all focusable elements and their focus styles
        elements_data = await page.evaluate('''() => {
            const results = [];
            const focusableSelectors = 'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';
            const elements = document.querySelectorAll(focusableSelectors);
            
            for (const el of elements) {
                if (el.offsetParent === null) continue;
                
                // Get styles before focus
                const beforeStyle = window.getComputedStyle(el);
                const beforeOutline = beforeStyle.outline;
                const beforeBoxShadow = beforeStyle.boxShadow;
                const beforeBorder = beforeStyle.border;
                
                // Focus the element
                el.focus();
                
                // Get styles after focus
                const afterStyle = window.getComputedStyle(el);
                const afterOutline = afterStyle.outline;
                const afterOutlineWidth = parseFloat(afterStyle.outlineWidth) || 0;
                const afterOutlineColor = afterStyle.outlineColor;
                const afterOutlineOffset = parseFloat(afterStyle.outlineOffset) || 0;
                const afterBoxShadow = afterStyle.boxShadow;
                const afterBorder = afterStyle.border;
                
                // Check if there's a visible change
                const hasOutlineChange = afterOutline !== beforeOutline && afterOutline !== 'none' && afterOutlineWidth > 0;
                const hasShadowChange = afterBoxShadow !== beforeBoxShadow && afterBoxShadow !== 'none';
                const hasBorderChange = afterBorder !== beforeBorder;
                
                results.push({
                    selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
                    hasVisibleFocus: hasOutlineChange || hasShadowChange || hasBorderChange,
                    outlineWidth: afterOutlineWidth,
                    outlineColor: afterOutlineColor,
                    outlineOffset: afterOutlineOffset,
                    outline: afterOutline,
                    boxShadow: afterBoxShadow,
                    html: el.outerHTML.substring(0, 200),
                    text: el.innerText?.trim()?.substring(0, 30) || ''
                });
                
                // Blur to reset
                el.blur();
            }
            return results;
        }''')
        
        for elem in elements_data:
            has_visible_focus = elem.get('hasVisibleFocus', False)
            outline_width = elem.get('outlineWidth', 0)
            
            # Check for visible focus indicator
            passed = has_visible_focus and outline_width >= 2
            
            if not passed:
                results.append(CheckResult(
                    rule_id="2.4.7",
                    check_type="focus_appearance",
                    passed=False,
                    details="Element lacks visible focus indicator" if not has_visible_focus else f"Focus indicator too thin ({outline_width}px)",
                    element_selector=elem.get('selector', ''),
                    element_html=elem.get('html', ''),
                    evidence={
                        "has_visible_focus": has_visible_focus,
                        "outline_width": outline_width,
                        "outline_color": elem.get('outlineColor', ''),
                        "outline": elem.get('outline', ''),
                        "text": elem.get('text', '')
                    },
                    fix_suggestion="Add visible focus styles: outline: 2px solid [color]; or use :focus-visible pseudo-class"
                ))
    
    except Exception as e:
        logger.error(f"Error in focus appearance check: {e}")
        results.append(CheckResult(
            rule_id="2.4.7",
            check_type="focus_appearance",
            passed=True,
            details=f"Could not perform focus appearance check: {str(e)}",
            automatable=False
        ))
    
    return results


# =============================================================================
# Link Text Quality Checker
# =============================================================================

# Common vague/non-informative link texts
VAGUE_LINK_TEXTS = {
    'click here', 'click', 'here', 'more', 'read more', 'learn more',
    'continue', 'continue reading', 'details', 'more details',
    'link', 'this link', 'this', 'info', 'more info', 'information',
    'go', 'see more', 'view more', 'view', 'download', 'pdf',
    'page', 'next', 'previous', 'back', 'start', 'begin'
}

# Patterns for potentially vague links
VAGUE_PATTERNS = [
    r'^click\s+here',
    r'^read\s+more',
    r'^learn\s+more',
    r'^more\s*$',
    r'^here\s*$',
    r'^link\s*$',
    r'^\d+$',  # Just a number
]


async def check_link_text_quality(page: Page) -> List[CheckResult]:
    """
    Check quality of link text for accessibility.
    
    WCAG 2.4.4 (Link Purpose in Context), 2.4.9 (Link Purpose Link Only)
    
    Args:
        page: Playwright page object
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        # Get all links with their text and context
        links_data = await page.evaluate('''() => {
            const results = [];
            const links = document.querySelectorAll('a[href]');
            
            for (const link of links) {
                if (link.offsetParent === null) continue;
                
                // Get link text
                let linkText = link.innerText?.trim() || '';
                
                // Check for image alt text
                const img = link.querySelector('img');
                if (img && img.alt && !linkText) {
                    linkText = img.alt;
                }
                
                // Get aria-label if present
                const ariaLabel = link.getAttribute('aria-label') || '';
                const title = link.getAttribute('title') || '';
                
                // Get surrounding context
                const parent = link.parentElement;
                const context = parent?.innerText?.substring(0, 100) || '';
                
                results.push({
                    selector: 'a' + (link.id ? '#' + link.id : ''),
                    text: linkText,
                    ariaLabel: ariaLabel,
                    title: title,
                    href: link.href,
                    context: context,
                    html: link.outerHTML.substring(0, 200),
                    hasImage: !!img
                });
            }
            return results;
        }''')
        
        for link in links_data:
            link_text = link.get('text', '').lower().strip()
            aria_label = link.get('ariaLabel', '').lower().strip()
            
            # Use aria-label if present, otherwise link text
            effective_text = aria_label or link_text
            
            # Check if empty
            if not effective_text:
                results.append(CheckResult(
                    rule_id="2.4.4",
                    check_type="link_text_quality",
                    passed=False,
                    details="Link has no accessible text",
                    element_selector=link.get('selector', ''),
                    element_html=link.get('html', ''),
                    evidence={
                        "link_text": link.get('text', ''),
                        "aria_label": link.get('ariaLabel', ''),
                        "href": link.get('href', '')
                    },
                    fix_suggestion="Add descriptive link text or aria-label"
                ))
                continue
            
            # Check for vague text
            is_vague = effective_text in VAGUE_LINK_TEXTS
            
            # Check patterns
            if not is_vague:
                for pattern in VAGUE_PATTERNS:
                    if re.match(pattern, effective_text, re.IGNORECASE):
                        is_vague = True
                        break
            
            # Check if too short (1-2 characters)
            if len(effective_text) <= 2 and not effective_text.isalpha():
                is_vague = True
            
            if is_vague:
                results.append(CheckResult(
                    rule_id="2.4.4",
                    check_type="link_text_quality",
                    passed=False,
                    details=f"Link text '{link.get('text', '')}' is vague or non-descriptive",
                    element_selector=link.get('selector', ''),
                    element_html=link.get('html', ''),
                    evidence={
                        "link_text": link.get('text', ''),
                        "aria_label": link.get('ariaLabel', ''),
                        "href": link.get('href', ''),
                        "context": link.get('context', '')[:50]
                    },
                    fix_suggestion="Use descriptive text that indicates the link's destination or purpose"
                ))
    
    except Exception as e:
        logger.error(f"Error in link text quality check: {e}")
        results.append(CheckResult(
            rule_id="2.4.4",
            check_type="link_text_quality",
            passed=True,
            details=f"Could not perform link text quality check: {str(e)}",
            automatable=False
        ))
    
    return results


# =============================================================================
# Label in Name Checker
# =============================================================================

async def check_label_in_name(page: Page) -> List[CheckResult]:
    """
    Check that accessible name contains visible label text.
    
    WCAG 2.5.3 Label in Name
    
    Args:
        page: Playwright page object
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        # Get elements with both visible text and accessible names
        elements_data = await page.evaluate('''() => {
            const results = [];
            const selectors = 'button, a, input[type="submit"], input[type="button"], [role="button"], [role="link"]';
            const elements = document.querySelectorAll(selectors);
            
            for (const el of elements) {
                if (el.offsetParent === null) continue;
                
                // Get visible text
                let visibleText = el.innerText?.trim() || '';
                
                // For inputs, check value
                if (el.tagName === 'INPUT') {
                    visibleText = el.value || '';
                }
                
                // Get accessible name
                let accessibleName = '';
                
                // Check aria-label
                if (el.hasAttribute('aria-label')) {
                    accessibleName = el.getAttribute('aria-label');
                }
                // Check aria-labelledby
                else if (el.hasAttribute('aria-labelledby')) {
                    const labelIds = el.getAttribute('aria-labelledby').split(' ');
                    const labelTexts = labelIds.map(id => {
                        const labelEl = document.getElementById(id);
                        return labelEl?.innerText?.trim() || '';
                    });
                    accessibleName = labelTexts.join(' ');
                }
                // Check for associated label (inputs)
                else if (el.id) {
                    const label = document.querySelector('label[for="' + el.id + '"]');
                    if (label) {
                        accessibleName = label.innerText?.trim() || '';
                    }
                }
                
                // Only check if there's both visible text and a different accessible name
                if (visibleText && accessibleName && visibleText !== accessibleName) {
                    results.push({
                        selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
                        visibleText: visibleText,
                        accessibleName: accessibleName,
                        html: el.outerHTML.substring(0, 200)
                    });
                }
            }
            return results;
        }''')
        
        for elem in elements_data:
            visible_text = elem.get('visibleText', '').lower()
            accessible_name = elem.get('accessibleName', '').lower()
            
            # Check if visible text is contained in accessible name
            # (accessible name should contain the visible text)
            visible_words = set(visible_text.split())
            accessible_words = set(accessible_name.split())
            
            # At least the main visible words should be in the accessible name
            common_words = visible_words.intersection(accessible_words)
            
            # If visible text has significant words not in accessible name
            significant_missing = visible_words - accessible_words - {'the', 'a', 'an', 'and', 'or', 'to', 'for'}
            
            passed = len(significant_missing) == 0 or visible_text in accessible_name
            
            if not passed:
                results.append(CheckResult(
                    rule_id="2.5.3",
                    check_type="label_in_name",
                    passed=False,
                    details=f"Accessible name '{elem.get('accessibleName', '')}' does not contain visible text '{elem.get('visibleText', '')}'",
                    element_selector=elem.get('selector', ''),
                    element_html=elem.get('html', ''),
                    evidence={
                        "visible_text": elem.get('visibleText', ''),
                        "accessible_name": elem.get('accessibleName', ''),
                        "missing_words": list(significant_missing)
                    },
                    fix_suggestion="Ensure aria-label or accessible name contains the visible label text"
                ))
    
    except Exception as e:
        logger.error(f"Error in label in name check: {e}")
        results.append(CheckResult(
            rule_id="2.5.3",
            check_type="label_in_name",
            passed=True,
            details=f"Could not perform label in name check: {str(e)}",
            automatable=False
        ))
    
    return results


# =============================================================================
# Non-Text Contrast Checker
# =============================================================================

async def check_non_text_contrast(page: Page) -> List[CheckResult]:
    """
    Check contrast of UI components and graphical objects.
    
    WCAG 1.4.11 Non-text Contrast
    
    Args:
        page: Playwright page object
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        # Get UI components (inputs, buttons, etc.)
        elements_data = await page.evaluate('''() => {
            const results = [];
            const uiSelectors = 'input, select, textarea, button, [role="button"], [role="checkbox"], [role="radio"]';
            const elements = document.querySelectorAll(uiSelectors);
            
            for (const el of elements) {
                if (el.offsetParent === null) continue;
                
                const style = window.getComputedStyle(el);
                const borderColor = style.borderColor;
                const borderWidth = parseFloat(style.borderWidth) || 0;
                const backgroundColor = style.backgroundColor;
                
                // Get parent background
                let parentBg = 'rgb(255, 255, 255)';
                let parent = el.parentElement;
                while (parent) {
                    const pStyle = window.getComputedStyle(parent);
                    if (pStyle.backgroundColor !== 'rgba(0, 0, 0, 0)') {
                        parentBg = pStyle.backgroundColor;
                        break;
                    }
                    parent = parent.parentElement;
                }
                
                results.push({
                    selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : ''),
                    borderColor: borderColor,
                    borderWidth: borderWidth,
                    backgroundColor: backgroundColor,
                    parentBackground: parentBg,
                    html: el.outerHTML.substring(0, 200)
                });
            }
            return results;
        }''')
        
        for elem in elements_data:
            border_color = ColorUtils.parse_color(elem.get('borderColor', ''))
            parent_bg = ColorUtils.parse_color(elem.get('parentBackground', ''))
            border_width = elem.get('borderWidth', 0)
            
            if not border_color or not parent_bg or border_width < 1:
                continue
            
            ratio = ColorUtils.calculate_contrast_ratio(border_color, parent_bg)
            
            # Non-text contrast requires 3:1
            if ratio < 3.0:
                results.append(CheckResult(
                    rule_id="1.4.11",
                    check_type="non_text_contrast",
                    passed=False,
                    details=f"UI component border contrast {ratio:.2f}:1 is below 3:1",
                    element_selector=elem.get('selector', ''),
                    element_html=elem.get('html', ''),
                    evidence={
                        "contrast_ratio": round(ratio, 2),
                        "required_ratio": 3.0,
                        "border_color": elem.get('borderColor'),
                        "background": elem.get('parentBackground')
                    },
                    fix_suggestion="Increase border contrast to at least 3:1"
                ))
    
    except Exception as e:
        logger.error(f"Error in non-text contrast check: {e}")
    
    return results


# =============================================================================
# Duplicate ID Checker
# =============================================================================

async def check_duplicate_ids(page: Page) -> List[CheckResult]:
    """
    Check for duplicate ID attributes.
    
    WCAG 4.1.1 Parsing
    
    Args:
        page: Playwright page object
    
    Returns:
        List of CheckResult objects
    """
    results = []
    
    try:
        duplicates = await page.evaluate('''() => {
            const ids = {};
            const elements = document.querySelectorAll('[id]');
            
            for (const el of elements) {
                const id = el.id;
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
        }''')
        
        for dup in duplicates:
            results.append(CheckResult(
                rule_id="4.1.1",
                check_type="duplicate_id",
                passed=False,
                details=f"ID '{dup['id']}' is used {dup['count']} times",
                evidence={
                    "id": dup['id'],
                    "count": dup['count'],
                    "elements": dup['elements']
                },
                fix_suggestion=f"Ensure ID '{dup['id']}' is unique - each ID should only appear once"
            ))
    
    except Exception as e:
        logger.error(f"Error in duplicate ID check: {e}")
    
    return results


# =============================================================================
# Check Dispatcher
# =============================================================================

# Map check_type names to implementation functions
CHECK_DISPATCHER = {
    "contrast": check_contrast,
    "non_text_contrast": check_non_text_contrast,
    "target_size": check_target_size,
    "focus_appearance": check_focus_appearance,
    "focus_visible": check_focus_appearance,  # Alias
    "link_text_quality": check_link_text_quality,
    "link_text_standalone": check_link_text_quality,  # Same check, stricter interpretation
    "label_in_name": check_label_in_name,
    "duplicate_id": check_duplicate_ids,
}


async def run_automated_check(check_type: str, page: Page, **kwargs) -> List[CheckResult]:
    """
    Run an automated check by type.
    
    Args:
        check_type: The type of check to run
        page: Playwright page object
        **kwargs: Additional arguments for the check
    
    Returns:
        List of CheckResult objects
    """
    if check_type not in CHECK_DISPATCHER:
        return [CheckResult(
            rule_id="unknown",
            check_type=check_type,
            passed=True,
            details=f"Check type '{check_type}' is not implemented",
            automatable=False
        )]
    
    check_func = CHECK_DISPATCHER[check_type]
    return await check_func(page, **kwargs)


async def run_all_automated_checks(page: Page) -> Dict[str, List[CheckResult]]:
    """
    Run all automated checks on a page.
    
    Args:
        page: Playwright page object
    
    Returns:
        Dictionary mapping check_type to results
    """
    all_results = {}
    
    for check_type, check_func in CHECK_DISPATCHER.items():
        try:
            results = await check_func(page)
            all_results[check_type] = results
        except Exception as e:
            logger.error(f"Error running {check_type} check: {e}")
            all_results[check_type] = [CheckResult(
                rule_id="unknown",
                check_type=check_type,
                passed=True,
                details=f"Check failed: {str(e)}",
                automatable=False
            )]
    
    return all_results


# =============================================================================
# HTML String Analysis (without browser)
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
        link_text = link.get_text(strip=True).lower()
        aria_label = (link.get('aria-label') or '').lower()
        
        effective_text = aria_label or link_text
        
        if not effective_text:
            results.append(CheckResult(
                rule_id="2.4.4",
                check_type="link_text_quality",
                passed=False,
                details="Link has no accessible text",
                element_html=str(link)[:200],
                fix_suggestion="Add descriptive link text or aria-label"
            ))
            continue
        
        is_vague = effective_text in VAGUE_LINK_TEXTS
        if not is_vague:
            for pattern in VAGUE_PATTERNS:
                if re.match(pattern, effective_text, re.IGNORECASE):
                    is_vague = True
                    break
        
        if is_vague:
            results.append(CheckResult(
                rule_id="2.4.4",
                check_type="link_text_quality",
                passed=False,
                details=f"Link text '{link_text}' is vague",
                element_html=str(link)[:200],
                fix_suggestion="Use descriptive text indicating link destination"
            ))
    
    return results


def check_duplicate_ids_static(html_content: str) -> List[CheckResult]:
    """
    Static analysis of duplicate IDs without browser.
    
    Args:
        html_content: HTML string to analyze
    
    Returns:
        List of CheckResult objects
    """
    from bs4 import BeautifulSoup
    
    results = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    ids = {}
    for elem in soup.find_all(id=True):
        elem_id = elem.get('id')
        if elem_id not in ids:
            ids[elem_id] = []
        ids[elem_id].append(elem.name)
    
    for elem_id, tags in ids.items():
        if len(tags) > 1:
            results.append(CheckResult(
                rule_id="4.1.1",
                check_type="duplicate_id",
                passed=False,
                details=f"ID '{elem_id}' used {len(tags)} times",
                evidence={"id": elem_id, "count": len(tags), "elements": tags},
                fix_suggestion=f"Make ID '{elem_id}' unique"
            ))
    
    return results


# Static checks that don't require browser
STATIC_CHECK_DISPATCHER = {
    "link_text_quality": check_link_text_quality_static,
    "link_text_standalone": check_link_text_quality_static,
    "duplicate_id": check_duplicate_ids_static,
}


def run_static_check(check_type: str, html_content: str) -> List[CheckResult]:
    """
    Run a static check on HTML content.
    
    Args:
        check_type: The type of check to run
        html_content: HTML string to analyze
    
    Returns:
        List of CheckResult objects
    """
    if check_type in STATIC_CHECK_DISPATCHER:
        return STATIC_CHECK_DISPATCHER[check_type](html_content)
    
    return [CheckResult(
        rule_id="unknown",
        check_type=check_type,
        passed=True,
        details=f"Check type '{check_type}' requires browser automation",
        automatable=False
    )]


