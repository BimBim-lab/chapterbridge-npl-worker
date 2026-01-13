"""OCR JSON text extractor for manhwa segments."""

import json
import re
from typing import List, Dict, Any
from ..utils import get_logger

logger = get_logger(__name__)


def extract_page_number(r2_key: str) -> int:
    """Extract page number from R2 key."""
    match = re.search(r'page[-_]?(\d+)', r2_key, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    match = re.search(r'(\d+)\.json$', r2_key)
    if match:
        return int(match.group(1))
    
    return 0


def extract_text_from_ocr_json(ocr_data: Dict[str, Any]) -> List[str]:
    """
    Extract text lines from OCR JSON.
    
    Supports common OCR output formats:
    - {"lines": [{"text": "..."}, ...]}
    - {"blocks": [{"lines": [{"text": "..."}]}]}
    - {"text": "..."}
    - [{"text": "..."}]
    """
    lines = []
    
    if isinstance(ocr_data, list):
        for item in ocr_data:
            if isinstance(item, dict) and 'text' in item:
                lines.append(item['text'])
            elif isinstance(item, str):
                lines.append(item)
        return lines
    
    if 'lines' in ocr_data:
        for line in ocr_data['lines']:
            if isinstance(line, dict) and 'text' in line:
                lines.append(line['text'])
            elif isinstance(line, str):
                lines.append(line)
    
    elif 'blocks' in ocr_data:
        for block in ocr_data['blocks']:
            if 'lines' in block:
                for line in block['lines']:
                    if isinstance(line, dict) and 'text' in line:
                        lines.append(line['text'])
                    elif isinstance(line, str):
                        lines.append(line)
            elif 'text' in block:
                lines.append(block['text'])
    
    elif 'text' in ocr_data:
        text = ocr_data['text']
        if isinstance(text, str):
            lines = text.split('\n')
        elif isinstance(text, list):
            lines = text
    
    elif 'words' in ocr_data:
        words = []
        for word in ocr_data['words']:
            if isinstance(word, dict) and 'text' in word:
                words.append(word['text'])
            elif isinstance(word, str):
                words.append(word)
        if words:
            lines = [' '.join(words)]
    
    return [line.strip() for line in lines if line and line.strip()]


def extract_manhwa_text(ocr_assets: List[Dict[str, Any]], ocr_contents: List[str]) -> str:
    """
    Extract clean text from manhwa OCR JSON files.
    
    Args:
        ocr_assets: List of asset records with r2_key
        ocr_contents: List of raw JSON content strings (matching assets order)
    
    Returns:
        Combined text with page separators
    """
    pages: List[tuple] = []
    
    for asset, content in zip(ocr_assets, ocr_contents):
        r2_key = asset.get('r2_key', '')
        page_num = extract_page_number(r2_key)
        
        try:
            ocr_data = json.loads(content)
            lines = extract_text_from_ocr_json(ocr_data)
            
            if lines:
                pages.append((page_num, lines))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse OCR JSON from {r2_key}: {e}")
            continue
    
    pages.sort(key=lambda x: x[0])
    
    result_parts = []
    for page_num, lines in pages:
        page_header = f"[PAGE {page_num:04d}]"
        page_text = '\n'.join(lines)
        result_parts.append(f"{page_header}\n{page_text}")
    
    logger.info(f"Extracted text from {len(pages)} manhwa pages")
    
    return '\n\n'.join(result_parts)
