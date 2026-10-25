"""Cross-check gazetteer coordinates against OpenStreetMap Nominatim (1 request/second).

Prints places whose OSM match is more than --km away. Review those by hand; OSM can
also be wrong or pick a namesake. Usage: python scripts/verify_gazetteer.py [--km 1.2]
"""
import argparse, json, math, sys, time
from pathlib import Path
import httpx

UA = "DhakaCrimeMap/0.1 (research prototype; gazetteer check)"
VIEWBOX = "90.10,24.00,90.60,23.55"


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--km", type=float, default=1.2)
    args = ap.parse_args()
    places = json.loads((Path(__file__).parent.parent / "data/dhaka_places.json").read_text())
    with httpx.Client(headers={"User-Agent": UA}, timeout=20) as c:
        for p in places:
            q = p["name_en"].split(" (")[0] + ", Dhaka, Bangladesh"
            r = c.get("https://nominatim.openstreetmap.org/search",
                      params={"q": q, "format": "jsonv2", "limit": 1, "viewbox": VIEWBOX, "bounded": 1})
            time.sleep(1.1)
            hits = r.json() if r.status_code == 200 else []
            if not hits:
                print(f"NOHIT  {p['id']:<24} {q}"); continue
            h = hits[0]; d = km((p["lat"], p["lng"]), (float(h["lat"]), float(h["lon"])))
            flag = "FAR   " if d > args.km else "ok    "
            print(f"{flag} {p['id']:<24} {d:5.2f} km  osm={float(h['lat']):.4f},{float(h['lon']):.4f} "
                  f"{h.get('category')}/{h.get('type')}  {h['display_name'][:70]}")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
