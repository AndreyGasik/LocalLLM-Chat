# http_client.py
import requests

_HTTP = requests.Session()
_NO_PROXY = {"http": None, "https": None}
