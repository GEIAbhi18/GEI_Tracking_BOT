import logging
import threading
import gspread
from google.oauth2.service_account import Credentials
from clients.config import (
    TENANTS_SHEET_ID,
    TENANTS_SERVICE_ACCOUNT,
    TENANTS_PRIVATE_KEY,
    TENANTS_MASTER_TAB,
)

logger = logging.getLogger(__name__)

_gc = None
_ss = None
_lock = threading.Lock()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_spreadsheet() -> gspread.Spreadsheet:
    """Lazily initializes and caches the gspread client and spreadsheet."""
    global _gc, _ss
    if _ss is not None:
        return _ss

    with _lock:
        if _ss is not None:
            return _ss

        if not TENANTS_SERVICE_ACCOUNT or not TENANTS_PRIVATE_KEY:
            raise RuntimeError(
                "Tenants Google Sheets credentials not configured. "
                "Set TENANTS_SERVICE_ACCOUNT and TENANTS_PRIVATE_KEY in .env"
            )

        if not TENANTS_SHEET_ID:
            raise RuntimeError("TENANTS_SHEET_ID not configured in .env")

        pk = TENANTS_PRIVATE_KEY.strip().strip("'").strip('"').replace("\\n", "\n")

        project_id = "gei-whatsapp-bot"
        if TENANTS_SERVICE_ACCOUNT and "@" in TENANTS_SERVICE_ACCOUNT:
            domain = TENANTS_SERVICE_ACCOUNT.split("@")[1]
            if "." in domain:
                project_id = domain.split(".")[0]

        creds_info = {
            "type": "service_account",
            "project_id": project_id,
            "private_key": pk,
            "client_email": TENANTS_SERVICE_ACCOUNT,
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        _gc = gspread.authorize(creds)
        _ss = _gc.open_by_key(TENANTS_SHEET_ID)
        logger.info(f"Connected to Tenants Google Sheet: '{_ss.title}'")
        return _ss


def fetch_master_tenant_records() -> list:
    """
    Fetches all client rows from the MASTER tab of the tenants Google Sheet.
    Only the MASTER sheet is read per project requirements.
    Returns a list of dicts with stripped keys and values.
    """
    ss = _get_spreadsheet()
    ws = ss.worksheet(TENANTS_MASTER_TAB)
    all_values = ws.get_all_values()

    if not all_values or len(all_values) < 2:
        logger.warning(f"Tenants MASTER tab has no data or only headers")
        return []

    headers = [h.strip() for h in all_values[0]]
    records = []

    for row_idx, row in enumerate(all_values[1:], start=2):
        if not any(str(c).strip() for c in row):
            continue  # Skip entirely blank rows

        # Pad row with empty strings if shorter than headers
        padded_row = list(row) + [""] * (len(headers) - len(row))
        row_dict = {headers[i]: padded_row[i].strip() for i in range(len(headers))}
        row_dict["_row_number"] = row_idx
        records.append(row_dict)

    logger.info(f"Fetched {len(records)} non-empty rows from Tenants MASTER sheet")
    return records
