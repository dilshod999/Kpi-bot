"""
KPI Bot для Маметниязов Дилшод
Пересылай сообщения из группы — бот сам посчитает твой KPI и зарплату.
"""

import json
import os
import re
from datetime import datetime, date
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

TOKEN = os.environ.get("TOKEN", "")
DATA_FILE = "kpi_data.json"
MY_NAME = "Маметниязов Дилшод"
PRICE_PER_CARD = 800


def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"records": {}}

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_report(text: str) -> dict | None:
    result = {}

    # Дата
    date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
    if date_match:
        try:
            result["date"] = datetime.strptime(date_match.group(1), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            result["date"] = date.today().isoformat()
    else:
        result["date"] = date.today().isoformat()

    # Кол-во вышедших
    workers_match = re.search(r"[Кк]ол[- ]?во вышедших[^\d✅]*[✅]?\s*(\d+)", text)
    if workers_match:
        result["workers"] = int(workers_match.group(1))
    else:
        workers_match2 = re.search(r"✅\s*(\d+)", text)
        result["workers"] = int(workers_match2.group(1)) if workers_match2 else None

    # Присутствие Дилшода
    present = None
    for line in text.splitlines():
        if MY_NAME.lower() in line.lower():
            if "✅" in line:
                present = True
            elif "❌" in line:
                present = False
            break

    if present is None:
        return None

    result["present"] = present

    # TOTAL
    total_match = re.search(r"TOTAL[:\s]+(\d+)", text, re.IGNORECASE)
    result["total_team"] = int(total_match.group(1)) if total_match else None

    # Карты — русские и английские названия
    cards = {}
    card_types = [
        "Дебет Хумо", "Дебет Виза", "Кредит Хумо", "Кредит Мастер",
        "Договор", "Переупоковка", "Переупаковка",
        "Debit", "Credit", "Repacking card", "Treaty", "Visa", "Master card"
    ]
    for card_type in card_types:
        pattern = rf"{re.escape(card_type)}\s*[-:]\s*(\d+)"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            cards[card_type] = int(m.group(1))
    if cards:
        result["cards"] = cards

    return result


def calc_salary(total_team: int, workers: int) -> tuple[float, int]:
    per_person = total_team / workers
    salary = round(per_person * PRICE_PER_CARD)
    return per_person, salary


def get_monthly_stats(data: dict) -> dict:
    today = date.today()
    month_prefix = today.strftime("%Y-%m")
    records = {k: v for k, v in data["records"].items() if k.startswith(month_prefix)}

    total_days = len(records)
    present_days = sum(1 for v in records.values() if v.get("present"))
    absent_days = total_days - present_days
    attendance_pct = round(present_days / total_days * 100) if total_days else 0

    total_salary = 0
    for v in records.values():
        if v.get("present") and v.get("total_team") and v.get("workers"):
            _, sal = calc_salary(v["total_team"], v["workers"])
            total_salary += sal

    return {
        "month": today.strftime("%B %Y"),
        "total_days": total_days,
        "present_days": present_days,
        "absent_days": absent_days,
        "attendance_pct": attendance_pct,
        "total_salary": total_salary,
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📊 Мой KPI за месяц"], ["📅 История"], ["❓ Помощь"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Привет, Дилшод!\n\n"
        "Пересылай мне ежедневные отчёты из группы — я буду считать твой KPI и зарплату.\n\n"
        "Нажми 📊 чтобы увидеть статистику за месяц.",
        reply_markup=reply_markup
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""

    if "📊 Мой KPI за месяц" in text:
        await show_monthly_kpi(update, context)
        return
    if "📅 История" in text:
        await show_history(update, context)
        return
    if "❓ Помощь" in text:
        await show_help(update, context)
        return

    parsed = parse_report(text)
    if parsed is None:
        await update.message.reply_text(
            "🤔 Не нашёл твоё имя в этом сообщении.\n"
            f"Ищу: *{MY_NAME}*",
            parse_mode="Markdown"
        )
        return

    data = load_data()
    day_key = parsed["date"]

    if day_key in data["records"]:
        await update.message.reply_text(f"⚠️ Запись за *{day_key}* обновляю...", parse_mode="Markdown")

    data["records"][day_key] = {
        "present":    parsed["present"],
        "total_team": parsed.get("total_team"),
        "workers":    parsed.get("workers"),
        "cards":      parsed.get("cards", {}),
    }
    save_data(data)

    status = "✅ Вышел на работу" if parsed["present"] else "❌ Не вышел"

    total_str = ""
    if parsed.get("total_team"):
        total_str = f"\n📦 Карты команды: *{parsed['total_team']}*"
    if parsed.get("workers"):
        total_str += f"  |  👥 Людей: *{parsed['workers']}*"

    cards_str = ""
    if parsed.get("cards"):
        lines = [f"  • {k}: {v}" for k, v in parsed["cards"].items()]
        cards_str = "\n💳 Разбивка карт:\n" + "\n".join(lines)

    salary_str = ""
    if parsed["present"] and parsed.get("total_team") and parsed.get("workers"):
        per_person, salary = calc_salary(parsed["total_team"], parsed["workers"])
        salary_str = (
            f"\n\n💰 *Твоя зарплата за день:*\n"
            f"   {parsed['total_team']} ÷ {parsed['workers']} × {PRICE_PER_CARD} = "
            f"*{salary:,} сум*"
        )
    elif not parsed["present"]:
        salary_str = "\n\n💰 Зарплата за этот день: *0 сум* (не вышел)"

    await update.message.reply_text(
        f"📋 *Отчёт за {day_key}*\n\n"
        f"{status}{total_str}{cards_str}{salary_str}\n\n"
        "Нажми 📊 чтобы увидеть статистику за месяц.",
        parse_mode="Markdown"
    )


async def show_monthly_kpi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["records"]:
        await update.message.reply_text("📭 Нет данных. Перешли первый отчёт из группы!")
        return

    s = get_monthly_stats(data)
    bar_filled = "🟩" * (s["attendance_pct"] // 10)
    bar_empty = "⬜" * (10 - s["attendance_pct"] // 10)
    salary_line = f"\n\n💰 Зарплата за месяц: *{s['total_salary']:,} сум*" if s["total_salary"] else ""

    await update.message.reply_text(
        f"📊 *KPI за {s['month']}*\n\n"
        f"📅 Рабочих дней в базе: *{s['total_days']}*\n"
        f"✅ Вышел: *{s['present_days']}* дн.\n"
        f"❌ Не вышел: *{s['absent_days']}* дн.\n\n"
        f"📈 Посещаемость: *{s['attendance_pct']}%*\n"
        f"{bar_filled}{bar_empty}"
        f"{salary_line}",
        parse_mode="Markdown"
    )


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["records"]:
        await update.message.reply_text("📭 История пуста.")
        return

    today = date.today()
    month_prefix = today.strftime("%Y-%m")
    records = dict(sorted({k: v for k, v in data["records"].items() if k.startswith(month_prefix)}.items()))

    if not records:
        await update.message.reply_text("📭 Нет записей за текущий месяц.")
        return

    lines = []
    for day_key, val in records.items():
        icon = "✅" if val.get("present") else "❌"
        if val.get("present") and val.get("total_team") and val.get("workers"):
            _, sal = calc_salary(val["total_team"], val["workers"])
            sal_str = f" | 💰 {sal:,}"
        else:
            sal_str = " | 💰 0"
        lines.append(f"{icon} {day_key}{sal_str} сум")

    await update.message.reply_text(
        f"📅 *История за {today.strftime('%B %Y')}:*\n\n" + "\n".join(lines),
        parse_mode="Markdown"
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Как пользоваться:*\n\n"
        "1️⃣ Зайди в группу с отчётами\n"
        "2️⃣ Удержи сообщение → *Переслать*\n"
        "3️⃣ Перешли мне\n"
        "4️⃣ Я посчитаю зарплату\n\n"
        f"🔍 Ищу имя: *{MY_NAME}*\n"
        f"💳 Цена за карту: *{PRICE_PER_CARD} сум*",
        parse_mode="Markdown"
    )


if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("🤖 Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
