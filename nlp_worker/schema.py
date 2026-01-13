"""JSON schema definitions for NLP pack model output."""

import json
from typing import Dict, Any, Optional
from jsonschema import validate, ValidationError
from .utils import get_logger

logger = get_logger(__name__)

NLP_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["cleaned_text", "segment_summary", "segment_entities"],
    "properties": {
        "cleaned_text": {
            "type": "string",
            "description": "Cleaned, deduped text with watermarks/boilerplate removed"
        },
        "segment_summary": {
            "type": "object",
            "required": ["summary", "summary_short", "events", "beats", "key_dialogue", "tone"],
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Full narrative summary of what happened"
                },
                "summary_short": {
                    "type": "string",
                    "description": "1-2 sentence headline summary"
                },
                "events": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Chronological list of key events"
                },
                "beats": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "description": {"type": "string"}
                        }
                    },
                    "description": "Story beat objects (setup/conflict/twist/resolution)"
                },
                "key_dialogue": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker": {"type": "string"},
                            "to": {"type": "string"},
                            "text": {"type": "string"},
                            "importance": {"type": "string"}
                        },
                        "required": ["speaker", "text"]
                    },
                    "description": "Important quotes with speaker and optional target"
                },
                "tone": {
                    "type": "object",
                    "properties": {
                        "primary": {"type": "string"},
                        "secondary": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "intensity": {"type": "number"}
                    },
                    "description": "Tone analysis"
                }
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
                "required": ["name", "aliases", "character_facts"],
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "character_facts": {
                        "type": "array",
                        "items": {"type": "object"}
                    },
                    "description": {"type": "string"}
                }
            },
            "description": "Character updates (only for novel segments)"
        }
    }
}


def get_vllm_guided_json_schema() -> Dict[str, Any]:
    """Get the JSON schema for vLLM guided generation."""
    return NLP_OUTPUT_SCHEMA


def validate_model_output(output: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate model output against schema.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        validate(instance=output, schema=NLP_OUTPUT_SCHEMA)
        return True, None
    except ValidationError as e:
        return False, str(e.message)


def parse_model_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse and validate model JSON response.
    
    Returns:
        Parsed dict if valid, None if parsing/validation fails
    """
    try:
        data = json.loads(response_text)
        
        is_valid, error = validate_model_output(data)
        if not is_valid:
            logger.error(f"Model output validation failed: {error}")
            return None
        
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse model response as JSON: {e}")
        return None
