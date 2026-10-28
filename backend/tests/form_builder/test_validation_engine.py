# ============================================================
# FORM BUILDER VALIDATION ENGINE — UNIT TESTS
# tests/form_builder/test_validation_engine.py
#
# Coverage target per plan §4 Phase 2 checkpoint:
#   • All 24 field types: 3+ cases each (valid / invalid type / boundary)
#   • All 10 conditional logic operators
#   • All 4 conditional logic actions (show, hide, require, clear)
#   • Role-based edit filtering
#   • Stage-based required check
#   • Draft mode skips required checks
#   • Uniqueness callback integration
#   • Stateless guarantee (same input → same output)
# ============================================================

import os
os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://opsyn:opsyn@localhost:5432/opsyn_test")
os.environ.setdefault("SECRET_KEY",
    "test-secret-key-minimum-32-characters-long-for-jwt-signing")
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("SMTP_PASSWORD", "test")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("ALLOWED_ORIGINS_STR", "http://localhost:5173")

import pytest
from datetime import date, datetime, time

from app.modules.form_builder.validation_engine import (
    ValidationContext, ValidationResult, FieldError,
    validate, _eval_operator, _field_is_hidden, _coerce,
)


# ── Fixtures ──────────────────────────────────────────────────

def ctx(**kwargs) -> ValidationContext:
    defaults = {
        "tenant_id": "tenant-1",
        "submitting_user_role": "admin",
        "current_pipeline_stage_order": 0,
        "is_draft": False,
    }
    return ValidationContext(**{**defaults, **kwargs})


def field(key: str, ftype: str, **kwargs) -> dict:
    """Build a minimal field definition dict."""
    return {
        "field_key": key,
        "label": key.replace("_", " ").title(),
        "field_type": ftype,
        "is_required": False,
        "validation_rules": {},
        "options": [],
        "conditional_logic": None,
        "role_editable": None,
        "stage_required_at": None,
        **kwargs,
    }


def ok(result: ValidationResult) -> None:
    assert result.is_valid, f"Expected valid but got errors: {result.errors}"


def err(result: ValidationResult, code: str | None = None) -> None:
    assert not result.is_valid, "Expected invalid but got no errors"
    if code:
        codes = [e.error_code for e in result.errors]
        assert code in codes, f"Expected error code '{code}' in {codes}"


# ══════════════════════════════════════════════════════════════
#  1. STRING
# ══════════════════════════════════════════════════════════════

class TestString:
    def test_valid(self):
        r = validate([field("name", "string")], {"name": "Alice"}, ctx())
        ok(r)
        assert r.coerced_data["name"] == "Alice"

    def test_invalid_type_number_is_coerced_to_string(self):
        r = validate([field("name", "string")], {"name": 42}, ctx())
        ok(r)
        assert r.coerced_data["name"] == "42"

    def test_min_length_boundary(self):
        fd = field("name", "string", validation_rules={"min_length": 5})
        r = validate([fd], {"name": "ab"}, ctx())
        err(r, "min_length")

    def test_max_length_boundary(self):
        fd = field("name", "string", validation_rules={"max_length": 3})
        r = validate([fd], {"name": "toolong"}, ctx())
        err(r, "max_length")

    def test_regex_pass(self):
        fd = field("code", "string", validation_rules={"regex": r"^[A-Z]{3}$"})
        r = validate([fd], {"code": "ABC"}, ctx())
        ok(r)

    def test_regex_fail(self):
        fd = field("code", "string", validation_rules={"regex": r"^[A-Z]{3}$"})
        r = validate([fd], {"code": "abc"}, ctx())
        err(r, "regex")

    def test_allowed_chars_alphanumeric(self):
        fd = field("ref", "string", validation_rules={"allowed_chars": "alphanumeric"})
        r = validate([fd], {"ref": "hello world"}, ctx())
        err(r, "allowed_chars")

    def test_required_empty(self):
        fd = field("name", "string", is_required=True)
        r = validate([fd], {}, ctx())
        err(r, "required")
        assert "name" in r.missing_required_fields


# ══════════════════════════════════════════════════════════════
#  2. TEXT
# ══════════════════════════════════════════════════════════════

class TestText:
    def test_valid(self):
        r = validate([field("bio", "text")], {"bio": "Hello world\nLine 2"}, ctx())
        ok(r)

    def test_min_length(self):
        fd = field("bio", "text", validation_rules={"min_length": 10})
        r = validate([fd], {"bio": "Short"}, ctx())
        err(r, "min_length")

    def test_max_length(self):
        fd = field("bio", "text", validation_rules={"max_length": 5})
        r = validate([fd], {"bio": "This is too long"}, ctx())
        err(r, "max_length")


