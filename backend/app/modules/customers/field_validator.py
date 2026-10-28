# ============================================================
# OPSYN CUSTOMER FIELD VALIDATOR — app/modules/customers/field_validator.py
# Validates submitted field values against field_definition.validation_rules.
# Returns structured field-level errors (not a generic 422).
# ============================================================

from __future__ import annotations

import re
from typing import Any


def _validate_single(
    key: str,
    value: Any,
    field_type: str,
    rules: dict | None,
    is_required: bool,
) -> str | None:
    """
    Returns an error message string if the value is invalid, else None.
    rules keys: min_length, max_length, regex, min, max, options_list
    """
    rules = rules or {}

    # Required check
    if is_required and (value is None or value == ""):
        return "This field is required."

    # Skip further validation if empty and not required
    if value is None or value == "":
        return None

    str_val = str(value)

    if field_type == "text" or field_type == "textarea":
        if "min_length" in rules and len(str_val) < rules["min_length"]:
            return f"Must be at least {rules['min_length']} characters."
        if "max_length" in rules and len(str_val) > rules["max_length"]:
            return f"Must be at most {rules['max_length']} characters."
        if "regex" in rules:
            if not re.fullmatch(rules["regex"], str_val):
                return "Value does not match required pattern."

    elif field_type == "email":
        if "max_length" in rules and len(str_val) > rules["max_length"]:
            return f"Must be at most {rules['max_length']} characters."
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str_val):
            return "Invalid email address."

    elif field_type == "phone":
        pattern = rules.get("regex", r"^\+?[0-9]{7,15}$")
        if not re.fullmatch(pattern, str_val.replace(" ", "")):
            return "Invalid phone number."

    elif field_type == "number":
        try:
            num = float(str_val)
        except ValueError:
            return "Must be a valid number."
        if "min" in rules and num < rules["min"]:
            return f"Must be at least {rules['min']}."
        if "max" in rules and num > rules["max"]:
            return f"Must be at most {rules['max']}."

    elif field_type == "select":
        options = rules.get("options_list", [])
        if options and str_val not in options:
            return f"Must be one of: {', '.join(options)}."

    elif field_type == "multiselect":
        options = rules.get("options_list", [])
        submitted = value if isinstance(value, list) else [str_val]
        invalid = [v for v in submitted if v not in options]
        if options and invalid:
            return f"Invalid option(s): {', '.join(invalid)}. Must be from: {', '.join(options)}."

    elif field_type == "date":
        import datetime
        try:
            datetime.date.fromisoformat(str_val)
        except ValueError:
            return "Invalid date. Use ISO format YYYY-MM-DD."

    # file type: MIME validation is handled at upload; skip here
    return None


def validate_field_values(
    submitted: dict[str, Any],
    field_defs: list[dict],
) -> dict[str, str]:
    """
    Validate submitted field values against a list of field definitions.

    field_defs: list of dicts with keys: key, field_type, validation_rules, is_required
    submitted:  dict of {field_key: value}

    Returns: dict of {field_key: error_message} — empty dict means all valid.
    """
    errors: dict[str, str] = {}

    for fd in field_defs:
        key       = fd["key"]
        ftype     = fd.get("field_type", "text")
        rules     = fd.get("validation_rules") or {}
        required  = fd.get("is_required", False)
        value     = submitted.get(key)

        err = _validate_single(key, value, ftype, rules, required)
        if err:
            errors[key] = err

    # Flag submitted keys that don't correspond to any known field
    known = {fd["key"] for fd in field_defs}
    for key in submitted:
        if key not in known:
            errors[key] = "Unknown field key."

    return errors
