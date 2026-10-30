from flask import Blueprint, jsonify

from countries import COUNTRIES
from ip_country import detect_request_country

bp = Blueprint("geo_ip", __name__, url_prefix="/api/geo")

_COUNTRY_LIST = [{"code": code, "name": name} for code, name in COUNTRIES.items()]


@bp.get("")
def where_am_i():
    """For the sign-up form's Country dropdown: the full country list plus
    a suggestion from the visitor's IP. No suggestion when the IP is a
    VPN/proxy/datacenter address (its location means nothing) -- the user
    just picks."""
    detected = detect_request_country()
    suggested = None if detected["is_vpn"] else detected["country"]
    return jsonify(
        {
            "suggested_country": suggested,
            "is_vpn": detected["is_vpn"],
            "countries": _COUNTRY_LIST,
        }
    )
