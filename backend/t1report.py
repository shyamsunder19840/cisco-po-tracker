"""T1 Process Report: export Business Central T1ProcessData (the output of Report 80000 "T1ProcessBatch") to Excel.

The Excel columns are the dataset columns of Report 80000, in the same order and with the same names.
Data comes from the custom API page 80054 (businesscentral/Page 80054 T1 Process Report API.al).
"""
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

import bc
import bcsync

# (Excel column = dataset column name of Report 80000, API field, kind). Order = dataset order.
COLUMNS = [
    ("Account_Manager_Name", "accountManagerName", "text"),
    ("BSO_No", "bsoNo", "text"),
    ("BSO_Line_No", "bsoLineNo", "int"),
    ("BSO_Order_Date", "bsoOrderDate", "date"),
    ("BSO_Quantity", "bsoQuantity", "num"),
    ("Pending_Qty_to_Create_SO", "pendingToCreateSOQty", "num"),
    ("Cisco_Non_Cisco", "ciscoNonCisco", "text"),
    ("Project_Non_Project", "projectNonProject", "text"),
    ("SO_No", "soNo", "text"),
    ("SODate", "soDate", "date"),
    ("POType", "poType", "text"),
    ("SO_Line_No", "soLineNo", "int"),
    ("SO_Qty", "soQty", "num"),
    ("Qty_Shipped", "quantityShipped", "num"),
    ("SO_Pending_Qty", "soPendingQuantity", "num"),
    ("Customer_PO_No", "customerPONo", "text"),
    ("Customer_PO_Date", "customerPODate", "date"),
    ("Master_Customer_ID", "masterCustomerID", "text"),
    ("Master_Customer_Name", "masterCustomerName", "text"),
    ("Customer_ID", "customerID", "text"),
    ("Customer_Name", "customerName", "text"),
    ("Ship_to_Customer_Name", "shipToCustomerName", "text"),
    ("Ship_To_City", "shipToCity", "text"),
    ("Major_Minor", "majorMinor", "text"),
    ("Link_to_Major", "linkToMajor", "text"),
    ("PO_LtoM_Line_No", "poLtoMLineNo", "text"),
    ("Part_Code", "partCode", "text"),
    ("Product_Description", "productDescription", "text"),
    ("Previous_Schedule_Ship_Date", "previousScheduleShipDate", "text"),
    ("Scheduled_Date", "scheduledDate", "date"),
    ("Service_Deley_days", "serviceDelayDays", "text"),
    ("Ship_Date_Status", "shipDateStatus", "text"),
    ("Estimate_Delivery_Date_for_Complete_Shipment", "estDelDateCompShipment", "date"),
    ("Estimate_Delivery_Date_for_Partial_Shipment", "estDelDatePartiShipment", "date"),
    ("Sales_Invoice_No", "salesInvoiceNo", "text"),
    ("Sales_Invoice_Date", "salesInvoiceDate", "date"),
    ("Dispatch_No", "podNo", "text"),
    ("Dispatch_Through", "dispatchThrough", "text"),
    ("Dispatch_Date", "dispatchDate", "date"),
    ("Customer_Delivery_Date", "customerDeliveryDate", "date"),
    ("Line_Status", "lineStatus", "text"),
    ("Line_Type", "lineType", "text"),
    ("SO_Amount", "soAmount", "num"),
    ("Job_No", "jobNo", "text"),
    ("Job_Task_No", "jobTaskNo", "text"),
    ("Proactive_PO_No", "proactivePONo", "text"),
    ("Proactive_PO_Line_No", "proactivePOLineNo", "int"),
    ("Proactive_PO_Date", "proactivePODate", "date"),
    ("Proactive_Vendor_Name", "proactiveVendorName", "text"),
    ("CISCO_Order_Status", "ciscoOrderStatus", "text"),
    ("CISCO_Order_No", "ciscoOrderNo", "text"),
    ("CISCO_Shipset_No", "ciscoShipsetNo", "text"),
    ("Port_for_Receive_Import_Shipment", "portForReceiveImpShipment", "text"),
    ("Product_GRN_Date", "productReceiveDate", "date"),
    ("Purchase_Invoice_No", "purchaseInvoiceNo", "text"),
    ("Purchase_Invoice_Date", "purchaseInvoiceDate", "date"),
    ("Proactive_Order_Status", "proactiveOrderStatus", "text"),
    ("Technology", "technology", "text"),
    ("Sales_Team", "salesTeams", "text"),
    ("Comments", "comments", "text"),
    ("Job_Status", "jobStatus", "text"),
    ("SO_Order_Month", None, "month"),            # derived from SODate, as GetSOMonth() does in the report
    ("BSO_Line_Item_No", None, "text"),           # not stored in T1ProcessData -> left blank
    ("Proactive_PO_Buyer_Line_No", None, "text"),  # not stored in T1ProcessData -> left blank
]
NOT_STORED = [h for h, f, _ in COLUMNS if f is None and h != "SO_Order_Month"]
MONTHS = ["Jan", "Feb", "March", "April", "May", "June", "July", "August", "Sept", "Oct", "Nov", "Dec"]
DATE_FMT = "dd-mm-yyyy"
ORDER_BY = "bsoOrderDate,bsoNo,bsoLineNo,entryNo"
_SAFE = re.compile(r"^[A-Za-z0-9._\-]+$")


