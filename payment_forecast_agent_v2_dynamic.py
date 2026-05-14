#!/usr/bin/env python3
import os
import requests
import sqlite3
import json
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
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        task_name TEXT UNIQUE,
        instruction TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS execution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        task_name TEXT,
        message_received TEXT,
        response_generated TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

def save_or_update_task(task_name: str, instruction: str):
    """タスクを保存または更新"""
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('''
    INSERT OR REPLACE INTO tasks 
    (task_name, instruction, updated_at) 
    VALUES (?, ?, datetime('now'))
    ''', (task_name, instruction))
    conn.commit()
    conn.close()
    print(f"✅ タスク保存：{task_name}")

def get_task(task_name: str):
    """タスクを取得"""
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('SELECT instruction FROM tasks WHERE task_name = ?', (task_name,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_all_tasks():
    """全タスクを取得"""
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('SELECT task_name, instruction FROM tasks')
    results = c.fetchall()
    conn.close()
    return results

def save_execution(task_name: str, message: str, response: str):
    """実行履歴を保存"""
    conn = sqlite3.connect('ai_agent_memory.db')
    c = conn.cursor()
    c.execute('''
    INSERT INTO execution_log 
    (task_name, message_received, response_generated) 
    VALUES (?, ?, ?)
    ''', (task_name, message, response))
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
        "max_tokens": 2048,
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

# ============= 指示判定エンジン =============

def analyze_message(user_message: str):
    """Claude で メッセージを分析して、新規か修正か、どのタスクかを判定"""
    
    all_tasks = get_all_tasks()
    task_list = "\n".join([f"- {name}: {instruction[:50]}..." for name, instruction in all_tasks])
    
    if not task_list:
        task_list = "（保存済みタスクなし）"
    
    prompt = f"""あなたは Enks 社の経理AIエージェントです。

【受け取ったメッセージ】
{user_message}

【現在のタスク一覧】
{task_list}

【判定タスク】
このメッセージを分析して、以下を JSON で出力してください：

{{
  "message_type": "new_task" / "update_task" / "execute_task" / "unknown",
  "task_name": "タスク名（例：入金チェック、請求書照合）",
  "instruction": "具体的な指示内容（new_taskまたはupdate_taskの場合）",
  "reason": "判定理由"
}}

判定基準：
- new_task: 新しい業務を指示（「●●をチェックして」など初めての業務）
- update_task: 既存タスクを修正（「いや、△△に変えて」など既存業務の修正）
- execute_task: 既存タスクを実行（「チェック」「確認」など簡潔な実行指示）
- unknown: 判定不可
"""
    
    response = call_claude(prompt)
    
    try:
        # JSON を抽出
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    
    return {
        "message_type": "unknown",
        "task_name": "不明",
        "instruction": user_message,
        "reason": "分析失敗"
    }

# ============= 実行エンジン =============

def execute_task(task_name: str, instruction: str):
    """タスクを実行し、報告を生成"""
    
    prompt = f"""あなたは Enks 社の経理AIエージェントです。

【タスク名】
{task_name}

【指示内容】
{instruction}

【対応】
この指示に基づいて、{task_name} の報告を生成してください。

形式：
📊 {task_name} 報告書
✅ チェック完了
🔍 [具体的な分析内容]
🚨 要注視：[該当なければ「なし」]

詳細な報告を作成してください。"""
    
    report = call_claude(prompt)
    return report if report else "実行エラー"

# ============= Main =============

def main():
    print(f"\n🤖 AI エージェント起動 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    init_database()
    
    # ① Chatwork からメッセージ取得
    user_message = get_latest_message()
    
    if not user_message:
        print("⚠️  メッセージなし\n")
        return
    
    print(f"📥 受信：{user_message[:80]}\n")
    
    # ② Claude で メッセージを分析
    print("🤖 メッセージを分析中...")
    analysis = analyze_message(user_message)
    
    print(f"分析結果：{analysis['message_type']} / {analysis['task_name']}\n")
    
    message_type = analysis['message_type']
    task_name = analysis['task_name']
    instruction = analysis['instruction']
    
    # ③ 判定結果に基づいて処理
    if message_type == "new_task":
        # 新規タスク → 保存
        print(f"✨ 新しいタスク：{task_name}")
        save_or_update_task(task_name, instruction)
        report = f"✅ 新しいタスク「{task_name}」を記憶しました。\n\n指示内容：\n{instruction}"
    
    elif message_type == "update_task":
        # 既存タスク修正 → 上書き保存
        print(f"🔄 タスク修正：{task_name}")
        save_or_update_task(task_name, instruction)
        report = f"✅ タスク「{task_name}」を更新しました。\n\n新しい指示：\n{instruction}"
    
    elif message_type == "execute_task":
        # 実行指示 → 保存済みタスクで実行
        print(f"▶️  タスク実行：{task_name}")
        saved_instruction = get_task(task_name)
        if saved_instruction:
            report = execute_task(task_name, saved_instruction)
            print(f"✅ タスク実行完了")
        else:
            report = f"❌ タスク「{task_name}」が見つかりません"
    
    else:
        # 判定不可
        report = "⚠️  メッセージの意図が判定できませんでした。\n\n以下の形式で指示してください：\n- 新規：「入金チェック：このシートの A列を見てね」\n- 修正：「入金チェック：いや、B列を見てね」\n- 実行：「入金チェック」or「チェック」"
    
    # ④ Chatwork に投稿
    print(f"\n💬 Chatwork に投稿")
    post_to_chatwork(report)
    print("✅ 投稿完了\n")
    
    # ⑤ 実行履歴を保存
    save_execution(task_name, user_message, report)
    
    print("=" * 80)
    print("✅ 実行完了\n")

if __name__ == "__main__":
    main()