# ══════════════════════════════════════════════════════════════
#  3. INTEGER
# ══════════════════════════════════════════════════════════════

class TestInteger:
    def test_valid_int(self):
        r = validate([field("age", "integer")], {"age": 25}, ctx())
        ok(r)
        assert r.coerced_data["age"] == 25

    def test_valid_string_int(self):
        r = validate([field("age", "integer")], {"age": "30"}, ctx())
        ok(r)
        assert r.coerced_data["age"] == 30

    def test_invalid_type(self):
        r = validate([field("age", "integer")], {"age": "not-a-number"}, ctx())
        err(r, "type_error")

    def test_min_boundary(self):
        fd = field("age", "integer", validation_rules={"min": 18})
        r = validate([fd], {"age": 17}, ctx())
        err(r, "min")

    def test_max_boundary(self):
        fd = field("age", "integer", validation_rules={"max": 120})
        r = validate([fd], {"age": 121}, ctx())
        err(r, "max")

    def test_float_with_decimal_rejected(self):
        r = validate([field("count", "integer")], {"count": "3.7"}, ctx())
        err(r, "type_error")


# ══════════════════════════════════════════════════════════════
#  4. FLOAT
# ══════════════════════════════════════════════════════════════

class TestFloat:
    def test_valid(self):
        r = validate([field("rate", "float")], {"rate": 3.14}, ctx())
        ok(r)
        assert abs(r.coerced_data["rate"] - 3.14) < 1e-9

    def test_string_float(self):
        r = validate([field("rate", "float")], {"rate": "2.50"}, ctx())
        ok(r)

    def test_invalid_type(self):
        r = validate([field("rate", "float")], {"rate": "abc"}, ctx())
        err(r, "type_error")

    def test_decimal_places(self):
        fd = field("rate", "float", validation_rules={"decimal_places": 2})
        r = validate([fd], {"rate": 3.14159}, ctx())
        err(r, "decimal_places")

    def test_min(self):
        fd = field("temp", "float", validation_rules={"min": 0.0})
        r = validate([fd], {"temp": -1.0}, ctx())
        err(r, "min")


# ══════════════════════════════════════════════════════════════
#  5. BOOLEAN
# ══════════════════════════════════════════════════════════════

class TestBoolean:
    def test_true(self):
        r = validate([field("active", "boolean")], {"active": True}, ctx())
        ok(r)
        assert r.coerced_data["active"] is True

    def test_string_true(self):
        r = validate([field("active", "boolean")], {"active": "true"}, ctx())
        ok(r)
        assert r.coerced_data["active"] is True

    def test_string_false(self):
        r = validate([field("active", "boolean")], {"active": "false"}, ctx())
        ok(r)
        assert r.coerced_data["active"] is False

    def test_invalid_type(self):
        r = validate([field("active", "boolean")], {"active": "maybe"}, ctx())
        err(r, "type_error")

    def test_int_zero_is_false(self):
        r = validate([field("active", "boolean")], {"active": 0}, ctx())
        ok(r)
        assert r.coerced_data["active"] is False


# ══════════════════════════════════════════════════════════════
#  6. DATE
# ══════════════════════════════════════════════════════════════

class TestDate:
    def test_valid_iso(self):
        r = validate([field("dob", "date")], {"dob": "1990-01-15"}, ctx())
        ok(r)

    def test_invalid_format(self):
        r = validate([field("dob", "date")], {"dob": "15/01/1990"}, ctx())
        err(r, "type_error")

    def test_no_future(self):
        fd = field("dob", "date", validation_rules={"no_future": True})
        r = validate([fd], {"dob": "2099-12-31"}, ctx())
        err(r, "no_future")

    def test_no_past(self):
        fd = field("appt", "date", validation_rules={"no_past": True})
        r = validate([fd], {"appt": "2000-01-01"}, ctx())
        err(r, "no_past")

    def test_min_date(self):
        fd = field("appt", "date", validation_rules={"min_date": "2026-01-01"})
        r = validate([fd], {"appt": "2025-12-31"}, ctx())
        err(r, "min_date")

    def test_max_date(self):
        fd = field("appt", "date", validation_rules={"max_date": "2026-12-31"})
        r = validate([fd], {"appt": "2027-01-01"}, ctx())
        err(r, "max_date")


# ══════════════════════════════════════════════════════════════
#  7. DATETIME
# ══════════════════════════════════════════════════════════════

