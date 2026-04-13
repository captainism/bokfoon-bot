from flask import Flask, request, abort
import requests
import os
import threading
import time

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, LocationMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_SECRET")
OPENWEATHER_API_KEY = os.getenv("OW_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

users = {}

# ==========================
# ดึงข้อมูลฝุ่น (กันพัง)
# ==========================
def get_air_quality(lat, lon):
    try:
        url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
        res = requests.get(url, timeout=10)

        if res.status_code != 200:
            print("API ERROR:", res.text)
            return None, None

        data = res.json()["list"][0]
        pm25 = data["components"]["pm2_5"]
        aqi = data["main"]["aqi"]

        return pm25, aqi

    except Exception as e:
        print("get_air_quality ERROR:", e)
        return None, None


# ==========================
# แปล AQI
# ==========================
def interpret_aqi(aqi):
    if aqi == 1:
        return "ดี 😊", "อากาศดีมาก"
    elif aqi == 2:
        return "พอใช้ 😐", "ยังโอเค"
    elif aqi == 3:
        return "เริ่มมีผล 😷", "ควรใส่หน้ากาก"
    elif aqi == 4:
        return "แย่ ⚠️", "หลีกเลี่ยงกิจกรรมกลางแจ้ง"
    else:
        return "อันตราย ☠️", "ควรอยู่ในอาคาร"


# ==========================
# รับ Location
# ==========================
@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    lat = event.message.latitude
    lon = event.message.longitude

    pm25, aqi = get_air_quality(lat, lon)

    if pm25 is None:
        reply = "❌ ดึงข้อมูลอากาศไม่สำเร็จ ลองใหม่อีกครั้ง"
    else:
        level, advice = interpret_aqi(aqi)

        users[user_id] = {
            "lat": lat,
            "lon": lon,
            "last_alert": 0,
            "last_aqi": aqi
        }

        reply = f"""📍 ตำแหน่งของคุณ

PM2.5: {pm25:.2f} µg/m³
ระดับ: {level}

คำแนะนำ:
{advice}
"""

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


# ==========================
# Home route
# ==========================
@app.route("/")
def home():
    return "OK", 200


# ==========================
# Webhook
# ==========================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature")
        abort(400)
    except Exception as e:
        print("Webhook ERROR:", e)
        abort(500)

    return 'OK'


# ==========================
# Loop แจ้งเตือน
# ==========================
def air_check_loop():
    while True:
        try:
            if len(users) == 0:
                time.sleep(600)
                continue

            for user_id, data in list(users.items()):
                pm25, aqi = get_air_quality(data["lat"], data["lon"])

                if pm25 is None:
                    continue

                level, advice = interpret_aqi(aqi)
                old_aqi = data.get("last_aqi", 1)

                if aqi >= 3 and old_aqi < 3:
                    now = time.time()

                    if now - data["last_alert"] > 3600:
                        message = f"""⚠️ อากาศเริ่มแย่!

PM2.5: {pm25:.2f} µg/m³
ระดับ: {level}

คำแนะนำ:
{advice}
"""
                        line_bot_api.push_message(
                            user_id,
                            TextSendMessage(text=message)
                        )

                        users[user_id]["last_alert"] = now

                users[user_id]["last_aqi"] = aqi

        except Exception as e:
            print("Loop ERROR:", e)

        time.sleep(3600)


# ==========================
# Start thread
# ==========================
threading.Thread(target=air_check_loop, daemon=True).start()


# ==========================
# Run (สำคัญมาก)
# ==========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print("Starting on port:", port)
    app.run(host="0.0.0.0", port=port)
