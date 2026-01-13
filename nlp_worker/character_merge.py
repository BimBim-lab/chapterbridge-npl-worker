"""Character merge logic for novel segments."""

from typing import List, Dict, Any, Optional
from .utils import get_logger

logger = get_logger(__name__)


def normalize_name(name: str) -> str:
    """Normalize a name for comparison."""
    return name.lower().strip()


def find_existing_character(
    work_characters: List[Dict],
    name: str,
    aliases: List[str]
) -> Optional[Dict]:
    """
    Find an existing character by name or alias match.
    
    Args:
        work_characters: List of existing character records
        name: The character name to find
        aliases: List of aliases to check
    
    Returns:
        Matching character record or None
    """
    name_normalized = normalize_name(name)
    aliases_normalized = {normalize_name(a) for a in aliases}
    aliases_normalized.add(name_normalized)
    
    for char in work_characters:
        char_name_normalized = normalize_name(char['name'])
        
        if char_name_normalized in aliases_normalized:
            return char
        
        existing_aliases = char.get('aliases', [])
        for alias in existing_aliases:
            if normalize_name(alias) in aliases_normalized:
                return char
    
    return None


def merge_aliases(existing: List[str], new: List[str]) -> List[str]:
    """Merge alias lists, deduping by normalized name."""
    seen = set()
    result = []
    
    for alias in existing + new:
        normalized = normalize_name(alias)
        if normalized not in seen:
            seen.add(normalized)
            result.append(alias)
    
    return result


def normalize_fact_text(fact: Dict) -> str:
    """Normalize a fact for deduplication."""
    text = fact.get('fact', '')
    return text.lower().strip()


def merge_character_facts(
    existing: List[Dict],
    new: List[Dict],
    segment_number: int
) -> List[Dict]:
    """
    Merge character facts, deduping by normalized text.
    
    Args:
        existing: Existing facts list
        new: New facts to add
        segment_number: Current segment number for context
    
    Returns:
        Merged facts list
    """
    seen_facts = {normalize_fact_text(f) for f in existing}
    result = list(existing)
    
    for fact in new:
        normalized = normalize_fact_text(fact)
        if normalized and normalized not in seen_facts:
            if 'chapter' not in fact and 'segment' not in fact:
                fact['segment'] = segment_number
            result.append(fact)
            seen_facts.add(normalized)
    
    return result


def process_character_updates(
    work_id: str,
    work_characters: List[Dict],
    character_updates: List[Dict],
    segment_number: int,
    model_version: str,
    db_client: Any
) -> Dict[str, int]:
    """
    Process character updates from model output.
    
    Args:
        work_id: The work ID
        work_characters: Existing characters for this work
        character_updates: New character data from model
        segment_number: Current segment number
        model_version: Model version string
        db_client: Database client for updates
    
    Returns:
        Stats dict with counts of inserted/updated
    """
    stats = {'inserted': 0, 'updated': 0}
    
    for char_update in character_updates:
        name = char_update.get('name', '').strip()
        if not name:
            continue
        
        aliases = char_update.get('aliases', [])
        facts = char_update.get('character_facts', [])
        description = char_update.get('description', '')
        
        existing = find_existing_character(work_characters, name, aliases)
        
        if existing:
            merged_aliases = merge_aliases(existing.get('aliases', []), aliases)
            merged_facts = merge_character_facts(
                existing.get('character_facts', []),
                facts,
                segment_number
            )
            
            new_description = description
            if not new_description or (existing.get('description') and len(existing['description']) > len(description)):
                new_description = existing.get('description', '')
            
            db_client.update_character(existing['id'], {
                'aliases': merged_aliases,
                'character_facts': merged_facts,
                'description': new_description,
                'model_version': model_version
            })
            
            existing['aliases'] = merged_aliases
            existing['character_facts'] = merged_facts
            
            stats['updated'] += 1
            logger.info(f"Updated character: {name}")
        else:
            formatted_facts = []
            for fact in facts:
                if 'chapter' not in fact and 'segment' not in fact:
                    fact['segment'] = segment_number
                formatted_facts.append(fact)
            
            new_char = db_client.upsert_character(
                work_id=work_id,
                name=name,
                aliases=aliases,
                character_facts=formatted_facts,
                description=description,
                model_version=model_version
            )
            
            if new_char:
                work_characters.append(new_char)
            
            stats['inserted'] += 1
            logger.info(f"Inserted new character: {name}")
    
    return stats
