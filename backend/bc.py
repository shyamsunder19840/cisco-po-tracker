"""Business Central client: list POs by orderDate."""
import os
import re
import threading
import time

import requests

TOKEN_TTL = 50 * 60
_lock = threading.Lock()
_token = {"value": None, "at": 0.0}
SUFFIX = re.compile(r"-[MS]$", re.I)


def strip_suffix(number):
    return SUFFIX.sub("", number.strip())


def get_token(force=False):
    with _lock:
        if not force and _token["value"] and time.time() - _token["at"] < TOKEN_TTL:
            return _token["value"]
        r = requests.post(
            f"https://login.microsoftonline.com/{os.environ['BC_TENANT']}/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": os.environ["BC_CLIENT_ID"],
                "client_secret": os.environ["BC_CLIENT_SECRET"],
                "username": os.environ["BC_USERNAME"],
                "password": os.environ["BC_PASSWORD"],
                "resource": os.environ["BC_RESOURCE"],
            },
            timeout=30,
        )
        if not r.ok:  # don't use raise_for_status: its message embeds the URL (with secrets)
            raise RuntimeError(f"Business Central token request failed (HTTP {r.status_code}): {r.text[:120]}")
        _token.update(value=r.json()["access_token"], at=time.time())
        return _token["value"]


def _fetch(url, params):
    for attempt in range(2):
        r = requests.get(
            url, params=params,
            headers={"Authorization": f"Bearer {get_token(force=attempt == 1)}",
                     "Accept": "application/json"},
            timeout=60)
        if r.status_code == 401 and attempt == 0:
            continue
        r.raise_for_status()
        return r.json()


def list_pos_by_date(from_date, to_date):
    """Return (pos, bc_rows). pos: [{po, orderDate, bc_numbers}] deduped by suffix-stripped number."""
    url = os.environ["BC_PO_URL"]
    params = {"$filter": f"orderDate ge {from_date} and orderDate le {to_date}",
              "$select": "number,orderDate"}
    rows = []
    while url:
        j = _fetch(url, params)
        rows += j.get("value", [])
        url, params = j.get("@odata.nextLink"), None
    prefix = os.environ.get("BC_PO_PREFIX", "POCSIN")
    merged = {}
    for x in rows:
        num = x["number"]
        if not num.startswith(prefix):
            continue
        key = strip_suffix(num)
        e = merged.setdefault(key, {"po": key, "orderDate": x["orderDate"], "bc_numbers": []})
        e["orderDate"] = min(e["orderDate"], x["orderDate"])
        if num not in e["bc_numbers"]:
            e["bc_numbers"].append(num)
    return sorted(merged.values(), key=lambda e: e["po"]), rows


def reset():
    with _lock:
        _token.update(value=None, at=0.0)
