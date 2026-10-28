# ============================================================
# OPSYN FORM VALIDATOR — app/modules/forms/validator.py
# Server-side validation for 10 field types.
# Returns field-level errors (422-compatible dict).
# ============================================================

from __future__ import annotations
import re
from typing import Any

# E.164 phone: optional + then 7–15 digits
_PHONE_RE   = re.compile(r'^\+?[1-9]\d{6,14}$')
_EMAIL_RE   = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_COORD_RE   = re.compile(r'^-?\d+(\.\d+)?$')


def _err(field_key: str, msg: str) -> dict:
    return {"field": field_key, "message": msg}


def validate_submission(
    fields: list[dict],
    submitted_data: dict[str, Any],
) -> list[dict]:
    """
    Validate submitted_data against a list of field definitions.

    fields: list of dicts with keys matching FormField columns.
    submitted_data: the raw payload from the client.

    Returns a list of error dicts (empty = no errors).
    Each error: {"field": field_key, "message": "..."}
    """
    errors: list[dict] = []

    for field in fields:
        key   = field["field_key"]
        ftype = field["field_type"]
        req   = field.get("required", False)
        rules = field.get("validation_rules") or {}
        opts  = field.get("options") or []

        raw = submitted_data.get(key)
        missing = raw is None or raw == "" or raw == []

        if req and missing:
            errors.append(_err(key, "This field is required."))
            continue

        if missing:
            continue

        if ftype == "text":
            val = str(raw)
            if "min_length" in rules and len(val) < int(rules["min_length"]):
                errors.append(_err(key, f"Minimum {rules['min_length']} characters required."))
            if "max_length" in rules and len(val) > int(rules["max_length"]):
                errors.append(_err(key, f"Maximum {rules['max_length']} characters allowed."))
            if "regex" in rules and not re.match(rules["regex"], val):
                errors.append(_err(key, rules.get("regex_message", "Invalid format.")))

        elif ftype == "textarea":
            val = str(raw)
            if "min_length" in rules and len(val) < int(rules["min_length"]):
                errors.append(_err(key, f"Minimum {rules['min_length']} characters required."))
            if "max_length" in rules and len(val) > int(rules["max_length"]):
                errors.append(_err(key, f"Maximum {rules['max_length']} characters allowed."))

        elif ftype == "number":
            try:
                num = float(raw)
            except (TypeError, ValueError):
                errors.append(_err(key, "Must be a valid number."))
                continue
            if "min" in rules and num < float(rules["min"]):
                errors.append(_err(key, f"Value must be at least {rules['min']}."))
            if "max" in rules and num > float(rules["max"]):
                errors.append(_err(key, f"Value must be at most {rules['max']}."))

        elif ftype == "dropdown":
            allowed = [str(o.get("value", o)) if isinstance(o, dict) else str(o) for o in opts]
            if allowed and str(raw) not in allowed:
                errors.append(_err(key, "Selected option is not valid."))

        elif ftype == "date":
            from datetime import date as _date
            try:
                parsed = _date.fromisoformat(str(raw))
            except ValueError:
                errors.append(_err(key, "Must be a valid date (YYYY-MM-DD)."))
                continue
            if "min_date" in rules:
                try:
                    if parsed < _date.fromisoformat(rules["min_date"]):
                        errors.append(_err(key, f"Date must be on or after {rules['min_date']}."))
                except ValueError:
                    pass
            if "max_date" in rules:
                try:
                    if parsed > _date.fromisoformat(rules["max_date"]):
                        errors.append(_err(key, f"Date must be on or before {rules['max_date']}."))
                except ValueError:
                    pass

        elif ftype == "phone":
            if not _PHONE_RE.match(str(raw).strip()):
                errors.append(_err(key, "Must be a valid phone number (e.g. +2348012345678)."))

        elif ftype == "email":
            if not _EMAIL_RE.match(str(raw).strip().lower()):
                errors.append(_err(key, "Must be a valid email address."))

        elif ftype == "boolean":
            if not isinstance(raw, bool):
                errors.append(_err(key, "Must be true or false."))

        elif ftype == "file":
            # Expect {"name": "...", "size_bytes": 123456, "mime_type": "image/png"}
            if not isinstance(raw, dict):
                errors.append(_err(key, "Invalid file object."))
                continue
            if "allowed_extensions" in rules:
                name = raw.get("name", "")
                ext  = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in [e.lower().lstrip(".") for e in rules["allowed_extensions"]]:
                    errors.append(_err(key, f"File type '{ext}' is not allowed."))
            if "max_size_mb" in rules:
                size_mb = raw.get("size_bytes", 0) / (1024 * 1024)
                if size_mb > float(rules["max_size_mb"]):
                    errors.append(_err(key, f"File must not exceed {rules['max_size_mb']} MB."))

        elif ftype == "coordinates":
            # Expect {"lat": "6.5244", "lng": "3.3792"} or numeric values
            if not isinstance(raw, dict):
                errors.append(_err(key, "Coordinates must be an object with lat and lng."))
                continue
            lat_raw = str(raw.get("lat", "")).strip()
            lng_raw = str(raw.get("lng", "")).strip()
            if not _COORD_RE.match(lat_raw):
                errors.append(_err(key, "Latitude must be a valid number."))
            elif not (-90 <= float(lat_raw) <= 90):
                errors.append(_err(key, "Latitude must be between -90 and 90."))
            if not _COORD_RE.match(lng_raw):
                errors.append(_err(key, "Longitude must be a valid number."))
            elif not (-180 <= float(lng_raw) <= 180):
                errors.append(_err(key, "Longitude must be between -180 and 180."))

    return errors
