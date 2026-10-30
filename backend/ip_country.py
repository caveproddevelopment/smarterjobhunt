"""Where is this request coming from? Used to decide whether a user pays
through Razorpay (India) or Stripe (everyone else).

Two pieces:
  * client_ip()      -- the visitor's real IP behind Railway's proxy.
  * lookup_ip(ip)    -- country + "is this a VPN/proxy/datacenter/Tor exit?"
                        via ipapi.is (free tier: 1,000 lookups/day without a
                        key; set IPAPI_KEY for more).

Everything here fails soft: a timeout, a bad response or a missing IP just
returns country=None, which makes the caller fall back to the country the
user picked on the sign-up form. Payment routing must never break sign-up.
"""
import ipaddress
import threading
import time

import requests
from flask import current_app, request

from countries import normalize_country

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_MAX = 5000
_TIMEOUT_SECONDS = 2.5


def _valid_public_ip(value):
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast:
        return None
    return str(ip)


def client_ip():
    """The visitor's IP. Railway's edge proxy sets X-Real-IP and appends the
    address it saw to X-Forwarded-For, so prefer X-Real-IP, then the
    right-most X-Forwarded-For entry (the left-most ones can be sent by the
    client itself and are trivially spoofed), then the socket address."""
    candidates = [request.headers.get("X-Real-IP")]
    forwarded = request.headers.get("X-Forwarded-For", "")
    candidates += [part for part in reversed(forwarded.split(","))]
    candidates.append(request.remote_addr)
    for candidate in candidates:
        ip = _valid_public_ip(candidate)
        if ip:
            return ip
    return None


def lookup_ip(ip):
    """{"country": "IN" | None, "is_vpn": bool} for an IP address.

    is_vpn is True for VPNs, proxies, Tor exits and datacenter/hosting
    ranges -- anything where the IP's location says little about where the
    person actually is."""
    unknown = {"country": None, "is_vpn": False}
    if not ip:
        return unknown

    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(ip)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return dict(hit[1])

    params = {"q": ip}
    api_key = current_app.config.get("IPAPI_KEY")
    if api_key:
        params["key"] = api_key
    try:
        resp = requests.get("https://api.ipapi.is/", params=params, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        current_app.logger.warning("IP country lookup failed for %s", ip)
        return unknown

    location = data.get("location") or {}
    result = {
        "country": normalize_country(location.get("country_code")),
        "is_vpn": any(
            bool(data.get(flag))
            for flag in ("is_vpn", "is_proxy", "is_tor", "is_datacenter", "is_abuser")
        ),
    }
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[ip] = (now, result)
    return dict(result)


def detect_request_country():
    """lookup_ip() for the current request's visitor."""
    return lookup_ip(client_ip())


def decide_billing_country(ip_country, ip_is_vpn, chosen_country):
    """The country that decides the payment provider.

    The IP's country wins when we trust it (we got one, and it isn't a
    VPN/proxy/datacenter address). Otherwise fall back to what the user
    picked on the sign-up form. None means we know neither, and the
    frontend has to ask before checkout."""
    if ip_country and not ip_is_vpn:
        return ip_country
    return chosen_country or None
