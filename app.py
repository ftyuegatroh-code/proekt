import os
import requests
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-12345'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


# Модель пользователя
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    tasks = db.relationship('Task', backref='author', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Модель задачи
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attachment = db.Column(db.String(200))  # имя прикрепленного файла
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Создание таблиц
with app.app_context():
    db.create_all()


# Главная страница
@app.route('/')
def index():
    return render_template('index.html')


# Регистрация
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('Имя пользователя уже существует', 'danger')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Регистрация успешна! Теперь войдите', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


# Вход
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f'Добро пожаловать, {username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Неверное имя пользователя или пароль', 'danger')

    return render_template('login.html')


# Выход
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


# Дашборд (список задач)
@app.route('/dashboard')
@login_required
def dashboard():
    # Получаем все задачи текущего пользователя
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all()

    # Использование стороннего API (совет дня)
    try:
        response = requests.get('https://api.adviceslip.com/advice', timeout=5)
        advice = response.json()['slip']['advice'] if response.status_code == 200 else 'Будьте продуктивны!'
    except:
        advice = 'Не удалось получить совет'

    # Статистика
    total = len(tasks)
    completed = sum(1 for t in tasks if t.completed)

    return render_template('dashboard.html',
                           tasks=tasks,
                           advice=advice,
                           total=total,
                           completed=completed)


# Добавление задачи
@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    title = request.form.get('title')
    description = request.form.get('description', '')

    if not title:
        flash('Название задачи не может быть пустым', 'danger')
        return redirect(url_for('dashboard'))

    # Обработка загрузки файла
    attachment = None
    if 'attachment' in request.files:
        file = request.files['attachment']
        if file and file.filename:
            filename = secure_filename(file.filename)
            # Добавляем timestamp к имени
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_filename = f"{timestamp}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            attachment = unique_filename

    task = Task(title=title, description=description, attachment=attachment, user_id=current_user.id)
    db.session.add(task)
    db.session.commit()

    flash('Задача добавлена!', 'success')
    return redirect(url_for('dashboard'))


# Переключение статуса задачи
@app.route('/toggle_task/<int:task_id>')
@login_required
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('dashboard'))

    task.completed = not task.completed
    db.session.commit()

    status = "выполнена" if task.completed else "не выполнена"
    flash(f'Задача "{task.title}" отмечена как {status}', 'info')
    return redirect(url_for('dashboard'))


# Удаление задачи
@app.route('/delete_task/<int:task_id>')
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('dashboard'))

    # Удаляем прикрепленный файл если есть
    if task.attachment:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], task.attachment)
        if os.path.exists(file_path):
            os.remove(file_path)

    db.session.delete(task)
    db.session.commit()

    flash('Задача удалена', 'success')
    return redirect(url_for('dashboard'))


# Скачивание прикрепленного файла
@app.route('/download/<filename>')
@login_required
def download_file(filename):
    # Проверяем, принадлежит ли файл текущему пользователю
    task = Task.query.filter_by(attachment=filename, user_id=current_user.id).first()
    if not task:
        flash('Файл не найден или доступ запрещен', 'danger')
        return redirect(url_for('dashboard'))

    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)


# REST API - получение задач в JSON
@app.route('/api/tasks', methods=['GET'])
@login_required
def api_tasks():
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    tasks_list = [
        {
            'id': t.id,
            'title': t.title,
            'description': t.description,
            'completed': t.completed,
            'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'has_attachment': bool(t.attachment)
        }
        for t in tasks
    ]
    return jsonify({
        'status': 'success',
        'user': current_user.username,
        'tasks': tasks_list,
        'stats': {
            'total': len(tasks_list),
            'completed': sum(1 for t in tasks_list if t['completed'])
        }
    })


# Скачивание базы данных в CSV (альтернативное хранение данных)
@app.route('/export/csv')
@login_required
def export_csv():
    import csv
    from io import StringIO

    tasks = Task.query.filter_by(user_id=current_user.id).all()

    # Создаем CSV в памяти
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Title', 'Description', 'Completed', 'Created At', 'Has Attachment'])

    for task in tasks:
        writer.writerow([
            task.id,
            task.title,
            task.description,
            'Yes' if task.completed else 'No',
            task.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'Yes' if task.attachment else 'No'
        ])

    output.seek(0)

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=tasks_export.csv'}
    )


if __name__ == '__main__':
    app.run(debug=True)