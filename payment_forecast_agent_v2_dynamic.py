#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")

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
    
    print(f"DEBUG: API キー長：{len(ANTHROPIC_API_KEY)}")
    print(f"DEBUG: Chatwork ルーム ID：{CHATWORK_ROOM_ID}")
    
    try:
        response = requests.post(url, headers=headers, json=data)
        print(f"DEBUG: ステータスコード：{response.status_code}")
        print(f"DEBUG: レスポンス：{response.text[:200]}")
        
        if response.status_code == 200:
            result = response.json()
            return result['content'][0]['text']
        else:
            print(f"Claude API エラー: {response.status_code} {response.text}")
    except Exception as e:
        print(f"リクエスト エラー: {e}")
    
    return None

def main():
    print("\n" + "=" * 80)
    print(f"🤖 入金予測AIエージェント起動")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    print("\n📥 Chatwork からメッセージを取得")
    user_message = get_latest_message()
    
    if not user_message:
        print("⚠️  メッセージがありません")
        return
    
    print(f"✅ メッセージ取得：{user_message[:80]}...")
    
    print("\n🤖 Claude で分析")
    prompt = f"""あなたは Enks 社の経理AIエージェントです。

【メッセージ】
{user_message}

入金チェック報告を作成してください。"""
    
    report = call_claude(prompt)
    
    if not report:
        report = "🚨 Claude からの応答がありませんでした"
    
    print("\n【報告】")
    print(report)
    
    print("\n💬 Chatwork に投稿")
    if post_to_chatwork(report):
        print("✅ 投稿完了")
    
    print("\n✅ 実行完了\n")

if __name__ == "__main__":
    main()
