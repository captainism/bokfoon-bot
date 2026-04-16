from flask import Flask, request, abort
import requests
import os
import threading
import time

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
        url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
        res = requests.get(url, timeout=10)

        if res.status_code != 200:
            return None, None

        data = res.json()["list"][0]
        return data["components"]["pm2_5"], data["main"]["aqi"]

    except:
        return None, None


# ==========================
# PM2.5 → AQI (US Standard)
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


# ==========================
# FLEX UI
# ==========================
def build_flex(user_id):
    bubbles = []

    if user_id in users:
        for i, loc in enumerate(users[user_id]):
            bubble = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": loc["name"],
                            "weight": "bold",
                            "size": "xl"
                        }
                    ]
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "height": "sm",
                            "action": {
                                "type": "postback",
                                "label": "🔍 บอกฝุ่น",
                                "data": f"action=check&id={i}"
                            },
                            "color": "#75CDFF"
                        },
                        {
                            "type": "button",
                            "style": "primary",
                            "height": "sm",
                            "action": {
                                "type": "postback",
                                "label": "🗑️ ลบ",
                                "data": f"action=delete&id={i}"
                            },
                            "color": "#F75454"
                        }
                    ]
                }
            }

            bubbles.append(bubble)

    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "➕ เพิ่มสถานที่",
                    "weight": "bold",
                    "size": "xl"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "เพิ่ม",
                        "data": "action=add"
                    },
                    "color": "#78F78D"
                }
            ]
        }
    })

    return FlexSendMessage(
        alt_text="รายการสถานที่",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )


# ==========================
# TEXT
# ==========================
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text == "รายการ":
        flex_msg = build_flex(user_id)
        line_bot_api.reply_message(event.reply_token, flex_msg)

    elif pending_action.get(user_id) == "waiting_name":
        pending_name[user_id] = text
        pending_action[user_id] = "waiting_location"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"📍 ส่ง location สำหรับ '{text}'")
        )


# ==========================
# LOCATION
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

        if user_id not in users:
            users[user_id] = []

        users[user_id].append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "last_alert": 0,
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
        reply = "📌 ตั้งชื่อสถานที่นี้ว่าอะไรดี?"

    elif "action=check" in data:
        idx = int(data.split("id=")[1])
        loc = users[user_id][idx]

        pm25, _ = get_air_quality(loc["lat"], loc["lon"])

        if pm25 is None:
            reply = "❌ ดึงข้อมูลไม่สำเร็จ"
        else:
            aqi_real = pm25_to_aqi(pm25)
            level, advice = interpret_aqi(aqi_real)
            trend = get_trend(loc["last_aqi"], aqi_real)

            reply = f"""📍 {loc['name']}

PM2.5: {pm25:.2f}
AQI: {aqi_real}
ระดับ: {level}
{trend}

{advice}
"""

            loc["last_aqi"] = aqi_real

    elif "action=delete" in data:
        idx = int(data.split("id=")[1])
        removed = users[user_id].pop(idx)
        reply = f"🗑️ ลบ {removed['name']} แล้ว"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))


# ==========================
# LOOP ALERT
# ==========================
def air_check_loop():
    while True:
        for user_id, locs in users.items():
            for loc in locs:
                pm25, _ = get_air_quality(loc["lat"], loc["lon"])

                if pm25 is None:
                    continue

                aqi_real = pm25_to_aqi(pm25)
                old = loc["last_aqi"]

                if aqi_real >= 150 and old < 150:
                    if time.time() - loc["last_alert"] > 3600:
                        level, advice = interpret_aqi(aqi_real)
                        trend = get_trend(old, aqi_real)

                        msg = f"""⚠️ {loc['name']}

PM2.5: {pm25:.2f}
AQI: {aqi_real}
ระดับ: {level}
{trend}

{advice}
"""

                        line_bot_api.push_message(user_id, TextSendMessage(text=msg))
                        loc["last_alert"] = time.time()

                loc["last_aqi"] = aqi_real

        time.sleep(3600)


threading.Thread(target=air_check_loop, daemon=True).start()


# ==========================
# WEBHOOK
# ==========================
@app.route("/")
def home():
    return "OK", 200


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


# ==========================
# RUN
# ==========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
