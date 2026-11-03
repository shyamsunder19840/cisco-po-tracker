"""Cisco Order Status API client (token + checkOrderStatus + response parsing)."""
import os
import threading
import time
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter

# One pooled session so parallel calls reuse TCP/TLS connections.
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=32))

_cache = {}  # po -> (timestamp, response json)

TOKEN_TTL = 55 * 60
_lock = threading.Lock()
_token = {"value": None, "at": 0.0}

COLUMNS = [
    "PO ID", "Sales Order Reference", "PO Line Number", "Line ID Set", "SO Line Ref",
    "Major/Minor", "Item ID", "Quantity", "Status Code", "Shipment DateTime",
    "Est. Delivery DateTime", "Recommit DateTime", "Recommit Reason",
    "Delivery Status", "Final Scheduled Ship Date",
    "Order Status", "Web Order ID", "Last Product Ship", "SO Line Number",
    "Estimated Ship DateTime", "Promised Delivery DateTime", "Ship From",
]

# Response paths already mapped to a named column above; anything else is
# still kept, under its raw path, so no field returned by Cisco is dropped.
FRIENDLY = {
    "ID": "PO ID",
    "SalesOrderReference[0].ID": "Sales Order Reference",
    "Status[0].Description": "Order Status",
    "DocumentReference[WebOrder_ID].ID": "Web Order ID",
    "DocumentReference[LastProductShip].ID": "Last Product Ship",
    "LineNumberID": "PO Line Number",
    "LineIDSet[0].ID[0]": "Line ID Set",
    "Description[SOLineNumber]": "SO Line Number",
    "SalesOrderReference.LineNumberID": "SO Line Ref",
    "Item.ID": "Item ID",
    "Item.Lot[0].Quantity": "Quantity",
    "Status[0].Code": "Status Code",
    "Status[0].Extension[ShipmentDateTime].DateTime[0]": "Shipment DateTime",
    "Status[0].Extension[EstimatedShipDateTime].DateTime[0]": "Estimated Ship DateTime",
    "Status[0].ID[EstimatedDeliveryDateTime]": "Est. Delivery DateTime",
    "Status[0].ID[RecommitDateTime]": "Recommit DateTime",
    "Status[0].ID[RecommitReason]": "Recommit Reason",
    "PromisedDeliveryDateTime": "Promised Delivery DateTime",
    "ShipFromParty[0].Location[0].Name[0]": "Ship From",
}


