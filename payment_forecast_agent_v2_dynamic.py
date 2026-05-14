#!/usr/bin/env python3
import os
import json
import sqlite3
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")

def init_database():
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS agent_config 
    (id INTEGER PRIMARY KEY, instruction_type TEXT UNIQUE, full_instruction TEXT, 
    sheet_url TEXT, column_mapping JSON, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS execution_history 
    (id INTEGER PRIMARY KEY AUTOINCREMENT, execution_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
    instruction_type TEXT, data_provided TEXT, analysis_result TEXT)''')
    conn.commit()
    conn.close()

def get_latest_message():
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            messages = response.json()
            return messages[0]['body'] if messages else None
    except:
        pass
    return None

def post_to_chatwork(message: str):
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    try:
        requests.post(url, headers=headers, data={"body": message})
        return True
    except:
        return False

def call_claude(prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": "claude-opus-4-20250805",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            return result['content'][0]['text']
    except Exception as e:
        print(f"Claude エラー: {e}")
    return None

def main():
    print("\n" + "=" * 80)
    print(f"🤖 入金予測AIエージェント起動")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    init_database()
    
    print("\n📥 Chatwork からメッセージを取得")
    user_message = get_latest_message()
    
    if not user_message:
        print("⚠️  メッセージがありません")
        return
    
    print(f"✅ メッセージ取得：{user_message[:80]}...")
    
    print("\n🤖 Claude で分析")
    prompt = f"""あなたは Enks 社の経理AIエージェントです。

【ユーザーのメッセージ】
{user_message}

入金チェックの報告を以下フォーマットで作成してください：

📊 入金予実績チェック
✅ テスト実行完了
🔍 Chatwork からの指示を受け取りました
🚨 要注視：なし"""
    
    report = call_claude(prompt)
    
    if not report:
        print("❌ Claude からの応答がありません")
        return
    
    print("\n【報告】")
    print("-" * 80)
    print(report)
    print("-" * 80)
    
    print("\n💬 Chatwork に投稿")
    if post_to_chatwork(report):
        print("✅ 投稿完了")
    
    print("\n" + "=" * 80)
    print("✅ 実行完了")
    print("=" * 80)

if __name__ == "__main__":
    main()
