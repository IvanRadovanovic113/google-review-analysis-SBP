import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

BATCH_SIZE = 1000

PRICE_MAP = {
    "$": 1, "$$": 2, "$$$": 3, "$$$$": 4,
    "₩": 1, "₩₩": 2, "₩₩₩": 3, "₩₩₩₩": 4,
}


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


def normalize_price(raw_price):
    return PRICE_MAP.get(raw_price)


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
        "price":          normalize_price(raw.get("price")),
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


def deduplicate_places(db):
    """Uklanja duplikate po gmap_id iz places (sirovi podaci mogu imati vise dokumenata s istim ID-jem).
    Poziva se jednom nakon sto su svi meta fajlovi ucitani."""
    pipeline = [
        {"$group": {"_id": "$gmap_id", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    dups = list(db.places.aggregate(pipeline))
    if dups:
        ids_to_delete = []
        for dup in dups:
            ids_to_delete.extend(dup["ids"][1:])
        db.places.delete_many({"_id": {"$in": ids_to_delete}})
        print(f"  Obrisano {len(ids_to_delete)} duplikata ({len(dups)} gmap_id vrednosti)")
    else:
        print("  Nema duplikata")


def confirm_drop(collection_names: list[str]) -> bool:
    print(f"\nKolekcije {collection_names} ce biti obrisane pre ucitavanja.")
    ans = input("Nastavi? [y/N]: ").strip().lower()
    return ans == "y"


def build_states_stats(db):
    """states: ukupno mesta i broj sa cenom po drzavi (Q3)"""
    print("\n--- Racunanje 'states' (Q3) ---")
    pipeline = [
        {"$group": {
            "_id": "$state_name",
            "ukupno_mesta": {"$sum": 1},
            "mesta_sa_cenom": {"$sum": {"$cond": [{"$ne": ["$price", None]}, 1, 0]}},
        }},
        {"$addFields": {
            "procenat_sa_cenom": {
                "$round": [{"$multiply": [{"$divide": ["$mesta_sa_cenom", "$ukupno_mesta"]}, 100]}, 2]
            }
        }},
    ]
    docs = list(db.places.aggregate(pipeline))
    db.states.drop()
    if docs:
        db.states.insert_many(docs)
    print(f"  states: {len(docs)} dokumenata")


def build_category_stats(db):
    """category_stats: prosek recenzija i broj mesta po (state_name, category) (Q2)"""
    print("--- Racunanje 'category_stats' (Q2) ---")
    pipeline = [
        {"$unwind": "$category"},
        {"$group": {
            "_id": {"state_name": "$state_name", "category": "$category"},
            "prosek_recenzija": {"$avg": "$num_of_reviews"},
            "broj_mesta": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0,
            "state_name": "$_id.state_name",
            "category": "$_id.category",
            "prosek_recenzija": 1,
            "broj_mesta": 1,
        }},
    ]
    docs = list(db.places.aggregate(pipeline, allowDiskUse=True))
    db.category_stats.drop()
    if docs:
        db.category_stats.insert_many(docs)
        db.category_stats.create_index([("state_name", 1), ("category", 1)], unique=True)
    print(f"  category_stats: {len(docs)} dokumenata")


def build_price_tier_stats(db):
    """price_tier_stats: prosecna ocena i broj mesta po (state_name, price) (Q3)"""
    print("--- Racunanje 'price_tier_stats' (Q3) ---")
    pipeline = [
        {"$match": {"price": {"$ne": None}}},
        {"$group": {
            "_id": {"state_name": "$state_name", "price": "$price"},
            "prosecna_ocena": {"$avg": "$avg_rating"},
            "broj_mesta": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0,
            "state_name": "$_id.state_name",
            "price": "$_id.price",
            "prosecna_ocena": 1,
            "broj_mesta": 1,
        }},
    ]
    docs = list(db.places.aggregate(pipeline))
    db.price_tier_stats.drop()
    if docs:
        db.price_tier_stats.insert_many(docs)
        db.price_tier_stats.create_index([("state_name", 1), ("price", 1)], unique=True)
    print(f"  price_tier_stats: {len(docs)} dokumenata")


def build_pct_bez_teksta(db, states: list[str]):
    """Po drzavi racuna procenat recenzija bez teksta po biznisu, upisuje u places.pct_bez_teksta (Q5).
    Radi se drzava po drzava da se smanji memorijski pritisak nad 6.7M recenzija."""
    print("--- Racunanje 'pct_bez_teksta' po biznisu, po drzavi (Q5) ---")
    for state in states:
        pipeline = [
            {"$match": {"state_name": state}},
            {"$group": {
                "_id": "$gmap_id",
                "ukupno": {"$sum": 1},
                "bez_teksta": {"$sum": {"$cond": [
                    {"$or": [{"$eq": ["$text", None]}, {"$eq": ["$text", ""]}]}, 1, 0
                ]}},
            }},
            {"$addFields": {"pct_bez_teksta": {"$divide": ["$bez_teksta", "$ukupno"]}}},
        ]
        stats = list(db.reviews.aggregate(pipeline, allowDiskUse=True))
        ops = [
            UpdateOne({"gmap_id": s["_id"]}, {"$set": {"pct_bez_teksta": s["pct_bez_teksta"]}})
            for s in stats
        ]
        for i in range(0, len(ops), BATCH_SIZE):
            db.places.bulk_write(ops[i:i + BATCH_SIZE], ordered=False)
        print(f"  {state}: {len(stats):,} biznisa azurirano")


def build_category_text_stats(db):
    """category_text_stats: prosecan pct_bez_teksta po kategoriji (Q5)"""
    print("--- Racunanje 'category_text_stats' (Q5) ---")
    pipeline = [
        {"$match": {"pct_bez_teksta": {"$ne": None}}},
        {"$unwind": "$category"},
        {"$group": {
            "_id": "$category",
            "prosek_pct_bez_teksta": {"$avg": "$pct_bez_teksta"},
            "broj_biznisa": {"$sum": 1},
        }},
    ]
    docs = list(db.places.aggregate(pipeline, allowDiskUse=True))
    db.category_text_stats.drop()
    if docs:
        db.category_text_stats.insert_many(docs)
    print(f"  category_text_stats: {len(docs)} dokumenata")


def main():
    parser = argparse.ArgumentParser(description="Ucitava Google Maps podatke u optimizovanu MongoDB semu (v2)")
    parser.add_argument("--uri", default=os.getenv("MONGO_URI_V2", "mongodb://localhost:27018"))
    parser.add_argument("--db",  default=os.getenv("MONGO_DB",  "sbp_projekat"))
    default_podaci = str(Path(__file__).resolve().parent.parent / "podaci")
    parser.add_argument("--podaci", default=default_podaci, help="Folder sa JSONL fajlovima")
    parser.add_argument("--yes", action="store_true", help="Preskoci potvrdu brisanja kolekcija")
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

    print(f"Konekcija na MongoDB (v2 - optimizovana sema): {args.uri} / baza: {args.db}")
    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"[ERROR] Ne mogu da se povezem na MongoDB: {e}")
        sys.exit(1)

    db = client[args.db]
    existing = db.list_collection_names()
    managed = ["places", "reviews", "states", "category_stats", "price_tier_stats", "category_text_stats"]
    to_drop = [c for c in managed if c in existing]

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
    states = []
    for filepath in meta_files:
        state = state_name_from_filename(filepath)
        states.append(state)
        n = load_file(filepath, places_col, transform_place, state)
        print(f"  {filepath.name}: {n:,} dokumenata ({state})")
        total_places += n
    print(f"Ucitano places (pre deduplikacije): {total_places:,}")
    print("--- Deduplikacija 'places' po gmap_id ---")
    deduplicate_places(db)
    print(f"Ukupno places: {places_col.count_documents({}):,}\n")

    print(f"--- Ucitavanje review fajlova u 'reviews' ({len(review_files)} fajlova) ---")
    total_reviews = 0
    for filepath in review_files:
        state = state_name_from_filename(filepath)
        n = load_file(filepath, reviews_col, transform_review, state)
        print(f"  {filepath.name}: {n:,} dokumenata ({state})")
        total_reviews += n
    print(f"Ukupno reviews: {total_reviews:,}\n")

    build_states_stats(db)
    build_category_stats(db)
    build_price_tier_stats(db)
    build_pct_bez_teksta(db, states)
    build_category_text_stats(db)

    print("\nGotovo!")
    print(f"  places:              {places_col.count_documents({}):,}")
    print(f"  reviews:             {reviews_col.count_documents({}):,}")
    print(f"  states:              {db.states.count_documents({}):,}")
    print(f"  category_stats:      {db.category_stats.count_documents({}):,}")
    print(f"  price_tier_stats:    {db.price_tier_stats.count_documents({}):,}")
    print(f"  category_text_stats: {db.category_text_stats.count_documents({}):,}")
    print("\nSledeci korak: python python_scripts/create_indexes.py")


if __name__ == "__main__":
    main()
