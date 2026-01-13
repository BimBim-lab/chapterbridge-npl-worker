"""Deterministic R2 key builder for derived assets."""

from typing import Dict

def build_cleaned_text_key(
    media_type: str,
    work_id: str,
    edition_id: str,
    segment_type: str,
    segment_number: float
) -> str:
    """
    Build deterministic R2 key for cleaned text.
    
    Format: derived/{media}/{work_id}/{edition_id}/{segment_type}-{NNNN}/cleaned.txt
    """
    number_str = f"{int(segment_number):04d}"
    
    return f"derived/{media_type}/{work_id}/{edition_id}/{segment_type}-{number_str}/cleaned.txt"


def build_key_from_segment(segment: Dict, edition: Dict) -> str:
    """Build cleaned text key from segment and edition data."""
    return build_cleaned_text_key(
        media_type=edition['media_type'],
        work_id=edition['work_id'],
        edition_id=edition['id'],
        segment_type=segment['segment_type'],
        segment_number=segment['number']
    )
