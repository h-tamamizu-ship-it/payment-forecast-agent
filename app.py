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
        
        # ✅ AI の返信（✅で始まる）に反応しない
        if message_body.startswith('✅'):
            print(f"⚠️ AI の返信をスキップ")
            return 'OK', 200
        
        # メッセージのハッシュ値を計算（重複排除用）
        message_hash = str(hash(message_body))
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 同じメッセージが既に処理されているか確認
        c.execute('SELECT id FROM messages WHERE message_hash = ?', (message_hash,))
        if c.fetchone():
            print(f"⚠️ 重複メッセージをスキップ")
            conn.close()
            return 'OK', 200
        
        print(f"📥 受信: {message_body}")
        
        prompt = f"経理分析AI として以下のメッセージに答えてください（簡潔に）：{message_body}"
        ai_response = call_claude_api(prompt)
        
        # DB に保存
        c.execute('INSERT INTO messages (timestamp, user_message, ai_response, message_hash) VALUES (?, ?, ?, ?)',
                  (datetime.now().isoformat(), message_body, ai_response, message_hash))
        conn.commit()
        conn.close()
        
        report = f"✅ {ai_response}"
        post_to_chatwork(report)
        
        return 'OK', 200
    
    except Exception as e:
        print(f"❌ エラー: {e}")
        traceback.print_exc()
        return 'Error', 500
