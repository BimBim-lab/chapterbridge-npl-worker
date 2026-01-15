"""Pydantic models and schema validation for NLP pack model output."""

import json
import re
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator
from .utils import get_logger

logger = get_logger(__name__)


class SegmentSummaryModel(BaseModel):
    """Segment summary model - simplified structure."""
    summary: str = ""
    summary_short: str = ""
    events: List[str] = Field(default_factory=list)

    @field_validator('events', mode='before')
    @classmethod
    def ensure_events_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v) if v else []


class SegmentEntitiesModel(BaseModel):
    """Segment entities model - simplified structure."""
    characters: List[Any] = Field(default_factory=list)
    locations: List[Any] = Field(default_factory=list)
    keywords: List[Any] = Field(default_factory=list)
    time_context: str = "unknown"

    @field_validator('time_context', mode='before')
    @classmethod
    def validate_time_context(cls, v):
        """Ensure time_context is valid."""
        if not v or not isinstance(v, str):
            return "unknown"
        valid_values = ['present', 'past', 'future', 'mixed', 'unknown']
        v_lower = v.lower().strip()
        return v_lower if v_lower in valid_values else "unknown"

    @model_validator(mode='before')
    @classmethod
    def ensure_all_lists(cls, data):
        if not isinstance(data, dict):
            return {'time_context': 'unknown'}
        fields = ['characters', 'locations', 'keywords']
        for field in fields:
            if field not in data or data[field] is None:
                data[field] = []
            elif not isinstance(data[field], list):
                data[field] = [data[field]] if data[field] else []
        if 'time_context' not in data:
            data['time_context'] = 'unknown'
        return data


class CharacterUpdateModel(BaseModel):
    """Character update from model output."""
    name: str
    aliases: List[str] = Field(default_factory=list)
    facts: List[str] = Field(default_factory=list)  # Simple array of fact strings
    
    @field_validator('name', mode='before')
    @classmethod
    def validate_name(cls, v):
        """Ensure name is a proper character name, not generic terms."""
        if not v or not isinstance(v, str):
            return ""
        
        v = v.strip()
        lower_v = v.lower()
        
        # Filter out generic/invalid names
        invalid_names = [
            'ayah', 'ibu', 'bapak', 'kakak', 'adik', 'anak', 'orang tua',
            'pria', 'wanita', 'laki-laki', 'perempuan', 'orang',
            'orang kekar', 'pria berbaju', 'wanita muda', 'pemuda',
            'anak laki-laki', 'anak perempuan', 'gadis', 'bocah',
            'he', 'she', 'they', 'person', 'man', 'woman', 'boy', 'girl',
            'father', 'mother', 'brother', 'sister', 'parent', 'child',
            'unknown', 'unnamed', 'none', 'n/a'
        ]
        
        if lower_v in invalid_names:
            return ""
        
        # Must have at least 2 characters and not be all numbers
        if len(v) < 2 or v.isdigit():
            return ""
        
        return v
    
    @field_validator('aliases', mode='before')
    @classmethod
    def ensure_aliases_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v) if v else []
    
    @field_validator('facts', mode='before')
    @classmethod
    def ensure_facts_list(cls, v):
        """Ensure facts is a list of strings."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(item).strip() for item in v if item and str(item).strip()]
        return []


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
        if not isinstance(v, list):
            return []
        # Filter out invalid entries (strings, nulls, etc)
        valid_updates = []
        for item in v:
            if isinstance(item, dict) and item.get('name'):
                valid_updates.append(item)
            else:
                logger.warning(f"Skipping invalid character_update entry: {type(item)} - {item}")
        return valid_updates

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
    """Get the JSON schema for vLLM guided generation - simplified structure."""
    return {
        "type": "object",
        "required": ["segment_summary", "segment_entities"],
        "properties": {
            "segment_summary": {
                "type": "object",
                "required": ["summary", "summary_short", "events"],
                "properties": {
                    "summary": {"type": "string"},
                    "summary_short": {"type": "string"},
                    "events": {"type": "array", "items": {"type": "string"}}
                }
            },
            "segment_entities": {
                "type": "object",
                "required": ["characters", "locations", "keywords", "time_context"],
                "properties": {
                    "characters": {"type": "array"},
                    "locations": {"type": "array"},
                    "keywords": {"type": "array"},
                    "time_context": {"type": "string", "enum": ["present", "past", "future", "mixed", "unknown"]}
                }
            },
            "character_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "aliases", "facts"],
                    "properties": {
                        "name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "facts": {"type": "array", "items": {"type": "string"}}
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
