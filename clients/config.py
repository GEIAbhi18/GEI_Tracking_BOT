import os
from dotenv import load_dotenv

load_dotenv()

# ── Google Sheets Credentials ───────────────────────────────────────────────
TENANTS_SHEET_ID = os.getenv("TENANTS_SHEET_ID", "1nU6iZoVxJexzU9ikl84IUi57W3rjLtXff_ZBq5qJwhk")
TENANTS_SERVICE_ACCOUNT = os.getenv("TENANTS_SERVICE_ACCOUNT", "gei-clients-whatsapp-bot@gei-whatsapp-bot.iam.gserviceaccount.com")
TENANTS_PRIVATE_KEY = os.getenv("TENANTS_PRIVATE_KEY", "")
TENANTS_MASTER_TAB = "MASTER"

# ── Factech API Configuration ───────────────────────────────────────────────
FACTECH_BASE_URL = os.getenv("FACTECH_BASE_URL", "https://api.isocietymanager.com").rstrip("/")
FACTECH_API_KEY = os.getenv("FACTECH_API_KEY", "84kRVwKiBZrjJL2loRWXlhh_u6AJp_b6Wq_OKsbm250")
FACTECH_USERNAME = os.getenv("FACTECH_USERNAME", "")
FACTECH_PASSWORD = os.getenv("FACTECH_PASSWORD", "")

# Building Site IDs:
# 467 - GEBB I
# 593 - GEBB II
# 926 - GETT
BUILDING_SITE_MAP = {
    "GEBB1": "467",
    "GEBB I": "467",
    "GEBB-1": "467",
    "BAY 1": "467",
    "GEBB2": "593",
    "GEBB II": "593",
    "GEBB-2": "593",
    "BAY 2": "593",
    "GETT": "926",
}

DEFAULT_SITE_ID = "467"

# ── Sync Configuration ──────────────────────────────────────────────────────
CLIENT_SYNC_INTERVAL_MINUTES = int(os.getenv("CLIENT_SYNC_INTERVAL_MINUTES", "30"))

def get_site_id_for_building(building: str) -> str:
    """Returns the Factech Site ID for a given building name/code."""
    if not building:
        return DEFAULT_SITE_ID
    # pyrefly: ignore [unnecessary-type-conversion]
    b = str(building).strip().upper()
    for k, v in BUILDING_SITE_MAP.items():
        if k.upper() == b:
            return v
    if "GEBB" in b and "2" in b or "BAY 2" in b:
        return "593"
    if "GEBB" in b and "1" in b or "BAY 1" in b or "GEBB I" in b:
        return "467"
    if "GETT" in b or "TERRACE" in b:
        return "926"
    return DEFAULT_SITE_ID
