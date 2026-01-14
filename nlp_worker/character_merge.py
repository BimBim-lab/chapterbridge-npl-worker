"""Character merge logic for novel segments with profile-based descriptions."""

import re
import unicodedata
from typing import List, Dict, Any, Optional, Set
from .utils import get_logger

logger = get_logger(__name__)


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


def generate_character_description(profile: Dict[str, str], name: str = "") -> str:
    """
    Generate 2-4 sentence character description from profile.
    
    Args:
        profile: Character profile dict with fields
        name: Character name for context
    
    Returns:
        Formatted description string (2-4 sentences)
    """
    if not profile or not isinstance(profile, dict):
        return ""
    
    sentences = []
    
    # Sentence 1: Role + occupation/rank (core identity)
    role = profile.get('role_identity', '').strip()
    occupation = profile.get('occupation_rank_status', '').strip()
    
    if role and occupation:
        sentences.append(f"{name} adalah {role} dengan status {occupation}.")
    elif role:
        sentences.append(f"{name} adalah {role}.")
    elif occupation:
        sentences.append(f"{name} memiliki status {occupation}.")
    
    # Sentence 2: Ability + personality (core traits)
    ability = profile.get('core_ability_or_skill', '').strip()
    personality = profile.get('core_personality', '').strip()
    
    if ability and personality:
        sentences.append(f"Memiliki kemampuan {ability} dengan kepribadian {personality}.")
    elif ability:
        sentences.append(f"Memiliki kemampuan {ability}.")
    elif personality:
        sentences.append(f"Kepribadian {personality}.")
    
    # Sentence 3: Goal/motivation (optional but important)
    goal = profile.get('motivation_or_goal', '').strip()
    if goal:
        sentences.append(f"Tujuannya adalah {goal}.")
    
    # Sentence 4: Notable extras (affiliation, appearance, backstory, secret)
    extras = []
    
    affiliation = profile.get('affiliation', '').strip()
    if affiliation:
        extras.append(f"tergabung dalam {affiliation}")
    
    appearance = profile.get('distinctive_appearance', '').strip()
    if appearance:
        extras.append(f"{appearance}")
    
    backstory = profile.get('backstory_hook', '').strip()
    if backstory:
        extras.append(backstory)
    
    secret = profile.get('notable_constraint_or_secret', '').strip()
    if secret:
        extras.append(secret)
    
    if extras:
        sentences.append(f"{', '.join(extras[:2])}.")  # Max 2 extras to keep it concise
    
    # Combine into 2-4 sentences
    description = " ".join(sentences[:4])  # Cap at 4 sentences
    return description if description else ""


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
    
    # Simple check: prefer new if longer and substantial
    if not existing_norm:
        return True
    
    if len(new_desc) > len(existing_desc) * 1.5 and len(new_desc) > 50:
        return True
    
    return False


def process_character_updates(
    work_id: str,
    work_characters: List[Dict],
    character_updates: List[Any],  # Can be List[CharacterUpdateModel] or List[Dict]
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
        # Support both dict and CharacterUpdateModel
        if hasattr(char_update, 'name'):
            # CharacterUpdateModel instance
            name = (char_update.name or '').strip()
            aliases = char_update.aliases or []
            facts = char_update.facts or []
        else:
            # Dict (backward compatibility)
            name = (char_update.get('name') or '').strip()
            aliases = char_update.get('aliases') or []
            facts = char_update.get('facts') or []
        
        if not name:
            logger.debug("Skipping character with empty name")
            stats['skipped'] += 1
            continue
        
        # Don't generate description - leave empty per user request
        description = ""
        
        # Convert facts array to character_facts format for storage
        new_facts = []
        for fact in facts:
            if fact and str(fact).strip():
                new_facts.append({
                    'fact': str(fact).strip(),
                    'segment': segment_number,
                    'source': source_id
                })
        
        existing = find_existing_character(work_characters, name, aliases)
        
        if existing:
            merged_aliases = merge_aliases(
                existing.get('aliases', []), 
                aliases,
                existing.get('name', '')
            )
            
            # Merge new facts with existing facts (simple append)
            existing_facts = existing.get('character_facts', [])
            merged_facts = existing_facts + new_facts
            
            db_client.update_character(existing['id'], {
                'aliases': merged_aliases,
                'character_facts': merged_facts,
                'description': '',  # Keep empty
                'model_version': model_version
            })
            
            existing['aliases'] = merged_aliases
            existing['character_facts'] = merged_facts
            
            stats['updated'] += 1
            logger.debug(f"Updated character: {name} (aliases: {len(merged_aliases)}, facts: {len(merged_facts)})")
        else:
            clean_aliases = merge_aliases([], aliases, name)
            
            new_char = db_client.upsert_character(
                work_id=work_id,
                name=name,
                aliases=clean_aliases,
                character_facts=new_facts,
                description='',  # Keep empty per user request
                model_version=model_version
            )
            
            if new_char:
                work_characters.append(new_char)
            
            stats['inserted'] += 1
            logger.debug(f"Inserted new character: {name}")
    
    logger.info(f"Character updates complete: {stats}")
    return stats
