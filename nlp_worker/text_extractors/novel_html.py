"""HTML text extractor for novel segments."""

import re
from typing import List, Set
from bs4 import BeautifulSoup
from ..utils import get_logger

logger = get_logger(__name__)

REMOVE_TAGS = [
    'script', 'style', 'nav', 'footer', 'header', 'aside',
    'noscript', 'iframe', 'form', 'button', 'input', 'select',
    'textarea', 'svg', 'canvas', 'video', 'audio', 'figure',
    'figcaption', 'meta', 'link'
]

BOILERPLATE_PATTERNS = [
    r'chapter\s+\d+\s*[-:]\s*$',
    r'^advertisement$',
    r'^sponsored\s+content$',
    r'^please\s+support\s+us',
    r'^join\s+our\s+discord',
    r'^read\s+more\s+at',
    r'^translator[:\s]',
    r'^editor[:\s]',
    r'^proofreader[:\s]',
    r'^tip\s+jar',
    r'^patreon',
    r'^ko-?fi',
    r'^copyright\s+\d{4}',
    r'all\s+rights\s+reserved',
    r'^next\s+chapter',
    r'^previous\s+chapter',
    r'^table\s+of\s+contents',
    r'^loading',
    r'^comments?\s*\(\d+\)',
]

BOILERPLATE_REGEX = re.compile('|'.join(BOILERPLATE_PATTERNS), re.IGNORECASE)


def extract_paragraphs(soup: BeautifulSoup) -> List[str]:
    """Extract paragraph text from soup."""
    paragraphs = []
    
    for tag in REMOVE_TAGS:
        for elem in soup.find_all(tag):
            elem.decompose()
    
    for elem in soup.find_all(class_=re.compile(r'(?i)(ad|sidebar|widget|social|share|comment|footer|header|nav|menu)')):
        elem.decompose()
    
    content_area = soup.find(class_=re.compile(r'(?i)(content|chapter|reading|text|entry|article|post-content)'))
    if not content_area:
        content_area = soup.find('article') or soup.find('main') or soup.body or soup
    
    for p in content_area.find_all(['p', 'div']):
        if p.find_all(['p', 'div']):
            continue
        
        text = p.get_text(separator=' ', strip=True)
        
        if text and len(text) > 10:
            paragraphs.append(text)
    
    return paragraphs


def clean_paragraphs(paragraphs: List[str]) -> List[str]:
    """Clean and dedupe paragraphs, removing boilerplate."""
    cleaned = []
    seen: Set[str] = set()
    
    for para in paragraphs:
        para = re.sub(r'\s+', ' ', para).strip()
        
        if BOILERPLATE_REGEX.search(para):
            continue
        
        normalized = para.lower()
        if normalized in seen:
            continue
        
        if len(para) < 20 and not any(c.isalpha() for c in para):
            continue
        
        seen.add(normalized)
        cleaned.append(para)
    
    return cleaned


def extract_novel_text(html_content: str) -> str:
    """
    Extract clean story text from HTML content.
    
    Args:
        html_content: Raw HTML content
    
    Returns:
        Clean text with paragraphs separated by blank lines
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    paragraphs = extract_paragraphs(soup)
    cleaned = clean_paragraphs(paragraphs)
    
    logger.info(f"Extracted {len(cleaned)} paragraphs from HTML")
    
    return '\n\n'.join(cleaned)
