"""Character merge logic for novel segments with improved alias matching and deduplication."""

import re
import unicodedata
from typing import List, Dict, Any, Optional, Set
from .utils import get_logger

logger = get_logger(__name__)

BOILERPLATE_DESCRIPTIONS = {
    'unknown', 'n/a', 'none', 'no description', 'to be determined',
    'main character', 'protagonist', 'antagonist', 'supporting character'
}


def normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip, normalize unicode, remove extra spaces."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s\'-]', '', text)
    return text


def normalize_alias(alias: str) -> str:
    """Normalize an alias for comparison and deduplication."""
    if not alias:
        return ""
    normalized = normalize_text(alias)
    normalized = re.sub(r"['\"]", "", normalized)
    return normalized.strip()


def find_existing_character(
    work_characters: List[Dict],
    name: str,
    aliases: List[str]
) -> Optional[Dict]:
    """
    Find an existing character by name or alias match (case-insensitive).
    
    Checks:
    1. Exact name match (normalized)
    2. Any new alias matches existing name
    3. Any new alias matches any existing alias
    4. New name matches any existing alias
    
    Args:
        work_characters: List of existing character records
        name: The character name to find
        aliases: List of aliases to check
    
    Returns:
        Matching character record or None
    """
    name_normalized = normalize_alias(name)
    
    all_search_terms: Set[str] = {name_normalized}
    for alias in aliases:
        norm = normalize_alias(alias)
        if norm:
            all_search_terms.add(norm)
    
    for char in work_characters:
        char_name_normalized = normalize_alias(char.get('name', ''))
        
        if char_name_normalized in all_search_terms:
            return char
        
        existing_aliases = char.get('aliases', []) or []
        for existing_alias in existing_aliases:
            if normalize_alias(existing_alias) in all_search_terms:
                return char
    
    return None


def merge_aliases(existing: List[str], new: List[str], canonical_name: str = "") -> List[str]:
    """
    Merge alias lists with proper deduplication.
    
    - Dedupes by normalized form
    - Preserves original casing of first occurrence
    - Excludes the canonical name from aliases
    """
    seen_normalized: Set[str] = set()
    result: List[str] = []
    
    canonical_norm = normalize_alias(canonical_name)
    if canonical_norm:
        seen_normalized.add(canonical_norm)
    
    for alias in (existing or []) + (new or []):
        if not alias or not alias.strip():
            continue
        
        normalized = normalize_alias(alias)
        if not normalized:
            continue
        
        if normalized not in seen_normalized:
            seen_normalized.add(normalized)
            result.append(alias.strip())
    
    return result


def normalize_fact_for_dedupe(fact: Dict) -> str:
    """
    Create a normalized key for fact deduplication.
    
    Combines: normalized fact text + optional chapter/segment reference
    """
    text = fact.get('fact', '')
    normalized = normalize_text(text)
    
    chapter = fact.get('chapter') or fact.get('segment')
    if chapter:
        return f"{normalized}__ch{chapter}"
    
    return normalized


def merge_character_facts(
    existing: List[Dict],
    new: List[Dict],
    segment_number: int,
    source_id: Optional[str] = None
) -> List[Dict]:
    """
    Merge character facts with improved deduplication.
    
    - Dedupes by normalized text + chapter/segment
    - Adds segment number to new facts without chapter/segment
    - Optionally adds source identifier
    """
    seen_facts: Set[str] = set()
    result: List[Dict] = []
    
    for fact in (existing or []):
        key = normalize_fact_for_dedupe(fact)
        if key and key not in seen_facts:
            seen_facts.add(key)
            result.append(fact)
    
    for fact in (new or []):
        fact_text = fact.get('fact', '').strip()
        if not fact_text:
            continue
        
        new_fact = dict(fact)
        
        if 'chapter' not in new_fact and 'segment' not in new_fact:
            new_fact['segment'] = segment_number
        
        if source_id and 'source' not in new_fact:
            new_fact['source'] = source_id
        
        key = normalize_fact_for_dedupe(new_fact)
        if key and key not in seen_facts:
            seen_facts.add(key)
            result.append(new_fact)
    
    return result


