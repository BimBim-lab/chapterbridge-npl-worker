"""Pydantic models and schema validation for NLP pack model output."""

import json
import re
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator
from .utils import get_logger

logger = get_logger(__name__)


class ToneModel(BaseModel):
    """Tone analysis model."""
    primary: str = ""
    secondary: List[str] = Field(default_factory=list)
    intensity: float = 0.5

    @field_validator('secondary', mode='before')
    @classmethod
    def ensure_secondary_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v) if v else []


class DialogueModel(BaseModel):
    """Key dialogue entry."""
    speaker: str
    text: str
    to: Optional[str] = None
    importance: str = "normal"


class BeatModel(BaseModel):
    """Story beat model."""
    type: str = ""
    description: str = ""


class SegmentSummaryModel(BaseModel):
    """Segment summary model with all required fields."""
    summary: str = ""
    summary_short: str = ""
    events: List[str] = Field(default_factory=list)
    beats: List[Dict[str, Any]] = Field(default_factory=list)
    key_dialogue: List[Dict[str, Any]] = Field(default_factory=list)
    tone: Dict[str, Any] = Field(default_factory=lambda: {"primary": "", "secondary": [], "intensity": 0.5})

    @field_validator('events', mode='before')
    @classmethod
    def ensure_events_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v) if v else []

    @field_validator('beats', 'key_dialogue', mode='before')
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        return list(v) if v else []

    @field_validator('tone', mode='before')
    @classmethod
    def ensure_tone_dict(cls, v):
        if v is None or not isinstance(v, dict):
            return {"primary": "", "secondary": [], "intensity": 0.5}
        if 'secondary' not in v or v['secondary'] is None:
            v['secondary'] = []
        if 'intensity' not in v or v['intensity'] is None:
            v['intensity'] = 0.5
        return v


class SegmentEntitiesModel(BaseModel):
    """Segment entities model - all fields must be lists."""
    characters: List[Any] = Field(default_factory=list)
    locations: List[Any] = Field(default_factory=list)
    items: List[Any] = Field(default_factory=list)
    time_refs: List[Any] = Field(default_factory=list)
    organizations: List[Any] = Field(default_factory=list)
    factions: List[Any] = Field(default_factory=list)
    titles_ranks: List[Any] = Field(default_factory=list)
    skills: List[Any] = Field(default_factory=list)
    creatures: List[Any] = Field(default_factory=list)
    concepts: List[Any] = Field(default_factory=list)
    relationships: List[Any] = Field(default_factory=list)
    emotions: List[Any] = Field(default_factory=list)
    keywords: List[Any] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def ensure_all_lists(cls, data):
        if not isinstance(data, dict):
            return {}
        fields = [
            'characters', 'locations', 'items', 'time_refs', 'organizations',
            'factions', 'titles_ranks', 'skills', 'creatures', 'concepts',
            'relationships', 'emotions', 'keywords'
        ]
        for field in fields:
            if field not in data or data[field] is None:
                data[field] = []
            elif not isinstance(data[field], list):
                data[field] = [data[field]] if data[field] else []
        return data


class CharacterFactModel(BaseModel):
    """Character fact model."""
    fact: str = ""
    chapter: Optional[int] = None
    segment: Optional[int] = None
    source: Optional[str] = None


class CharacterUpdateModel(BaseModel):
    """Character update from model output."""
    name: str
    aliases: List[str] = Field(default_factory=list)
    character_facts: List[Dict[str, Any]] = Field(default_factory=list)
    description: str = ""

    @field_validator('aliases', mode='before')
    @classmethod
    def ensure_aliases_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v) if v else []

    @field_validator('character_facts', mode='before')
    @classmethod
    def ensure_facts_list(cls, v):
        if v is None:
            return []
        return list(v) if v else []


