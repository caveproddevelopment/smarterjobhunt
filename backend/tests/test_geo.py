"""Unit tests for geo.py (the Location + distance filter's place lookup).
No database needed.

    cd backend && python -m pytest tests/test_geo.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geo  # noqa: E402


@pytest.mark.parametrize("text, label", [
    ("Austin, TX", "Austin, TX, US"),
    ("austin", "Austin, TX, US"),
    ("Paris, TX", "Paris, TX, US"),
    ("Paris", "Paris, France"),
    ("New York, NY", "New York City, NY, US"),
    ("NYC", "New York City, NY, US"),
    ("Bangalore", "Bengaluru, India"),
    ("Bengaluru, Karnataka, India", "Bengaluru, India"),
    ("Gurgaon, Haryana", "Gurugram, India"),
    ("San Francisco Bay Area", "San Francisco, CA, US"),
    ("Greater Boston Area", "Boston, MA, US"),
    ("US-CA-San Jose", "San Jose, CA, US"),
    ("London, ON", "London, Canada"),
    ("London, UK", "London, United Kingdom"),
    ("Portland, ME", "Portland, ME, US"),
    ("Vancouver, WA", "Vancouver, WA, US"),
    ("Winston-Salem, NC", "Winston-Salem, NC, US"),
    ("Texas", "Texas, US"),
    ("TX", "Texas, US"),
    ("Georgia", "Georgia, US"),
    ("Washington State", "Washington, US"),
    ("India", "India"),
])
def test_resolve(text, label):
    place = geo.resolve_query(text)
    assert place is not None and place.label == label


@pytest.mark.parametrize("text", ["", "Multiple Locations", "Remote", "xyzzy"])
def test_unplaceable(text):
    assert geo.resolve_query(text) is None


def test_multi_location_listing():
    labels = [p.label for p in geo.parse_job_location("Boston, MA; New York, NY | Remote")]
    assert labels == ["Boston, MA, US", "New York City, NY, US"]


def test_city_radius():
    austin = geo.resolve_query("Austin, TX")
    assert geo.location_matches("Round Rock, TX", austin, 25)      # ~20 mi
    assert not geo.location_matches("San Antonio, TX", austin, 50)  # ~75 mi
    assert geo.location_matches("San Antonio, TX", austin, 100)
    assert not geo.location_matches("Remote", austin, 500)


def test_statewide_posting_counts_for_a_city_in_that_state():
    austin = geo.resolve_query("Austin")
    assert geo.location_matches("Texas", austin, 10)
    assert not geo.location_matches("California", austin, 10)


def test_state_query_includes_state_and_nearby():
    texas = geo.resolve_query("Texas")
    assert geo.location_matches("El Paso, TX", texas, 0)
    assert geo.location_matches("Shreveport, LA", texas, 50)     # just over the border
    assert not geo.location_matches("Shreveport, LA", texas, 5)
    assert not geo.location_matches("Denver, CO", texas, 100)


def test_country_query():
    india = geo.resolve_query("India")
    assert geo.location_matches("Pune, Maharashtra", india, 0)
    assert not geo.location_matches("Austin, TX", india, 500)
