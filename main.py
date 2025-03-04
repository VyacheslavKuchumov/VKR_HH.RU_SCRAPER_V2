import argparse

from api import ApiHhRu



parser = argparse.ArgumentParser(description="Greet multiple names.")
parser.add_argument('regions', nargs='+', help='List of regions')
args = parser.parse_args()


areas_to_scrape = args.regions
# areas_to_scrape = ['Свердловская область', 'Москва', 'Республика Татарстан']
job_api = ApiHhRu(areas=areas_to_scrape)
job_api.fetch_and_store_vacancies()