class TestDatetime:
    def test_valid(self):
        r = validate([field("ts", "datetime")], {"ts": "2026-05-18T10:30:00"}, ctx())
        ok(r)

    def test_invalid_format(self):
        r = validate([field("ts", "datetime")], {"ts": "not-a-datetime"}, ctx())
        err(r, "type_error")

    def test_min_date(self):
        fd = field("ts", "datetime", validation_rules={"min_date": "2026-06-01T00:00:00"})
        r = validate([fd], {"ts": "2026-05-01T00:00:00"}, ctx())
        err(r, "min_date")


# ══════════════════════════════════════════════════════════════
#  8. TIME
# ══════════════════════════════════════════════════════════════

class TestTime:
    def test_valid(self):
        r = validate([field("t", "time")], {"t": "09:30"}, ctx())
        ok(r)

    def test_invalid_format(self):
        r = validate([field("t", "time")], {"t": "9am"}, ctx())
        err(r, "type_error")

    def test_min_time(self):
        fd = field("t", "time", validation_rules={"min_time": "09:00"})
        r = validate([fd], {"t": "08:00"}, ctx())
        err(r, "min_time")

    def test_max_time(self):
        fd = field("t", "time", validation_rules={"max_time": "17:00"})
        r = validate([fd], {"t": "18:00"}, ctx())
        err(r, "max_time")


# ══════════════════════════════════════════════════════════════
#  9. EMAIL
# ══════════════════════════════════════════════════════════════

