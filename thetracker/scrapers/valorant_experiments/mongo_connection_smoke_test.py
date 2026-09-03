from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")

db = client.valorant

result = db.test.insert_one({"status": "ok"})

print("Inserted:", result.inserted_id)