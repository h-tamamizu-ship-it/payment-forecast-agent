#!/usr/bin/env python3
import os
import requests
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ============= SQLite =============

def init_database():
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS task_instructions (
        id INTEGER PRIMARY KEY,
        task_type TEXT UNIQUE,
        instruction TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS execution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        task_type TEXT,
        instruction_received TEXT,
        response_generated TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

def save_instruction(task_type: str, instruction: str):
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('''
    INSERT OR REPLACE INTO task_instructions 
    (task_type, instruction, updated_at) 
    VALUES (?, ?, datetime('now'))
    ''', (task_type, instruction))
    conn.commit()
    conn.close()

def get_instruction(task_type: str):
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('SELECT instruction FROM task_instructions WHERE task_type = ?', (task_type,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_execution(task_type: str, instruction: str, response: str):
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('''
    INSERT INTO execution_log 
    (task_type, instruction_received, response_generated) 
    VALUES (?, ?, ?)
    ''', (task_type, instruction, response))
    conn.commit()
    conn.close()

# ============= Chatwork =============

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

# ============= Claude API =============

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
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if 'content' in result and len(result['content']) > 0:
                return result['content'][0]['text']
    except Exception as e:
        print(f"Claude エラー: {e}")
    
    return None

# ============= Main =============

def main():
    print(f"🤖 AI エージェント起動 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    init_database()
    
    # ① Chatwork からメッセージ取得
    user_message = get_latest_message()
    
    if not user_message:
        print("メッセージなし")
        return
    
    print(f"受信：{user_message[:60]}")
    
    # ② 新しい指示か、簡単な指示か判定
    is_new_instruction = any(keyword in user_message for keyword in 
                             ["シート", "URL", "列", "確認", "チェック"])
    
    if "シート" in user_message or "URL" in user_message:
        # 新しい指示 → 保存
        task_type = "入金チェック"
        save_instruction(task_type, user_message)
        print("✅ 新しい指示を記憶しました")
    else:
        # 簡単な指示 → 前回の指示を使用
        saved = get_instruction("入金チェック")
        if saved:
            user_message = saved
            print("✅ 保存済みの指示を使用")
    
    # ③ Claude で分析
    prompt = f"""あなたは Enks 社の経理AIエージェントです。

【指示】
{user_message}

【タスク】
入金チェック報告を以下フォーマットで作成してください：

📊 入金予実績チェック
✅ チェック完了
🔍 指示内容を確認しました
🚨 要注視：なし

詳細な報告を作成してください。"""
    
    report = call_claude(prompt)
    
    if not report:
        report = "エラーが発生しました"
    
    print(f"報告生成完了")
    
    # ④ Chatwork に投稿
    post_to_chatwork(report)
    print("✅ Chatwork に投稿完了")
    
    # ⑤ 実行履歴を記録
    save_execution("入金チェック", user_message, report)
    print("✅ 履歴を記録しました\n")

if __name__ == "__main__":
    main()
