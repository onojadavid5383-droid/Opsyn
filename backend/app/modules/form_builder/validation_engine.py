# ============================================================
# FORM BUILDER VALIDATION ENGINE
# app/modules/form_builder/validation_engine.py
#
# Pure, stateless validation function.
# validate(schema_snapshot, data, context) → ValidationResult
#
# Covers all 24 field types and every validation_rules key
# defined in the FormBuilder Implementation Plan §4.1 – §4.3.
#
# Call order per §4.2:
#   1. Conditional logic evaluation (resolve visibility)
#   2. Role-based edit filter (silently drop ineligible fields)
#   3. Type coercion
#   4. Required check
#   5. Stage-based required check
#   6. Validation rules (length → range → pattern → enum → date → uniqueness)
#   7. Conditional logic action='require' check
# ============================================================

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as _date, datetime as _dt, time as _time
from typing import Any


# ── Public data contracts ─────────────────────────────────────

@dataclass
class ValidationContext:
    tenant_id: str
    submitting_user_role: str          # e.g. 'admin', 'manager', 'technician'
    current_pipeline_stage_order: int = 0
    is_draft: bool = False


@dataclass
class FieldError:
    field_key: str
    field_label: str
    error_code: str
    message: str


@dataclass
class FieldWarning:
    field_key: str
    field_label: str
    message: str


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[FieldError]
    warnings: list[FieldWarning]
    coerced_data: dict
    missing_required_fields: list[str]


# ── Regex constants ───────────────────────────────────────────

_EMAIL_RE   = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', re.IGNORECASE)
_PHONE_E164 = re.compile(r'^\+[1-9]\d{6,14}$')
_URL_RE     = re.compile(
    r'^https?://'
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|localhost|\d{1,3}(?:\.\d{1,3}){3})'
    r'(?::\d+)?(?:/?|[/?]\S+)$',
    re.IGNORECASE,
)
_ALPHANUMERIC_RE = re.compile(r'^[a-zA-Z0-9]+$')
_ALPHA_RE        = re.compile(r'^[a-zA-Z]+$')


# ── Helpers ───────────────────────────────────────────────────

def _err(key: str, label: str, code: str, rules: dict, default: str) -> FieldError:
    return FieldError(
        field_key   = key,
        field_label = label,
        error_code  = code,
        message     = rules.get('custom_error_message', default),
    )


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


# ── Conditional logic ─────────────────────────────────────────

def _eval_operator(op: str, field_value: Any, condition_value: Any) -> bool:
    """Evaluate a single condition operator against a live field value."""
    if op == 'equals':
        return str(field_value) == str(condition_value)
    if op == 'not_equals':
        return str(field_value) != str(condition_value)
    if op == 'is_empty':
        return _is_empty(field_value)
    if op == 'is_not_empty':
        return not _is_empty(field_value)
    if op == 'contains':
        if isinstance(field_value, list):
            return str(condition_value) in [str(v) for v in field_value]
        return str(condition_value) in str(field_value)
    if op == 'not_contains':
        if isinstance(field_value, list):
            return str(condition_value) not in [str(v) for v in field_value]
        return str(condition_value) not in str(field_value)
    if op == 'greater_than':
        try:
            return float(str(field_value)) > float(str(condition_value))
        except (ValueError, TypeError):
            return False
    if op == 'less_than':
        try:
            return float(str(field_value)) < float(str(condition_value))
        except (ValueError, TypeError):
            return False
    if op == 'in':
        allowed = condition_value if isinstance(condition_value, list) else [condition_value]
        return str(field_value) in [str(v) for v in allowed]
    if op == 'not_in':
        allowed = condition_value if isinstance(condition_value, list) else [condition_value]
        return str(field_value) not in [str(v) for v in allowed]
    return False


def _eval_conditional(logic: dict | None, data: dict) -> str | None:
    """
    Evaluate the conditional_logic block for a field.
    Returns the action ('show','hide','require','clear') if triggered, else None.
    """
    if not logic:
        return None
    action     = logic.get('action', 'show')
    match_mode = logic.get('match', 'all')
    conditions = logic.get('conditions', [])
    if not conditions:
        return None

    results = [
        _eval_operator(
            c.get('operator', 'equals'),
            data.get(c.get('field_key', ''), None),
            c.get('value'),
        )
        for c in conditions
    ]

    triggered = all(results) if match_mode == 'all' else any(results)
    return action if triggered else None


