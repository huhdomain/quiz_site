import sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session
import random
import os
import json
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # 실제 서비스에서는 더 강력한 키를 사용하세요.

DATABASE = 'database.db'
QUIZ_FILE = 'quiz.xlsx'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)", ('홍길동', '1111'))
        db.commit()
    print("Database initialized and default user added.")

def load_quiz_data():
    if not os.path.exists(QUIZ_FILE):
        print(f"Error: {QUIZ_FILE} not found. Please ensure the quiz file exists.")
        return pd.DataFrame() # Return empty DataFrame
    try:
        df = pd.read_excel(QUIZ_FILE)
        return df
    except Exception as e:
        print(f"Error loading quiz file: {e}")
        return pd.DataFrame()

# Import global object for get_db
from flask import g

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()
        user = cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if user:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('quiz'))
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    quiz_df = load_quiz_data()
    if quiz_df.empty:
        return "문제 파일을 불러올 수 없습니다. quiz.xlsx 파일을 확인해주세요."

    if 'quiz_state' not in session:
        session['quiz_state'] = {
            'questions': random.sample(quiz_df.index.tolist(), min(5, len(quiz_df))),
            'current_question_index': 0,
            'user_answers': []
        }

    quiz_state = session['quiz_state']
    current_index = quiz_state['current_question_index']

    if request.method == 'POST':
        user_answer = request.form.get('answer')
        if user_answer:
            quiz_state['user_answers'].append(user_answer)
        quiz_state['current_question_index'] += 1
        session['quiz_state'] = quiz_state # Update session after modification

    if quiz_state['current_question_index'] < len(quiz_state['questions']):
        question_index = quiz_state['questions'][quiz_state['current_question_index']]
        question_data = quiz_df.loc[question_index]
        question_text = question_data['문제']
        options = [question_data[f'보기{chr(96 + i)}'] for i in range(1, 5) if pd.notna(question_data[f'보기{chr(96 + i)}'])]
        # random.shuffle(options) # Shuffle options - 사용자가 요청한 대로 순서 유지
        is_last_question = (quiz_state['current_question_index'] == len(quiz_state['questions']) - 1)
        return render_template('quiz.html', question=question_text, options=options, current_question_number=current_index + 1, total_questions=len(quiz_state['questions']), is_last_question=is_last_question)
    else:
        return redirect(url_for('result'))

@app.route('/result')
def result():
    if not session.get('logged_in') or 'quiz_state' not in session:
        return redirect(url_for('login'))

    quiz_df = load_quiz_data()
    if quiz_df.empty:
        return "문제 파일을 불러올 수 없습니다. quiz.xlsx 파일을 확인해주세요."

    quiz_state = session['quiz_state']
    results = []
    correct_count = 0

    for i, q_idx in enumerate(quiz_state['questions']):
        question_data = quiz_df.loc[q_idx]
        user_answer = quiz_state['user_answers'][i] if i < len(quiz_state['user_answers']) else "응답 없음"
        correct_answer = str(question_data['정답'])
        explanation = question_data['해설']

        # Compare only the first character of the answer after stripping whitespace and converting to lowercase
        is_correct = (str(user_answer).strip().lower()[0] == correct_answer.strip().lower()[0]) if user_answer and correct_answer else False
        if is_correct:
            correct_count += 1
        
        results.append({
            'question': question_data['문제'],
            'user_answer': user_answer,
            'correct_answer': correct_answer,
            'explanation': explanation,
            'is_correct': is_correct
        })
    
    # Save quiz results to JSON file
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    username = session.get('username', 'unknown_user')
    
    result_data = []
    for res in results:
        result_data.append({
            '일시': timestamp,
            '이름': username,
            '문제': res['question'],
            '답변': res['user_answer'],
            '정답': res['correct_answer'],
            'OX': 'O' if res['is_correct'] else 'X',
            '해설': res['explanation']
        })

    result_file_path = os.path.join('result', f'{username}.json')
    
    # Read existing data if file exists, then append new data
    existing_data = []
    if os.path.exists(result_file_path):
        try:
            with open(result_file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = [] # Handle empty or invalid JSON file

    if isinstance(existing_data, list):
        existing_data.extend(result_data)
    else: # If existing_data is not a list (e.g., single dict), convert to list and extend
        existing_data = [existing_data] if existing_data else []
        existing_data.extend(result_data)

    # Ensure the result directory exists
    os.makedirs(os.path.dirname(result_file_path), exist_ok=True)

    with open(result_file_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=4)
    
    session.pop('quiz_state', None) # Reset quiz state after showing results

    return render_template('result.html', results=results, correct_count=correct_count, total_questions=len(quiz_state['questions']))

if __name__ == '__main__':
    init_db()
    app.run(debug=True) 