class NLPOutputModel(BaseModel):
    """Complete NLP output model with normalization."""
    segment_summary: SegmentSummaryModel = Field(default_factory=SegmentSummaryModel)
    segment_entities: SegmentEntitiesModel = Field(default_factory=SegmentEntitiesModel)
    character_updates: List[CharacterUpdateModel] = Field(default_factory=list)

    @field_validator('character_updates', mode='before')
    @classmethod
    def ensure_char_updates_list(cls, v):
        if v is None:
            return []
        return list(v) if v else []

    @model_validator(mode='before')
    @classmethod
    def ensure_required_fields(cls, data):
        if not isinstance(data, dict):
            return {'segment_summary': {}, 'segment_entities': {}}
        if 'segment_summary' not in data or data['segment_summary'] is None:
            data['segment_summary'] = {}
        if 'segment_entities' not in data or data['segment_entities'] is None:
            data['segment_entities'] = {}
        return data


def normalize_model_output(raw_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize model output to ensure all required fields exist with correct types.
    
    Args:
        raw_output: Raw model output dict
    
    Returns:
        Normalized dict with all required fields
    """
    try:
        model = NLPOutputModel.model_validate(raw_output)
        return model.model_dump()
    except Exception as e:
        logger.warning(f"Normalization had issues, applying defaults: {e}")
        return NLPOutputModel().model_dump()


def validate_and_normalize(raw_output: Dict[str, Any]) -> tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Validate and normalize model output.
    
    Returns:
        (is_valid, normalized_output, error_message)
    """
    try:
        model = NLPOutputModel.model_validate(raw_output)
        normalized = model.model_dump()
        
        if not normalized.get('segment_summary', {}).get('summary'):
            return False, normalized, "summary is empty"
        
        return True, normalized, None
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return False, {}, str(e)


def get_vllm_guided_json_schema() -> Dict[str, Any]:
    """Get the JSON schema for vLLM guided generation."""
    return {
        "type": "object",
        "required": ["segment_summary", "segment_entities"],
        "properties": {
            "segment_summary": {
                "type": "object",
                "required": ["summary", "summary_short", "events", "beats", "key_dialogue", "tone"],
                "properties": {
                    "summary": {"type": "string"},
                    "summary_short": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "string"}},
                    "beats": {"type": "array", "items": {"type": "object"}},
                    "key_dialogue": {"type": "array", "items": {"type": "object"}},
                    "tone": {"type": "object"}
                }
            },
            "segment_entities": {
                "type": "object",
                "required": [
                    "characters", "locations", "items", "time_refs", "organizations",
                    "factions", "titles_ranks", "skills", "creatures", "concepts",
                    "relationships", "emotions", "keywords"
                ],
                "properties": {
                    "characters": {"type": "array"},
                    "locations": {"type": "array"},
                    "items": {"type": "array"},
                    "time_refs": {"type": "array"},
                    "organizations": {"type": "array"},
                    "factions": {"type": "array"},
                    "titles_ranks": {"type": "array"},
                    "skills": {"type": "array"},
                    "creatures": {"type": "array"},
                    "concepts": {"type": "array"},
                    "relationships": {"type": "array"},
                    "emotions": {"type": "array"},
                    "keywords": {"type": "array"}
                }
            },
            "character_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "character_facts": {"type": "array", "items": {"type": "object"}},
                        "description": {"type": "string"}
                    }
                }
            }
        }
    }


def build_repair_prompt(invalid_json: str, error: str) -> str:
    """Build a prompt to repair invalid JSON."""
    return f"""The following JSON output failed validation with this error:
{error}

Please fix the JSON to match the required schema. All fields in segment_entities must be arrays (never null).
All fields in segment_summary must exist.

Invalid JSON:
{invalid_json[:2000]}...

Output ONLY the corrected valid JSON object."""


def parse_model_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse and validate model JSON response.
    
    Returns:
        Normalized dict if valid, None if parsing fails
    """
    try:
        data = json.loads(response_text)
        is_valid, normalized, error = validate_and_normalize(data)
        
        if not is_valid:
            logger.warning(f"Validation issue (returning normalized): {error}")
        
        return normalized
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse model response as JSON: {e}")
        return None
