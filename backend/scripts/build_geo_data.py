"""Builds backend/data/cities.tsv.gz, the offline city list geo.py uses to
turn job locations ("Austin, TX") and the Location filter box into map
coordinates for the distance slider.

Only needed when you want to refresh the data -- the generated file is
committed, so production never runs this and needs no extra package.

    pip install geonamescache==3.0.2
    cd backend && python scripts/build_geo_data.py

Data: GeoNames (https://www.geonames.org), CC BY 4.0, via geonamescache.
Cities with population >= 5,000.
"""
import gzip
import json
import os

import geonamescache

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT = os.path.join(DATA_DIR, "cities.tsv.gz")
REGIONS_OUT = os.path.join(DATA_DIR, "regions.json")

# Alternate names are only kept for bigger cities, and only plain ASCII ones
# that aren't airport-style codes ("AUS" would collide with Australia), so
# "Bangalore" -> Bengaluru and "Gurgaon" -> Gurugram work without flooding
# the index with obscure historical names for small towns.
ALT_MIN_POPULATION = 100_000


def _keep_alt(alt, name):
    if not alt or alt == name or not alt.isascii() or "\t" in alt or "|" in alt:
        return False
    stripped = alt.replace(" ", "").replace(".", "")
    if stripped.isupper() and len(stripped) <= 4:
        return False
    return alt[0].isupper()


def main():
    gc = geonamescache.GeonamesCache(min_city_population=5000)
    rows = []
    for city in gc.get_cities().values():
        alts = []
        if city["population"] >= ALT_MIN_POPULATION:
            alts = sorted({a for a in city["alternatenames"] if _keep_alt(a, city["name"])})
        rows.append((
            city["name"],
            "|".join(alts),
            city["countrycode"],
            city["admin1code"] or "",
            f"{city['latitude']:.4f}",
            f"{city['longitude']:.4f}",
            str(city["population"]),
        ))
    rows.sort(key=lambda r: -int(r[6]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
        f.write("# GeoNames cities (pop >= 5000), CC BY 4.0 -- see scripts/build_geo_data.py\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"wrote {len(rows)} cities to {OUT} ({os.path.getsize(OUT) // 1024} KB)")

    regions = {
        "countries": sorted(
            [c["iso"], c["iso3"], c["name"]] for c in gc.get_countries().values()
        ),
        "us_states": sorted([code, s["name"]] for code, s in gc.get_us_states().items()),
    }
    with open(REGIONS_OUT, "w", encoding="utf-8") as f:
        json.dump(regions, f, separators=(",", ":"))
    print(f"wrote {len(regions['countries'])} countries, {len(regions['us_states'])} US states to {REGIONS_OUT}")


if __name__ == "__main__":
    main()
