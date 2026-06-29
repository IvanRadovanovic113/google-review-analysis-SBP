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