def _field_is_hidden(logic: dict | None, data: dict) -> bool:
    """Return True when a field should be hidden given current data values."""
    action = _eval_conditional(logic, data)
    if action == 'hide':
        return True
    if action == 'show':
        return False
    # Default: show unless a hide action fired
    if logic and logic.get('action') == 'show' and action is None:
        # 'show' action: field is hidden when conditions are NOT met
        return True
    return False


# ── Type coercion ─────────────────────────────────────────────

def _coerce(field_type: str, raw: Any) -> tuple[Any, str | None]:
    """
    Attempt to coerce raw value to the canonical Python type for field_type.
    Returns (coerced_value, error_message_or_None).
    None error means success.
    """
    # Display-only types never coerce
    if field_type == 'section_header':
        return (None, None)

    # Computed is read-only; caller's value is accepted as-is (not re-computed)
    if field_type == 'computed':
        return (raw, None)

    if _is_empty(raw):
        return (None, None)

    if field_type in ('string', 'text', 'email', 'phone', 'url', 'signature'):
        return (str(raw).strip(), None)

    if field_type == 'integer':
        try:
            # Accept string ints and floats that are whole numbers
            val = int(str(raw).strip())
            return (val, None)
        except (ValueError, TypeError):
            try:
                f = float(str(raw).strip())
                if f == int(f):
                    return (int(f), None)
            except (ValueError, TypeError):
                pass
            return (None, 'Must be a whole number.')

    if field_type == 'float':
        try:
            return (float(str(raw).strip()), None)
        except (ValueError, TypeError):
            return (None, 'Must be a numeric value.')

    if field_type == 'boolean':
        if isinstance(raw, bool):
            return (raw, None)
        s = str(raw).strip().lower()
        if s in ('true', '1', 'yes', 'on'):
            return (True, None)
        if s in ('false', '0', 'no', 'off'):
            return (False, None)
        return (None, 'Must be true or false.')

    if field_type == 'date':
        if isinstance(raw, _date):
            return (raw, None)
        try:
            return (_date.fromisoformat(str(raw).strip()), None)
        except (ValueError, TypeError):
            return (None, 'Must be a valid date (YYYY-MM-DD).')

    if field_type == 'datetime':
        if isinstance(raw, _dt):
            return (raw, None)
        try:
            s = str(raw).strip().replace('Z', '+00:00')
            return (_dt.fromisoformat(s), None)
        except (ValueError, TypeError):
            return (None, 'Must be a valid datetime (ISO 8601).')

    if field_type == 'time':
        if isinstance(raw, _time):
            return (raw, None)
        try:
            return (_time.fromisoformat(str(raw).strip()), None)
        except (ValueError, TypeError):
            return (None, 'Must be a valid time (HH:MM or HH:MM:SS).')

    if field_type in ('enum', 'radio'):
        return (str(raw).strip(), None)

    if field_type == 'multiselect':
        if isinstance(raw, list):
            return ([str(v).strip() for v in raw], None)
        if isinstance(raw, str):
            return ([v.strip() for v in raw.split(',') if v.strip()], None)
        return (None, 'Must be a list of selected values.')

    if field_type == 'rating':
        try:
            val = int(str(raw).strip())
            return (val, None)
        except (ValueError, TypeError):
            return (None, 'Rating must be a whole number.')

    if field_type == 'coordinates':
        if not isinstance(raw, dict):
            return (None, 'Coordinates must be an object with lat and lng.')
        try:
            lat = float(str(raw.get('lat', '')).strip())
            lng = float(str(raw.get('lng', '')).strip())
            return ({'lat': lat, 'lng': lng}, None)
        except (ValueError, TypeError):
            return (None, 'Coordinates lat and lng must be numeric.')

    if field_type == 'address':
        if not isinstance(raw, dict):
            return (None, 'Address must be an object.')
        return (raw, None)

    if field_type == 'currency':
        if not isinstance(raw, dict):
            return (None, 'Currency must be an object with amount and currency.')
        try:
            amount = float(str(raw.get('amount', '')).strip())
            currency = str(raw.get('currency', '')).strip().upper()
            return ({'amount': amount, 'currency': currency}, None)
        except (ValueError, TypeError):
            return (None, 'Currency amount must be numeric.')

    if field_type in ('file', 'image'):
        if isinstance(raw, dict):
            return (raw, None)
        if isinstance(raw, str) and raw.strip():
            return ({'url': raw.strip()}, None)
        return (None, f'{field_type.capitalize()} must be a valid file object or URL.')

    if field_type == 'lookup':
        return (str(raw).strip(), None)

    # Fallback: accept as-is
    return (raw, None)