def flatten(node, path, out):
    """Flatten nested JSON to {path: leaf}. Lists of typed items use the typeCode as key."""
    if isinstance(node, dict):
        if "value" in node and set(node) <= {"value", "typeCode", "schemeVersionID", "unitCode", "currencyID"}:
            if isinstance(node["value"], (dict, list)):  # nested object wrapped in "value"
                flatten(node["value"], path, out)
            else:
                out[path] = node["value"]
            return
        for k, v in node.items():
            if k != "typeCode":
                flatten(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            tc = v.get("typeCode") if isinstance(v, dict) else None
            flatten(v, f"{path}[{tc or i}]", out)
    else:
        out[path] = node


def get_token(force=False):
    with _lock:
        if not force and _token["value"] and time.time() - _token["at"] < TOKEN_TTL:
            return _token["value"]
        r = SESSION.post(
            os.environ["CISCO_TOKEN_URL"],
            params={
                "grant_type": "client_credentials",
                "client_id": os.environ["CISCO_URL_CLIENT_ID"],
                "client_secret": os.environ["CISCO_URL_CLIENT_SECRET"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "client_id": os.environ["CISCO_HDR_CLIENT_ID"],
                "client_secret": os.environ["CISCO_HDR_CLIENT_SECRET"],
                "grant_type": "client_credentials",
            },
            data={},
            timeout=15,
        )
        if not r.ok:  # don't use raise_for_status: its message embeds the URL (with secrets)
            raise RuntimeError(f"Cisco token request failed (HTTP {r.status_code}): {r.text[:120]}")
        _token.update(value=r.json()["access_token"], at=time.time())
        return _token["value"]


def _payload(po):
    return {"GetPurchaseOrder": {"value": {
        "DataArea": {"PurchaseOrder": [{"PurchaseOrderHeader": {
            "ID": {"value": po},
            "DocumentReference": [{"ID": {"value": ""}}],
            "SalesOrderReference": [{"ID": {"value": ""}}],
            "Description": [{"value": "No", "typeCode": "details"}],
        }}]},
        "ApplicationArea": {
            "CreationDateTime": "datetime",
            "BODID": {"value": "BoDID-test", "schemeVersionID": "V1"},
        },
    }}}


def check_order_status(po, retries=2):
    """POST checkOrderStatus. Retries on 5xx/429/network errors; other 4xx fail immediately."""
    hit = _cache.get(po)
    if hit and time.time() - hit[0] < int(os.environ.get("CISCO_CACHE_SECONDS", 600)):
        return hit[1]
    last = None
    for attempt in range(retries + 1):
        try:
            r = SESSION.post(
                os.environ["CISCO_ORDER_URL"],
                json=_payload(po),
                headers={
                    "Authorization": f"Bearer {get_token()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=30,
            )
            if r.status_code == 401 and attempt == 0:
                get_token(force=True)
                continue
            if r.status_code == 429:  # rate limited: back off, then retry
                time.sleep(float(r.headers.get("Retry-After", 2 * (attempt + 1))))
                last = RuntimeError("429 Too Many Requests")
                continue
            if 400 <= r.status_code < 500:
                raise ValueError(f"Cisco returned {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            data = r.json()
            _cache[po] = (time.time(), data)
            return data
        except ValueError:
            raise
        except requests.RequestException as e:
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"Cisco API failed after retries: {last}")


# ---- parsing helpers -------------------------------------------------------

def _val(node):
    return node.get("value", "") if isinstance(node, dict) else ""


def _first(lst):
    return lst[0] if isinstance(lst, list) and lst else {}


def _typed(items, type_code):
    for it in items or []:
        if isinstance(it, dict) and it.get("typeCode") == type_code:
            return it
    return {}


def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    for fn in (datetime.fromisoformat,
               lambda x: datetime.strptime(x, "%Y-%m-%d"),
               lambda x: datetime.strptime(x, "%d-%b-%Y")):
        try:
            d = fn(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _delivery_status(recommit, status, est):
    if recommit:
        return "Dates Shifted"
    if status.lower() == "closed":
        return "Shipped from Cisco"
    if status.lower() == "shipped":
        return "ASEA Hold"
    if est:
        return "Scheduled"
    return "Scheduling Pending"


def parse_response(data):
    """Flatten a checkOrderStatus response into one dict per PurchaseOrderLine."""
    try:
        po = data["ShowPurchaseOrder"]["value"]["DataArea"]["PurchaseOrder"][0]
    except (KeyError, IndexError, TypeError):
        return []
    hdr = po.get("PurchaseOrderHeader", {})
    po_id = _val(hdr.get("ID"))
    so_ref = _val(_first(hdr.get("SalesOrderReference")).get("ID"))
    rows = []
    for line in po.get("PurchaseOrderLine", []) or []:
        status0 = _first(line.get("Status"))
        so_line = _val((line.get("SalesOrderReference") or {}).get("LineNumberID"))
        line_ids = ", ".join(
            _val(i) for s in line.get("LineIDSet", []) or [] for i in s.get("ID", []) or []
        )
        ship = _val(_first(_typed(status0.get("Extension"), "ShipmentDateTime").get("DateTime")))
        est = _val(_typed(status0.get("ID"), "EstimatedDeliveryDateTime"))
        recommit = _val(_typed(status0.get("ID"), "RecommitDateTime"))
        reason = _val(_typed(status0.get("ID"), "RecommitReason"))
        code = _val(status0.get("Code"))
        dts = [d for d in (_parse_dt(ship), _parse_dt(est)) if d]
        final = min(dts).date().isoformat() if dts else ""
        item = line.get("Item") or {}
        flat = {}
        flatten(hdr, "", flat)
        flatten(line, "", flat)
        row = {}
        for path, val in flat.items():
            row[FRIENDLY.get(path, path)] = val
        row.update({
            "PO ID": po_id,
            "Sales Order Reference": so_ref,
            "PO Line Number": _val(line.get("LineNumberID")),
            "Line ID Set": line_ids,
            "SO Line Ref": so_line,
            "Major/Minor": "Major" if so_line.endswith(".0") else ("Minor" if so_line else ""),
            "Item ID": _val(item.get("ID")),
            "Quantity": _val(_first(item.get("Lot")).get("Quantity")),
            "Status Code": code,
            "Shipment DateTime": ship,
            "Est. Delivery DateTime": est,
            "Recommit DateTime": recommit,
            "Recommit Reason": reason,
            "Delivery Status": _delivery_status(recommit, code, est),
            "Final Scheduled Ship Date": final,
        })
        rows.append(row)
    return rows


def reset():
    """Drop cached token and results (called after settings change)."""
    with _lock:
        _token.update(value=None, at=0.0)
    _cache.clear()
