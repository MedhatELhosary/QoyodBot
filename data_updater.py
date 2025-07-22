import requests
import pandas as pd
import os
from datetime import datetime

API_KEY = "1afc69708a435b4542d74c57b"
HEADERS = {"API-KEY": API_KEY}
FROM_DATE = "2023-01-01"
TO_DATE = datetime.today().strftime("%Y-%m-%d")

FOLDER_NAME = "data"
LAST_UPDATE_FILE = os.path.join(FOLDER_NAME, "last_update.txt")
os.makedirs(FOLDER_NAME, exist_ok=True)

def save_to_excel(data, filename):
    df = pd.DataFrame(data)
    path = os.path.join(FOLDER_NAME, filename)
    df.to_excel(path, index=False)
    print(f"✅ تم الحفظ: {path}")

def was_updated_today():
    if os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "r") as f:
            last_date = f.read().strip()
        return last_date == datetime.today().strftime("%Y-%m-%d")
    return False

def mark_updated_today():
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(datetime.today().strftime("%Y-%m-%d"))

def update_all_data():
    try:
        print("⬇️ تحميل: contacts.xlsx ...")
        url = "https://www.qoyod.com/api/2.0/customers"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        customers = response.json().get("customers", [])
        save_to_excel(customers, "contacts.xlsx")

        print("⬇️ تحميل: invoices.xlsx ...")
        url = "https://www.qoyod.com/api/2.0/invoices"
        params = {"from_date": FROM_DATE, "to_date": TO_DATE}
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        invoices = response.json().get("invoices", [])
        save_to_excel(invoices, "invoices.xlsx")

        print("⬇️ تحميل: credit_notes.xlsx ...")
        url = "https://www.qoyod.com/api/2.0/credit_notes"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        notes = response.json().get("credit_notes", [])
        save_to_excel(notes, "credit_notes.xlsx")

        print("⬇️ تحميل: payments.xlsx ...")
        url = "https://www.qoyod.com/api/2.0/invoice_payments"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        payments = response.json().get("receipts", [])
        save_to_excel(payments, "payments.xlsx")

        mark_updated_today()
        print("✅ تم تحديث البيانات بنجاح.")
        return True

    except Exception as e:
        print(f"❌ حصل خطأ أثناء تحميل البيانات: {e}")
        return False