class T1ApiMissing(Exception):
    pass


def _url():
    return os.environ["BC_T1_API_URL"].rstrip("/")


def _to_date(v):
    s = str(v or "").strip()
    if not s or s.startswith("0001"):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def fetch_rows(start, end, bso_nos=(), url=None, fields=None, limit=None, order_by=ORDER_BY, customer_pos=(), proactive_pos=()):
    """Read T1ProcessData rows with BSO Order Date in [start, end] (ISO dates, both optional),
    optionally for given BSO numbers and/or Customer PO numbers."""
    parts = []
    if start and end:
        parts.append(f"bsoOrderDate ge {start} and bsoOrderDate le {end}")
    for field, vals, label in (("bsoNo", bso_nos, "BSO"), ("customerPONo", customer_pos, "Customer PO"),
                                ("proactivePONo", proactive_pos, "Proactive PO")):
        vals = [v for v in vals if v]
        bad = [v for v in vals if not _SAFE.match(v)]
        if bad:
            raise ValueError(f"Invalid {label} number(s): {', '.join(bad[:5])}")
        if vals:
            parts.append("(" + " or ".join(f"{field} eq '{v}'" for v in vals) + ")")
    flt = " and ".join(parts)
    select = fields or sorted({f for _, f, _ in COLUMNS if f} | {"entryNo"})
    target, params, rows = url or _url(), {"$select": ",".join(select), "$orderby": order_by}, []
    if flt:
        params["$filter"] = flt
    while target:
        r = bcsync._request("GET", target, params=params, headers={"Prefer": "odata.maxpagesize=5000"})
        if r.status_code == 404:
            raise T1ApiMissing(
                "The t1ProcessReport API was not found in Business Central. Publish the AL page in "
                "businesscentral/Page 80054 T1 Process Report API.al (project 5- APIManagement-Project), "
                "or fix 'T1 Process Report API URL' in Settings.")
        if not r.ok:
            raise RuntimeError(f"Reading T1 data failed: {bcsync._err(r)}")
        j = r.json()
        rows += j.get("value", [])
        if limit and len(rows) > limit:
            raise OverflowError(len(rows))
        target, params = j.get("@odata.nextLink"), None
    return rows


def customer_pos(rows, prefix="", field="proactivepono"):
    """Distinct Cisco PO numbers (suffix-stripped, upper-cased) from the Proactive PO No. of T1 rows.

    Returns (pos, skipped): skipped = distinct values ignored (blank values aren't counted)
    because they don't start with the Cisco PO prefix or aren't plain alphanumeric.
    """
    pos, skipped = {}, set()
    for r in rows:
        v = str({k.lower(): x for k, x in r.items()}.get(field) or "").strip()
        if not v:
            continue
        po = bc.strip_suffix(v).upper()
        if re.fullmatch(r"[A-Z0-9]+", po) and po.startswith(prefix.upper()):
            pos[po] = None
        else:
            skipped.add(v)
    return sorted(pos), len(skipped)


def _cell(kind, value):
    if kind == "date":
        return _to_date(value)
    if kind in ("num", "int"):
        if value in (None, ""):
            return None
        return int(value) if kind == "int" else float(value)
    return None if value in (None, "") else str(value)


