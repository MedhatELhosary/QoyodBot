import os
import json
import pandas as pd
from dotenv import load_dotenv
from telegram import Update
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import nest_asyncio
import asyncio
from data_updater import update_all_data, was_updated_today
import pdfkit

nest_asyncio.apply()

# تحميل متغيرات البيئة
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_PASSWORD = os.getenv("ADMIN_PASSWORD")

AUTHORIZED_USERS_FILE = "authorized_users.json"

if not os.path.exists(AUTHORIZED_USERS_FILE):
    with open(AUTHORIZED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

def load_authorized_users():
    with open(AUTHORIZED_USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_authorized_user(user_id):
    users = load_authorized_users()
    if user_id not in users:
        users.append(user_id)
        with open(AUTHORIZED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f)

def is_authorized(user_id):
    return user_id in load_authorized_users()

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text.strip()

    if not is_authorized(user_id):
        if "awaiting_password" not in context.user_data:
            context.user_data["awaiting_password"] = True
            await update.message.reply_text("🔐 من فضلك أدخل كلمة المرور للمتابعة:")
        else:
            if message == BOT_PASSWORD:
                save_authorized_user(user_id)
                context.user_data["awaiting_password"] = False
                await update.message.reply_text("✅ تم التحقق بنجاح! يمكنك الآن طلب كشف حساب.\n\n🧾 أرسل كود العميل:")
            else:
                await update.message.reply_text("❌ كلمة المرور غير صحيحة. حاول مرة أخرى.")
        return

    if not message.isdigit():
        await update.message.reply_text("❌ من فضلك أرسل رقم معرف العميل (ID) فقط.")
        return

    client_id = int(message)
    await update.message.reply_text("🔄 يتم التحقق من آخر تحديث للبيانات...")

    try:
        if was_updated_today():
            await update.message.reply_text("ℹ️ البيانات محدثة بالفعل اليوم.")
        else:
            await update.message.reply_text("⬇️ يتم تحميل البيانات من قيود...")
            success = update_all_data()
            if success:
                await update.message.reply_text("✅ تم تحميل وتحديث البيانات بنجاح.")
            else:
                await update.message.reply_text("❌ حدث خطأ أثناء تحميل البيانات.")
                return
    except Exception as e:
        await update.message.reply_text(f"❌ حصل خطأ غير متوقع: {str(e)}")
        return

    await update.message.reply_text(f"📄 جاري إنشاء كشف الحساب للعميل رقم {client_id}...")
    await process_account_statement(update, context, client_id)

# إعداد المسارات
FROM_DATE = "2023-01-01"
TO_DATE = datetime.today().strftime("%Y-%m-%d")

BASE_PATH = "data"
OUTPUT_DIR = os.path.join(BASE_PATH, "statements")
os.makedirs(OUTPUT_DIR, exist_ok=True)

contacts = pd.read_excel(os.path.join(BASE_PATH, "contacts.xlsx"))
invoices = pd.read_excel(os.path.join(BASE_PATH, "invoices.xlsx"))
payments = pd.read_excel(os.path.join(BASE_PATH, "payments.xlsx"))
credits = pd.read_excel(os.path.join(BASE_PATH, "credit_notes.xlsx"))

template_path = os.path.join(BASE_PATH, "template.html")

env = Environment(loader=FileSystemLoader(BASE_PATH))
template = env.get_template("template.html")

async def process_account_statement(update, context, client_id: int):
    try:
        customer = contacts[contacts["id"] == client_id]
        if customer.empty:
            await update.message.reply_text("❌ لم يتم العثور على هذا العميل.")
            return

        customer = customer.iloc[0]
        customer_name = customer["name"]
        rows = []

        def format_date(date_str):
            try:
                return pd.to_datetime(date_str).strftime("%d-%m-%Y")
            except:
                return ""

        # فواتير العميل
        cust_invoices = invoices[invoices["contact_id"] == client_id]
        for _, row in cust_invoices.iterrows():
            ref = f"INV-{row['id']}"
            description = row["description"]
            if pd.isna(description) or not str(description).strip():
                description = f"فاتورة - {ref}"
            rows.append({
                "date": format_date(row["issue_date"]),
                "type": "فاتورة",
                "description": description,
                "ref": ref,
                "debit": row["total"],
                "credit": 0,
            })

        # مدفوعات العميل
        cust_payments = payments[payments["contact_id"] == client_id]
        for _, row in cust_payments.iterrows():
            ref = str(row["reference"])
            description = row.get("description") or f"دفعة - {ref}"
            rows.append({
                "date": format_date(row["date"]),
                "type": "دفعة",
                "description": description,
                "ref": ref,
                "debit": 0,
                "credit": row["amount"],
            })

        # الإشعارات الدائنة
        cust_credits = credits[credits["contact_id"] == client_id]
        for _, row in cust_credits.iterrows():
            ref = str(row["reference"])
            description = f"إشعار دائن - {ref}"
            rows.append({
                "date": format_date(row["issue_date"]),
                "type": "إشعار دائن",
                "description": description,
                "ref": ref,
                "debit": 0,
                "credit": row["total_amount"],
            })

        rows = sorted(rows, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y") if x["date"] else datetime.min)
        balance = 0
        for row in rows:
            balance += row["debit"] - row["credit"]
            row["balance"] = balance

        html = template.render(
            customer_name=customer_name,
            from_date=format_date(FROM_DATE),
            to_date=format_date(TO_DATE),
            rows=rows,
            final_balance=balance
        )

        filename = os.path.join(OUTPUT_DIR, f"{customer_name}.pdf")

        if os.getenv("RAILWAY_ENVIRONMENT"):
            wkhtmltopdf_path = os.path.abspath("bin/wkhtmltopdf")  # نسخة Linux
        else:
            wkhtmltopdf_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

        font_path = os.path.abspath(os.path.join(BASE_PATH, "Cairo-Regular.ttf"))
        font_css = f"""
          <style>
             @font-face {{
                font-family: 'Cairo';
                src: url('file:///{font_path.replace(os.sep, "/")}');
             }}
             body {{
                font-family: 'Cairo', sans-serif;
             }}
          </style>
        """

        html = font_css + html

        pdfkit.from_string(html, filename, options={
            'encoding': 'UTF-8',
            'page-size': 'A4',
            'margin-top': '10mm',
            'margin-bottom': '10mm',
            'margin-left': '10mm',
            'margin-right': '10mm',
            'enable-local-file-access': None
        }, configuration=config)

        with open(filename, "rb") as f:
            await update.message.reply_document(f, filename=os.path.basename(filename))
            await update.message.reply_text("✅ تم إرسال كشف الحساب بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء توليد كشف الحساب: {str(e)}")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    print("✅ Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
