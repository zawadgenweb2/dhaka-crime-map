"""One-off: look up OpenStreetMap points for places that have none (new upazilas, new thanas).

Writes data/sources/osm-points-<date>.json, which scripts/build_places.py merges. Nominatim usage policy: one request
per second, identifying User-Agent, results cached in the repo (never queried at run time).
Run on a machine with internet:  python scripts/fill_points.py  then  python scripts/build_places.py
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "DhakaCrimeMap/0.2 (+https://github.com/zawadgenweb2/dhaka-crime-map)"


def main() -> None:
    data = json.loads((ROOT / "data" / "places.json").read_text(encoding="utf-8"))
    dist = {d["id"]: d for d in data["districts"]}
    out = {}
    for p in data["places"]:
        if p["lat"] is not None:
            continue
        d = dist[p["district"]]
        box = f"{d['lng'] - 0.6},{d['lat'] + 0.6},{d['lng'] + 0.6},{d['lat'] - 0.6}"
        for q in (f"{p['name_en']}, {d['name_en']}, Bangladesh", f"{p['name_bn']}, {d['name_bn']}"):
            url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                {"q": q, "format": "jsonv2", "limit": 1, "viewbox": box, "bounded": 1, "countrycodes": "bd"})
            time.sleep(1.1)
            hits = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))
            if hits:
                h = hits[0]
                out[p["id"]] = {"lat": round(float(h["lat"]), 5), "lng": round(float(h["lon"]), 5),
                                "osm": f"{h['osm_type']}/{h['osm_id']}", "match": h["display_name"][:120], "query": q}
                break
        print(p["id"], "->", out.get(p["id"], {}).get("match", "not found"))
    path = ROOT / "data" / "sources" / f"osm-points-{date.today().isoformat()}.json"
    path.write_text(json.dumps({"note": "Points from OpenStreetMap Nominatim (ODbL), looked up once for places "
                                        "without a Wikidata point.", "points": out}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


if __name__ == "__main__":
    main()