# Second sheet: the purchase line fields that "Sync into Business Central" reads and writes (see sync.py / bcsync.FIELDS)
PL_COLUMNS = [
    ("Document No", "documentNo", "text"),
    ("Line No", "lineNo", "int"),
    ("Buyers Line No", "buyersLineNo", "text"),
    ("CISCO SO Line No", "ciscoSOLineNo", "text"),
    ("Shipset", "shipset", "text"),
    ("CISCO Delivery Status", "ciscoDeliveryStatus", "text"),
    ("Scheduled Date", "scheduledDate", "date"),
    ("Previous Scheduled Date", "previousScheduledDate", "text"),
    ("Estimate Delivery Date", "estimateDeliveryDate", "date"),
]
PL_SHEET = "Purchase Lines"


def purchase_lines(rows, chunk=15, workers=6):
    """Purchase lines (sync fields only) of every purchase order document that appears in the T1 rows."""
    docs = sorted({str(r.get("proactivePONo") or r.get("ProactivePONo") or "").strip() for r in rows} - {""})
    docs = [d for d in docs if _SAFE.match(d)]
    groups = [docs[i:i + chunk] for i in range(0, len(docs), chunk)]
    out = []
    with ThreadPoolExecutor(workers) as ex:
        for part in ex.map(bcsync.fetch_lines, groups):
            out += part
    return sorted(out, key=lambda ln: (str(ln.get("documentNo", "")), int(ln.get("lineNo") or 0)))


def _header_row(ws, heads):
    cells = []
    for head in heads:
        c = WriteOnlyCell(ws, value=head)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
        cells.append(c)
    ws.append(cells)


def _purchase_sheet(wb, pl_rows, note):
    ws = wb.create_sheet(PL_SHEET)
    for i, (head, _, _) in enumerate(PL_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(14, min(len(head) + 4, 44))
    if pl_rows is None:  # the lines could not be read: say so instead of leaving the sheet out
        ws.append([f"Purchase lines could not be read: {note}"])
        return
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(PL_COLUMNS))}{max(len(pl_rows) + 1, 2)}"
    _header_row(ws, [h for h, _, _ in PL_COLUMNS])
    for ln in pl_rows:
        ln = {k.lower(): v for k, v in ln.items()}
        out = []
        for _, field, kind in PL_COLUMNS:
            v = _cell(kind, ln.get(field.lower()))
            if kind == "date" and v is not None:
                c = WriteOnlyCell(ws, value=v)
                c.number_format = DATE_FMT
                out.append(c)
            else:
                out.append(v)
        ws.append(out)


CISCO_SHEET = "Cisco API Data"


def _cisco_sheet(wb, rows, cols):
    """Third sheet: the lines of the last Check status, exactly as the app table shows them."""
    ws = wb.create_sheet(CISCO_SHEET)
    for i, head in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(14, min(len(head) + 4, 40))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max(len(cols), 1))}{max(len(rows) + 1, 2)}"
    _header_row(ws, cols)
    for r in rows:
        ws.append([_plain(r.get(c)) for c in cols])


def _plain(v):
    """Excel-friendly value: numbers stay numbers, nested JSON is written as text."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return json.dumps(v, ensure_ascii=False)


def build_xlsx(rows, pl_rows=False, pl_note="", cisco_rows=None, cisco_cols=()):
    """Return the workbook as BytesIO. Uses write-only mode so large exports stay light on memory.

    pl_rows: purchase lines for the second sheet; None = they could not be read (pl_note says why); False = no second sheet."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("T1 Report")
    for i, (head, _, kind) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(14, min(len(head) + 4, 44))  # wide enough for the heading + filter arrow
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(len(rows) + 1, 2)}"
    header = []
    for head, _, _ in COLUMNS:
        c = WriteOnlyCell(ws, value=head.replace("_", " "))  # report names use '_', the Excel headings use spaces
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
        header.append(c)
    ws.append(header)
    for r in rows:
        r = {k.lower(): v for k, v in r.items()}  # API field names are matched ignoring case
        out = []
        for _, field, kind in COLUMNS:
            if kind == "month":
                d = _to_date(r.get("sodate"))
                out.append(MONTHS[d.month - 1] if d else None)
                continue
            v = _cell(kind, r.get(field.lower())) if field else None
            if kind == "date" and v is not None:
                c = WriteOnlyCell(ws, value=v)
                c.number_format = DATE_FMT
                out.append(c)
            else:
                out.append(v)
        ws.append(out)
    if pl_rows is not False:
        _purchase_sheet(wb, pl_rows, pl_note)
    if cisco_rows is not None:
        _cisco_sheet(wb, cisco_rows, list(cisco_cols))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
