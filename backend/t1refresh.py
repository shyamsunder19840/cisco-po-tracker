"""Rebuild the T1ProcessData lines of purchase orders in Business Central after their purchase lines were synced.

The rebuild itself runs inside Business Central (businesscentral/Codeunit 80055 T1 Process Line Refresh.al, which
ports the logic of Report 80000 "T1 Process Batch"); it is started through the bound action `refreshT1Data` of the
API page in businesscentral/Page 80055 T1 Refresh API.al: one call per purchase order document.
"""
import os
import re

import bcsync

_SAFE = re.compile(r"^[A-Za-z0-9._\-]+$")
ACTION = "Microsoft.NAV.refreshT1Data"


class T1RefreshApiMissing(Exception):
    """The t1Refresh API page is not published in Business Central."""


def _url():
    url = os.environ.get("BC_T1_REFRESH_API_URL", "").strip()
    if not url:  # same company / API group as the purchaseLineSync page
        url = os.environ["BC_SYNC_API_URL"].rstrip("/").rsplit("/", 1)[0] + "/t1Refresh"
    return url.rstrip("/")


def _missing():
    return T1RefreshApiMissing(
        "The t1Refresh API was not found in Business Central. Publish 'Page 80055 T1 Refresh API.al' and "
        "'Codeunit 80055 T1 Process Line Refresh.al' (project 5- APIManagement-Project), or fix 'T1 Refresh API URL' in Settings.")


def check_api():
    r = bcsync._request("GET", _url(), params={"$top": 1})
    if r.status_code == 404:
        raise _missing()
    if not r.ok:
        raise RuntimeError(f"T1 refresh API check failed: {bcsync._err(r)}")


def refresh(docs):
    """Rebuild the T1 lines for the purchase order documents (e.g. ['POCSIN1-M', 'POCSIN1-S']).

    Returns {"docs": number of documents refreshed, "rows": T1 rows created (None if BC did not report it)}.
    """
    docs = [d for d in docs if d]
    bad = [d for d in docs if not _SAFE.match(d)]
    if bad:
        raise ValueError(f"Invalid document number(s): {', '.join(bad[:3])}")
    url = _url()
    r = bcsync._request("GET", url, params={"$filter": " or ".join(f"documentNo eq '{d}'" for d in docs),
                                            "$select": "id,documentNo"})
    if r.status_code == 404:
        raise _missing()
    if not r.ok:
        raise RuntimeError(f"Finding purchase orders failed: {bcsync._err(r)}")
    done, rows = 0, None
    for h in r.json().get("value", []):
        a = bcsync._request("POST", f"{url}({h['id']})/{ACTION}", json={}, headers={"Content-Type": "application/json"})
        if not a.ok:
            raise RuntimeError(f"T1 refresh of {h.get('documentNo')} failed: {bcsync._err(a)}")
        done += 1
        try:
            rows = (rows or 0) + int(a.json()["t1Rows"])
        except (KeyError, ValueError, TypeError):
            pass  # BC did not report the row count
    return {"docs": done, "rows": rows}
