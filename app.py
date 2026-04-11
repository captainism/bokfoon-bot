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

def get_air_quality(lat, lon):
    url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    res = requests.get(url).json()
    data = res["list"][0]
    return data["components"]["pm2_5"], data["main"]["aqi"]

def interpret_aqi(aqi):
    if aqi == 1:
        return "ดี 😊", "อากาศดี"
    elif aqi == 2:
        return "พอใช้ 😐", "ยังโอเค"
    elif aqi == 3:
        return "เริ่มมีผล 😷", "ควรใส่หน้ากาก"
    elif aqi == 4:
        return "แย่ ⚠️", "หลีกเลี่ยงกิจกรรมกลางแจ้ง"
    else:
        return "อันตราย ☠️", "อยู่ในอาคาร"

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    lat = event.message.latitude
    lon = event.message.longitude

    users[user_id] = {"lat": lat, "lon": lon, "last_alert": 0}

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="📍 บันทึกตำแหน่งแล้ว ระบบจะตรวจอากาศให้อัตโนมัติ")
    )

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# 🔥 Loop เช็คอากาศ
def air_loop():
    while True:
        if len(users) == 0:
            time.sleep(600)
            continue

        for user_id, data in users.items():
            pm25, aqi = get_air_quality(data["lat"], data["lon"])

            if aqi >= 3:
                now = time.time()
                if now - data["last_alert"] > 3600:
                    level, advice = interpret_aqi(aqi)

                    msg = f"""⚠️ อากาศไม่ดี
PM2.5: {pm25}
ระดับ: {level}
{advice}
"""
                    line_bot_api.push_message(
                        user_id,
                        TextSendMessage(text=msg)
                    )

                    users[user_id]["last_alert"] = now

        time.sleep(3600)  # 🔥 เช็คทุก 1 ชั่วโมง

threading.Thread(target=air_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)