class TestEmail:
    def test_valid(self):
        r = validate([field("email", "email")], {"email": "user@example.com"}, ctx())
        ok(r)

    def test_invalid_format(self):
        r = validate([field("email", "email")], {"email": "not-an-email"}, ctx())
        err(r, "email_format")

    def test_missing_at(self):
        r = validate([field("email", "email")], {"email": "userexample.com"}, ctx())
        err(r, "email_format")

    def test_max_length(self):
        fd = field("email", "email", validation_rules={"max_length": 10})
        r = validate([fd], {"email": "a@b.com"}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  10. PHONE
# ══════════════════════════════════════════════════════════════

class TestPhone:
    def test_valid_e164(self):
        r = validate([field("phone", "phone")], {"phone": "+2348012345678"}, ctx())
        ok(r)

    def test_missing_plus(self):
        r = validate([field("phone", "phone")], {"phone": "2348012345678"}, ctx())
        err(r, "phone_format")

    def test_too_short(self):
        r = validate([field("phone", "phone")], {"phone": "+123"}, ctx())
        err(r, "phone_format")

    def test_local_number_rejected(self):
        r = validate([field("phone", "phone")], {"phone": "08012345678"}, ctx())
        err(r, "phone_format")


# ══════════════════════════════════════════════════════════════
#  11. URL
# ══════════════════════════════════════════════════════════════

class TestUrl:
    def test_valid_https(self):
        r = validate([field("site", "url")], {"site": "https://example.com"}, ctx())
        ok(r)

    def test_valid_http(self):
        r = validate([field("site", "url")], {"site": "http://example.com/path?q=1"}, ctx())
        ok(r)

    def test_invalid_no_scheme(self):
        r = validate([field("site", "url")], {"site": "example.com"}, ctx())
        err(r, "url_format")

    def test_invalid_ftp(self):
        r = validate([field("site", "url")], {"site": "ftp://example.com"}, ctx())
        err(r, "url_format")


# ══════════════════════════════════════════════════════════════
#  12. ENUM
# ══════════════════════════════════════════════════════════════

class TestEnum:
    _opts = [{"value": "A", "label": "Option A"}, {"value": "B", "label": "Option B"}]

    def test_valid_option(self):
        fd = field("choice", "enum", options=self._opts)
        r = validate([fd], {"choice": "A"}, ctx())
        ok(r)

    def test_invalid_option(self):
        fd = field("choice", "enum", options=self._opts)
        r = validate([fd], {"choice": "C"}, ctx())
        err(r, "invalid_option")

    def test_no_options_accepts_any(self):
        fd = field("choice", "enum", options=[])
        r = validate([fd], {"choice": "anything"}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  13. MULTISELECT
# ══════════════════════════════════════════════════════════════

class TestMultiselect:
    _opts = [{"value": "X"}, {"value": "Y"}, {"value": "Z"}]

    def test_valid_list(self):
        fd = field("tags", "multiselect", options=self._opts)
        r = validate([fd], {"tags": ["X", "Y"]}, ctx())
        ok(r)
        assert r.coerced_data["tags"] == ["X", "Y"]

    def test_invalid_item(self):
        fd = field("tags", "multiselect", options=self._opts)
        r = validate([fd], {"tags": ["X", "W"]}, ctx())
        err(r, "invalid_option")

    def test_min_selections(self):
        fd = field("tags", "multiselect",
                   options=self._opts, validation_rules={"min_selections": 2})
        r = validate([fd], {"tags": ["X"]}, ctx())
        err(r, "min_selections")

    def test_max_selections(self):
        fd = field("tags", "multiselect",
                   options=self._opts, validation_rules={"max_selections": 1})
        r = validate([fd], {"tags": ["X", "Y"]}, ctx())
        err(r, "max_selections")

    def test_csv_string_coercion(self):
        fd = field("tags", "multiselect", options=[])
        r = validate([fd], {"tags": "X,Y,Z"}, ctx())
        ok(r)
        assert r.coerced_data["tags"] == ["X", "Y", "Z"]


# ══════════════════════════════════════════════════════════════
#  14. RADIO
# ══════════════════════════════════════════════════════════════

class TestRadio:
    _opts = [{"value": "yes"}, {"value": "no"}]

    def test_valid(self):
        fd = field("consent", "radio", options=self._opts)
        r = validate([fd], {"consent": "yes"}, ctx())
        ok(r)

    def test_invalid(self):
        fd = field("consent", "radio", options=self._opts)
        r = validate([fd], {"consent": "maybe"}, ctx())
        err(r, "invalid_option")

    def test_empty_options_accepts_any(self):
        fd = field("consent", "radio", options=[])
        r = validate([fd], {"consent": "anything"}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  15. FILE
# ══════════════════════════════════════════════════════════════

class TestFile:
    def test_valid_dict(self):
        fd = field("doc", "file")
        r = validate([fd], {"doc": {"url": "/uploads/doc.pdf",
                                    "mime_type": "application/pdf",
                                    "size_bytes": 1024}}, ctx())
        ok(r)

    def test_invalid_mime(self):
        fd = field("doc", "file",
                   validation_rules={"allowed_mime_types": ["application/pdf"]})
        r = validate([fd], {"doc": {"mime_type": "image/png", "size_bytes": 100}}, ctx())
        err(r, "allowed_mime_types")

    def test_max_size(self):
        fd = field("doc", "file",
                   validation_rules={"max_size_mb": 1})
        r = validate([fd], {"doc": {"mime_type": "application/pdf",
                                    "size_bytes": 2_000_000}}, ctx())
        err(r, "max_size_mb")

    def test_url_string_coerced(self):
        fd = field("doc", "file")
        r = validate([fd], {"doc": "https://example.com/file.pdf"}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  16. IMAGE
# ══════════════════════════════════════════════════════════════

class TestImage:
    def test_valid(self):
        fd = field("photo", "image")
        r = validate([fd], {"photo": {"url": "/img.jpg", "mime_type": "image/jpeg",
                                       "size_bytes": 500_000, "width": 800, "height": 600}}, ctx())
        ok(r)

    def test_min_width(self):
        fd = field("photo", "image", validation_rules={"min_width": 1000})
        r = validate([fd], {"photo": {"width": 500, "height": 600,
                                       "mime_type": "image/jpeg", "size_bytes": 100}}, ctx())
        err(r, "min_width")

    def test_min_height(self):
        fd = field("photo", "image", validation_rules={"min_height": 1000})
        r = validate([fd], {"photo": {"width": 1200, "height": 400,
                                       "mime_type": "image/jpeg", "size_bytes": 100}}, ctx())
        err(r, "min_height")


# ══════════════════════════════════════════════════════════════
#  17. COORDINATES
# ══════════════════════════════════════════════════════════════

class TestCoordinates:
    def test_valid(self):
        r = validate([field("loc", "coordinates")],
                     {"loc": {"lat": 6.5244, "lng": 3.3792}}, ctx())
        ok(r)

    def test_invalid_lat(self):
        r = validate([field("loc", "coordinates")],
                     {"loc": {"lat": 95.0, "lng": 3.3792}}, ctx())
        err(r, "lat_range")

    def test_invalid_lng(self):
        r = validate([field("loc", "coordinates")],
                     {"loc": {"lat": 6.5, "lng": 200.0}}, ctx())
        err(r, "lng_range")

    def test_zero_zero_warns(self):
        r = validate([field("loc", "coordinates")],
                     {"loc": {"lat": 0.0, "lng": 0.0}}, ctx())
        ok(r)
        assert any("0, 0" in w.message or "(0, 0)" in w.message for w in r.warnings)

    def test_not_a_dict(self):
        r = validate([field("loc", "coordinates")], {"loc": "6.52,3.37"}, ctx())
        err(r, "type_error")


# ══════════════════════════════════════════════════════════════
#  18. ADDRESS
# ══════════════════════════════════════════════════════════════

class TestAddress:
    def test_valid(self):
        fd = field("addr", "address")
        r = validate([fd], {"addr": {"street": "1 Main St", "city": "Lagos",
                                      "country": "NG", "postcode": "100001"}}, ctx())
        ok(r)

    def test_required_sub_fields_missing(self):
        fd = field("addr", "address",
                   validation_rules={"required_sub_fields": ["street", "city"]})
        r = validate([fd], {"addr": {"country": "NG"}}, ctx())
        assert not r.is_valid

    def test_not_a_dict(self):
        r = validate([field("addr", "address")], {"addr": "1 Main St"}, ctx())
        err(r, "type_error")


# ══════════════════════════════════════════════════════════════
#  19. CURRENCY
# ══════════════════════════════════════════════════════════════

class TestCurrency:
    def test_valid(self):
        r = validate([field("fee", "currency")],
                     {"fee": {"amount": 5000.00, "currency": "NGN"}}, ctx())
        ok(r)

    def test_invalid_currency(self):
        fd = field("fee", "currency",
                   validation_rules={"allowed_currencies": ["NGN", "USD"]})
        r = validate([fd], {"fee": {"amount": 100, "currency": "JPY"}}, ctx())
        err(r, "allowed_currencies")

    def test_min_amount(self):
        fd = field("fee", "currency", validation_rules={"min": 500})
        r = validate([fd], {"fee": {"amount": 100, "currency": "NGN"}}, ctx())
        err(r, "min")

    def test_not_a_dict(self):
        r = validate([field("fee", "currency")], {"fee": "500 NGN"}, ctx())
        err(r, "type_error")


# ══════════════════════════════════════════════════════════════
#  20. RATING
# ══════════════════════════════════════════════════════════════

class TestRating:
    def test_valid(self):
        fd = field("score", "rating",
                   validation_rules={"min_rating": 1, "max_rating": 5})
        r = validate([fd], {"score": 4}, ctx())
        ok(r)

    def test_below_min(self):
        fd = field("score", "rating", validation_rules={"min_rating": 1})
        r = validate([fd], {"score": 0}, ctx())
        err(r, "min_rating")

    def test_above_max(self):
        fd = field("score", "rating", validation_rules={"max_rating": 5})
        r = validate([fd], {"score": 6}, ctx())
        err(r, "max_rating")

    def test_invalid_type(self):
        r = validate([field("score", "rating")], {"score": "excellent"}, ctx())
        err(r, "type_error")


# ══════════════════════════════════════════════════════════════
#  21. SIGNATURE
# ══════════════════════════════════════════════════════════════

class TestSignature:
    def test_valid_base64(self):
        r = validate([field("sig", "signature")],
                     {"sig": "data:image/png;base64,AAABBB"}, ctx())
        ok(r)
        assert r.coerced_data["sig"] == "data:image/png;base64,AAABBB"

    def test_required_empty(self):
        fd = field("sig", "signature", is_required=True)
        r = validate([fd], {}, ctx())
        err(r, "required")

    def test_any_string_accepted(self):
        r = validate([field("sig", "signature")], {"sig": "somestring"}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  22. LOOKUP
# ══════════════════════════════════════════════════════════════

class TestLookup:
    def test_valid_uuid_string(self):
        r = validate([field("customer_ref", "lookup")],
                     {"customer_ref": "00000000-0000-0000-0000-000000000001"}, ctx())
        ok(r)
        assert r.coerced_data["customer_ref"] == "00000000-0000-0000-0000-000000000001"

    def test_required_empty(self):
        fd = field("customer_ref", "lookup", is_required=True)
        r = validate([fd], {}, ctx())
        err(r, "required")

    def test_any_string_accepted_by_engine(self):
        r = validate([field("ref", "lookup")], {"ref": "some-id"}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  23. COMPUTED
# ══════════════════════════════════════════════════════════════

class TestComputed:
    def test_computed_value_not_stored(self):
        fd = field("total", "computed",
                   validation_rules={"formula": "{price} * {qty}"})
        r = validate([fd], {"total": 1500}, ctx())
        ok(r)
        # Computed fields are never stored in coerced_data
        assert "total" not in r.coerced_data

    def test_computed_no_errors(self):
        fd = field("total", "computed")
        r = validate([fd], {}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  24. SECTION_HEADER
# ══════════════════════════════════════════════════════════════

class TestSectionHeader:
    def test_display_only_no_errors(self):
        fd = field("section_1", "section_header", is_required=True)
        r = validate([fd], {}, ctx())
        ok(r)
        assert "section_1" not in r.coerced_data

    def test_no_validation_applied(self):
        fd = field("sep", "section_header",
                   validation_rules={"min_length": 99})
        r = validate([fd], {"sep": ""}, ctx())
        ok(r)


# ══════════════════════════════════════════════════════════════
#  CONDITIONAL LOGIC — all 10 operators
# ══════════════════════════════════════════════════════════════

class TestConditionalOperators:
    def _eval(self, op, field_val, cond_val) -> bool:
        return _eval_operator(op, field_val, cond_val)

    def test_equals_match(self):
        assert self._eval("equals", "Business", "Business") is True

    def test_equals_no_match(self):
        assert self._eval("equals", "Residential", "Business") is False

    def test_not_equals_match(self):
        assert self._eval("not_equals", "A", "B") is True

    def test_not_equals_no_match(self):
        assert self._eval("not_equals", "A", "A") is False

    def test_contains_string(self):
        assert self._eval("contains", "hello world", "world") is True

    def test_contains_list(self):
        assert self._eval("contains", ["a", "b"], "b") is True

    def test_not_contains(self):
        assert self._eval("not_contains", "hello", "world") is True

    def test_greater_than(self):
        assert self._eval("greater_than", "10", "5") is True
        assert self._eval("greater_than", "3", "5") is False

    def test_less_than(self):
        assert self._eval("less_than", "3", "5") is True
        assert self._eval("less_than", "10", "5") is False

    def test_is_empty(self):
        assert self._eval("is_empty", None, None) is True
        assert self._eval("is_empty", "", None) is True
        assert self._eval("is_empty", "value", None) is False

    def test_is_not_empty(self):
        assert self._eval("is_not_empty", "x", None) is True
        assert self._eval("is_not_empty", None, None) is False

    def test_in(self):
        assert self._eval("in", "B", ["A", "B", "C"]) is True
        assert self._eval("in", "D", ["A", "B", "C"]) is False

    def test_not_in(self):
        assert self._eval("not_in", "D", ["A", "B", "C"]) is True
        assert self._eval("not_in", "A", ["A", "B", "C"]) is False


# ══════════════════════════════════════════════════════════════
#  CONDITIONAL LOGIC ACTIONS — hide, show, require
# ══════════════════════════════════════════════════════════════

class TestConditionalActions:
    def _schema(self, logic) -> list[dict]:
        return [
            field("trigger", "enum", options=[{"value": "yes"}, {"value": "no"}]),
            {**field("target", "string", is_required=False), "conditional_logic": logic},
        ]

    def test_hide_skips_required_check(self):
        """Hidden field is never validated even if it has data."""
        logic = {"action": "hide", "match": "all",
                 "conditions": [{"field_key": "trigger", "operator": "equals", "value": "yes"}]}
        schema = [
            field("trigger", "enum"),
            {**field("target", "string", is_required=True), "conditional_logic": logic},
        ]
        # trigger=yes → target is hidden → no required error even though target is empty
        r = validate(schema, {"trigger": "yes"}, ctx())
        ok(r)

    def test_show_hides_when_conditions_not_met(self):
        """Show action: field hidden when conditions NOT met."""
        logic = {"action": "show", "match": "all",
                 "conditions": [{"field_key": "trigger", "operator": "equals", "value": "Business"}]}
        schema = [
            field("trigger", "enum"),
            {**field("target", "string", is_required=True), "conditional_logic": logic},
        ]
        # trigger=Residential → show conditions not met → target hidden → no required error
        r = validate(schema, {"trigger": "Residential"}, ctx())
        ok(r)

    def test_show_reveals_when_conditions_met(self):
        """Show action: field visible (and required) when conditions MET."""
        logic = {"action": "show", "match": "all",
                 "conditions": [{"field_key": "trigger", "operator": "equals", "value": "Business"}]}
        schema = [
            field("trigger", "enum"),
            {**field("target", "string", is_required=True), "conditional_logic": logic},
        ]
        # trigger=Business → show conditions met → target visible and required → error
        r = validate(schema, {"trigger": "Business"}, ctx())
        err(r, "required")

    def test_require_makes_field_required_when_conditions_met(self):
        """Require action: field becomes required when conditions met."""
        logic = {"action": "require", "match": "all",
                 "conditions": [{"field_key": "trigger", "operator": "equals", "value": "yes"}]}
        schema = [
            field("trigger", "enum"),
            {**field("target", "string", is_required=False), "conditional_logic": logic},
        ]
        # trigger=yes → target conditionally required → missing → error
        r = validate(schema, {"trigger": "yes"}, ctx())
        err(r, "required")

    def test_require_not_triggered_when_conditions_not_met(self):
        """Require action: field stays optional when conditions not met."""
        logic = {"action": "require", "match": "all",
                 "conditions": [{"field_key": "trigger", "operator": "equals", "value": "yes"}]}
        schema = [
            field("trigger", "enum"),
            {**field("target", "string", is_required=False), "conditional_logic": logic},
        ]
        r = validate(schema, {"trigger": "no"}, ctx())
        ok(r)

    def test_any_match_mode(self):
        """OR (any) mode: triggered if at least one condition is true."""
        logic = {"action": "hide", "match": "any",
                 "conditions": [
                     {"field_key": "a", "operator": "equals", "value": "X"},
                     {"field_key": "b", "operator": "equals", "value": "Y"},
                 ]}
        schema = [
            field("a", "string"), field("b", "string"),
            {**field("target", "string", is_required=True), "conditional_logic": logic},
        ]
        r = validate(schema, {"a": "X", "b": "Z"}, ctx())
        ok(r)  # a=X matches → target hidden → no required error

    def test_all_match_mode_both_must_match(self):
        """AND (all) mode: only triggered if all conditions are true."""
        logic = {"action": "hide", "match": "all",
                 "conditions": [
                     {"field_key": "a", "operator": "equals", "value": "X"},
                     {"field_key": "b", "operator": "equals", "value": "Y"},
                 ]}
        schema = [
            field("a", "string"), field("b", "string"),
            {**field("target", "string", is_required=True), "conditional_logic": logic},
        ]
        # Only a=X, b≠Y → conditions not all met → target visible → required error
        r = validate(schema, {"a": "X", "b": "Z"}, ctx())
        err(r, "required")


# ══════════════════════════════════════════════════════════════
#  ROLE-BASED FILTERING
# ══════════════════════════════════════════════════════════════

class TestRoleFiltering:
    def test_field_dropped_when_role_not_in_role_editable(self):
        """Field silently dropped when submitter's role is not in role_editable."""
        fd = {**field("admin_note", "string"), "role_editable": ["admin", "manager"]}
        r = validate([fd], {"admin_note": "secret"}, ctx(submitting_user_role="technician"))
        ok(r)
        assert "admin_note" not in r.coerced_data

    def test_field_accepted_when_role_in_role_editable(self):
        fd = {**field("note", "string"), "role_editable": ["admin", "manager"]}
        r = validate([fd], {"note": "visible"}, ctx(submitting_user_role="admin"))
        ok(r)
        assert r.coerced_data["note"] == "visible"

    def test_no_role_editable_allows_all_roles(self):
        """role_editable=None means all roles can submit this field."""
        fd = field("name", "string")
        r = validate([fd], {"name": "Alice"}, ctx(submitting_user_role="technician"))
        ok(r)
        assert r.coerced_data["name"] == "Alice"

    def test_role_case_insensitive(self):
        fd = {**field("note", "string"), "role_editable": ["Admin"]}
        r = validate([fd], {"note": "hi"}, ctx(submitting_user_role="admin"))
        ok(r)
        assert "note" in r.coerced_data

    def test_required_field_dropped_by_role_no_error(self):
        """Required field silently dropped if role can't edit — no required error."""
        fd = {**field("secret", "string", is_required=True), "role_editable": ["admin"]}
        r = validate([fd], {"secret": "value"},
                     ctx(submitting_user_role="technician"))
        ok(r)
        assert "secret" not in r.coerced_data


# ══════════════════════════════════════════════════════════════
#  STAGE-BASED REQUIRED
# ══════════════════════════════════════════════════════════════

class TestStageBased:
    def test_field_required_when_stage_reached(self):
        fd = {**field("gis_data", "string"), "stage_required_at": 3}
        r = validate([fd], {}, ctx(current_pipeline_stage_order=3))
        err(r, "stage_required")

    def test_field_not_required_before_stage(self):
        fd = {**field("gis_data", "string"), "stage_required_at": 3}
        r = validate([fd], {}, ctx(current_pipeline_stage_order=2))
        ok(r)

    def test_field_required_at_higher_stage_too(self):
        fd = {**field("gis_data", "string"), "stage_required_at": 3}
        r = validate([fd], {}, ctx(current_pipeline_stage_order=5))
        err(r, "stage_required")


# ══════════════════════════════════════════════════════════════
#  DRAFT MODE
# ══════════════════════════════════════════════════════════════

class TestDraftMode:
    def test_required_not_enforced_in_draft(self):
        fd = field("name", "string", is_required=True)
        r = validate([fd], {}, ctx(is_draft=True))
        ok(r)

    def test_stage_required_not_enforced_in_draft(self):
        fd = {**field("gis", "string"), "stage_required_at": 1}
        r = validate([fd], {}, ctx(is_draft=True, current_pipeline_stage_order=5))
        ok(r)

    def test_type_errors_still_raised_in_draft(self):
        """Type coercion errors surface even in draft mode."""
        r = validate([field("age", "integer")], {"age": "abc"}, ctx(is_draft=True))
        err(r, "type_error")

    def test_valid_data_still_coerced_in_draft(self):
        r = validate([field("age", "integer")], {"age": "25"}, ctx(is_draft=True))
        ok(r)
        assert r.coerced_data["age"] == 25


# ══════════════════════════════════════════════════════════════
#  UNIQUENESS CHECKER CALLBACK
# ══════════════════════════════════════════════════════════════

class TestUniqueness:
    def test_passes_when_unique(self):
        fd = field("email", "email",
                   validation_rules={"unique_in_schema": True})
        checker = lambda fkey, tid, val: True  # always unique
        r = validate([fd], {"email": "a@b.com"}, ctx(), uniqueness_checker=checker)
        ok(r)

    def test_fails_when_duplicate(self):
        fd = field("email", "email",
                   validation_rules={"unique_in_schema": True})
        checker = lambda fkey, tid, val: False  # always duplicate
        r = validate([fd], {"email": "a@b.com"}, ctx(), uniqueness_checker=checker)
        err(r, "unique_in_schema")

    def test_uniqueness_not_checked_without_callback(self):
        fd = field("email", "email",
                   validation_rules={"unique_in_schema": True})
        r = validate([fd], {"email": "a@b.com"}, ctx(), uniqueness_checker=None)
        ok(r)


# ══════════════════════════════════════════════════════════════
#  STATELESS GUARANTEE
# ══════════════════════════════════════════════════════════════

class TestStateless:
    def test_same_input_same_output(self):
        schema = [
            field("name", "string", is_required=True,
                  validation_rules={"min_length": 2}),
            field("age", "integer"),
        ]
        data = {"name": "Al", "age": 25}
        c = ctx()
        r1 = validate(schema, data, c)
        r2 = validate(schema, data, c)
        assert r1.is_valid == r2.is_valid
        assert len(r1.errors) == len(r2.errors)
        assert r1.coerced_data == r2.coerced_data

    def test_invalid_input_same_errors(self):
        schema = [field("age", "integer", validation_rules={"min": 18})]
        data   = {"age": 10}
        c      = ctx()
        r1 = validate(schema, data, c)
        r2 = validate(schema, data, c)
        assert r1.errors[0].error_code == r2.errors[0].error_code


# ══════════════════════════════════════════════════════════════
#  MULTIPLE FIELDS — MIXED VALID / INVALID
# ══════════════════════════════════════════════════════════════

class TestMixedSchema:
    def test_multiple_errors_collected(self):
        schema = [
            field("name",  "string",  is_required=True),
            field("email", "email",   is_required=True),
            field("age",   "integer", validation_rules={"min": 18}),
        ]
        r = validate(schema, {"age": 10}, ctx())
        assert not r.is_valid
        codes = [e.error_code for e in r.errors]
        assert "required" in codes     # name missing
        assert "required" in codes     # email missing
        assert "min" in codes          # age < 18
        assert len(r.errors) >= 3

    def test_partial_submission_stores_valid_fields(self):
        schema = [
            field("name",  "string"),
            field("email", "email",  validation_rules={"max_length": 3}),
        ]
        r = validate(schema, {"name": "Alice", "email": "toolong@x.com"}, ctx())
        assert not r.is_valid
        assert "name" in r.coerced_data  # valid field still stored
        # email failed its rule — not in coerced_data
        # (engine only stores fields that pass all rules)

    def test_custom_error_message_used(self):
        fd = field("code", "string",
                   validation_rules={"regex": r"^[A-Z]+$",
                                     "custom_error_message": "Code must be uppercase letters only."})
        r = validate([fd], {"code": "abc123"}, ctx())
        assert not r.is_valid
        assert r.errors[0].message == "Code must be uppercase letters only."
