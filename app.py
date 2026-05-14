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
    
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT UNIQUE,
        instruction TEXT,
        created_at TEXT,
        updated_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user_message TEXT,
        ai_response TEXT,
        task_name TEXT
    )''')
    
    conn.commit()
    conn.close()

def get_all_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT task_name, instruction FROM tasks ORDER BY updated_at DESC')
    tasks = c.fetchall()
    conn.close()
    return tasks

def save_or_update_task(task_name, instruction):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    c.execute('SELECT id FROM tasks WHERE task_name = ?', (task_name,))
    if c.fetchone():
        c.execute('UPDATE tasks SET instruction = ?, updated_at = ? WHERE task_name = ?',
                  (instruction, now, task_name))
        print(f"✅ タスク更新: {task_name}")
    else:
        c.execute('INSERT INTO tasks (task_name, instruction, created_at, updated_at) VALUES (?, ?, ?, ?)',
                  (task_name, instruction, now, now))
        print(f"✅ タスク新規作成: {task_name}")
    
    conn.commit()
    conn.close()

def get_task(task_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT instruction FROM tasks WHERE task_name = ?', (task_name,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def save_conversation(user_message, ai_response, task_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO conversation_history (timestamp, user_message, ai_response, task_name) VALUES (?, ?, ?, ?)',
              (datetime.now().isoformat(), user_message, ai_response, task_name))
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
        "max_tokens": 2048,
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

def analyze_message(user_message):
    tasks = get_all_tasks()
    tasks_text = "\n".join([f"- {name}: {inst[:50]}..." for name, inst in tasks]) if tasks else "（保存済みタスクなし）"
    
    prompt = f"""あなたは Enks 社の経理AI秘書です。

【受け取ったメッセージ】
{user_message}

【現在の保存済みタスク】
{tasks_text}

【判定タスク】
このメッセージを分析して、以下を JSON で出力してください：

{{
  "message_type": "new_task" / "update_task" / "execute_task" / "unknown",
  "task_name": "タスク名（例：入金チェック、請求書照合）",
  "instruction": "具体的な指示内容（new_task または update_task の場合）",
  "reason": "判定理由"
}}

判定基準：
- new_task: 新しい業務を指示（「●●をチェックして」など初めての業務）
- update_task: 既存タスクを修正（「いや、△△に変えて」など既存業務の修正）
- execute_task: 既存タスクを実行（「チェック」「確認」など簡潔な実行指示）
- unknown: 判定不可

JSON だけを出力してください。"""
    
    response = call_claude_api(prompt)
    
    try:
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"JSON パース失敗: {e}")
    
    return {
        "message_type": "unknown",
        "task_name": "不明",
        "instruction": user_message,
        "reason": "分析失敗"
    }

def execute_task(task_name, instruction):
    prompt = f"""あなたは Enks 社の経理AI秘書です。

【タスク名】
{task_name}

【指示内容】
{instruction}

【対応】
この指示に基づいて、{task_name} の報告を作成してください。

形式：
📊 {task_name} チェック結果
✅ 実行完了
🔍 [具体的な分析内容またはフィードバック]
🚨 要注視：[該当なければ「なし」]

データがまだ提供されていない場合は、どのようなデータが必要かを指摘してください。
詳細な報告を作成してください。"""
    
    return call_claude_api(prompt)

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
        
        if message_body.startswith('✅'):
            print(f"⚠️ AI の返信をスキップ")
            return 'OK', 200
        
        message_hash = hashlib.sha256(message_body.encode()).hexdigest()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('SELECT message_hash FROM processed_messages WHERE message_hash = ?', (message_hash,))
        if c.fetchone():
            print(f"⚠️ 既に処理済み: {message_body[:30]}")
            conn.close()
            return 'OK', 200
        
        print(f"📥 新規メッセージ: {message_body}")
        
        c.execute('INSERT INTO processed_messages (message_hash, timestamp) VALUES (?, ?)',
                  (message_hash, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        # 分析
        analysis = analyze_message(message_body)
        print(f"分析結果: {analysis['message_type']} / {analysis['task_name']}")
        
        message_type = analysis['message_type']
        task_name = analysis['task_name']
        instruction = analysis.get('instruction', message_body)
        
        if message_type == "new_task":
            save_or_update_task(task_name, instruction)
            ai_response = f"✅ 新しいタスク「{task_name}」を記憶しました。\n\n指示内容：\n{instruction}"
        
        elif message_type == "update_task":
            save_or_update_task(task_name, instruction)
            ai_response = f"✅ タスク「{task_name}」を更新しました。\n\n新しい指示：\n{instruction}"
        
        elif message_type == "execute_task":
            saved_instruction = get_task(task_name)
            if saved_instruction:
                ai_response = execute_task(task_name, saved_instruction)
                print(f"✅ タスク実行: {task_name}")
            else:
                ai_response = f"❌ タスク「{task_name}」が見つかりません。\n\n保存済みタスク：\n"
                tasks = get_all_tasks()
                if tasks:
                    ai_response += "\n".join([f"- {name}" for name, _ in tasks])
                else:
                    ai_response += "（なし）\n\n新しいタスクは「タスク名：指示内容」という形式で教えてください。"
        
        else:
            ai_response = "⚠️ メッセージの意図が判定できませんでした。\n\n以下の形式で指示してください：\n- 新規：「入金チェック：このシートの A列を見てね」\n- 修正：「入金チェック：いや、B列を見てね」\n- 実行：「入金チェック」 or 「チェック」"
        
        save_conversation(message_body, ai_response, task_name)
        post_to_chatwork(ai_response)
        
        return 'OK', 200
    
    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        return 'Error', 500
