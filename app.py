from flask import Flask, request
import requests
import json
import os
import sqlite3
from datetime import datetime
import traceback
import hashlib

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

DB_PATH = "/tmp/payment_forecast.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS processed_messages (
        message_hash TEXT PRIMARY KEY,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

def call_claude_api(prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        result = response.json()
        if "content" in result:
            return result["content"][0]["text"]
        else:
            return f"エラー: {result}"
    except Exception as e:
        return f"失敗: {str(e)}"

def post_to_chatwork(message: str):
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    try:
        requests.post(url, headers=headers, data={"body": message}, timeout=10)
    except Exception as e:
        print(f"Chatwork error: {e}")

@app.route('/', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return 'OK', 200
    
    try:
        if not os.path.exists(DB_PATH):
            init_db()
        
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict() if request.form else {}
        
        message_body = data.get('webhook_event', {}).get('body', '')
        
        if not message_body:
            return 'OK', 200
        
        # AI の返信（✅で始まる）に反応しない
        if message_body.startswith('✅'):
            print(f"⚠️ AI の返信をスキップ")
            return 'OK', 200
        
        # SHA256 でハッシュ（確実に重複排除）
        message_hash = hashlib.sha256(message_body.encode()).hexdigest()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 既に処理済みかチェック
        c.execute('SELECT message_hash FROM processed_messages WHERE message_hash = ?', (message_hash,))
        if c.fetchone():
            print(f"⚠️ 既に処理済み: {message_body[:30]}")
            conn.close()
            return 'OK', 200
        
        print(f"📥 新規メッセージ: {message_body}")
        
        # 処理済みとしてマーク
        c.execute('INSERT INTO processed_messages (message_hash, timestamp) VALUES (?, ?)',
                  (message_hash, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        # Claude が分析
        prompt = f"経理分析AI として以下のメッセージに答えてください（簡潔に）：{message_body}"
        ai_response = call_claude_api(prompt)
        
        # Chatwork に返信
        report = f"✅ {ai_response}"
        post_to_chatwork(report)
        
        return 'OK', 200
    
    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        return 'Error', 500
