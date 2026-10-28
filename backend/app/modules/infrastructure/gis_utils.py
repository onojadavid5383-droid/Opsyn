# ============================================================
# OPSYN GIS UTILITIES — app/modules/infrastructure/gis_utils.py
# Coordinate validation and PostGIS WKT point generation.
# Used by the Infrastructure upload validation engine.
# ============================================================

from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Coordinate storage is not uniform across the infrastructure tables, and the
# difference matters:
#
#   cabinets, olts, splitter_boxes   double precision  (~15-16 significant digits)
#   infrastructure_sites             numeric(10,7)     (~1 cm at the equator)
#
# FTTX_INFRASTRUCTURE_FIXES.md item 3 says to "match the ORM's Numeric(10,7)
# precision" for the asset tables; that is wrong for those three, which are
# double precision. So nothing is rounded here. Rounding a double column to 7dp
# would silently discard data the column can hold, which is a worse defect than
# the one being fixed.
#
# What actually drifted the coordinates was make_point() interpolating a
# binary64's repr into WKT, so the geometry column ended up holding
# 6.524377999999 while the numeric column beside it held 6.524378. Parsing to
# Decimal and rendering the WKT from it fixes that without touching precision.
#
# The warning threshold is therefore set at the point where a value stops being
# a coordinate and starts being a data-entry artefact, and beyond what a double
# reproduces exactly.
MAX_SIGNIFICANT_DECIMALS = 12


def normalize_coordinate(
    raw: object,
    field: str = "coordinate",
) -> tuple[Decimal | None, str | None, str | None]:
    """Return (value, error, warning) for one coordinate.

    Parses straight to Decimal rather than through float, and returns the value
    unrounded. Callers that need a fixed-scale rendering should quantize where
    the target column's precision is known, not here.
    """
    if raw is None or str(raw).strip() == "":
        return None, f"'{field}' is required", None

    text = str(raw).strip()
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, f"'{field}' must be a valid number (got '{raw}')", None

    if not value.is_finite():
        return None, f"'{field}' must be a finite number (got '{raw}')", None

    # Decimal keeps trailing zeros, so "6.50" and "6.5" compare equal but
    # render differently. Strip them so the WKT and the numeric column agree.
    value = value.normalize()

    warning = None
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > MAX_SIGNIFICANT_DECIMALS:
        warning = (
            f"'{field}' has more than {MAX_SIGNIFICANT_DECIMALS} decimal places "
            f"({text}); stored as given"
        )
    return value, None, warning


def validate_coordinates(
    longitude: float | Decimal | str | None,
    latitude: float | Decimal | str | None,
) -> tuple[bool, list[str]]:
    """Return (is_valid, errors). Never raises — accumulates all errors."""
    errors: list[str] = []

    if longitude is None or latitude is None:
        errors.append("Longitude and latitude are required")
        return False, errors

    try:
        lng = Decimal(str(longitude))
    except (InvalidOperation, ValueError, TypeError):
        errors.append("Longitude must be a valid number")
        lng = None

    try:
        lat = Decimal(str(latitude))
    except (InvalidOperation, ValueError, TypeError):
        errors.append("Latitude must be a valid number")
        lat = None

    if lng is not None and lat is not None:
        # Reject (0, 0) coordinates — Null Island in Gulf of Guinea indicates missing data
        if lng == 0 and lat == 0:
            errors.append("Coordinates (0, 0) indicate missing or invalid location data")

    if lng is not None and not (Decimal(-180) <= lng <= Decimal(180)):
        errors.append("Longitude must be a number between -180 and 180")

    if lat is not None and not (Decimal(-90) <= lat <= Decimal(90)):
        errors.append("Latitude must be a number between -90 and 90")

    return len(errors) == 0, errors


def make_point(longitude: Decimal | float, latitude: Decimal | float):
    """Return a geoalchemy2 WKTElement for geometry(Point,4326) columns.

    This function requires geoalchemy2 to be installed. No fallback is provided
    as the database schema requires PostGIS geometry types.

    The coordinates are interpolated straight into the WKT string, so they
    must be Decimal (or an int). Do not pass a float here: repr() of a
    binary64 would put 6.524377999999 in the geometry column and no longer
    match the longitude/longitude columns beside it.
    """
    from geoalchemy2 import WKTElement
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)
