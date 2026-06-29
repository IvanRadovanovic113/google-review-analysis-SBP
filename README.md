# Google Review Analysis — SBP projekat

Analiza Google Maps recenzija za 5 saveznih država SAD, sa ciljem poređenja performansi upita na neoptimalnoj i optimizovanoj MongoDB šemi.

## Podaci

Podaci su preuzeti sa:
- https://mcauleylab.ucsd.edu:8443/public_datasets/gdrive/googlelocal/

Korišćene savezne države:
- Alaska
- Delaware
- Rhode Island
- Vermont
- Wyoming

Fajlovi se stavljaju u folder `podaci/` (nije na gitu zbog veličine ~2.1 GB):
- `meta-<Drzava>.json` — podaci o biznis lokacijama
- `review-<Drzava>.json` — recenzije korisnika

## Pokretanje

Detaljna uputstva: `UPUTSTVO.md`

Kratak pregled:
1. Pokrenuti MongoDB: `docker run -d --name sbp-mongo -p 27017:27017 -v sbp-mongo-data:/data/db mongo:7`
2. Instalirati zavisnosti: `pip install pymongo tqdm`
3. Učitati podatke: `python python_scripts/load_data.py`

## Struktura baze

Baza: `sbp_projekat`

**Kolekcija `places`** (~66,800 dokumenata) — jedna lokacija/biznis po dokumentu  
**Kolekcija `reviews`** (~6,707,912 dokumenata) — jedna recenzija po dokumentu  
Veza: `reviews.gmap_id → places.gmap_id`
