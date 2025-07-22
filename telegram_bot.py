import os
import json
import pandas as pd
from dotenv import load_dotenv
from telegram import Update
import pdfkit
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import nest_asyncio
nest_asyncio.apply()
import asyncio
from data_updater import update_all_data, was_updated_today  # ✅ التعديل هنا

# تحميل متغيرات البيئة
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_PASSWORD = os.getenv("ADMIN_PASSWORD")

AUTHORIZED_USERS_FILE = "authorized_users.json"

# تأكد من وجود ملف المستخدمين
if not os.path.exists(AUTHORIZED_USERS_FILE):
    with open(AUTHORIZED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

# تحميل المستخدمين المصرح لهم
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

    # ✅ التحقق من كلمة السر
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

    # ✅ التأكد من الكود المرسل
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
# إعدادات عامة
FROM_DATE = "2023-01-01"
TO_DATE = datetime.today().strftime("%Y-%m-%d")

# المسارات
BASE_PATH = "data"
OUTPUT_DIR = os.path.join(BASE_PATH, "statements")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# تحميل البيانات من ملفات Excel
contacts = pd.read_excel(os.path.join(BASE_PATH, "contacts.xlsx"))
invoices = pd.read_excel(os.path.join(BASE_PATH, "invoices.xlsx"))
payments = pd.read_excel(os.path.join(BASE_PATH, "payments.xlsx"))
credits = pd.read_excel(os.path.join(BASE_PATH, "credit_notes.xlsx"))

# إعداد قالب Jinja2
template_html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: 'Arial'; direction: rtl; }
        h2 { text-align: center; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { border: 1px solid #000; padding: 4px; text-align: center; }
        .summary { margin-top: 10px; font-weight: bold; }
    </style>
</head>
<body>
    <h2>كشف حساب - {{ customer_name }}</h2>
    <p style="text-align:center">
        مؤسسة روافد الخليجية<br>
        تم التصدير بتاريخ {{ to_date }}<br>
        عن الفترة من {{ from_date }} إلى {{ to_date }}
    </p>
    <table>
        <thead>
            <tr>
                <th>التاريخ</th>
                <th>النوع</th>
                <th>وصف العملية</th>
                <th>المرجع</th>
                <th>مدين</th>
                <th>دائن</th>
                <th>الرصيد</th>
            </tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <td>{{ row.date }}</td>
                <td>{{ row.type }}</td>
                <td>{{ row.description }}</td>
                <td>{{ row.ref }}</td>
                <td>{{ "{:,.2f}".format(row.debit) if row.debit else "" }}</td>
                <td>{{ "{:,.2f}".format(row.credit) if row.credit else "" }}</td>
                <td>{{ "{:,.2f}".format(row.balance) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    <p class="summary">الرصيد الختامي: {{ "{:,.2f}".format(final_balance) }}</p>
</body>
</html>
"""
template_path = os.path.join(BASE_PATH, "template.html")
with open(template_path, "w", encoding="utf-8") as f:
    f.write(template_html)

env = Environment(loader=FileSystemLoader(BASE_PATH))
template = env.get_template("template.html")

# -----------------------
async def process_account_statement(update, context, client_id: int):
    try:
        # التحقق من وجود العميل
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

        # الفواتير
        cust_invoices = invoices[invoices["contact_id"] == client_id]
        for _, row in cust_invoices.iterrows():
            rows.append({
                "date": format_date(row["issue_date"]),
                "type": "فاتورة",
                "description": row.get("description", ""),
                "ref": f"INV-{row['id']}",
                "debit": row["total"],
                "credit": 0,
            })

        # المدفوعات
        cust_payments = payments[payments["contact_id"] == client_id]
        for _, row in cust_payments.iterrows():
            rows.append({
                "date": format_date(row["date"]),
                "type": "دفعة",
                "description": row.get("description", ""),
                "ref": str(row["reference"]),
                "debit": 0,
                "credit": row["amount"],
            })

        # الإشعارات الدائنة
        cust_credits = credits[credits["contact_id"] == client_id]
        for _, row in cust_credits.iterrows():
            rows.append({
                "date": format_date(row["issue_date"]),
                "type": "إشعار دائن",
                "description": "",
                "ref": str(row["reference"]),
                "debit": 0,
                "credit": row["total_amount"],
            })

        # ترتيب العمليات وحساب الرصيد
        rows = sorted(rows, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y") if x["date"] else datetime.min)
        balance = 0
        for row in rows:
            balance += row["debit"] - row["credit"]
            row["balance"] = balance

        # توليد HTML
        html = template.render(
            customer_name=customer_name,
            from_date=format_date(FROM_DATE),
            to_date=format_date(TO_DATE),
            rows=rows,
            final_balance=balance
        )

        # توليد PDF
        filename = os.path.join(OUTPUT_DIR, f"{customer_name}.pdf")
        config = pdfkit.configuration(wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")
        pdfkit.from_string(html, filename, configuration=config)

        # إرسال الملف
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
    nest_asyncio.apply()
    asyncio.run(main())
