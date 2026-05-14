#!/usr/bin/env python3
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

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
    except:
        pass

def call_claude(prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01"
    }
    data = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if 'content' in result and len(result['content']) > 0:
                return result['content'][0]['text']
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")
    
    return None

def main():
    print(f"🤖 AI エージェント起動 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    user_message = get_latest_message()
    
    if not user_message:
        print("メッセージなし")
        return
    
    print(f"メッセージ: {user_message[:60]}")
    
    report = call_claude(f"以下のメッセージについて入金チェック報告を作成してください：\n\n{user_message}")
    
    if report:
        print(f"報告: {report[:100]}")
        post_to_chatwork(report)
        print("✅ 完了")
    else:
        print("❌ 応答なし")

if __name__ == "__main__":
    main()
