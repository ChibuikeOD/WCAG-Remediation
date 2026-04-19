"""
WCAG Rules Engine - Core engine for running accessibility checks.

This module provides the RulesEngine class that:
- Loads WCAG rules from JSONC files
- Executes selector-based checks on parsed DOM
- Computes contrast ratios and other accessibility metrics
- Runs automated checks (contrast, target size, focus, link text, label in name)
- Returns structured evidence for each issue found
"""
import json
import re
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup, Tag
from datetime import datetime
import logging

from .models import (
    WCAGRule, RuleFile, WCAGLevel, WCAGPrinciple, Severity,
    IssueStatus, AccessibilityIssue, AccessibilityReport,
    DocumentInfo, PrincipleSummary, ElementLocation, SelectorCheck
)
from .config import settings

# Import automated checks
from .automated_checks import (
    CHECK_DISPATCHER,
    STATIC_CHECK_DISPATCHER,
    run_static_check,
    CheckResult,
    HAS_PLAYWRIGHT
)

logger = logging.getLogger(__name__)

# Check types that require browser automation
BROWSER_REQUIRED_CHECKS = {
    'contrast', 'non_text_contrast', 'target_size', 
    'focus_appearance', 'focus_visible', 'label_in_name'
}

# Check types that can be done statically
STATIC_CAPABLE_CHECKS = {
    'link_text_quality', 'link_text_standalone', 'duplicate_id'
}


def parse_jsonc(file_path: Path) -> Dict[str, Any]:
    """Parse a JSONC (JSON with comments) file."""
    content = file_path.read_text(encoding='utf-8')
    
    # Remove single-line comments
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Remove multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    
    return json.loads(content)


class ColorUtils:
    """Utility class for color contrast calculations."""
    
    @staticmethod
    def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c * 2 for c in hex_color])
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    @staticmethod
    def rgb_to_relative_luminance(r: int, g: int, b: int) -> float:
        """
        Calculate relative luminance per WCAG 2.0.
        WCAG 1.4.3 Contrast (Minimum)
        """
        def adjust(c: int) -> float:
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        
        return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)
    
    @staticmethod
    def calculate_contrast_ratio(color1: str, color2: str) -> float:
        """
        Calculate contrast ratio between two colors.
        WCAG 1.4.3 Contrast (Minimum)
        """
        try:
            rgb1 = ColorUtils.hex_to_rgb(color1)
            rgb2 = ColorUtils.hex_to_rgb(color2)
            
            l1 = ColorUtils.rgb_to_relative_luminance(*rgb1)
            l2 = ColorUtils.rgb_to_relative_luminance(*rgb2)
            
            lighter = max(l1, l2)
            darker = min(l1, l2)
            
            return (lighter + 0.05) / (darker + 0.05)
        except (ValueError, TypeError):
            return 0.0
    
    @staticmethod
    def is_large_text(font_size: float, is_bold: bool = False) -> bool:
        """
        Determine if text qualifies as large text per WCAG.
        Large text is 18pt+ or 14pt+ bold.
        WCAG 1.4.3 Contrast (Minimum)
        """
        if is_bold:
            return font_size >= 14
        return font_size >= 18


