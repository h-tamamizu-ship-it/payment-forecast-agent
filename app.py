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

def get_task_history(task_name, limit=5):
    """特定のタスクに関する過去のやり取りを取得"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT user_message, ai_response FROM conversation_history 
                 WHERE task_name = ? 
                 ORDER BY timestamp DESC 
                 LIMIT ?''', (task_name, limit))
    history = c.fetchall()
    conn.close()
    return history

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

def detect_task_and_type(user_message):
    """
    メッセージから：
    1. タスク名を検出（保存済みタスク名が含まれているか）
    2. メッセージタイプを判定（新規/修正/実行/通常質問）
    """
    
    tasks = get_all_tasks()
    task_names = [name for name, _ in tasks]
    
    # 保存済みタスク名がメッセージに含まれているか確認
    detected_task = None
    for task_name in task_names:
        if task_name in user_message:
            detected_task = task_name
            break
    
    if detected_task:
        # 既存タスク関連のメッセージ
        # 「修正」「変更」「いや」「別に」など修正キーワードがあるか
        修正_keywords = ["いや", "変更", "修正", "別に", "じゃなくて", "のじゃなく", "もっと", "削除", "追加", "こう出して", "こういう形式", "この順番", "違う"]
        
        is_update = any(keyword in user_message for keyword in 修正_keywords)
        
        if is_update:
            return {
                "task_name": detected_task,
                "message_type": "update_or_refine",
                "reason": "既存タスクの修正・改善指示"
            }
        else:
            return {
                "task_name": detected_task,
                "message_type": "follow_up_question",
                "reason": "既存タスクについての質問・フォローアップ"
            }
    else:
        # タスク名が含まれていない
        # 新規タスクか、通常の質問かを判定
        task_keywords = ["チェック", "確認", "分析", "レポート", "照合", "集計", "計算"]
        is_new_task = any(keyword in user_message for keyword in task_keywords)
        
        if is_new_task:
            return {
                "task_name": None,
                "message_type": "new_task",
                "reason": "新しい業務指示と思われる"
            }
        else:
            return {
                "task_name": None,
                "message_type": "general_question",
                "reason": "通常の質問・雑談"
            }

def execute_task_with_history(task_name, original_instruction, user_message):
    """
    タスクを実行する。
    過去のやり取り履歴を参照して、過去の修正指示を自動で反映させる。
    """
    
    # 過去のやり取りを取得
    history = get_task_history(task_name, limit=5)
    
    # 過去のやり取りから「修正パターン」を抽出
    history_text = ""
    if history:
        history_text = "\n\n【過去のやり取り履歴】\n"
        for user_msg, ai_resp in reversed(history):  # 古い順に表示
            history_text += f"ユーザー: {user_msg[:100]}\n"
            history_text += f"AI: {ai_resp[:100]}...\n\n"
    
    prompt = f"""あなたは Enks 社の経理AI秘書です。

【タスク名】
{task_name}

【初期指示】
{original_instruction}

【ユーザーの最新リクエスト】
{user_message}

{history_text}

【対応】
以下のルールで報告を作成してください：

1. 過去のやり取りから「ユーザーの好みの形式・詳細度」を学習
2. 最新リクエストを反映（「もっと詳しく」「エリア別で」など）
3. 過去の修正を全て反映したレポートを出力

形式例：
📊 {task_name} レポート
✅ 実行完了
🔍 [詳細な内容 - 過去の修正全て反映]
🚨 要注視：[該当なければ「なし」]

詳細なレポートを作成してください。"""
    
    return call_claude_api(prompt)

def answer_question(user_message, relevant_task=None):
    """
    通常の質問に答える。
    関連するタスクがあれば、そのコンテキストを含める。
    """
    
    context = ""
    if relevant_task:
        instruction = get_task(relevant_task)
        if instruction:
            context = f"\n\n【関連するタスク: {relevant_task}】\n指示: {instruction}"
    
    prompt = f"""あなたは Enks 社の経理AI秘書です。

【ユーザーの質問】
{user_message}
{context}

【対応】
質問に対して、簡潔かつ正確に答えてください。
必要に応じて、関連するタスク情報を活用してください。"""
    
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
        
        # Webhook イベントから送信者情報を取得
        webhook_event = data.get('webhook_event', {})
        message_body = webhook_event.get('body', '')
        account_id = webhook_event.get('account_id', '')
        
        print(f"📥 account_id = {account_id}, message = {message_body[:50]}")
        
        if not message_body:
            return 'OK', 200
        
        # ===== AI からの投稿は無視（account_id が空 = AI） =====
        if not account_id:
            print(f"⚠️ AI からの投稿をスキップ")
            return 'OK', 200
        
        # 重複排除
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
        
        # ========== メッセージタイプの判定 ==========
        
        detection = detect_task_and_type(message_body)
        message_type = detection['message_type']
        task_name = detection['task_name']
        
        print(f"判定: {message_type} / {task_name}")
        
        # ========== メッセージタイプに応じた処理 ==========
        
        if message_type == "new_task":
            # 新規タスク指示
            # Claude に「これは何というタスクか」を判定させる
            prompt = f"""このメッセージから、タスク名を抽出してください（5文字程度）：
{message_body}

例：「入金チェック」「請求書照合」

タスク名だけを返してください。"""
            
            extracted_task_name = call_claude_api(prompt).strip()
            if not extracted_task_name or len(extracted_task_name) > 20:
                extracted_task_name = "新規タスク"
            
            save_or_update_task(extracted_task_name, message_body)
            ai_response = f"✅ 新しいタスク「{extracted_task_name}」を記憶しました。\n\n指示内容：\n{message_body}"
            save_conversation(message_body, ai_response, extracted_task_name)
        
        elif message_type == "update_or_refine":
            # 既存タスクの修正・改善指示
            # 現在の指示に新しい要望を追加
            current_instruction = get_task(task_name)
            updated_instruction = f"{current_instruction}\n\n【追加指示】\n{message_body}"
            
            save_or_update_task(task_name, updated_instruction)
            ai_response = f"✅ タスク「{task_name}」を更新しました。\n\n追加指示：\n{message_body}\n\n次回からはこの修正を反映して実行します。"
            save_conversation(message_body, ai_response, task_name)
        
        elif message_type == "follow_up_question":
            # 既存タスクについてのフォローアップ質問
            # 過去のやり取りを参照してレポートを実行
            current_instruction = get_task(task_name)
            ai_response = execute_task_with_history(task_name, current_instruction, message_body)
            print(f"✅ タスク実行（履歴参照）: {task_name}")
            save_conversation(message_body, ai_response, task_name)
        
        else:
            # 通常の質問・雑談
            ai_response = answer_question(message_body, relevant_task=task_name)
            # 通常質問は履歴に保存しない
            print(f"💬 通常質問に回答")
        
        # Chatwork に投稿
        post_to_chatwork(ai_response)
        
        return 'OK', 200
    
    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        return 'Error', 500
