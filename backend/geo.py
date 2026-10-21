"""Offline place lookup for the job-listings Location + distance filter.

Jobs only store location as scraped text ("Austin, TX", "Bengaluru,
Karnataka, India", "New York, NY; Remote"), and what a visitor types in the
Location box is free text too. Both go through the same parser here, which
looks names up in a bundled GeoNames city list (data/cities.tsv.gz, built by
scripts/build_geo_data.py) -- no API key, no network call, no DB change.

What a place can resolve to:
  - a city    -> its coordinates; the radius is measured from there
  - a US state ("Texas", "TX") -> a job counts if it's in that state or
    within the radius of any city in it
  - a country ("India")        -> a job counts if it's in that country
    (the radius doesn't apply -- countries are already big areas)

Locations that can't be placed ("Multiple Locations", "Remote") never match
on distance; routes/jobs.py adds remote jobs back in separately.
"""
import gzip
import json
import math
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE_LAT = 69.0

# Words that wrap a place name without being part of it.
_NOISE_WORDS = {
    "remote", "hybrid", "onsite", "on site", "in office", "office", "offices", "hq",
    "headquarters", "greater", "area", "metro", "metropolitan", "region", "based",
    "city of", "downtown", "campus", "work from home", "wfh", "anywhere", "or",
}

# Common job-posting shorthands that the city list doesn't spell this way.
_ALIASES = {
    "nyc": "new york city",
    "new york ny": "new york city",
    "sf": "san francisco",
    "bay area": "san francisco",
    "sf bay": "san francisco",
    "silicon valley": "san jose",
    "dc": "washington dc",
    "washington d c": "washington dc",
    "bombay": "mumbai",
    "ncr": "new delhi",
    "delhi ncr": "new delhi",
    "washington state": "wa",
}

# Canadian provinces -> GeoNames admin1 codes, so "London, ON" means the
# Ontario one, not London, England.
_CA_PROVINCES = {
    "ab": "01", "alberta": "01", "bc": "02", "british columbia": "02", "mb": "03",
    "manitoba": "03", "nb": "04", "new brunswick": "04", "nl": "05", "newfoundland": "05",
    "ns": "07", "nova scotia": "07", "on": "08", "ontario": "08", "pe": "09", "pei": "09",
    "qc": "10", "quebec": "10", "sk": "11", "saskatchewan": "11",
}

_COUNTRY_ALIASES = {
    "usa": "US", "us": "US", "u s": "US", "u s a": "US", "united states of america": "US",
    "america": "US", "uk": "GB", "u k": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "great britain": "GB", "britain": "GB", "uae": "AE",
    "south korea": "KR", "korea": "KR", "russia": "RU", "vietnam": "VN",
}

# Two-letter country codes that are also everyday words or US state codes;
# they only count as a country when nothing else claims them.
_WEAK_COUNTRY_CODES = {"in", "is", "it", "me", "my", "no", "to", "at", "be", "by", "do",
                       "go", "us", "ca", "co", "ga", "al", "ar", "de", "id", "il", "la",
                       "ma", "md", "mn", "mo", "mt", "ne", "pa", "sc", "tn", "va"}

# Splits a job location listing several places ("Austin, TX; Remote",
# "NYC | London", "Boston / Remote") into one piece per place.
_MULTI_SPLIT = re.compile(r";|\||\n|/| \bor\b | & | and ", re.IGNORECASE)


@dataclass(frozen=True)
class Place:
    kind: str           # "city", "state" (US only) or "country"
    country: str        # ISO-2, e.g. "US"
    state: str = ""     # US state code for US cities/states, else GeoNames admin1 code
    lat: float = 0.0
    lon: float = 0.0
    label: str = ""


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9,]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


