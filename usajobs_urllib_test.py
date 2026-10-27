
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json

usajobs_email = "mcdaniel.amaiya@gmail.com"
usajobs_key = " 1HQJzBg9GsJeJ3rT1f/DXNYKtILu3mcB6Bsk6/TiotA="

params = {
    "Keyword": "Python",
    "Page": 1,
    "ResultsPerPage": 10
}

url = "https://data.usajobs.gov/api/search?" + urlencode(params)

request = Request(url, headers={
    "Host": "data.usajobs.gov",
    "User-Agent": REGISTERED_EMAIL,
    "Authorization-Key": API_KEY
})

with urlopen(request, timeout=15) as response:
    data = json.load(response)

jobs = data.get("SearchResult", {}).get("SearchResultItems", [])

for job in jobs:
    fields = job.get("MatchedObjectDescriptor", {})
    print(fields.get("PositionTitle"))
    print(fields.get("OrganizationName"))