class RulesEngine:
    """
    Core engine for executing WCAG accessibility checks.
    
    Loads rules from JSONC files and executes them against parsed HTML/DOM.
    """
    
    def __init__(self, rules_dir: Optional[Path] = None):
        """
        Initialize the Rules Engine.
        
        Args:
            rules_dir: Path to directory containing WCAG rule files
        """
        self.rules_dir = rules_dir or settings.RULES_DIR
        self.rules: Dict[str, List[WCAGRule]] = {}
        self.rule_files: Dict[str, RuleFile] = {}
        self._load_rules()
    
    def _load_rules(self) -> None:
        """Load all WCAG rule files from the rules directory."""
        rule_files = [
            ("perceivable", "wcag_perceivable.jsonc"),
            ("operable", "wcag_operable.jsonc"),
            ("understandable", "wcag_understandable.jsonc"),
            ("robust", "wcag_robust.jsonc"),
        ]
        
        for principle_key, filename in rule_files:
            file_path = self.rules_dir / filename
            if file_path.exists():
                try:
                    data = parse_jsonc(file_path)
                    rule_file = RuleFile(**data)
                    self.rule_files[principle_key] = rule_file
                    self.rules[principle_key] = rule_file.rules
                    logger.info(f"Loaded {len(rule_file.rules)} rules from {filename}")
                except Exception as e:
                    logger.error(f"Error loading {filename}: {e}")
            else:
                logger.warning(f"Rule file not found: {file_path}")
    
    def get_all_rules(self) -> List[WCAGRule]:
        """Get all loaded rules as a flat list."""
        all_rules = []
        for rules in self.rules.values():
            all_rules.extend(rules)
        return all_rules
    
    def get_rules_by_level(self, level: WCAGLevel, include_lower: bool = True) -> List[WCAGRule]:
        """
        Get rules filtered by WCAG level.
        
        Args:
            level: Target WCAG level (A, AA, or AAA)
            include_lower: Include lower levels (e.g., A rules when targeting AA)
        """
        levels_to_include = []
        if level == WCAGLevel.AAA:
            levels_to_include = [WCAGLevel.A, WCAGLevel.AA, WCAGLevel.AAA] if include_lower else [WCAGLevel.AAA]
        elif level == WCAGLevel.AA:
            levels_to_include = [WCAGLevel.A, WCAGLevel.AA] if include_lower else [WCAGLevel.AA]
        else:
            levels_to_include = [WCAGLevel.A]
        
        return [rule for rule in self.get_all_rules() if rule.wcag_level in levels_to_include]
    
    def get_rules_by_tag(self, tag: str) -> List[WCAGRule]:
        """Get rules that have a specific tag."""
        return [rule for rule in self.get_all_rules() if tag in rule.tags]
    
    def _get_element_location(self, element: Tag, soup: BeautifulSoup) -> ElementLocation:
        """Extract location information for an element."""
        # Get a CSS-like selector path
        path_parts = []
        current = element
        while current and current.name:
            part = current.name
            if current.get('id'):
                part += f"#{current['id']}"
            elif current.get('class'):
                classes = ' '.join(current['class']) if isinstance(current['class'], list) else current['class']
                part += f".{classes.replace(' ', '.')}"
            path_parts.insert(0, part)
            current = current.parent
        
        selector = ' > '.join(path_parts[-4:])  # Last 4 parts for readability
        
        # Get HTML snippet
        html_snippet = str(element)[:200]
        if len(str(element)) > 200:
            html_snippet += "..."
        
        return ElementLocation(
            selector=selector,
            html_snippet=html_snippet
        )
    
    def _check_selector(
        self,
        soup: BeautifulSoup,
        check: SelectorCheck,
        rule: WCAGRule,
        principle: WCAGPrinciple
    ) -> List[AccessibilityIssue]:
        """
        Execute a single selector check against the DOM.
        
        Args:
            soup: Parsed HTML document
            check: The selector check to execute
            rule: The WCAG rule this check belongs to
            principle: The WCAG principle
        
        Returns:
            List of accessibility issues found
        """
        issues = []
        
        # Check if this is a special check_type that requires different handling
        check_type = getattr(check, 'check_type', None) or (
            check.model_extra.get('check_type') if hasattr(check, 'model_extra') else None
        )
        
        if check_type:
            # Handle special check types
            if check_type in STATIC_CAPABLE_CHECKS:
                # Run static check
                html_content = str(soup)
                static_results = run_static_check(check_type, html_content)
                for result in static_results:
                    if not result.passed:
                        issue = AccessibilityIssue(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            principle=principle,
                            wcag_level=rule.wcag_level,
                            status=IssueStatus.FAIL,
                            severity=Severity.ERROR,
                            message=result.details,
                            fix_suggestion=result.fix_suggestion or check.fix,
                            element_location=ElementLocation(
                                selector=result.element_selector or '',
                                html_snippet=result.element_html or ''
                            ) if result.element_selector or result.element_html else None,
                            automatable_fix=False,
                            evidence=result.evidence or {}
                        )
                        issues.append(issue)
                return issues
            
            elif check_type in BROWSER_REQUIRED_CHECKS:
                # These require Playwright - mark for deferred execution
                # They will be run separately via run_browser_checks()
                logger.debug(f"Check type '{check_type}' requires browser automation - will be run separately")
                return issues
        
        try:
            # Handle :has() pseudo-selector (not natively supported by BeautifulSoup)
            selector = check.selector
            
            # Check for :has() - we need to handle this manually
            if ':has(' in selector or ':not(:has(' in selector:
                # Skip complex selectors that require JavaScript evaluation
                # These will be handled by Playwright
                return issues
            
            # Handle :empty pseudo-selector
            if ':empty' in selector:
                base_selector = selector.replace(':empty', '')
                elements = soup.select(base_selector)
                elements = [el for el in elements if not el.get_text(strip=True) and not el.find_all()]
            else:
                elements = soup.select(selector)
            
            for element in elements:
                severity = Severity(check.severity) if hasattr(check, 'severity') and check.severity else Severity.ERROR
                
                issue = AccessibilityIssue(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    principle=principle,
                    wcag_level=rule.wcag_level,
                    status=IssueStatus.FAIL if severity == Severity.ERROR else IssueStatus.WARNING,
                    severity=severity,
                    message=check.error,
                    fix_suggestion=check.fix,
                    element_location=self._get_element_location(element, soup),
                    automatable_fix=rule.automatable and severity == Severity.ERROR,
                    evidence={
                        "tag_name": element.name,
                        "attributes": dict(element.attrs) if element.attrs else {},
                        "text_content": element.get_text(strip=True)[:100] if element.get_text(strip=True) else None
                    }
                )
                issues.append(issue)
                
        except Exception as e:
            logger.debug(f"Selector check failed for '{check.selector}': {e}")
        
        return issues
    
    def get_browser_check_types(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all check types that require browser automation.
        
        Returns:
            Dictionary mapping check_type to list of rule info
        """
        browser_checks = {}
        
        for rule in self.get_all_rules():
            for check in rule.selector_checks:
                check_type = getattr(check, 'check_type', None) or (
                    check.model_extra.get('check_type') if hasattr(check, 'model_extra') else None
                )
                if check_type in BROWSER_REQUIRED_CHECKS:
                    if check_type not in browser_checks:
                        browser_checks[check_type] = []
                    browser_checks[check_type].append({
                        'rule_id': rule.id,
                        'rule_name': rule.name,
                        'wcag_level': rule.wcag_level,
                        'check': check
                    })
        
        return browser_checks
    
    def convert_check_results_to_issues(
        self,
        results: List[CheckResult],
        principle: WCAGPrinciple
    ) -> List[AccessibilityIssue]:
        """
        Convert CheckResult objects to AccessibilityIssue objects.
        
        Args:
            results: List of CheckResult from automated checks
            principle: The WCAG principle for these issues
        
        Returns:
            List of AccessibilityIssue objects
        """
        issues = []
        
        for result in results:
            if not result.passed:
                # Look up the rule for additional context
                rule = self.get_rule_by_id(result.rule_id)
                
                issue = AccessibilityIssue(
                    rule_id=result.rule_id,
                    rule_name=rule.name if rule else f"WCAG {result.rule_id}",
                    principle=principle,
                    wcag_level=rule.wcag_level if rule else WCAGLevel.AA,
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
    
    def analyze_html(
        self,
        html_content: str,
        document_info: DocumentInfo,
        target_level: WCAGLevel = WCAGLevel.AA,
        include_aaa: bool = False
    ) -> AccessibilityReport:
        """
        Analyze HTML content for accessibility issues.
        
        Args:
            html_content: The HTML content to analyze
            document_info: Information about the document
            target_level: Target WCAG conformance level
            include_aaa: Include AAA-level checks
        
        Returns:
            Complete accessibility report
        """
        start_time = datetime.now()
        
        # Parse HTML
        soup = BeautifulSoup(html_content, 'html5lib')
        
        # Get applicable rules
        level = WCAGLevel.AAA if include_aaa else target_level
        rules = self.get_rules_by_level(level)
        
        all_issues: List[AccessibilityIssue] = []
        issues_by_principle: Dict[str, List[AccessibilityIssue]] = {
            "Perceivable": [],
            "Operable": [],
            "Understandable": [],
            "Robust": []
        }
        
        # Extract document metadata
        title_tag = soup.find('title')
        if title_tag:
            document_info.title = title_tag.get_text(strip=True)
        
        html_tag = soup.find('html')
        if html_tag and html_tag.get('lang'):
            document_info.language = html_tag.get('lang')
        
        # Execute rules
        for principle_key, rule_list in self.rules.items():
            principle = self.rule_files[principle_key].principle
            
            for rule in rule_list:
                # Skip rules above target level
                if not include_aaa and rule.wcag_level == WCAGLevel.AAA:
                    continue
                if target_level == WCAGLevel.A and rule.wcag_level != WCAGLevel.A:
                    continue
                
                # Skip deprecated rules
                if rule.deprecated:
                    continue
                
                # Execute selector checks
                for check in rule.selector_checks:
                    issues = self._check_selector(soup, check, rule, principle)
                    all_issues.extend(issues)
                    issues_by_principle[principle.value].extend(issues)
                
                # Add manual review items if rule requires it
                if rule.manual_review_required and not rule.selector_checks:
                    # Create a manual review reminder
                    issue = AccessibilityIssue(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        principle=principle,
                        wcag_level=rule.wcag_level,
                        status=IssueStatus.MANUAL_REVIEW,
                        severity=Severity.INFO,
                        message=f"Manual review required: {rule.name}",
                        fix_suggestion=rule.manual_review_notes or rule.description,
                        automatable_fix=False
                    )
                    all_issues.append(issue)
                    issues_by_principle[principle.value].append(issue)
        
        # Calculate summaries
        principle_summaries = []
        for principle_key, rule_file in self.rule_files.items():
            principle = rule_file.principle.value
            principle_issues = issues_by_principle.get(principle, [])
            
            summary = PrincipleSummary(
                principle=rule_file.principle,
                principle_number=rule_file.principle_number,
                total_issues=len(principle_issues),
                errors=len([i for i in principle_issues if i.severity == Severity.ERROR]),
                warnings=len([i for i in principle_issues if i.severity == Severity.WARNING]),
                passed=0,  # Will be calculated based on total applicable rules
                manual_review=len([i for i in principle_issues if i.status == IssueStatus.MANUAL_REVIEW])
            )
            principle_summaries.append(summary)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Build report
        report = AccessibilityReport(
            document=document_info,
            target_level=target_level,
            total_issues=len(all_issues),
            total_errors=len([i for i in all_issues if i.severity == Severity.ERROR]),
            total_warnings=len([i for i in all_issues if i.severity == Severity.WARNING]),
            total_manual_review=len([i for i in all_issues if i.status == IssueStatus.MANUAL_REVIEW]),
            principle_summaries=principle_summaries,
            issues_by_principle=issues_by_principle,
            all_issues=all_issues,
            processing_time_ms=processing_time
        )
        
        return report
    
    def get_automatable_rules(self) -> List[WCAGRule]:
        """Get all rules that can be automatically checked."""
        return [rule for rule in self.get_all_rules() if rule.automatable]
    
    def get_rule_by_id(self, rule_id: str) -> Optional[WCAGRule]:
        """Get a specific rule by its WCAG criterion ID."""
        for rule in self.get_all_rules():
            if rule.id == rule_id:
                return rule
        return None


# Singleton instance
_engine_instance: Optional[RulesEngine] = None


def get_rules_engine() -> RulesEngine:
    """Get or create the singleton RulesEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RulesEngine()
    return _engine_instance



