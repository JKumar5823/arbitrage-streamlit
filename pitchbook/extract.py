"""Turn a PitchBook screenshot into structured records.

Primary path: Claude vision reads the screenshot and returns clean,
structured rows via a tool call. Fallback: local Tesseract OCR returns raw
text only (no structure) so the room still works offline / without an API key.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from PIL import Image

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Schema we ask Claude to populate. Fields are intentionally generic so the
# same extractor works across PitchBook profile, deal, and search-result
# screens. Unknown/missing fields should be omitted rather than guessed.
EXTRACTION_TOOL = {
    "name": "save_pitchbook_records",
    "description": (
        "Save the structured rows extracted from a PitchBook screenshot. "
        "Each visible entity (company, deal, fund, investor, person) becomes "
        "one record. Only include fields that are actually visible in the "
        "image; never invent or estimate values."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "description": "One object per row/entity visible on screen.",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "description": "company | deal | fund | investor | person | other",
                        },
                        "name": {"type": "string", "description": "Primary name/title of the entity."},
                        "company": {"type": "string"},
                        "deal_type": {"type": "string"},
                        "deal_size": {"type": "string", "description": "As shown, e.g. '$25.0M'."},
                        "deal_date": {"type": "string"},
                        "valuation": {"type": "string"},
                        "stage": {"type": "string"},
                        "industry": {"type": "string"},
                        "location": {"type": "string"},
                        "investors": {"type": "string", "description": "Comma-separated if multiple."},
                        "website": {"type": "string"},
                        "fields": {
                            "type": "object",
                            "description": "Any other labelled values shown, as key/value pairs.",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["entity_type", "name"],
                    "additionalProperties": True,
                },
            }
        },
        "required": ["records"],
    },
}

SYSTEM_PROMPT = (
    "You are a meticulous data-extraction engine for PitchBook screenshots. "
    "Read the image exactly as shown and transcribe the data into structured "
    "rows. Preserve numbers, currency symbols, and units verbatim. If a value "
    "is not visible, omit the field. Never fabricate data. If the screenshot "
    "shows a table, return one record per row."
)


@dataclass
class ExtractionResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    method: str = ""
    error: Optional[str] = None


def _image_to_b64_png(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def extract_with_claude(
    image: Image.Image,
    instructions: str = "",
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> ExtractionResult:
    """Extract structured records using Claude vision + tool use."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ExtractionResult(error="No ANTHROPIC_API_KEY set.", method="claude")

    try:
        import anthropic  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        return ExtractionResult(error=f"anthropic SDK not installed: {exc}", method="claude")

    client = anthropic.Anthropic(api_key=api_key)
    user_text = (
        "Extract every entity visible in this PitchBook screenshot into "
        "structured records using the save_pitchbook_records tool."
    )
    if instructions.strip():
        user_text += f"\n\nExtra instructions from the user:\n{instructions.strip()}"

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Cache the static system prompt across repeated captures.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "save_pitchbook_records"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": _image_to_b64_png(image),
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
    except Exception as exc:
        return ExtractionResult(error=f"Claude request failed: {exc}", method="claude")

    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "save_pitchbook_records":
            records = block.input.get("records", []) if isinstance(block.input, dict) else []
            return ExtractionResult(
                records=records,
                raw_text=json.dumps(records, indent=2),
                method=f"claude:{model}",
            )

    return ExtractionResult(error="Claude returned no structured records.", method="claude")


def extract_with_ocr(image: Image.Image) -> ExtractionResult:
    """Fallback: raw text via Tesseract. No structure."""
    try:
        import pytesseract  # noqa: PLC0415
    except Exception as exc:
        return ExtractionResult(
            error=(
                "pytesseract not available and no Claude key set. Install "
                "tesseract-ocr + pytesseract, or set ANTHROPIC_API_KEY.\n"
                f"Original error: {exc}"
            ),
            method="ocr",
        )

    text = pytesseract.image_to_string(image)
    return ExtractionResult(
        records=[{"entity_type": "other", "name": "(unstructured OCR)", "fields": {"text": text}}],
        raw_text=text,
        method="tesseract-ocr",
    )


def extract(
    image: Image.Image,
    instructions: str = "",
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    prefer: str = "claude",
) -> ExtractionResult:
    """Extract records, preferring Claude vision and falling back to OCR."""
    if prefer == "ocr":
        return extract_with_ocr(image)

    result = extract_with_claude(image, instructions=instructions, api_key=api_key, model=model)
    if result.error or not result.records:
        ocr = extract_with_ocr(image)
        if ocr.records and not ocr.error:
            ocr.error = f"(Claude unavailable: {result.error}) — fell back to OCR."
            return ocr
        # Surface the more informative error.
        return result if result.error else ocr
    return result
