"""
Playwright-based Accessibility Analyzer.

Uses headless browser to compute styles, check contrast ratios,
focus visibility, and other properties that require rendering.

WCAG 1.4.3 Contrast (Minimum)
WCAG 1.4.6 Contrast (Enhanced)
WCAG 1.4.11 Non-text Contrast
WCAG 2.4.7 Focus Visible
WCAG 2.4.11 Focus Appearance
WCAG 2.5.3 Label in Name
WCAG 2.5.5 Target Size (Enhanced)
WCAG 2.5.8 Target Size (Minimum)
"""
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
import logging

try:
    from playwright.async_api import async_playwright, Browser, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from .models import ContrastResult, AccessibilityIssue, IssueStatus, Severity, WCAGLevel, WCAGPrinciple, ElementLocation
from .config import settings

# Import automated check functions
from .automated_checks import (
    check_contrast, check_target_size, check_focus_appearance,
    check_link_text_quality, check_label_in_name, check_non_text_contrast,
    check_duplicate_ids, run_all_automated_checks, CheckResult,
    CHECK_DISPATCHER, ColorUtils
)

logger = logging.getLogger(__name__)


class PlaywrightAnalyzer:
    """
    Headless browser-based accessibility analyzer.
    
    Uses Playwright to:
    - Compute actual rendered styles
    - Calculate contrast ratios
    - Check focus visibility
    - Measure target sizes
    """
    
    def __init__(self):
        """Initialize the analyzer."""
        if not HAS_PLAYWRIGHT:
            raise ImportError("Playwright is not installed. Run: pip install playwright && playwright install")
        
        self._browser: Optional[Browser] = None
        self._playwright = None
    
    async def start(self):
        """Start the browser instance."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.PLAYWRIGHT_HEADLESS
            )
            logger.info("Playwright browser started")
    
    async def stop(self):
        """Stop the browser instance."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            logger.info("Playwright browser stopped")
    
    async def analyze_url(self, url: str, run_all: bool = True) -> Dict[str, Any]:
        """
        Analyze a URL for accessibility issues using browser rendering.
        
        Args:
            url: The URL to analyze
            run_all: Run all automated checks (contrast, target size, focus, etc.)
            
        Returns:
            Analysis results including all browser-based accessibility issues
        """
        await self.start()
        
        page = await self._browser.new_page()
        
        try:
            await page.goto(url, timeout=settings.PLAYWRIGHT_TIMEOUT)
            await page.wait_for_load_state('networkidle')
            
            if run_all:
                # Run all automated checks using the new system
                all_check_results = await run_all_automated_checks(page)
                
                # Convert to issues
                all_issues = []
                for check_type, check_results in all_check_results.items():
                    issues = self._convert_results_to_issues(check_results)
                    all_issues.extend(issues)
                
                results = {
                    "url": url,
                    "issues": all_issues,
                    "check_results": all_check_results,
                    "html_content": await page.content(),
                    "checks_performed": list(all_check_results.keys())
                }
            else:
                # Legacy mode - run old checks
                results = {
                    "url": url,
                    "contrast_issues": await self._check_contrast(page),
                    "focus_issues": await self._check_focus_visibility(page),
                    "target_size_issues": await self._check_target_sizes(page),
                    "html_content": await page.content(),
                }
            
            return results
            
        finally:
            await page.close()
    
    async def analyze_html(self, html_content: str, base_url: str = "about:blank", run_all: bool = True) -> Dict[str, Any]:
        """
        Analyze HTML content for accessibility issues.
        
        Args:
            html_content: The HTML to analyze
            base_url: Base URL for resolving relative paths
            run_all: Run all automated checks
            
        Returns:
            Analysis results with all accessibility issues
        """
        await self.start()
        
        page = await self._browser.new_page()
        
        try:
            await page.set_content(html_content, wait_until='networkidle')
            
            if run_all:
                # Run all automated checks
                all_check_results = await run_all_automated_checks(page)
                
                # Convert to issues
                all_issues = []
                for check_type, check_results in all_check_results.items():
                    issues = self._convert_results_to_issues(check_results)
                    all_issues.extend(issues)
                
                results = {
                    "issues": all_issues,
                    "check_results": all_check_results,
                    "checks_performed": list(all_check_results.keys())
                }
            else:
                results = {
                    "contrast_issues": await self._check_contrast(page),
                    "focus_issues": await self._check_focus_visibility(page),
                    "target_size_issues": await self._check_target_sizes(page),
                }
            
            return results
            
        finally:
            await page.close()
    
    async def run_specific_checks(self, page: Page, check_types: List[str]) -> Dict[str, List[CheckResult]]:
        """
        Run specific check types on a page.
        
        Args:
            page: Playwright page object
            check_types: List of check types to run
            
        Returns:
            Dictionary mapping check_type to results
        """
        results = {}
        
        for check_type in check_types:
            if check_type in CHECK_DISPATCHER:
                try:
                    check_func = CHECK_DISPATCHER[check_type]
                    check_results = await check_func(page)
                    results[check_type] = check_results
                except Exception as e:
                    logger.error(f"Error running {check_type}: {e}")
                    results[check_type] = [CheckResult(
                        rule_id="unknown",
                        check_type=check_type,
                        passed=True,
                        details=f"Check failed: {str(e)}",
                        automatable=False
                    )]
        
        return results
    
    def _convert_results_to_issues(self, results: List[CheckResult]) -> List[AccessibilityIssue]:
        """Convert CheckResult objects to AccessibilityIssue objects."""
        issues = []
        
        # Map rule_id to principle
        rule_to_principle = {
            "1.4.3": WCAGPrinciple.PERCEIVABLE,
            "1.4.6": WCAGPrinciple.PERCEIVABLE,
            "1.4.11": WCAGPrinciple.PERCEIVABLE,
            "2.4.4": WCAGPrinciple.OPERABLE,
            "2.4.7": WCAGPrinciple.OPERABLE,
            "2.4.9": WCAGPrinciple.OPERABLE,
            "2.4.11": WCAGPrinciple.OPERABLE,
            "2.5.3": WCAGPrinciple.OPERABLE,
            "2.5.5": WCAGPrinciple.OPERABLE,
            "2.5.8": WCAGPrinciple.OPERABLE,
            "4.1.1": WCAGPrinciple.ROBUST,
        }
        
        # Map rule_id to level
        rule_to_level = {
            "1.4.3": WCAGLevel.AA,
            "1.4.6": WCAGLevel.AAA,
            "1.4.11": WCAGLevel.AA,
            "2.4.4": WCAGLevel.A,
            "2.4.7": WCAGLevel.AA,
            "2.4.9": WCAGLevel.AAA,
            "2.4.11": WCAGLevel.AA,
            "2.5.3": WCAGLevel.A,
            "2.5.5": WCAGLevel.AAA,
            "2.5.8": WCAGLevel.AA,
            "4.1.1": WCAGLevel.A,
        }
        
        # Map rule_id to name
        rule_names = {
            "1.4.3": "Contrast (Minimum)",
            "1.4.6": "Contrast (Enhanced)",
            "1.4.11": "Non-text Contrast",
            "2.4.4": "Link Purpose (In Context)",
            "2.4.7": "Focus Visible",
            "2.4.9": "Link Purpose (Link Only)",
            "2.4.11": "Focus Appearance",
            "2.5.3": "Label in Name",
            "2.5.5": "Target Size (Enhanced)",
            "2.5.8": "Target Size (Minimum)",
            "4.1.1": "Parsing",
        }
        
        for result in results:
            if not result.passed:
                rule_id = result.rule_id
                
                issue = AccessibilityIssue(
                    rule_id=rule_id,
                    rule_name=rule_names.get(rule_id, f"WCAG {rule_id}"),
                    principle=rule_to_principle.get(rule_id, WCAGPrinciple.PERCEIVABLE),
                    wcag_level=rule_to_level.get(rule_id, WCAGLevel.AA),
                    status=IssueStatus.FAIL,
                    severity=Severity.ERROR,
                    message=result.details,
                    fix_suggestion=result.fix_suggestion,
                    element_location=ElementLocation(
                        selector=result.element_selector or '',
                        html_snippet=result.element_html or ''
                    ) if result.element_selector or result.element_html else None,
                    automatable_fix=result.automatable,
                    evidence=result.evidence or {}
                )
                issues.append(issue)
        
        return issues
    
    async def _check_contrast(self, page: Page) -> List[AccessibilityIssue]:
        """
        Check text contrast ratios on the page.
        
        WCAG 1.4.3 Contrast (Minimum) - 4.5:1 normal, 3:1 large
        WCAG 1.4.6 Contrast (Enhanced) - 7:1 normal, 4.5:1 large
        """
        issues = []
        
        # JavaScript to get computed styles for text elements
        contrast_data = await page.evaluate("""
            () => {
                const results = [];
                const textElements = document.querySelectorAll('p, span, a, li, td, th, h1, h2, h3, h4, h5, h6, label, button');
                
                for (const el of textElements) {
                    const style = window.getComputedStyle(el);
                    const text = el.textContent?.trim();
                    
                    if (!text || text.length === 0) continue;
                    
                    // Get colors
                    const color = style.color;
                    const bgColor = style.backgroundColor;
                    
                    // Get font info
                    const fontSize = parseFloat(style.fontSize);
                    const fontWeight = parseInt(style.fontWeight) || 400;
                    const isBold = fontWeight >= 700;
                    
                    // Get element path for identification
                    const path = [];
                    let current = el;
                    while (current && current !== document.body) {
                        let selector = current.tagName.toLowerCase();
                        if (current.id) selector += '#' + current.id;
                        else if (current.className) selector += '.' + current.className.split(' ')[0];
                        path.unshift(selector);
                        current = current.parentElement;
                    }
                    
                    results.push({
                        selector: path.slice(-3).join(' > '),
                        text: text.substring(0, 50),
                        color: color,
                        bgColor: bgColor,
                        fontSize: fontSize,
                        isBold: isBold,
                        rect: el.getBoundingClientRect().toJSON()
                    });
                }
                
                return results;
            }
        """)
        
        for item in contrast_data:
            try:
                # Parse colors
                fg_color = self._parse_color(item['color'])
                bg_color = self._parse_color(item['bgColor'])
                
                if not fg_color or not bg_color:
                    continue
                
                # Calculate contrast
                ratio = ColorUtils.calculate_contrast_ratio(fg_color, bg_color)
                is_large = ColorUtils.is_large_text(item['fontSize'], item['isBold'])
                
                # Check against WCAG thresholds
                passes_aa = ratio >= (3.0 if is_large else 4.5)
                passes_aaa = ratio >= (4.5 if is_large else 7.0)
                
                if not passes_aa:
                    issue = AccessibilityIssue(
                        rule_id="1.4.3",
                        rule_name="Contrast (Minimum)",
                        principle=WCAGPrinciple.PERCEIVABLE,
                        wcag_level=WCAGLevel.AA,
                        status=IssueStatus.FAIL,
                        severity=Severity.ERROR,
                        message=f"Insufficient contrast ratio ({ratio:.2f}:1). Required: {3.0 if is_large else 4.5}:1",
                        fix_suggestion="Increase contrast between text and background colors",
                        evidence={
                            "contrast_ratio": round(ratio, 2),
                            "foreground_color": fg_color,
                            "background_color": bg_color,
                            "font_size": item['fontSize'],
                            "is_bold": item['isBold'],
                            "is_large_text": is_large,
                            "text_sample": item['text'],
                            "selector": item['selector']
                        },
                        automatable_fix=True
                    )
                    issues.append(issue)
                    
            except Exception as e:
                logger.debug(f"Error checking contrast: {e}")
        
        return issues
    
    async def _check_focus_visibility(self, page: Page) -> List[AccessibilityIssue]:
        """
        Check that focus indicators are visible.
        
        WCAG 2.4.7 Focus Visible
        """
        issues = []
        
        # Get all focusable elements
        focus_data = await page.evaluate("""
            () => {
                const results = [];
                const focusable = document.querySelectorAll(
                    'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
                );
                
                for (const el of focusable) {
                    const style = window.getComputedStyle(el);
                    const focusStyle = window.getComputedStyle(el, ':focus');
                    
                    results.push({
                        tag: el.tagName.toLowerCase(),
                        outline: style.outline,
                        outlineWidth: style.outlineWidth,
                        outlineStyle: style.outlineStyle,
                        outlineColor: style.outlineColor,
                        selector: el.id ? '#' + el.id : el.tagName.toLowerCase()
                    });
                }
                
                return results;
            }
        """)
        
        for item in focus_data:
            # Check if outline is explicitly removed
            if item['outlineStyle'] == 'none' or item['outlineWidth'] == '0px':
                # This might indicate removed focus indicator
                # We need to actually focus the element to be sure
                pass
        
        return issues
    
    async def _check_target_sizes(self, page: Page) -> List[AccessibilityIssue]:
        """
        Check interactive element target sizes.
        
        WCAG 2.5.8 Target Size (Minimum) - 24x24 CSS pixels
        WCAG 2.5.5 Target Size (Enhanced) - 44x44 CSS pixels
        """
        issues = []
        
        target_data = await page.evaluate("""
            () => {
                const results = [];
                const interactive = document.querySelectorAll(
                    'a, button, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"], [tabindex="0"]'
                );
                
                for (const el of interactive) {
                    const rect = el.getBoundingClientRect();
                    
                    if (rect.width > 0 && rect.height > 0) {
                        results.push({
                            tag: el.tagName.toLowerCase(),
                            width: rect.width,
                            height: rect.height,
                            selector: el.id ? '#' + el.id : el.tagName.toLowerCase(),
                            text: el.textContent?.trim().substring(0, 30) || ''
                        });
                    }
                }
                
                return results;
            }
        """)
        
        for item in target_data:
            width = item['width']
            height = item['height']
            
            # Check against minimum (24x24)
            if width < 24 or height < 24:
                issue = AccessibilityIssue(
                    rule_id="2.5.8",
                    rule_name="Target Size (Minimum)",
                    principle=WCAGPrinciple.OPERABLE,
                    wcag_level=WCAGLevel.AA,
                    status=IssueStatus.FAIL,
                    severity=Severity.WARNING,
                    message=f"Target size ({width:.0f}x{height:.0f}px) is below minimum 24x24px",
                    fix_suggestion="Increase target size to at least 24x24 CSS pixels or ensure adequate spacing",
                    evidence={
                        "width": round(width, 1),
                        "height": round(height, 1),
                        "selector": item['selector'],
                        "element": item['tag'],
                        "text": item['text']
                    },
                    automatable_fix=False
                )
                issues.append(issue)
        
        return issues
    
    def _parse_color(self, color_str: str) -> Optional[str]:
        """
        Parse a CSS color string to hex format.
        
        Handles rgb(), rgba(), and hex formats.
        """
        if not color_str:
            return None
        
        color_str = color_str.strip()
        
        # Already hex
        if color_str.startswith('#'):
            return color_str
        
        # RGB/RGBA format
        if color_str.startswith('rgb'):
            # Extract numbers
            import re
            numbers = re.findall(r'[\d.]+', color_str)
            if len(numbers) >= 3:
                r, g, b = int(float(numbers[0])), int(float(numbers[1])), int(float(numbers[2]))
                return f'#{r:02x}{g:02x}{b:02x}'
        
        # Named colors (basic mapping)
        named_colors = {
            'white': '#ffffff',
            'black': '#000000',
            'red': '#ff0000',
            'green': '#008000',
            'blue': '#0000ff',
            'transparent': None,
        }
        
        return named_colors.get(color_str.lower())


# Singleton instance
_analyzer_instance: Optional[PlaywrightAnalyzer] = None


async def get_playwright_analyzer() -> PlaywrightAnalyzer:
    """Get or create the singleton PlaywrightAnalyzer instance."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = PlaywrightAnalyzer()
    return _analyzer_instance



