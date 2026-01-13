"""Subtitle (SRT/VTT) text extractor for anime segments."""

import re
from typing import List
from ..utils import get_logger

logger = get_logger(__name__)

NOISE_PATTERNS = [
    r'\[MUSIC\]',
    r'\[♪.*?\]',
    r'\[music\]',
    r'\[Music\]',
    r'♪.*?♪',
    r'\[.*?PLAYING\]',
    r'\[.*?playing\]',
    r'\(.*?music.*?\)',
    r'\[SILENCE\]',
    r'\[silence\]',
]

NOISE_REGEX = re.compile('|'.join(NOISE_PATTERNS), re.IGNORECASE)


def parse_srt(content: str) -> List[str]:
    """Parse SRT subtitle file and extract dialogue text."""
    lines = []
    current_text = []
    in_text_block = False
    
    for line in content.split('\n'):
        line = line.strip()
        
        if not line:
            if current_text:
                lines.append(' '.join(current_text))
                current_text = []
            in_text_block = False
            continue
        
        if line.isdigit():
            in_text_block = False
            continue
        
        if '-->' in line:
            in_text_block = True
            continue
        
        if in_text_block:
            cleaned = re.sub(r'<[^>]+>', '', line)
            cleaned = re.sub(r'\{[^}]+\}', '', cleaned)
            cleaned = cleaned.strip()
            if cleaned:
                current_text.append(cleaned)
    
    if current_text:
        lines.append(' '.join(current_text))
    
    return lines


def parse_vtt(content: str) -> List[str]:
    """Parse VTT subtitle file and extract dialogue text."""
    lines = []
    current_text = []
    in_cue = False
    
    content_lines = content.split('\n')
    
    for i, line in enumerate(content_lines):
        line = line.strip()
        
        if line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue
        
        if '-->' in line:
            in_cue = True
            continue
        
        if not line:
            if current_text:
                lines.append(' '.join(current_text))
                current_text = []
            in_cue = False
            continue
        
        if in_cue:
            cleaned = re.sub(r'<[^>]+>', '', line)
            cleaned = re.sub(r'\{[^}]+\}', '', cleaned)
            cleaned = cleaned.strip()
            if cleaned:
                current_text.append(cleaned)
    
    if current_text:
        lines.append(' '.join(current_text))
    
    return lines


def clean_dialogue_lines(lines: List[str]) -> List[str]:
    """Remove noise patterns and clean dialogue lines."""
    cleaned = []
    seen = set()
    
    for line in lines:
        line = NOISE_REGEX.sub('', line).strip()
        
        if not line or len(line) < 2:
            continue
        
        normalized = line.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        
        cleaned.append(line)
    
    return cleaned


def extract_subtitle_text(content: str, filename: str = '') -> str:
    """
    Extract clean dialogue text from subtitle file.
    
    Args:
        content: Raw subtitle file content
        filename: Optional filename to help detect format
    
    Returns:
        Clean text with dialogue in chronological order
    """
    filename_lower = filename.lower()
    
    if filename_lower.endswith('.vtt') or content.strip().startswith('WEBVTT'):
        lines = parse_vtt(content)
    else:
        lines = parse_srt(content)
    
    cleaned = clean_dialogue_lines(lines)
    
    logger.info(f"Extracted {len(cleaned)} dialogue lines from subtitle")
    
    return '\n'.join(cleaned)
