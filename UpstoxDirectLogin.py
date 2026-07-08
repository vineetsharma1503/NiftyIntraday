import urllib.parse
import pandas as pd
import requests
import Config


access_token = ""

url = f'{Config.get_upstox_v2_base_url()}/v2/user/get-funds-and-margin'
headers = {
    'accept': 'application/json',
    'Api-Version': '2.0',
    'Authorization': f'Bearer {access_token}'
}
params = {
    'segment': 'COM'  #'COM'
}

response = requests.get(url, headers=headers, params=params)
print(response.json())