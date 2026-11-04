"""Business Central client for the Purchase Line sync API (custom page, see businesscentral/*.al)."""
import os
import time

import requests

import bc

FIELDS = ["documentNo", "lineNo", "buyersLineNo", "ciscoSOLineNo", "shipset",
          "ciscoDeliveryStatus", "scheduledDate", "previousScheduledDate", "estimateDeliveryDate"]


class SyncApiMissing(Exception):
    """The custom purchaseLineSync API page is not published in Business Central."""


def _url():
    return os.environ["BC_SYNC_API_URL"].rstrip("/")


# One pooled session: connections (and their TLS handshakes) are reused instead of opened for every request.
_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=40))


def _request(method, url, retries=2, **kw):
    last = None
    extra = kw.pop("headers", {})
    for attempt in range(retries + 1):
        try:
            r = _SESSION.request(
                method, url, timeout=60,
                headers={"Authorization": f"Bearer {bc.get_token(force=attempt > 0 and last == 401)}",
                         "Accept": "application/json", **extra},
                **kw)
        except requests.RequestException as e:
            last = e
            time.sleep(1 + attempt)
            continue
        if r.status_code == 401 and attempt < retries:
            last = 401
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last = r.status_code
            time.sleep(float(r.headers.get("Retry-After", 2 * (attempt + 1))))
            continue
        return r
    raise RuntimeError(f"Business Central request failed after retries: {last}")


def _err(r):
    try:
        return r.json()["error"]["message"][:300]
    except Exception:  # noqa: BLE001
        return f"HTTP {r.status_code}"


def check_api():
    """Raise SyncApiMissing / RuntimeError if the API page can't be used."""
    r = _request("GET", _url(), params={"$top": 1})
    if r.status_code == 404:
        raise SyncApiMissing(
            "The purchaseLineSync API was not found in Business Central. Publish the AL page in "
            "businesscentral/Page 60544 Purchase Line Sync API.al, or fix 'Sync API URL' in Settings.")
    if not r.ok:
        raise RuntimeError(f"Business Central sync API check failed: {_err(r)}")


def fetch_lines(doc_nos):
    """All purchase lines for the given document numbers (e.g. PO-M and PO-S)."""
    flt = " or ".join("documentNo eq '%s'" % d.replace("'", "''") for d in doc_nos)
    url, params, out = _url(), {"$filter": flt, "$select": ",".join(["id"] + FIELDS)}, []
    while url:
        r = _request("GET", url, params=params, headers={"Prefer": "odata.maxpagesize=5000"})
        if not r.ok:
            raise RuntimeError(f"Reading purchase lines failed: {_err(r)}")
        j = r.json()
        out += j.get("value", [])
        url, params = j.get("@odata.nextLink"), None
    return out


def patch_line(line, fields):
    """PATCH one line using its ETag, so a concurrent edit by someone else is not overwritten."""
    r = _request("PATCH", f"{_url()}({line['id']})", json=fields,
                 headers={"If-Match": line.get("@odata.etag", "*"), "Content-Type": "application/json"})
    if r.status_code == 412:
        raise RuntimeError("Line was changed in Business Central meanwhile - run the sync again")
    if not r.ok:
        raise RuntimeError(_err(r))
