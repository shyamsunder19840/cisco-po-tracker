"""Editable app settings stored in backend/.env (secrets are never sent back to the browser)."""
import os
import re
import threading

from dotenv import dotenv_values, set_key

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_lock = threading.Lock()

# (key, label, group, secret, kind)
FIELDS = [
    # Both client ID/secret pairs are used only to get the access token; the order status call itself uses just that token.
    ("CISCO_TOKEN_URL", "Token URL", "Cisco token generation (OAuth)", False, "text"),
    ("CISCO_URL_CLIENT_ID", "Token request - Client ID (sent in the URL)", "Cisco token generation (OAuth)", False, "text"),
    ("CISCO_URL_CLIENT_SECRET", "Token request - Client secret (sent in the URL)", "Cisco token generation (OAuth)", True, "text"),
    ("CISCO_HDR_CLIENT_ID", "Token request - Client ID (sent in the headers)", "Cisco token generation (OAuth)", False, "text"),
    ("CISCO_HDR_CLIENT_SECRET", "Token request - Client secret (sent in the headers)", "Cisco token generation (OAuth)", True, "text"),
    ("CISCO_ORDER_URL", "Order status URL (called with the token above)", "Cisco Order Status API", False, "text"),
    ("BC_TENANT", "Tenant ID", "Business Central", False, "text"),
    ("BC_CLIENT_ID", "Client ID", "Business Central", False, "text"),
    ("BC_CLIENT_SECRET", "Client secret", "Business Central", True, "text"),
    ("BC_USERNAME", "Username", "Business Central", False, "text"),
    ("BC_PASSWORD", "Password", "Business Central", True, "text"),
    ("BC_RESOURCE", "Resource", "Business Central", False, "text"),
    ("BC_PO_URL", "Purchase orders URL", "Business Central", False, "text"),
    ("BC_PO_PREFIX", "Cisco PO prefix", "Business Central", False, "text"),
    ("STATUS_FILTER_ENABLED", "Filter by Status Code", "Data filter", False, "bool"),
    ("STATUS_FILTER_VALUES", "Keep only these Status Codes (one per line)", "Data filter", False, "list"),
    ("BC_SYNC_API_URL", "Sync API URL (purchaseLineSync)", "Business Central sync", False, "text"),
    ("SYNC_ESTIMATE_DAYS", "Estimate Delivery Date = latest scheduled date + days", "Business Central sync", False, "int"),
    ("SYNC_DATE_FORMAT", "Previous Scheduled Date format (e.g. %d-%m-%Y)", "Business Central sync", False, "text"),
    ("BC_T1_API_URL", "T1 Process Report API URL (t1ProcessReport)", "T1 Process Report", False, "text"),
    ("T1_MAX_ROWS", "Max rows per T1 export", "T1 Process Report", False, "int"),
    ("MAX_PO_PER_SEARCH", "Max POs per date search", "Performance & limits", False, "int"),
    ("CISCO_WORKERS", "Parallel Cisco calls", "Performance & limits", False, "int"),
    ("CISCO_CACHE_SECONDS", "Result cache (seconds, 0 = off)", "Performance & limits", False, "int"),
]
BY_KEY = {f[0]: f for f in FIELDS}


def public_view():
    """Settings for the UI. Secret values are replaced by a boolean 'set' flag."""
    out = []
    for key, label, group, secret, kind in FIELDS:
        val = os.environ.get(key, "")
        out.append({"key": key, "label": label, "group": group, "secret": secret, "kind": kind,
                    "value": "" if secret else val, "set": bool(val)})
    return out


def parse_list(text):
    """Split on newlines/commas/semicolons, drop blanks and case-insensitive duplicates."""
    seen, out = set(), []
    for tok in re.split(r"[\n,;]+", str(text or "")):
        tok = tok.strip()
        if tok and tok.lower() not in seen:
            seen.add(tok.lower())
            out.append(tok)
    return out


def validate(updates):
    errors = {}
    enabled = str(updates.get("STATUS_FILTER_ENABLED", os.environ.get("STATUS_FILTER_ENABLED", "false"))).lower() == "true"
    if "STATUS_FILTER_VALUES" in updates or "STATUS_FILTER_ENABLED" in updates:
        vals = updates.get("STATUS_FILTER_VALUES", os.environ.get("STATUS_FILTER_VALUES", ""))
        if enabled and not parse_list(vals):
            errors["STATUS_FILTER_VALUES"] = "Add at least one status, or turn the filter off"
    for key, val in updates.items():
        f = BY_KEY.get(key)
        if not f:
            errors[key] = "Unknown setting"
        elif f[4] == "bool":
            if str(val).lower() not in ("true", "false"):
                errors[key] = "Must be on or off"
        elif f[4] == "int":
            if not str(val).strip().isdigit():
                errors[key] = "Must be a whole number"
            elif key == "CISCO_WORKERS" and not 1 <= int(val) <= 50:
                errors[key] = "Must be between 1 and 50"
            elif key == "MAX_PO_PER_SEARCH" and int(val) < 1:
                errors[key] = "Must be at least 1"
        elif f[3] is False and key.endswith("URL") and not str(val).startswith(("http://", "https://")):
            errors[key] = "Must start with http:// or https://"
    return errors


def save(updates):
    """Persist to .env and apply to the running process. Blank secret = keep existing."""
    clean = {}
    for key, val in updates.items():
        f = BY_KEY.get(key)
        if not f:
            continue
        val = ", ".join(parse_list(val)) if f[4] == "list" else str(val).strip()
        if f[4] == "bool":
            val = val.lower()
        if f[3] and not val:
            continue  # keep stored secret
        clean[key] = val
    with _lock:
        if not os.path.exists(ENV_PATH):
            open(ENV_PATH, "w").close()
        for key, val in clean.items():
            set_key(ENV_PATH, key, val, quote_mode="always")
            os.environ[key] = val
    return list(clean)


def file_values():
    return dotenv_values(ENV_PATH)
