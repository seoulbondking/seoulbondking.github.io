"""BLS 시리즈 코드가 살아 있는지, 최신값과 이름을 확인한다.
   python tools/bls_probe.py WPU3012 WPS3012 ...
   키는 .env 의 BLS_API_KEY (출력하지 않는다)."""
import json, os, sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
for line in open(os.path.join(os.path.dirname(__file__), '..', '.env'), encoding='utf-8'):
    if '=' in line and not line.startswith('#'):
        k, v = line.strip().split('=', 1); os.environ.setdefault(k, v.strip().strip('"'))
ids = sys.argv[1:]
body = {"seriesid": ids, "startyear": "2025", "endyear": "2026", "catalog": True}
if os.environ.get('BLS_API_KEY'): body["registrationkey"] = os.environ['BLS_API_KEY']
req = urllib.request.Request("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=60))
for s in r['Results']['series']:
    d = s.get('data') or []
    cat = s.get('catalog') or {}
    print(s['seriesID'], len(d), (d[0]['year'] + d[0]['period'] + ' ' + d[0]['value']) if d else '-', '|', cat.get('series_title', ''))
