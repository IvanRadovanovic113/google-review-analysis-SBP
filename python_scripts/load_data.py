import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from tqdm import tqdm

BATCH_SIZE = 1000


def state_name_from_filename(path: Path) -> str:
    raw = path.stem.split("-", 1)[1]
    return raw.replace("_", " ")


def parse_hours(raw_hours) -> list | None:
    if not raw_hours:
        return None
    result = []
    for entry in raw_hours:
        day = entry[0]
        time_range = entry[1]
        if "–" in time_range:
            open_t, close_t = time_range.split("–", 1)
        else:
            open_t = close_t = time_range
        result.append({"day": day, "open": open_t, "close": close_t})
    return result


def parse_misc(raw_misc) -> dict | None:
    if not raw_misc:
        return None
    return {k.lower().replace(" ", "_"): v for k, v in raw_misc.items()}


def transform_place(raw: dict, state_name: str) -> dict:
    return {
        "gmap_id":        raw["gmap_id"],
        "name":           raw.get("name"),
        "address":        raw.get("address"),
        "state_name":     state_name,
        "location": {
            "type":        "Point",
            "coordinates": [raw["longitude"], raw["latitude"]],
        },
        "category":       raw.get("category"),
        "description":    raw.get("description"),
        "avg_rating":     raw.get("avg_rating"),
        "num_of_reviews": raw.get("num_of_reviews"),
        "price":          raw.get("price"),
        "hours":          parse_hours(raw.get("hours")),
        "misc":           parse_misc(raw.get("MISC")),
        "url":            raw.get("url"),
    }


def transform_review(raw: dict, state_name: str) -> dict:
    resp = raw.get("resp")
    return {
        "gmap_id":    raw["gmap_id"],
        "state_name": state_name,
        "user_id":    raw.get("user_id"),
        "user_name":  raw.get("name"),
        "time":       datetime.fromtimestamp(raw["time"] / 1000, tz=timezone.utc),
        "rating":     raw.get("rating"),
        "text":       raw.get("text"),
        "has_pics":   bool(raw.get("pics")),
        "response":   {
            "time": datetime.fromtimestamp(resp["time"] / 1000, tz=timezone.utc),
            "text": resp.get("text"),
        } if resp else None,
    }


def load_file(filepath: Path, collection, transform_fn, state_name: str) -> int:
    batch = []
    total_inserted = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(tqdm(f, desc=filepath.name, unit=" docs"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                batch.append(transform_fn(raw, state_name))
            except Exception as e:
                print(f"\n[WARN] {filepath.name} line {line_num}: {e}")
                continue
            if len(batch) >= BATCH_SIZE:
                collection.insert_many(batch, ordered=False)
                total_inserted += len(batch)
                batch.clear()
    if batch:
        collection.insert_many(batch, ordered=False)
        total_inserted += len(batch)
    return total_inserted


def confirm_drop(collection_names: list[str]) -> bool:
    print(f"\nKolekcije {collection_names} ce biti obrisane pre ucitavanja.")
    ans = input("Nastavi? [y/N]: ").strip().lower()
    return ans == "y"


def main():
    parser = argparse.ArgumentParser(description="Ucitava Google Maps podatke u MongoDB")
    parser.add_argument("--uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db",  default=os.getenv("MONGO_DB",  "sbp_projekat"))
    default_podaci = str(Path(__file__).resolve().parent.parent / "podaci")
    parser.add_argument("--podaci", default=default_podaci, help="Folder sa JSONL fajlovima")
    parser.add_argument("--yes", action="store_true", help="Preskoei potvrdu brisanja kolekcija")
    args = parser.parse_args()

    podaci_dir = Path(args.podaci)
    if not podaci_dir.is_dir():
        print(f"[ERROR] Folder '{podaci_dir}' ne postoji.")
        sys.exit(1)

    meta_files   = sorted(podaci_dir.glob("meta-*.json"))
    review_files = sorted(podaci_dir.glob("review-*.json"))

    if not meta_files and not review_files:
        print(f"[ERROR] Nema JSONL fajlova u '{podaci_dir}'.")
        sys.exit(1)

    print(f"Konekcija na MongoDB: {args.uri} / baza: {args.db}")
    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"[ERROR] Ne mogu da se povezem na MongoDB: {e}")
        sys.exit(1)

    db = client[args.db]
    existing = db.list_collection_names()
    to_drop = [c for c in ("places", "reviews") if c in existing]

    if to_drop:
        if not args.yes and not confirm_drop(to_drop):
            print("Prekinuto.")
            sys.exit(0)
        for name in to_drop:
            db.drop_collection(name)
            print(f"Obrisana kolekcija: {name}")

    places_col  = db["places"]
    reviews_col = db["reviews"]

    print(f"\n--- Ucitavanje meta fajlova u 'places' ({len(meta_files)} fajlova) ---")
    total_places = 0
    for filepath in meta_files:
        state = state_name_from_filename(filepath)
        n = load_file(filepath, places_col, transform_place, state)
        print(f"  {filepath.name}: {n:,} dokumenata ({state})")
        total_places += n
    print(f"Ukupno places: {total_places:,}\n")

    print(f"--- Ucitavanje review fajlova u 'reviews' ({len(review_files)} fajlova) ---")
    total_reviews = 0
    for filepath in review_files:
        state = state_name_from_filename(filepath)
        n = load_file(filepath, reviews_col, transform_review, state)
        print(f"  {filepath.name}: {n:,} dokumenata ({state})")
        total_reviews += n
    print(f"Ukupno reviews: {total_reviews:,}\n")

    print("Gotovo!")
    print(f"  places:  {places_col.count_documents({}):,}")
    print(f"  reviews: {reviews_col.count_documents({}):,}")


if __name__ == "__main__":
    main()
