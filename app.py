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

# เก็บข้อมูล user
users = {}
# format:
# user_id: {
#   lat, lon,
#   last_alert,
#   last_aqi
# }

# ==========================
# ดึงข้อมูลฝุ่น
# ==========================
def get_air_quality(lat, lon):
    url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    res = requests.get(url).json()

    data = res["list"][0]
    pm25 = data["components"]["pm2_5"]
    aqi = data["main"]["aqi"]

    return pm25, aqi


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
# รับ Location → ตอบทันที
# ==========================
@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    lat = event.message.latitude
    lon = event.message.longitude

    pm25, aqi = get_air_quality(lat, lon)
    level, advice = interpret_aqi(aqi)

    # บันทึก user + ค่า AQI ล่าสุด
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
# Webhook
# ==========================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


# ==========================
# ระบบแจ้งเตือนอัตโนมัติ
# ==========================
def air_check_loop():
    while True:
        if len(users) == 0:
            time.sleep(600)
            continue

        for user_id, data in users.items():
            lat = data["lat"]
            lon = data["lon"]

            pm25, aqi = get_air_quality(lat, lon)
            level, advice = interpret_aqi(aqi)

            old_aqi = data.get("last_aqi", 1)

            # 🔥 แจ้งเฉพาะ "จากดี → แย่"
            if aqi >= 3 and old_aqi < 3:
                now = time.time()

                # กัน spam (1 ชม./ครั้ง)
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

            # อัปเดตค่า AQI ล่าสุด
            users[user_id]["last_aqi"] = aqi

        time.sleep(3600)  # 🔥 เช็คทุก 1 ชั่วโมง


# ==========================
# Start background thread
# ==========================
threading.Thread(target=air_check_loop, daemon=True).start()


# ==========================
# Run
# ==========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
