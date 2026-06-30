import argparse
import os
import sys

from pymongo import ASCENDING, MongoClient


def main():
    parser = argparse.ArgumentParser(description="Kreira indekse na optimizovanoj (v2) MongoDB instanci")
    parser.add_argument("--uri", default=os.getenv("MONGO_URI_V2", "mongodb://localhost:27018"))
    parser.add_argument("--db",  default=os.getenv("MONGO_DB",  "sbp_projekat"))
    args = parser.parse_args()

    print(f"Konekcija na MongoDB (v2): {args.uri} / baza: {args.db}")
    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as e:
        print(f"[ERROR] Ne mogu da se povezem na MongoDB: {e}")
        sys.exit(1)

    db = client[args.db]

    print("\n--- Indeksi nad 'places' ---")
    name = db.places.create_index([("location", "2dsphere")])
    print(f"  {name}  ->  geoWithin/$centerSphere (Q1, Q2)")

    name = db.places.create_index([("gmap_id", ASCENDING)], unique=True)
    print(f"  {name}  ->  $ne filter u Q1, $lookup target u Q4/Q5")

    name = db.places.create_index([("category", ASCENDING)])
    print(f"  {name}  ->  $in filter u Q1, $unwind+$match u Q2")

    print("\n--- Indeksi nad 'reviews' ---")
    name = db.reviews.create_index([("gmap_id", ASCENDING)])
    print(f"  {name}  ->  $lookup source u Q4/Q5")

    name = db.reviews.create_index([("state_name", ASCENDING), ("time", ASCENDING)])
    print(f"  {name}  ->  compound: drzava + vremenski prozor (Q4)")

    print("\nGotovo! Trenutni indeksi:")
    for coll_name in ("places", "reviews"):
        print(f"\n{coll_name}:")
        for idx in db[coll_name].list_indexes():
            print(f"  {idx['name']}: {idx['key']}")


if __name__ == "__main__":
    main()
