from flask import Flask, request
import requests
import json
import os
import sqlite3
from datetime import datetime
import traceback
import hashlib
import gspread                                    # ← この 3 行を追加
from google.oauth2.service_account import Credentials
import re

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
AI_CHATWORK_API_KEY = os.getenv("AI_CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")  # ← この 1 行を追加

# AI アカウント ID
AI_ACCOUNT_ID = "11369834"

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
    
    c.execute('''CREATE TABLE IF NOT EXISTS google_sheets_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT UNIQUE,
        sheet_url TEXT,
        columns TEXT,
        last_updated TEXT
    )''')
    
    conn.commit()
    conn.close()
    
def init_google_sheets_client():
    """Google Sheets API クライアントを初期化"""
    try:
        if not GOOGLE_SHEETS_CREDENTIALS:
            print("⚠️ GOOGLE_SHEETS_CREDENTIALS が設定されていません")
            return None
        
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ Google Sheets クライアント初期化失敗: {e}")
        return None

GOOGLE_SHEETS_CLIENT = init_google_sheets_client()

def fetch_google_sheets_data(sheet_url, columns):
    """
    Google Sheets から指定列のデータを取得
    
    Args:
        sheet_url: Google Sheets の共有リンク
        columns: 抽出する列名のリスト（例：["日付", "金額", "説明"]）
    
    Returns:
        dict: {"status": "success" or "error", "data": [...], "message": "..."}
    """
    if not GOOGLE_SHEETS_CLIENT:
        return {"status": "error", "message": "Google Sheets クライアントが初期化されていません"}
    
    try:
        # URL から Spreadsheet ID を抽出
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match:
            return {"status": "error", "message": "無効な Google Sheets URL です"}
        
        spreadsheet_id = match.group(1)
        spreadsheet = GOOGLE_SHEETS_CLIENT.open_by_key(spreadsheet_id)
        
        # 最初のシートを取得
        worksheet = spreadsheet.get_worksheet(0)
        
        if not worksheet:
            return {"status": "error", "message": "シートが見つかりません"}
        
        # ヘッダー行を取得
        header_row = worksheet.row_values(1)
        
        # 指定列のインデックスを検出
        column_indices = {}
        for col_name in columns:
            if col_name in header_row:
                column_indices[col_name] = header_row.index(col_name)
            else:
                return {"status": "error", "message": f"列「{col_name}」が見つかりません。利用可能な列: {header_row}"}
        
        # 全行を取得
        all_rows = worksheet.get_all_values()
        
        # 指定列のデータのみを抽出
        extracted_data = []
        for row in all_rows[1:]:  # ヘッダーをスキップ
            row_data = {}
            for col_name, col_index in column_indices.items():
                row_data[col_name] = row[col_index] if col_index < len(row) else ""
            extracted_data.append(row_data)
        
        return {
            "status": "success",
            "data": extracted_data,
            "message": f"{len(extracted_data)} 行のデータを取得しました"
        }
    
    except gspread.exceptions.SpreadsheetNotFound:
        return {"status": "error", "message": "スプレッドシートが見つかりません。共有設定を確認してください"}
    except Exception as e:
        return {"status": "error", "message": f"Google Sheets 読み込みエラー: {str(e)}"}

def detect_google_sheets_config(user_message):
    """
    メッセージから Google Sheets 連携指示を検出
    """
    # Google Sheets URL を検出
    url_match = re.search(r'https://docs\.google\.com/spreadsheets/d/[a-zA-Z0-9-_]+', user_message)
    
    if not url_match:
        return {"detected": False}
    
    sheet_url = url_match.group(0)
    
    # 列情報を検出
    columns = []
    
    # columns: 形式を検出
    columns_match = re.search(r'columns?\s*[:：]\s*([^\n,]+(?:,[^\n,]+)*)', user_message)
    if columns_match:
        columns_text = columns_match.group(1)
        columns = [col.strip() for col in columns_text.split(',')]
    else:
        # URL の直後の情報から列を抽出
        after_url = user_message[url_match.end():]
        first_line = after_url.split('\n')[0]
        first_line = first_line.strip().strip('　').strip()
        
        if first_line and not any(keyword in first_line.lower() for keyword in ['http', 'google', 'sheets']):
            columns = [col.strip() for col in first_line.split(',')]
    
    if not columns:
        return {"detected": True, "sheet_url": sheet_url, "columns": None}
    
    return {
        "detected": True,
        "sheet_url": sheet_url,
        "columns": columns
    }

def save_google_sheets_config(task_name, sheet_url, columns):
    """Google Sheets 設定を保存"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    
    c.execute('SELECT id FROM google_sheets_config WHERE task_name = ?', (task_name,))
    
    columns_json = json.dumps(columns)
    
    if c.fetchone():
        c.execute('''UPDATE google_sheets_config 
                     SET sheet_url = ?, columns = ?, last_updated = ? 
                     WHERE task_name = ?''',
                  (sheet_url, columns_json, now, task_name))
    else:
        c.execute('''INSERT INTO google_sheets_config 
                     (task_name, sheet_url, columns, last_updated) 
                     VALUES (?, ?, ?, ?)''',
                  (task_name, sheet_url, columns_json, now))
    
    conn.commit()
    conn.close()
    print(f"✅ Google Sheets 設定を保存: {task_name}")

def get_google_sheets_config(task_name):
    """タスクの Google Sheets 設定を取得"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT sheet_url, columns FROM google_sheets_config WHERE task_name = ?', (task_name,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return {
            "sheet_url": result[0],
            "columns": json.loads(result[1])
        }
    return None

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

def post_to_chatwork(message: str, from_ai=True):
    """
    Chatwork にメッセージを投稿
    from_ai=True の場合は AI アカウントで投稿
    from_ai=False の場合はユーザーアカウントで投稿
    """
    api_key = AI_CHATWORK_API_KEY if from_ai else CHATWORK_API_KEY
    
    if not api_key:
        print(f"❌ API キーが設定されていません (from_ai={from_ai})")
        return
    
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {"X-ChatworkToken": api_key}
    try:
        requests.post(url, headers=headers, data={"body": message}, timeout=10)
        print(f"✅ Chatwork に投稿完了 (from_ai={from_ai})")
    except Exception as e:
        print(f"❌ Chatwork error: {e}")

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
        for user_msg, ai_resp in reversed(history):
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
        
        # ===== AI アカウントからの投稿は無視 =====
        if str(account_id) == AI_ACCOUNT_ID:
            print(f"⚠️ AI アカウント（{AI_ACCOUNT_ID}）からの投稿をスキップ")
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
            current_instruction = get_task(task_name)
            updated_instruction = f"{current_instruction}\n\n【追加指示】\n{message_body}"
            
            save_or_update_task(task_name, updated_instruction)
            ai_response = f"✅ タスク「{task_name}」を更新しました。\n\n追加指示：\n{message_body}\n\n次回からはこの修正を反映して実行します。"
            save_conversation(message_body, ai_response, task_name)
        
        elif message_type == "follow_up_question":
            # 既存タスクについてのフォローアップ質問
            current_instruction = get_task(task_name)
            ai_response = execute_task_with_history(task_name, current_instruction, message_body)
            print(f"✅ タスク実行（履歴参照）: {task_name}")
            save_conversation(message_body, ai_response, task_name)
        
        else:
            # 通常の質問・雑談
            ai_response = answer_question(message_body, relevant_task=task_name)
            print(f"💬 通常質問に回答")
        
        # ========== AI アカウントで Chatwork に投稿 ==========
        post_to_chatwork(ai_response, from_ai=True)
        
        return 'OK', 200
    
    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        return 'Error', 500
