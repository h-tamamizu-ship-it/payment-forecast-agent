#!/usr/bin/env python3
"""
修正版：入金予測AIエージェント
- proxies エラーを修正
- Chatwork から指示を受け取り、自動実行
"""

import anthropic
import os
import json
import sqlite3
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

# ============= 設定 =============

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")

# ============= Chatwork API =============

def get_latest_message_from_chatwork():
    """Chatwork から最新のメッセージを取得"""
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {
        "X-ChatworkToken": CHATWORK_API_KEY
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            messages = response.json()
            if messages:
                return messages[0]['body']
        return None
    except Exception as e:
        print(f"❌ Chatwork メッセージ取得エラー: {e}")
        return None

def post_to_chatwork(message: str) -> bool:
    """Chatwork にメッセージを投稿"""
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM_ID}/messages"
    headers = {
        "X-ChatworkToken": CHATWORK_API_KEY
    }
    data = {
        "body": message
    }
    
    try:
        response = requests.post(url, headers=headers, data=data)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Chatwork 投稿エラー: {e}")
        return False

# ============= Claude：メイン AI エージェント =============

def analyze_with_claude(user_instruction: str):
    """
    Claude に指示を与える
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    context = f"""
    あなたは Enks 社の入金予測チェック AI です。
    
    【ユーザーからの指示】
    {user_instruction}
    
    【やること】
    1. ユーザーの指示を理解する
    2. 指示に応じて分析・報告を生成
    3. 結果を Chatwork 報告用フォーマットで出力
    
    📊 [日付] 入金予実績チェック
    ✅ 全体：予測 ¥X 実績 ¥Y 乖離 ¥Z（パーセンテージ）
    
    🔍 キャリア別：
      • キャリアA：予測¥X → 実績¥Y（乖離¥Z）
    
    🚨 要注視：[異常があれば記載、なければ「なし」]
    
    【現在のステータス】
    - Google Sheets はまだセットアップされていません
    - Chatwork で「このシートを見てね」と指示が来たら、そこからデータを取得します
    - 初期段階なので、テスト実行です
    
    上記のフォーマットで、テスト用の報告文を生成してください。
    """
    
    message = client.messages.create(
        model="claude-opus-4-20250805",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": context}
        ]
    )
    
    return message.content[0].text

# ============= メイン処理 =============

def main():
    print("\n" + "=" * 80)
    print(f"🤖 入金予測AIエージェント起動 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print("=" * 80)
    
    try:
        # ステップ1：Chatwork から指示を読む
        print("\n📥 ステップ1：Chatwork から指示を受け取る")
        user_instruction = get_latest_message_from_chatwork()
        
        if not user_instruction:
            print("❌ Chatwork にメッセージがありません")
            print("\n💡 Chatwork で以下のような指示を送ってください：")
            default_message = """
入金チェックをテストしてください。
データはまだありませんが、テスト用の報告を作成してください。
            """
            user_instruction = default_message
            print(default_message)
        else:
            print(f"✅ 指示を受け取りました：{user_instruction[:100]}...")
        
        # ステップ2：Claude が指示を理解・分析
        print("\n🤖 ステップ2：Claude が指示を理解・分析")
        report = analyze_with_claude(user_instruction)
        
        print("\n【Claude の報告】")
        print("-" * 80)
        print(report)
        print("-" * 80)
        
        # ステップ3：Chatwork に投稿
        print("\n💬 ステップ3：Chatwork に投稿")
        success = post_to_chatwork(report)
        
        if success:
            print("✅ Chatwork 投稿完了")
        else:
            print("⚠️  Chatwork 投稿に失敗しました")
        
        # ステップ4：SQLite に履歴保存
        print("\n💾 ステップ4：履歴を保存")
        conn = sqlite3.connect('payment_forecast.db')
        c = conn.cursor()
        
        c.execute('''
        CREATE TABLE IF NOT EXISTS execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            instruction TEXT,
            report TEXT
        )
        ''')
        
        c.execute('''
        INSERT INTO execution_log (instruction, report) VALUES (?, ?)
        ''', (user_instruction, report))
        
        conn.commit()
        conn.close()
        
        print("✅ 履歴保存完了")
        
        print("\n" + "=" * 80)
        print("✅ 実行完了")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ エラー発生: {e}")
        import traceback
        traceback.print_exc()
        
        # エラーを Chatwork に投稿
        error_msg = f"🚨 入金チェック エラー\n{str(e)}"
        post_to_chatwork(error_msg)

# ============= エントリーポイント =============

if __name__ == "__main__":
    main()
