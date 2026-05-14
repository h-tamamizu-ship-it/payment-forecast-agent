#!/usr/bin/env python3
"""
入金予測AIエージェント（requests のみで実装）
- Google Sheets API ライブラリを使わない
- requests で直接 Google Sheets API を呼び出す
- Chatwork で指示を受け取る
"""

import anthropic
import os
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

# ============= 設定 =============

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CHATWORK_API_KEY = os.getenv("CHATWORK_API_KEY")
CHATWORK_ROOM_ID = os.getenv("CHATWORK_ROOM_ID")
SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")

# ============= Google Sheets API（requests のみ） =============

def get_access_token():
    """サービスアカウントから access token を取得"""
    try:
        credentials_dict = json.loads(SHEETS_CREDENTIALS_JSON)
        
        # JWT 作成
        import time
        import base64
        import hmac
        import hashlib
        
        header = {"alg": "RS256", "typ": "JWT"}
        now = int(time.time())
        payload = {
            "iss": credentials_dict["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + 3600,
            "iat": now
        }
        
        # Base64 エンコード
        header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        
        # 署名
        message = f"{header_encoded}.{payload_encoded}"
        private_key = credentials_dict["private_key"]
        signature = base64.urlsafe_b64encode(
            hmac.new(private_key.encode(), message.encode(), hashlib.sha256).digest()
        ).decode().rstrip('=')
        
        jwt = f"{message}.{signature}"
        
        # トークン取得
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt
            }
        )
        
        if response.status_code == 200:
            return response.json()["access_token"]
        else:
            print(f"Token 取得失敗: {response.text}")
            return None
    
    except Exception as e:
        print(f"Access Token 取得エラー: {e}")
        return None

def get_sheets_data(sheet_id: str, range_name: str):
    """Google Sheets からデータ取得（requests のみ）"""
    try:
        access_token = get_access_token()
        if not access_token:
            return None
        
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json().get('values', [])
        else:
            print(f"Sheets データ取得失敗: {response.text}")
            return None
    
    except Exception as e:
        print(f"Sheets データ取得エラー: {e}")
        return None

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
            if messages and len(messages) > 0:
                return messages[0]['body']
        return None
    except Exception as e:
        print(f"Chatwork メッセージ取得エラー: {e}")
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
        if response.status_code == 200:
            return True
        return False
    except Exception as e:
        print(f"Chatwork 投稿エラー: {e}")
        return False

# ============= Claude =============

def analyze_with_claude(user_instruction: str, sheet_data: dict = None):
    """Claude で分析・報告を生成"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    data_context = ""
    if sheet_data:
        data_context = f"\n【取得したデータ】\n{json.dumps(sheet_data, ensure_ascii=False)}"
    
    prompt = f"""
あなたは Enks 社の経理AI です。

【受け取った指示】
{user_instruction}
{data_context}

【やること】
この指示に応じて、入金チェックの報告を生成してください。

【報告フォーマット】
📊 [日付] 入金予実績チェック
✅ 全体：予測 ¥X 実績 ¥Y 乖離 ¥Z（±X%）

🔍 キャリア別：
  • キャリアA：予測¥X → 実績¥Y（乖離¥Z）
  • キャリアB：予測¥X → 実績¥Y（乖離¥Z）

🚨 要注視：[異常があれば記載、なければ「なし」]

上記のフォーマットで、報告を生成してください。
"""
    
    message = client.messages.create(
        model="claude-opus-4-20250805",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    return message.content[0].text

# ============= メイン =============

def main():
    print("\n" + "=" * 80)
    print(f"🤖 入金予測AIエージェント起動")
    print(f"📅 実行時刻：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    try:
        # ステップ1：Chatwork から最新メッセージを取得
        print("\n📥 ステップ1：Chatwork からメッセージを取得")
        message = get_latest_message_from_chatwork()
        
        if not message:
            print("⚠️  Chatwork にメッセージがありません")
            message = "テスト実行。Chatwork から指示をお待ちしています。"
        else:
            print(f"✅ メッセージ取得完了")
            print(f"   内容：{message[:100]}")
        
        # ステップ2：Claude で分析
        print("\n🤖 ステップ2：Claude で分析・報告生成")
        report = analyze_with_claude(message)
        
        print("\n【生成された報告】")
        print("-" * 80)
        print(report)
        print("-" * 80)
        
        # ステップ3：Chatwork に投稿
        print("\n💬 ステップ3：Chatwork に投稿")
        success = post_to_chatwork(report)
        
        if success:
            print("✅ 投稿完了")
        else:
            print("⚠️  投稿に失敗しました")
        
        print("\n" + "=" * 80)
        print("✅ 実行完了")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        
        # エラーを Chatwork に投稿
        try:
            error_msg = f"🚨 エラーが発生しました\n{str(e)}"
            post_to_chatwork(error_msg)
        except:
            pass

# ============= エントリーポイント =============

if __name__ == "__main__":
    main()
