import os

REVENUECAT_API_KEY = os.getenv("REVENUECAT_API_KEY", "")
REVENUECAT_URL = "https://api.revenuecat.com/v1/receipts"

class RevenueCatError(Exception):
    pass

def verify_purchase(receipt_data: str, app_user_id: str) -> dict:
    """
    Verifies a purchase receipt with RevenueCat.
    Args:
        receipt_data: The raw purchase token from iOS/Android/web.
        app_user_id: The user ID field used for RevenueCat customer mapping.
    Returns:
        RevenueCat's response as dict if successful.
    Raises:
        RevenueCatError: if verification fails.
    """
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RevenueCatError("requests dependency is not installed") from exc

    headers = {
        "Authorization": f"Bearer {REVENUECAT_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "app_user_id": app_user_id,
        "fetch_token": receipt_data
    }
    resp = requests.post(REVENUECAT_URL, json=body, headers=headers, timeout=15)
    try:
        resp.raise_for_status()
    except Exception as e:
        raise RevenueCatError(f"Request failed: {e}")
    data = resp.json()
    if not data.get("customer_info"):
        raise RevenueCatError(f"Malformed response: {data}")
    return data
