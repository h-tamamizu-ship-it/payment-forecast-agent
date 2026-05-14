#!/usr/bin/env python3
"""
完全版：入金予測AIエージェント
- 初回指示から全て SQLite に記憶
- 2回目以降は簡単な指示で自動実行
- 真の自律型AIエージェント
"""

import anthropic
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
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS agent_config (
        id INTEGER PRIMARY KEY,
        instruction_type TEXT UNIQUE,
        full_instruction TEXT,
        sheet_url TEXT,
        column_mapping JSON,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS execution_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        instruction_type TEXT,
        data_provided TEXT,
        analysis_result TEXT,
        chatwork_posted BOOLEAN
    )
    ''')
    
    conn.commit()
    return conn

def save_instruction(instruction_type: str, full_instruction: str, sheet_url: str = None, columns: dict = None):
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    
    c.execute('''
    INSERT OR REPLACE INTO agent_config 
    (instruction_type, full_instruction, sheet_url, column_mapping, updated_at)
    VALUES (?, ?, ?, ?, datetime('now'))
    ''', (
        instruction_type,
        full_instruction,
        sheet_url,
        json.dumps(columns) if columns else None
    ))
    
    conn.commit()
    conn.close()
    print(f"✅ 指示を記憶しました：{instruction_type}")

def get_saved_instruction(instruction_type: str):
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    
    c.execute('''
    SELECT full_instruction, sheet_url, column_mapping FROM agent_config
    WHERE instruction_type = ?
    ''', (instruction_type,))
    
    result = c.fetchone()
    conn.close()
    
    if result:
        return {
            "full_instruction": result[0],
            "sheet_url": result[1],
            "columns": json.loads(result[2]) if result[2] else {}
        }
    return None

def save_execution(instruction_type: str, data: str, result: str, posted: bool):
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    
    c.execute('''
    INSERT INTO execution_history 
    (instruction_type, data_provided, analysis_result, chatwork_posted)
    VALUES (?, ?, ?, ?)
    ''', (instruction_type, data, result, posted))
    
    conn.commit()
    conn.close()

def get_latest_message():
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            messages = response.json()
            if messages and len(messages) > 0:
                return messages[0]['body']
        return None
    except Exception as e:
        print(f"エラー: {e}")
        return None

def post_to_chatwork(message: str) -> bool:
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": CHATWORK_API_KEY}
    data = {"body": message}
    
    try:
        response = requests.post(url, headers=headers, data=data)
        return response.status_code == 200
    except Exception as e:
        print(f"エラー: {e}")
        return False

def analyze_with_claude(user_message: str, saved_instruction: dict = None):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    context = ""
    if saved_instruction:
        context = f"""
【保存されていた前回の指示】
{saved_instruction['full_instruction']}

【シート URL】
{saved_instruction['sheet_url']}

【列の構成】
{json.dumps(saved_instruction['columns'], ensure_ascii=False)}
        """
    
    prompt = f"""
あなたは Enks 社の経理AIエージェントです。

【ユーザーのメッセージ】
{user_message}

{context}

【やること】
1. このメッセージが「新しい指示」か「簡単な指示」かを判定
2. 新しい指示の場合：シート URL と列の構成を抽出
3. 簡単な指示の場合：前回の指示から自動実行

以下の JSON を出力してください：
{{
  "is_new_instruction": true/false,
  "instruction_type": "入金チェック",
  "sheet_url": "URL",
  "columns": {{"A列": "日付", ...}},
  "report": "Chatwork に投稿する報告文"
}}
"""
    
    message = client.messages.create(
        model="claude-opus-4-20250805",
        max_tokens=2000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    response_text = message.content[0].text
    try:
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    
    return {"is_new_instruction": False, "report": response_text}

def main():
    print("\n" + "=" * 80)
    print(f"🤖 入金予測AIエージェント起動")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    init_database()
    
    try:
        print("\n📥 Chatwork からメッセージを取得")
        user_message = get_latest_message()
        
        if not user_message:
            print("⚠️  メッセージがありません")
            return
        
        print(f"✅ メッセージ取得：{user_message[:80]}...")
        
        print("\n🤖 Claude で分析")
        analysis = analyze_with_claude(user_message)
        
        if analysis.get("is_new_instruction"):
            print("\n💾 新しい指示を記憶")
            save_instruction(
                instruction_type=analysis.get("instruction_type", "入金チェック"),
                full_instruction=user_message,
                sheet_url=analysis.get("sheet_url"),
                columns=analysis.get("columns")
            )
        
        report = analysis.get("report", "チェック完了")
        
        print("\n【報告】")
        print("-" * 80)
        print(report)
        print("-" * 80)
        
        print("\n💬 Chatwork に投稿")
        success = post_to_chatwork(report)
        
        if success:
            print("✅ 投稿完了")
        
        save_execution(
            instruction_type=analysis.get("instruction_type", "入金チェック"),
            data=user_message,
            result=report,
            posted=success
        )
        
        print("\n" + "=" * 80)
        print("✅ 実行完了")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