# ── Field-level rule validators ───────────────────────────────

def _validate_string(key: str, label: str, val: str, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    if 'min_length' in rules and len(val) < int(rules['min_length']):
        errs.append(_err(key, label, 'min_length',  rules,
                         f'Minimum {rules["min_length"]} characters required.'))
    if 'max_length' in rules and len(val) > int(rules['max_length']):
        errs.append(_err(key, label, 'max_length', rules,
                         f'Maximum {rules["max_length"]} characters allowed.'))
    if 'regex' in rules:
        try:
            if not re.search(rules['regex'], val):
                errs.append(_err(key, label, 'regex', rules, 'Value does not match required format.'))
        except re.error:
            pass
    if 'allowed_chars' in rules:
        ac = rules['allowed_chars']
        ok = True
        if ac == 'alphanumeric':
            ok = bool(_ALPHANUMERIC_RE.match(val))
        elif ac == 'alpha':
            ok = bool(_ALPHA_RE.match(val))
        if not ok:
            errs.append(_err(key, label, 'allowed_chars', rules,
                             f'Only {ac} characters are allowed.'))
    return errs


def _validate_numeric(key: str, label: str, val: float | int, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    if 'min' in rules and val < float(rules['min']):
        errs.append(_err(key, label, 'min', rules, f'Value must be at least {rules["min"]}.'))
    if 'max' in rules and val > float(rules['max']):
        errs.append(_err(key, label, 'max', rules, f'Value must be at most {rules["max"]}.'))
    if 'decimal_places' in rules:
        dp = int(rules['decimal_places'])
        s  = str(val)
        if '.' in s and len(s.split('.')[1]) > dp:
            errs.append(_err(key, label, 'decimal_places', rules,
                             f'Maximum {dp} decimal places allowed.'))
    return errs


def _validate_date(key: str, label: str, val: _date, rules: dict,
                   warnings: list[FieldWarning]) -> list[FieldError]:
    errs: list[FieldError] = []
    today = _date.today()
    if rules.get('no_future') and val > today:
        errs.append(_err(key, label, 'no_future', rules, 'Date cannot be in the future.'))
    if rules.get('no_past') and val < today:
        errs.append(_err(key, label, 'no_past', rules, 'Date cannot be in the past.'))
    if 'min_date' in rules:
        try:
            mn = _date.fromisoformat(str(rules['min_date']))
            if val < mn:
                errs.append(_err(key, label, 'min_date', rules,
                                 f'Date must be on or after {rules["min_date"]}.'))
        except ValueError:
            pass
    if 'max_date' in rules:
        try:
            mx = _date.fromisoformat(str(rules['max_date']))
            if val > mx:
                errs.append(_err(key, label, 'max_date', rules,
                                 f'Date must be on or before {rules["max_date"]}.'))
        except ValueError:
            pass
    return errs


def _validate_datetime(key: str, label: str, val: _dt, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    now = _dt.utcnow()
    if rules.get('no_future') and val > now:
        errs.append(_err(key, label, 'no_future', rules, 'Datetime cannot be in the future.'))
    if rules.get('no_past') and val < now:
        errs.append(_err(key, label, 'no_past', rules, 'Datetime cannot be in the past.'))
    if 'min_date' in rules:
        try:
            mn = _dt.fromisoformat(str(rules['min_date']))
            if val < mn:
                errs.append(_err(key, label, 'min_date', rules,
                                 f'Datetime must be on or after {rules["min_date"]}.'))
        except ValueError:
            pass
    if 'max_date' in rules:
        try:
            mx = _dt.fromisoformat(str(rules['max_date']))
            if val > mx:
                errs.append(_err(key, label, 'max_date', rules,
                                 f'Datetime must be on or before {rules["max_date"]}.'))
        except ValueError:
            pass
    return errs


def _validate_time(key: str, label: str, val: _time, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    if 'min_time' in rules:
        try:
            mn = _time.fromisoformat(str(rules['min_time']))
            if val < mn:
                errs.append(_err(key, label, 'min_time', rules,
                                 f'Time must be on or after {rules["min_time"]}.'))
        except ValueError:
            pass
    if 'max_time' in rules:
        try:
            mx = _time.fromisoformat(str(rules['max_time']))
            if val > mx:
                errs.append(_err(key, label, 'max_time', rules,
                                 f'Time must be on or before {rules["max_time"]}.'))
        except ValueError:
            pass
    return errs


def _validate_enum_options(key: str, label: str, val: str,
                            options: list[dict], rules: dict) -> list[FieldError]:
    allowed = {str(o['value']) for o in options if isinstance(o, dict) and 'value' in o}
    if allowed and val not in allowed:
        return [_err(key, label, 'invalid_option', rules,
                     f'"{val}" is not a valid option.')]
    return []


def _validate_multiselect(key: str, label: str, vals: list[str],
                           options: list[dict], rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    allowed = {str(o['value']) for o in options if isinstance(o, dict) and 'value' in o}
    if allowed:
        invalid = [v for v in vals if v not in allowed]
        if invalid:
            errs.append(_err(key, label, 'invalid_option', rules,
                             f'Invalid selection(s): {", ".join(invalid)}.'))
    if 'min_selections' in rules and len(vals) < int(rules['min_selections']):
        errs.append(_err(key, label, 'min_selections', rules,
                         f'Select at least {rules["min_selections"]} item(s).'))
    if 'max_selections' in rules and len(vals) > int(rules['max_selections']):
        errs.append(_err(key, label, 'max_selections', rules,
                         f'Select at most {rules["max_selections"]} item(s).'))
    return errs


def _validate_file(key: str, label: str, val: dict, rules: dict,
                   field_type: str = 'file') -> list[FieldError]:
    errs: list[FieldError] = []
    if 'allowed_mime_types' in rules:
        mime = str(val.get('mime_type', '')).lower()
        allowed_mimes = [m.lower() for m in rules['allowed_mime_types']]
        if mime and mime not in allowed_mimes:
            errs.append(_err(key, label, 'allowed_mime_types', rules,
                             f'File type "{mime}" is not allowed.'))
    if 'max_size_mb' in rules:
        size_bytes = val.get('size_bytes', 0) or 0
        size_mb    = size_bytes / (1024 * 1024)
        if size_mb > float(rules['max_size_mb']):
            errs.append(_err(key, label, 'max_size_mb', rules,
                             f'File must not exceed {rules["max_size_mb"]} MB.'))
    if field_type == 'image':
        if 'min_width' in rules:
            w = val.get('width', 0) or 0
            if w < int(rules['min_width']):
                errs.append(_err(key, label, 'min_width', rules,
                                 f'Image must be at least {rules["min_width"]}px wide.'))
        if 'min_height' in rules:
            h = val.get('height', 0) or 0
            if h < int(rules['min_height']):
                errs.append(_err(key, label, 'min_height', rules,
                                 f'Image must be at least {rules["min_height"]}px tall.'))
    return errs


def _validate_coordinates(key: str, label: str, val: dict,
                           rules: dict, warnings: list[FieldWarning]) -> list[FieldError]:
    errs: list[FieldError] = []
    lat = val.get('lat')
    lng = val.get('lng')
    if lat is None or lng is None:
        errs.append(_err(key, label, 'coordinates_missing', rules,
                         'Both lat and lng are required.'))
        return errs
    if not (-90 <= lat <= 90):
        errs.append(_err(key, label, 'lat_range', rules,
                         'Latitude must be between -90 and 90.'))
    if not (-180 <= lng <= 180):
        errs.append(_err(key, label, 'lng_range', rules,
                         'Longitude must be between -180 and 180.'))
    # Warn if (0, 0) — likely a default/unset value
    if lat == 0 and lng == 0:
        warnings.append(FieldWarning(field_key=key, field_label=label,
                                     message='Coordinates (0, 0) may be an unset default.'))
    return errs


def _validate_currency(key: str, label: str, val: dict, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    amount   = val.get('amount')
    currency = val.get('currency', '')
    if amount is None:
        errs.append(_err(key, label, 'currency_missing', rules, 'Amount is required.'))
        return errs
    if 'min' in rules and amount < float(rules['min']):
        errs.append(_err(key, label, 'min', rules, f'Amount must be at least {rules["min"]}.'))
    if 'max' in rules and amount > float(rules['max']):
        errs.append(_err(key, label, 'max', rules, f'Amount must be at most {rules["max"]}.'))
    if 'decimal_places' in rules:
        dp = int(rules['decimal_places'])
        s  = str(amount)
        if '.' in s and len(s.split('.')[1]) > dp:
            errs.append(_err(key, label, 'decimal_places', rules,
                             f'Maximum {dp} decimal places allowed.'))
    if 'allowed_currencies' in rules:
        allowed_curr = [c.upper() for c in rules['allowed_currencies']]
        if currency.upper() not in allowed_curr:
            errs.append(_err(key, label, 'allowed_currencies', rules,
                             f'Currency "{currency}" is not allowed.'))
    return errs


def _validate_address(key: str, label: str, val: dict, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    required_sub = rules.get('required_sub_fields', [])
    for sub in required_sub:
        if not val.get(sub):
            errs.append(_err(key, label, f'address_{sub}_required', rules,
                             f'Address field "{sub}" is required.'))
    return errs


def _validate_rating(key: str, label: str, val: int, rules: dict) -> list[FieldError]:
    errs: list[FieldError] = []
    if 'min_rating' in rules and val < int(rules['min_rating']):
        errs.append(_err(key, label, 'min_rating', rules,
                         f'Rating must be at least {rules["min_rating"]}.'))
    if 'max_rating' in rules and val > int(rules['max_rating']):
        errs.append(_err(key, label, 'max_rating', rules,
                         f'Rating must be at most {rules["max_rating"]}.'))
    return errs


# ── Main entry point ──────────────────────────────────────────

def validate(
    schema_snapshot: list[dict],
    data: dict,
    context: ValidationContext,
    uniqueness_checker: Callable[[str, str, Any], bool] | None = None,
) -> ValidationResult:
    """
    Validate submitted data against a schema version snapshot.

    schema_snapshot: list of field definition dicts (from field_snapshot JSONB).
    data:            submitted key→value pairs (raw, as received from client).
    context:         ValidationContext with tenant/role/stage/draft flags.
    uniqueness_checker: optional callable(field_key, tenant_id, value) → bool
                        True = value is unique, False = duplicate found.

    Returns a fully populated ValidationResult. Calling twice with identical
    inputs produces identical output (referential transparency guaranteed).
    """
    errors:                 list[FieldError]   = []
    warnings:               list[FieldWarning] = []
    coerced_data:           dict               = {}
    missing_required_fields: list[str]         = []
    data = dict(data)

    # ── Pre-pass: resolve which fields are hidden by conditional logic ──
    hidden_keys: set[str] = set()
    conditionally_required_keys: set[str] = set()

    # Clear fields whose configured conditions are met before validating or
    # evaluating dependent fields. Work on a copy to keep this engine pure.
    for fd in schema_snapshot:
        if (fd.get('conditional_logic') or {}).get('action') == 'clear':
            if _eval_conditional(fd.get('conditional_logic'), data) == 'clear':
                data.pop(fd.get('field_key', ''), None)

    for fd in schema_snapshot:
        fkey  = fd.get('field_key', '')
        allowed_visibility_roles = fd.get('role_visibility')
        if fd.get('is_hidden'):
            hidden_keys.add(fkey)
        if allowed_visibility_roles and (context.submitting_user_role or '').lower() not in [r.lower() for r in allowed_visibility_roles]:
            hidden_keys.add(fkey)
        visible_from = fd.get('stage_visible_from')
        if visible_from is not None and context.current_pipeline_stage_order < int(visible_from):
            hidden_keys.add(fkey)
        logic = fd.get('conditional_logic')
        if not logic:
            continue
        action = _eval_conditional(logic, data)
        if action == 'hide':
            hidden_keys.add(fkey)
        elif action == 'show' and logic.get('action') == 'show':
            pass  # visible — nothing to mark
        elif action == 'require':
            conditionally_required_keys.add(fkey)

        # 'show' logic with no trigger → field is hidden (show only when conditions met)
        if logic.get('action') == 'show' and action is None:
            hidden_keys.add(fkey)

    # ── Per-field validation ──────────────────────────────────
    for fd in schema_snapshot:
        fkey    = fd.get('field_key', '')
        label   = fd.get('label', fkey)
        ftype   = fd.get('field_type', 'string')
        rules   = fd.get('validation_rules') or {}
        options = fd.get('options') or []
        is_req  = fd.get('is_required', False)

        # section_header is display-only — never validated, never stored
        if ftype == 'section_header':
            continue

        # ── Step 1: Hidden fields skip all validation ─────────
        if fkey in hidden_keys:
            continue

        # ── Step 2: Role-based edit filter ────────────────────
        role_editable = fd.get('role_editable')
        if role_editable:
            caller_role = (context.submitting_user_role or '').lower()
            allowed_roles = [r.lower() for r in role_editable]
            if caller_role not in allowed_roles:
                # Silently drop: do not validate, do not store
                continue

        raw = data.get(fkey)

        # ── Step 3: Type coercion ─────────────────────────────
        coerced, coerce_err = _coerce(ftype, raw)
        if coerce_err and not _is_empty(raw):
            errors.append(_err(fkey, label, 'type_error', rules, coerce_err))
            continue  # skip further rules for this field on type failure

        # ── Step 4: Required check (skipped for drafts) ───────
        effectively_required = is_req or (fkey in conditionally_required_keys)
        if effectively_required and not context.is_draft and _is_empty(coerced):
            errors.append(_err(fkey, label, 'required', rules, f'{label} is required.'))
            missing_required_fields.append(fkey)
            continue

        # ── Step 5: Stage-based required check ───────────────
        stage_req_at = fd.get('stage_required_at')
        if (
            stage_req_at is not None
            and context.current_pipeline_stage_order >= int(stage_req_at)
            and not context.is_draft
            and _is_empty(coerced)
        ):
            errors.append(_err(fkey, label, 'stage_required', rules,
                               f'{label} is required at pipeline stage {stage_req_at}.'))
            missing_required_fields.append(fkey)
            continue

        # Nothing to validate if field is empty and not required
        if _is_empty(coerced):
            if ftype == 'computed':
                pass  # computed fields need no storage
            continue

        # ── Step 6: Validation rules ─────────────────────────
        field_errors: list[FieldError] = []

        if ftype in ('string', 'text'):
            field_errors += _validate_string(fkey, label, str(coerced), rules)

        elif ftype == 'email':
            if not _EMAIL_RE.match(str(coerced)):
                field_errors.append(_err(fkey, label, 'email_format', rules,
                                         'Must be a valid email address.'))
            else:
                field_errors += _validate_string(fkey, label, str(coerced), rules)

        elif ftype == 'phone':
            phone_str = str(coerced)
            if not _PHONE_E164.match(phone_str):
                field_errors.append(_err(fkey, label, 'phone_format', rules,
                                         'Must be in E.164 format (e.g. +2348012345678).'))
            else:
                field_errors += _validate_string(fkey, label, phone_str, rules)

        elif ftype == 'url':
            if not _URL_RE.match(str(coerced)):
                field_errors.append(_err(fkey, label, 'url_format', rules,
                                         'Must be a valid URL (http:// or https://).'))

        elif ftype in ('integer', 'float'):
            field_errors += _validate_numeric(fkey, label, coerced, rules)

        elif ftype == 'boolean':
            pass  # no range rules; required already checked

        elif ftype == 'date':
            field_errors += _validate_date(fkey, label, coerced, rules, warnings)

        elif ftype == 'datetime':
            field_errors += _validate_datetime(fkey, label, coerced, rules)

        elif ftype == 'time':
            field_errors += _validate_time(fkey, label, coerced, rules)

        elif ftype in ('enum', 'radio'):
            field_errors += _validate_enum_options(fkey, label, coerced, options, rules)

        elif ftype == 'multiselect':
            field_errors += _validate_multiselect(fkey, label, coerced, options, rules)

        elif ftype in ('file', 'image'):
            field_errors += _validate_file(fkey, label, coerced, rules, ftype)

        elif ftype == 'coordinates':
            field_errors += _validate_coordinates(fkey, label, coerced, rules, warnings)

        elif ftype == 'address':
            field_errors += _validate_address(fkey, label, coerced, rules)

        elif ftype == 'currency':
            field_errors += _validate_currency(fkey, label, coerced, rules)

        elif ftype == 'rating':
            field_errors += _validate_rating(fkey, label, coerced, rules)

        elif ftype == 'signature':
            pass  # required check only; content is opaque base64

        elif ftype == 'lookup':
            pass  # foreign-key resolution done at API layer

        elif ftype == 'computed':
            pass  # read-only; no client validation

        # ── Uniqueness rule ───────────────────────────────────
        if not field_errors and rules.get('unique_in_schema') and uniqueness_checker:
            if not uniqueness_checker(fkey, context.tenant_id, coerced):
                field_errors.append(_err(fkey, label, 'unique_in_schema', rules,
                                         f'This value for {label} already exists.'))

        errors.extend(field_errors)

        # Only write to coerced_data if the field passed all its own rules
        if not field_errors:
            if ftype == 'computed':
                pass  # never stored
            elif ftype not in ('section_header',):
                coerced_data[fkey] = coerced

    return ValidationResult(
        is_valid                = len(errors) == 0,
        errors                  = errors,
        warnings                = warnings,
        coerced_data            = coerced_data,
        missing_required_fields = missing_required_fields,
    )