class _Index:
    def __init__(self):
        self.cities = []          # (name, country, admin1, lat, lon, pop)
        self.by_name = {}         # normalized primary name -> [city idx]
        self.by_alt = {}          # normalized alternate name -> [city idx]
        self.state_codes = {}     # "tx" / "texas" -> "TX"
        self.state_names = {}     # "TX" -> "Texas"
        self.country_codes = {}   # "india" / "ind" / "in" -> "IN"
        self.country_names = {}   # "IN" -> "India"
        self.cities_by_state = {}  # "TX" -> [city idx]

        with gzip.open(os.path.join(_DATA_DIR, "cities.tsv.gz"), "rt", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                name, alts, cc, admin1, lat, lon, pop = line.rstrip("\n").split("\t")
                idx = len(self.cities)
                self.cities.append((name, cc, admin1, float(lat), float(lon), int(pop)))
                self.by_name.setdefault(_norm(name), []).append(idx)
                for alt in alts.split("|") if alts else ():
                    self.by_alt.setdefault(_norm(alt), []).append(idx)
                if cc == "US":
                    self.cities_by_state.setdefault(admin1, []).append(idx)

        with open(os.path.join(_DATA_DIR, "regions.json"), encoding="utf-8") as f:
            regions = json.load(f)
        for code, name in regions["us_states"]:
            self.state_codes[code.lower()] = code
            self.state_codes[_norm(name)] = code
            self.state_names[code] = name
        for iso2, iso3, name in regions["countries"]:
            self.country_names[iso2] = name
            self.country_codes[_norm(name)] = iso2
            self.country_codes[iso3.lower()] = iso2
            self.country_codes.setdefault(iso2.lower(), iso2)
        self.country_codes.update(_COUNTRY_ALIASES)

        # Bounding box of each US state's cities, used to skip the exact
        # distance check for jobs nowhere near a state.
        self.state_bbox = {}
        for code, idxs in self.cities_by_state.items():
            lats = [self.cities[i][3] for i in idxs]
            lons = [self.cities[i][4] for i in idxs]
            self.state_bbox[code] = (min(lats), max(lats), min(lons), max(lons))


_index = None
_index_lock = threading.Lock()


def _get_index():
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = _Index()
    return _index


def haversine_miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def _clean_piece(piece):
    text = _norm(piece)
    text = _ALIASES.get(text, text)
    parts = []
    for part in text.split(","):
        part = part.strip()
        part = _ALIASES.get(part, part)
        for noise in _NOISE_WORDS:
            part = re.sub(rf"\b{noise}\b", " ", part)
        part = re.sub(r"\s+", " ", part).strip()
        if part:
            parts.append(part)
    return parts


def _spans(words, max_len=4):
    for size in range(min(max_len, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            yield " ".join(words[start:start + size]), size


def _city_label(idx, city):
    name, cc, admin1 = city[0], city[1], city[2]
    if cc == "US":
        return f"{name}, {admin1}, US"
    return f"{name}, {_get_index().country_names.get(cc, cc)}"


def _parse_piece(piece):
    """One place name -> Place, or None if nothing recognisable is in it."""
    index = _get_index()
    parts = _clean_piece(piece)
    if not parts:
        return None

    phrases = set()
    for part in parts:
        for span, _ in _spans(part.split()):
            phrases.add(span)

    states_mentioned = {index.state_codes[p] for p in phrases if p in index.state_codes}
    countries_mentioned = {index.country_codes[p] for p in phrases
                           if p in index.country_codes and (p not in _WEAK_COUNTRY_CODES or len(parts) > 1)}

    provinces_mentioned = {_CA_PROVINCES[p] for p in parts[1:] if p in _CA_PROVINCES}

    best = None
    for part_no, part in enumerate(parts):
        for span, size in _spans(part.split()):
            for table, alt_penalty in ((index.by_name, 0.0), (index.by_alt, 1.0)):
                for idx in table.get(span, ()):
                    name, cc, admin1, lat, lon, pop = index.cities[idx]
                    score = 0.5 * size - 0.5 * part_no - alt_penalty + math.log10(max(pop, 10)) / 10
                    if cc == "US" and admin1 in states_mentioned:
                        score += 3
                    elif states_mentioned and cc == "US":
                        score -= 2
                    if cc == "CA" and admin1 in provinces_mentioned:
                        score += 3
                    elif provinces_mentioned and not states_mentioned:
                        score -= 2
                    if cc in countries_mentioned:
                        score += 3
                    elif countries_mentioned and not (cc == "US" and admin1 in states_mentioned):
                        score -= 3
                    # A lone word that's really a state/country name ("Texas",
                    # "Georgia") only counts as a city if the city is big.
                    is_region_word = span in index.state_codes or span in index.country_codes
                    if is_region_word and len(parts) == 1 and len(part.split()) == size and pop < 500_000:
                        continue
                    if best is None or score > best[0]:
                        best = (score, idx)

    if best is not None and best[0] > -1:
        idx = best[1]
        name, cc, admin1, lat, lon, pop = index.cities[idx]
        return Place("city", cc, admin1, lat, lon, _city_label(idx, index.cities[idx]))

    # No city: fall back to a US state, then a country. A US state wins a tie
    # ("Georgia" on a US-heavy job board is far more often the state).
    for part in parts:
        if part in index.state_codes and (len(part) > 2 or len(parts) > 1 or part.isalpha()):
            code = index.state_codes[part]
            return Place("state", "US", code, label=f"{index.state_names[code]}, US")
    for part in parts:
        code = index.country_codes.get(part)
        if code:
            return Place("country", code, label=index.country_names.get(code, code))
    return None


@lru_cache(maxsize=2048)
def resolve_query(text):
    """What the visitor typed in the Location box -> Place, or None."""
    text = (text or "").strip()
    if not text or len(text) > 200:
        return None
    return _parse_piece(text)


@lru_cache(maxsize=100_000)
def parse_job_location(text):
    """A job's scraped location -> tuple of every Place it mentions."""
    if not text:
        return ()
    places = []
    for piece in _MULTI_SPLIT.split(text):
        place = _parse_piece(piece)
        if place is not None and place not in places:
            places.append(place)
    return tuple(places)


def _near_state(lat, lon, state, radius):
    index = _get_index()
    bbox = index.state_bbox.get(state)
    if bbox is None:
        return False
    pad_lat = radius / MILES_PER_DEGREE_LAT
    pad_lon = radius / (MILES_PER_DEGREE_LAT * max(0.1, math.cos(math.radians(lat))))
    if not (bbox[0] - pad_lat <= lat <= bbox[1] + pad_lat and bbox[2] - pad_lon <= lon <= bbox[3] + pad_lon):
        return False
    return any(
        haversine_miles(lat, lon, index.cities[i][3], index.cities[i][4]) <= radius
        for i in index.cities_by_state[state]
    )


def place_matches(job_place, query, radius):
    if query.kind == "country":
        return job_place.country == query.country
    if query.kind == "state":
        if job_place.country == "US" and job_place.state == query.state:
            return True
        return job_place.kind == "city" and _near_state(job_place.lat, job_place.lon, query.state, radius)
    # query is a city
    if job_place.kind == "city":
        return haversine_miles(job_place.lat, job_place.lon, query.lat, query.lon) <= radius
    # A statewide posting ("Texas") is relevant to anyone searching from a
    # city in that state; a country-wide one is too broad to count.
    return job_place.kind == "state" and query.country == "US" and job_place.state == query.state


@lru_cache(maxsize=200_000)
def location_matches(location_text, query, radius):
    return any(place_matches(p, query, radius) for p in parse_job_location(location_text))
