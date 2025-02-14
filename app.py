from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import extract, func
import anthropic
import base64
import re
import os
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

# APIキーの取得と検証
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///kakeibo.db'
db = SQLAlchemy(app)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    income = db.Column(db.Integer, default=0)
    expense = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        income = int(request.form['income'])
        expense = int(request.form['expense'])
        
        new_entry = Entry(date=date, income=income, expense=expense)
        db.session.add(new_entry)
        db.session.commit()
        
        return redirect(url_for('index'))
    
    entries = Entry.query.order_by(Entry.date).all()
    return render_template('kakeibo.html', entries=entries)

@app.route('/edit/<int:id>', methods=['POST'])
def edit(id):
    entry = Entry.query.get_or_404(id)
    entry.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
    entry.income = int(request.form['income'])
    entry.expense = int(request.form['expense'])
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete(id):
    entry = Entry.query.get_or_404(id)
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/graph_data')
def graph_data():
    period = request.args.get('period', 'daily')
    
    if period == 'yearly':
        data = db.session.query(
            extract('year', Entry.date).label('period'),
            func.sum(Entry.income).label('income'),
            func.sum(Entry.expense).label('expense')
        ).group_by(extract('year', Entry.date)).order_by('period').all()
    elif period == 'monthly':
        data = db.session.query(
            func.strftime('%Y-%m', Entry.date).label('period'),
            func.sum(Entry.income).label('income'),
            func.sum(Entry.expense).label('expense')
        ).group_by(func.strftime('%Y-%m', Entry.date)).order_by('period').all()
    else:  # daily
        data = db.session.query(
            Entry.date.label('period'),
            func.sum(Entry.income).label('income'),
            func.sum(Entry.expense).label('expense')
        ).group_by(Entry.date).order_by(Entry.date).all()
    
    return jsonify({
        'labels': [str(row.period) for row in data],
        'income': [int(row.income) for row in data],
        'expense': [int(row.expense) for row in data]
    })

@app.route('/process_receipt', methods=['POST'])
def process_receipt():
    if 'image' not in request.files:
        return jsonify({'error': '画像が見つかりません'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': '画像が選択されていません'}), 400

    try:
        # 画像の読み込みとMIMEタイプの判定
        file_content = file.read()
        if file.filename.lower().endswith('.png'):
            media_type = 'image/png'
        elif file.filename.lower().endswith(('.jpg', '.jpeg')):
            media_type = 'image/jpeg'
        else:
            return jsonify({'error': '対応していない画像形式です。JPGまたはPNG形式の画像を使用してください。'}), 400

        # 画像をbase64エンコード
        image_data = base64.b64encode(file_content).decode('utf-8')
        
        # デバッグ情報
        app.logger.info(f"Processing image: {file.filename} ({media_type})")
        
        try:
            # Claude Vision APIの呼び出し
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            
            # メッセージの作成と送信
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "この画像はレシート、請求書、または見積書です。以下の情報を抽出してください：\n1. 日付（yyyy/mm/dd形式）\n2. 金額\n3. ドキュメントの種類（レシート、請求書、見積書）"
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data
                            }
                        }
                    ]
                }]
            )
        except anthropic.APIError as api_error:
            app.logger.error(f"Claude Vision API Error: {str(api_error)}")
            return jsonify({'error': f'Claude Vision API Error: {str(api_error)}'}), 500

        # レスポンスから情報を抽出
        response_text = message.content[0].text
        
        # 日付の抽出（yyyy/mm/dd形式を探す）
        date_match = re.search(r'\d{4}/\d{2}/\d{2}', response_text)
        extracted_date = date_match.group(0) if date_match else datetime.now().strftime('%Y/%m/%d')
        
        # 金額の抽出（数字の並びを探す）
        amount_match = re.search(r'金額[：:]\s*(\d+(?:,\d{3})*)', response_text)
        if amount_match:
            # カンマを除去して整数に変換
            amount = int(amount_match.group(1).replace(',', ''))
        else:
            # 数値のみのパターンを試す
            amount_match = re.search(r'(\d+(?:,\d{3})*)\s*円', response_text)
            amount = int(amount_match.group(1).replace(',', '')) if amount_match else 0
        
        # ドキュメントタイプの判定
        doc_type = None
        if '請求書' in response_text or '見積書' in response_text:
            income = amount
            expense = 0
        else:  # レシートとして扱う
            income = 0
            expense = amount

        return jsonify({
            'date': extracted_date or datetime.now().strftime('%Y-%m-%d'),
            'income': income,
            'expense': expense,
            'analysis': response_text
        })

    except Exception as e:
        app.logger.error(f"Error processing image: {str(e)}")
        return jsonify({'error': f'Error processing image: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5002)
