## Podaci moraju biti u folderu koji se zove podaci

## Pokretanje MongoDB (Docker)

docker run -d --name sbp-mongo -p 27017:27017 -v sbp-mongo-data:/data/db mongo:7

## Učitavanje podataka u bazu

python load_data.py

## Zavisnosti 

pip install pymongo tqdm

## Dobar ispis

Gotovo!
  places:  66,800
  reviews: 6,707,912

---

## v2 — optimizovana sema (druga instanca, port 27018)

Pokreće se paralelno sa v1 (gore) kako bi se mogla direktno porediti performansa
neoptimizovane (v1, port 27017) i optimizovane (v2, port 27018) baze.

### Pokretanje MongoDB v2 (Docker)

docker run -d --name sbp-mongo-v2 -p 27018:27017 -v sbp-mongo-v2-data:/data/db mongo:7

### Učitavanje podataka + pre-computed kolekcije

python load_data_Ivan_v2.py

### Kreiranje indeksa

python create_indexes.py

### Dobar ispis (load_data_Ivan_v2.py)

Gotovo!
  places:              66,800
  reviews:              6,707,912
  states:               5
  category_stats:       ~2,300
  price_tier_stats:     ~20
  category_text_stats:  ~2,300
