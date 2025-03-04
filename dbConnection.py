from pymongo import MongoClient

client = MongoClient("localhost", 27017)

db = client.job_forecast.hh_ru_jobs


