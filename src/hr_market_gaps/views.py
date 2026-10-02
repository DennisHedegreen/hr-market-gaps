from __future__ import annotations

from collections.abc import Mapping

from .models import Visibility


PUBLIC_DIRECT = {Visibility.PUBLIC.value, Visibility.AGGREGATED.value}
PARTNER_ALLOWED = {
    Visibility.PUBLIC.value,
    Visibility.AGGREGATED.value,
    Visibility.DELAYED.value,
    Visibility.CONTRACT_CONFIDENTIAL.value,
    Visibility.PERMISSIONED.value,
}


def public_projection(fields: Mapping[str, dict]) -> dict:
    """Fail-closed public projection.

    Field shape is ``{name: {value, visibility, ...}}``. PUBLIC and already
    AGGREGATED values may pass directly. DELAYED values require ``released`` to
    be explicitly true. PRIVATE, CONTRACT-CONFIDENTIAL, PERMISSIONED and unknown
    visibility values never pass to the public view.
    """

    result = {}
    for key, spec in fields.items():
        visibility = spec.get("visibility")
        if "value" not in spec:
            continue
        if visibility in PUBLIC_DIRECT:
            result[key] = spec["value"]
        elif visibility == Visibility.DELAYED.value and spec.get("released") is True:
            result[key] = spec["value"]
    return result


def partner_projection(fields: Mapping[str, dict], allowed: set[str]) -> dict:
    """Permissioned partner projection with an explicit field allow-list."""

    result = {}
    for key, spec in fields.items():
        if key not in allowed:
            continue
        visibility = spec.get("visibility")
        if "value" not in spec:
            continue
        if visibility in PARTNER_ALLOWED:
            result[key] = spec["value"]
    return result
