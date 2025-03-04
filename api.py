import os
import requests
import logging
import time
from pprint import pprint
from datetime import datetime
from dbConnection import db
from dotenv import set_key, find_dotenv
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# Tokens and credentials stored in the .env file
HH_RU_ACCESS_TOKEN = os.getenv('HH_RU_ACCESS_TOKEN')
HH_RU_REFRESH_TOKEN = os.getenv('HH_RU_REFRESH_TOKEN')
HH_RU_CLIENT_ID = os.getenv('HH_RU_CLIENT_ID')
HH_RU_CLIENT_SECRET = os.getenv('HH_RU_CLIENT_SECRET')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

vyachik_id = 1403125548

def bot_send_message(message, chat_id=vyachik_id, bot_token=TELEGRAM_TOKEN):
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    params = {
        'chat_id': chat_id,
        'text': message
    }
    response = requests.post(url, data=params)
    return response.json()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ApiHhRu:
    BASE_URL = 'https://api.hh.ru'
    COUNTRY = 'Россия'
    ACCESS_TOKEN = None
    AREAS = None

    def __init__(self, areas, token=HH_RU_ACCESS_TOKEN):
        self.ACCESS_TOKEN = token
        self.headers = {'Authorization': f'Bearer {self.ACCESS_TOKEN}'}
        self.AREAS = areas

    def refresh_access_token(self):
        """
        Refreshes the access token using the refresh token and updates the .env file.
        """
        url = 'https://hh.ru/oauth/token/'
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': HH_RU_REFRESH_TOKEN,
            'client_id': HH_RU_CLIENT_ID,
            'client_secret': HH_RU_CLIENT_SECRET,
        }
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            tokens = response.json()
            new_access_token = tokens.get('access_token')
            if new_access_token:
                self.ACCESS_TOKEN = new_access_token
                self.headers['Authorization'] = f'Bearer {self.ACCESS_TOKEN}'
                
                # Update the .env file with the new access token
                dotenv_path = find_dotenv()
                set_key(dotenv_path, 'HH_RU_ACCESS_TOKEN', new_access_token)
                
                logging.info("Access token refreshed and .env updated successfully.")
                return True
            else:
                logging.error("No new access token found in the response.")
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to refresh access token: {e}")
            return False

    def _get(self, url, params=None):
        """
        Helper method for GET requests with token refresh logic.
        If a 401 Unauthorized error occurs, the method attempts to refresh the access token and retries the request.
        """
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 401:  # Unauthorized, possibly token expired
                logging.info("Access token expired. Attempting to refresh token.")
                if self.refresh_access_token():
                    response = requests.get(url, headers=self.headers, params=params)
                else:
                    return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed: {e}")
            return None

    def fetch_countries(self):
        """Fetches the list of countries."""
        return self._get(f'{self.BASE_URL}/areas/countries') or []

    def find_country_url(self, country_name):
        """Finds the country URL by name."""
        countries = self.fetch_countries()
        return next((country['url'] for country in countries if country['name'] == country_name), '')

    def fetch_areas(self):
        """Fetches areas based on the specified country."""
        country_url = self.find_country_url(self.COUNTRY)
        if not country_url:
            logging.error("Country not found.")
            return []

        areas = self._get(country_url)
        if areas:
            return [area for area in areas.get('areas', []) if area['name'] in self.AREAS]
        return []

    def fetch_professional_roles(self):
        """Fetches the list of professional roles."""
        url = f'{self.BASE_URL}/professional_roles'
        roles = self._get(url)
        return roles.get('categories', []) if roles else []

    def get_vacancies(self, area_id, professional_role_id, page=0):
        """
        Fetches vacancies for a given area and role.
        Includes retry logic for multiple pages.
        """
        params = {
            'area': area_id,
            'professional_role': professional_role_id,
            'page': page,
            'per_page': 100,
        }
        return self._get(f'{self.BASE_URL}/vacancies', params)

    def fetch_all_vacancies(self, area_id, professional_role_id):
        """Fetches all vacancies for a given area and professional role."""
        vacancies, page, total_pages = [], 0, 1

        while page < total_pages:
            logging.info(f"Fetching page {page} for area {area_id} and role {professional_role_id}")
            data = self.get_vacancies(area_id, professional_role_id, page)

            if not data or 'items' not in data:
                logging.warning("No vacancies found or invalid data.")
                break

            vacancies.extend(data['items'])
            total_pages = data.get('pages', 1)
            page += 1

        return vacancies

    def save_vacancies_to_db(self, vacancies, area_name):
        """Saves vacancies to the database, avoiding duplicates."""
        inserted, duplicates = 0, 0

        for vacancy in vacancies:
            vacancy['entry_date'] = datetime.utcnow().strftime('%d.%m.%Y')
            vacancy['area_name'] = area_name

            if db.find_one({"id": vacancy['id'], "entry_date": vacancy['entry_date']}):
                duplicates += 1
                continue

            try:
                db.insert_one(vacancy)
                inserted += 1
            except Exception as e:
                logging.error(f"Error saving vacancy {vacancy['url']}: {e}")

        bot_send_message(f"Inserted: {inserted}, Duplicates: {duplicates}")
        logging.info(f"Inserted: {inserted}, Duplicates: {duplicates}")

    def fetch_and_store_vacancies(self):
        """Fetches and stores vacancies for all areas and roles."""
        areas = self.fetch_areas()
        if not areas:
            logging.error("No areas found.")
            return

        professional_roles = self.fetch_professional_roles()
        if not professional_roles:
            logging.error("No professional roles found.")
            return

        # Initialize a set to store unique role IDs
        unique_role_ids = set()
        filtered_roles = []

        for category in professional_roles:
            unique_roles_in_category = []
            for role in category['roles']:
                role_id = role['id']
                if role_id not in unique_role_ids:
                    unique_role_ids.add(role_id)
                    unique_roles_in_category.append(role)
            if unique_roles_in_category:
                filtered_roles.append({'roles': unique_roles_in_category})

        for area in areas:
            bot_send_message(message=f"Processing area {area['name']} (ID: {area['id']})")
            logging.info(f"Processing area {area['name']} (ID: {area['id']})")
            for category in filtered_roles:
                for role in category['roles']:
                    bot_send_message(message=f"Fetching vacancies for role {role['name']} (ID: {role['id']})")
                    logging.info(f"Fetching vacancies for role {role['name']} (ID: {role['id']})")
                    vacancies = self.fetch_all_vacancies(area['id'], role['id'])
                    self.save_vacancies_to_db(vacancies, area['name'])


