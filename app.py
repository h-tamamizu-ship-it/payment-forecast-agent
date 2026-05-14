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
    if request.method == 'GET':
        return 'OK', 200
    
    try:
        # どのデータ形式でも対応
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict() if request.form else {}
        
        print(f"DEBUG: Received data: {data}")
        
        # Chatwork Webhook のデータ形式に対応
        # webhook_event.body にメッセージが入っている
        message_body = data.get('webhook_event', {}).get('body', '')
        
        if not message_body:
            # もしくは他のフォーマットかもしれない
            print("DEBUG: No message_body found, checking alternative formats...")
            return 'OK', 200
        
        print(f"📥 受信メッセージ：{message_body}")
        
        # Chatwork に返信
        report = f"✅ 受け取りました：{message_body[:50]}"
        post_to_chatwork(report)
        
        return 'OK', 200
    except Exception as e:
        print(f"❌ エラー：{e}")
        import traceback
        traceback.print_exc()
        return 'Error', 500

def post_to_chatwork(message: str):
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    try:
        requests.post(url, headers=headers, data={"body": message})
        print("✅ Chatwork に投稿しました")
    except Exception as e:
        print(f"Chatwork 投稿エラー：{e}")
