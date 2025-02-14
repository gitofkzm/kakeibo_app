from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import extract, func

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

if __name__ == '__main__':
    app.run(debug=True, port=5002)
