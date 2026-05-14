from flask import Flask, request
import requests
import json
import os

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

@app.route('/', methods=['GET', 'POST'])
def webhook():
    try:
        data = request.get_json()
        message_body = data.get('webhook_event', {}).get('body', '')
        
        if not message_body:
            return 'OK', 200
        
        print(f"📥 受信：{message_body}")
        
        report = f"✅ 受け取りました：{message_body[:50]}"
        post_to_chatwork(report)
        
        return 'OK', 200
    except Exception as e:
        print(f"❌ エラー：{e}")
        return 'Error', 500

def post_to_chatwork(message: str):
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    try:
        requests.post(url, headers=headers, data={"body": message})
    except:
        pass