def should_update_description(existing_desc: str, new_desc: str) -> bool:
    """
    Determine if description should be updated.
    
    Update if:
    - Existing is empty/boilerplate and new is meaningful
    - New is significantly longer and not boilerplate
    """
    existing_norm = normalize_text(existing_desc or "")
    new_norm = normalize_text(new_desc or "")
    
    if not new_norm:
        return False
    
    if new_norm in BOILERPLATE_DESCRIPTIONS:
        return False
    
    if not existing_norm or existing_norm in BOILERPLATE_DESCRIPTIONS:
        return True
    
    if len(new_desc) > len(existing_desc) * 1.5 and len(new_desc) > 50:
        return True
    
    return False


def process_character_updates(
    work_id: str,
    work_characters: List[Dict],
    character_updates: List[Dict],
    segment_number: int,
    model_version: str,
    db_client: Any,
    media_type: str = 'novel'
) -> Dict[str, int]:
    """
    Process character updates from model output (NOVEL ONLY).
    
    Args:
        work_id: The work ID
        work_characters: Existing characters for this work
        character_updates: New character data from model
        segment_number: Current segment number
        model_version: Model version string
        db_client: Database client for updates
        media_type: Media type (only processes if 'novel')
    
    Returns:
        Stats dict with counts of inserted/updated/skipped
    """
    stats = {'inserted': 0, 'updated': 0, 'skipped': 0}
    
    if media_type != 'novel':
        logger.info(f"Skipping character updates for media_type={media_type} (novel only)")
        stats['skipped'] = len(character_updates) if character_updates else 0
        return stats
    
    if not character_updates:
        return stats
    
    source_id = f"segment_{segment_number}"
    
    for char_update in character_updates:
        name = (char_update.get('name') or '').strip()
        if not name:
            stats['skipped'] += 1
            continue
        
        aliases = char_update.get('aliases') or []
        facts = char_update.get('character_facts') or []
        description = (char_update.get('description') or '').strip()
        
        existing = find_existing_character(work_characters, name, aliases)
        
        if existing:
            merged_aliases = merge_aliases(
                existing.get('aliases', []), 
                aliases,
                existing.get('name', '')
            )
            merged_facts = merge_character_facts(
                existing.get('character_facts', []),
                facts,
                segment_number,
                source_id
            )
            
            new_description = existing.get('description', '')
            if should_update_description(new_description, description):
                new_description = description
            
            db_client.update_character(existing['id'], {
                'aliases': merged_aliases,
                'character_facts': merged_facts,
                'description': new_description,
                'model_version': model_version
            })
            
            existing['aliases'] = merged_aliases
            existing['character_facts'] = merged_facts
            existing['description'] = new_description
            
            stats['updated'] += 1
            logger.debug(f"Updated character: {name} (aliases: {len(merged_aliases)}, facts: {len(merged_facts)})")
        else:
            formatted_facts = []
            for fact in facts:
                new_fact = dict(fact)
                if 'chapter' not in new_fact and 'segment' not in new_fact:
                    new_fact['segment'] = segment_number
                if 'source' not in new_fact:
                    new_fact['source'] = source_id
                formatted_facts.append(new_fact)
            
            clean_aliases = merge_aliases([], aliases, name)
            
            new_char = db_client.upsert_character(
                work_id=work_id,
                name=name,
                aliases=clean_aliases,
                character_facts=formatted_facts,
                description=description if description not in BOILERPLATE_DESCRIPTIONS else '',
                model_version=model_version
            )
            
            if new_char:
                work_characters.append(new_char)
            
            stats['inserted'] += 1
            logger.debug(f"Inserted new character: {name}")
    
    logger.info(f"Character updates complete: {stats}")
    return stats
