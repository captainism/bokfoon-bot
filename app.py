from flask import Flask, request, abort
import requests
import os

from apscheduler.schedulers.background import BackgroundScheduler
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_SECRET")
OPENWEATHER_API_KEY = os.getenv("OW_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==========================
# DATA
# ==========================
users = {}
pending_action = {}
pending_name = {}

# ==========================
# API
# ==========================
def get_air_quality(lat, lon):
    try:
        if lat is None or lon is None:
            return None, None

        url = f"https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
        res = requests.get(url, timeout=10)

        if res.status_code != 200:
            print("API ERROR:", res.text)
            return None, None

        data = res.json()["list"][0]
        return data["components"]["pm2_5"], data["main"]["aqi"]

    except Exception as e:
        print("ERROR:", e)
        return None, None

# ==========================
# AQI
# ==========================
def pm25_to_aqi(pm25):
    if pm25 <= 12:
        return int((50/12) * pm25)
    elif pm25 <= 35.4:
        return int((100-51)/(35.4-12)*(pm25-12)+51)
    elif pm25 <= 55.4:
        return int((150-101)/(55.4-35.4)*(pm25-35.4)+101)
    elif pm25 <= 150.4:
        return int((200-151)/(150.4-55.4)*(pm25-55.4)+151)
    elif pm25 <= 250.4:
        return int((300-201)/(250.4-150.4)*(pm25-150.4)+201)
    else:
        return int((500-301)/(500-250.4)*(pm25-250.4)+301)

def interpret_aqi(aqi):
    if aqi <= 50: return "ดี 😊", "อากาศดีมาก"
    elif aqi <= 100: return "ปานกลาง 😐", "ยังโอเค"
    elif aqi <= 150: return "เริ่มมีผล 😷", "ควรใส่หน้ากาก"
    elif aqi <= 200: return "แย่ ⚠️", "หลีกเลี่ยงกิจกรรมกลางแจ้ง"
    else: return "อันตราย ☠️", "ควรอยู่ในอาคาร"

def get_trend(old, new):
    if new > old: return "📈 แย่ลง"
    elif new < old: return "📉 ดีขึ้น"
    return "➡️ คงที่"

def get_gradient(aqi):
    if aqi <= 50: return "#00E676"
    elif aqi <= 100: return "#FFD600"
    elif aqi <= 150: return "#FF9100"
    elif aqi <= 200: return "#FF3D00"
    else: return "#AA00FF"

# ==========================
# TIER
# ==========================
def get_tier(aqi):
    if aqi <= 50: return 1
    elif aqi <= 100: return 2
    elif aqi <= 150: return 3
    elif aqi <= 200: return 4
    else: return 5

# ==========================
# 🔥 FLEX STYLE (ใหม่)
# ==========================
def build_flex_content(aqi_real, level, trend, advice, pm25):
    return {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "xl",
        "contents": [

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": "AQI", "flex": 2, "weight": "bold", "size": "sm"},
                    {"type": "text", "text": str(aqi_real), "flex": 5, "size": "sm"}
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": "ระดับ", "flex": 2, "weight": "bold", "size": "sm"},
                    {"type": "text", "text": level, "flex": 5, "size": "sm"}
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": "สถานะ", "flex": 2, "weight": "bold", "size": "sm"},
                    {"type": "text", "text": trend, "flex": 5, "size": "sm"}
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": "คำแนะนำ", "flex": 2, "weight": "bold", "size": "sm"},
                    {"type": "text", "text": advice, "flex": 5, "size": "sm", "wrap": True}
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": "PM2.5", "flex": 2, "weight": "bold", "size": "sm"},
                    {"type": "text", "text": f"{pm25:.2f}", "flex": 5, "size": "sm"}
                ]
            }
        ]
    }

# ==========================
# FLEX AQI (แก้)
# ==========================
def build_aqi_flex(loc, pm25, aqi_real, trend, level, advice):
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": loc["name"], "weight": "bold", "size": "xl"},
                build_flex_content(aqi_real, level, trend, advice, pm25)
            ]
        }
    }

# ==========================
# WARN (แก้ให้ใช้ style เดียวกัน)
# ==========================
def check_air_quality_job():
    for user_id, locs in users.items():
        for loc in locs:

            pm25, _ = get_air_quality(loc["lat"], loc["lon"])
            if pm25 is None:
                continue

            new_aqi = pm25_to_aqi(pm25)
            old_aqi = loc["last_aqi"]

            if get_tier(new_aqi) > get_tier(old_aqi):

                level, advice = interpret_aqi(new_aqi)

                bubble = {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": f"⚠️ {loc['name']}", "weight": "bold", "size": "xl"},
                            build_flex_content(new_aqi, level, "📈 แย่ลง", advice, pm25)
                        ]
                    }
                }

                line_bot_api.push_message(user_id, FlexSendMessage(alt_text="Alert", contents=bubble))

            loc["last_aqi"] = new_aqi

# ==========================
# TEXT HANDLER
# ==========================
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text == "รายการ":
        line_bot_api.reply_message(event.reply_token, build_list_flex(user_id))

    elif text == "บอกฝุ่น":
        if user_id not in users or len(users[user_id]) == 0:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("❌ ไม่มีสถานที่"))
            return

        bubbles = []

        for loc in users[user_id]:
            pm25, _ = get_air_quality(loc["lat"], loc["lon"])
            if pm25 is None:
                continue

            aqi_real = pm25_to_aqi(pm25)
            level, advice = interpret_aqi(aqi_real)
            trend = get_trend(loc["last_aqi"], aqi_real)

            bubbles.append(build_aqi_flex(loc, pm25, aqi_real, trend, level, advice))
            loc["last_aqi"] = aqi_real

        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="AQI", contents={"type": "carousel", "contents": bubbles})
        )

    elif pending_action.get(user_id) == "waiting_name":
        pending_name[user_id] = text
        pending_action[user_id] = "waiting_location"
        line_bot_api.reply_message(event.reply_token, TextSendMessage("📍 ส่ง location"))

# ==========================
# LOCATION HANDLER
# ==========================
@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id

    if pending_action.get(user_id) != "waiting_location":
        return

    lat = event.message.latitude
    lon = event.message.longitude
    name = pending_name[user_id]

    pm25, _ = get_air_quality(lat, lon)

    if pm25 is None:
        reply = "❌ ดึงข้อมูลไม่สำเร็จ"
    else:
        aqi_real = pm25_to_aqi(pm25)

        users.setdefault(user_id, []).append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "last_aqi": aqi_real
        })

        reply = f"✅ เพิ่ม {name} แล้ว"

    del pending_name[user_id]
    del pending_action[user_id]

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# ==========================
# POSTBACK
# ==========================
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data

    if data == "action=add":
        pending_action[user_id] = "waiting_name"
        reply = "📌 ตั้งชื่อสถานที่"

    elif "action=delete" in data:
        idx = int(data.split("id=")[1])
        removed = users[user_id].pop(idx)
        reply = f"🗑️ ลบ {removed['name']} แล้ว"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# ==========================
# ROUTES
# ==========================
@app.route("/", methods=["GET"])
def home():
    return "OK"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

# ==========================
# SCHEDULER START
# ==========================
scheduler = BackgroundScheduler()
scheduler.add_job(check_air_quality_job, "interval", hours=1)
scheduler.start()

# ==========================
# RUN
# ==========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
