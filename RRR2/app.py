from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
import os
import uuid
import sqlite3
from werkzeug.utils import secure_filename

# Импортируем систему аутентификации
from auth import auth_system

# Импортируем Blueprint нормоконтроля
from normcontrol import normcontrol_bp

# Импортируем функционал из itog.py
from itog import doc_analyzer, rule_engine, allowed_file

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['STORAGE_FOLDER'] = 'storage'
app.config['SECRET_KEY'] = 'normcontrol-secret-key-2024-auth'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Создаем необходимые папки
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['STORAGE_FOLDER'], exist_ok=True)

# Регистрируем Blueprint нормоконтроля
app.register_blueprint(normcontrol_bp)

def get_controller_name(controller_id):
    """Получение имени нормоконтролёра по ID"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT first_name, last_name FROM users WHERE id = ?', (controller_id,))
        controller = cursor.fetchone()
        conn.close()
        
        if controller:
            return f"{controller[0]} {controller[1]}"
        return None
    except Exception as e:
        print(f"Ошибка при получении имени нормоконтролёра: {e}")
        return None

# Главная страница - редирект на аутентификацию
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('main_page'))
    return redirect(url_for('login'))

# Страница входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        result = auth_system.login_user(username, password)
        if result['success']:
            session['user_id'] = result['user']['id']
            session['user_data'] = result['user']
            return jsonify({'success': True, 'redirect': url_for('main_page')})
        else:
            return jsonify({'success': False, 'error': result['error']})
    
    return render_template('login.html')

# Страница регистрации
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role = request.form.get('role')
        
        result = auth_system.register_user(username, password, email, first_name, last_name, role)
        if result['success']:
            return jsonify({'success': True, 'message': 'Регистрация успешна! Теперь войдите в систему.'})
        else:
            return jsonify({'success': False, 'error': result['error']})
    
    return render_template('register.html')

# Главная страница приложения
@app.route('/main')
def main_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Получаем документы пользователя
    documents = auth_system.get_user_documents(session['user_id'], session['user_data']['role'])
    
    return render_template('main.html', 
                         user=session['user_data'],
                         documents=documents)

# Личный кабинет
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Получаем документы пользователя
    documents = auth_system.get_user_documents(session['user_id'], session['user_data']['role'])
    
    return render_template('profile.html', 
                         user=session['user_data'],
                         documents=documents)

# Страница истории загрузок
# История загрузок
@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Получаем документы пользователя
    documents = auth_system.get_user_documents(session['user_id'], session['user_data']['role'])
    
    return render_template('history.html', 
                         user=session['user_data'],
                         documents=documents,
                         get_controller_name=get_controller_name,
                         get_document_violations=get_document_violations)  # Добавляем новую функцию
# Анализ документа
@app.route('/analyze_document', methods=['POST'])
def analyze_document():
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
        
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
        
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': 'Требуется PDF-файл'}), 400

    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{filename}"
    
    # Временный путь для анализа
    temp_file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    # Постоянный путь для хранения
    storage_file_path = os.path.join(app.config['STORAGE_FOLDER'], unique_filename)
    
    file.save(temp_file_path)
    
    try:
        # Анализируем файл
        text_data = doc_analyzer.extract_text_from_pdf(temp_file_path)
        document_data = {'text_data': text_data}
        result = rule_engine.run_all_checks(document_data)
        
        # Определяем статус на основе результатов автоматической проверки
        has_violations = any(v['severity'] in ['high', 'medium'] for v in result['violations'])
        auto_status = 'Требует доработки' if has_violations else 'Нет замечаний'
        
        # Сохраняем файл в постоянное хранилище
        file.seek(0)  # Перемещаем указатель в начало файла
        file.save(storage_file_path)
        
        # Сохраняем документ в базу данных
        developer_name = f"{session['user_data']['first_name']} {session['user_data']['last_name']}"
        doc_result = auth_system.add_document(
            storage_file_path,
            filename, 
            session['user_id'], 
            developer_name,
            str(result)
        )
        
        if not doc_result['success']:
            raise Exception(doc_result['error'])

        # Если нет замечаний, назначаем нормоконтролера
        if auto_status == 'Нет замечаний':
            # Находим случайного нормоконтролера
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute('SELECT id, first_name, last_name FROM users WHERE role = "controller" LIMIT 1')
            controller = cursor.fetchone()
            
            if controller:
                controller_id, first_name, last_name = controller
                controller_name = f"{first_name} {last_name}"
                
                # Обновляем документ с назначением нормоконтролера
                cursor.execute('''
                    UPDATE documents 
                    SET current_controller_id = ?, status = 'Нет замечаний'
                    WHERE id = ?
                ''', (controller_id, doc_result['document_id']))
                conn.commit()
                print(f"✅ Документ {doc_result['document_id']} назначен нормоконтролеру {controller_name} (ID: {controller_id})")
            else:
                print("⚠️ Нет доступных нормоконтролеров")
            
            conn.close()
        
        # Удаляем временный файл
        os.remove(temp_file_path)
        
        return jsonify({
            'success': True,
            'result': result,
            'auto_status': auto_status,
            'document_id': doc_result['document_id']
        })
        
    except Exception as e:
        # Удаляем временные файлы в случае ошибки
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if os.path.exists(storage_file_path):
            os.remove(storage_file_path)
        return jsonify({'error': f'Ошибка анализа: {str(e)}'}), 500

# Скачивание документа
@app.route('/download_document/<int:document_id>')
def download_document(document_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    try:
        # Получаем информацию о документе из базы
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT filename, original_filename FROM documents WHERE id = ?', (document_id,))
        document = cursor.fetchone()
        conn.close()
        
        if not document:
            return jsonify({'error': 'Документ не найден'}), 404
        
        file_path = document[0]
        original_filename = document[1]
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Файл не найден на сервере'}), 404
        
        return send_file(file_path, as_attachment=True, download_name=original_filename)
        
    except Exception as e:
        return jsonify({'error': f'Ошибка загрузки: {str(e)}'}), 500

# Просмотр документа
@app.route('/view_document/<int:document_id>')
def view_document(document_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    try:
        # Получаем информацию о документе из базы
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM documents WHERE id = ?', (document_id,))
        document = cursor.fetchone()
        conn.close()
        
        if not document:
            return jsonify({'error': 'Документ не найден'}), 404
        
        file_path = document[0]
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Файл не найден на сервере'}), 404
        
        return send_file(file_path)
        
    except Exception as e:
        return jsonify({'error': f'Ошибка загрузки: {str(e)}'}), 500

# Обновление статуса документа
@app.route('/update_document_status', methods=['POST'])
def update_document_status():
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    document_id = request.form.get('document_id')
    new_status = request.form.get('new_status')
    notes = request.form.get('notes', '')
    
    user_name = f"{session['user_data']['first_name']} {session['user_data']['last_name']}"
    
    result = auth_system.update_document_status(
        document_id, 
        new_status, 
        session['user_id'], 
        user_name, 
        notes
    )
    
    if result['success']:
        return jsonify({'success': True, 'message': 'Статус обновлен'})
    else:
        return jsonify({'success': False, 'error': result['error']})

# Получение истории статусов документа
@app.route('/document_history/<int:document_id>')
def document_history(document_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    history = auth_system.get_document_status_history(document_id)
    return jsonify({'success': True, 'history': history})

# Замена документа (для повторной загрузки исправленной версии)
@app.route('/replace_document/<int:document_id>', methods=['POST'])
def replace_document(document_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
        
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
        
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': 'Требуется PDF-файл'}), 400
    
    try:
        # Получаем информацию о старом документе
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT filename, developer_id, status FROM documents WHERE id = ?', (document_id,))
        old_doc = cursor.fetchone()
        
        if not old_doc:
            return jsonify({'error': 'Документ не найден'}), 404
            
        # Проверяем, что пользователь - владелец документа
        if old_doc[1] != session['user_id']:
            return jsonify({'error': 'Нет прав для замены этого документа'}), 403
            
        # Проверяем, что документ требует доработки или имеет замечания
        if old_doc[2] != 'Требует доработки':
            return jsonify({'error': 'Документ не требует доработки'}), 400
            
        old_file_path = old_doc[0]
        
        # Создаем новое имя файла
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        new_file_path = os.path.join(app.config['STORAGE_FOLDER'], unique_filename)
        
        # Сохраняем новый файл
        file.save(new_file_path)
        
        # Анализируем новый файл
        text_data = doc_analyzer.extract_text_from_pdf(new_file_path)
        document_data = {'text_data': text_data}
        result = rule_engine.run_all_checks(document_data)
        
        # Определяем статус на основе результатов автоматической проверки
        has_violations = any(v['severity'] in ['high', 'medium'] for v in result['violations'])
        auto_status = 'Нет замечаний' if not has_violations else 'Исправлено'
        
        # Если нет замечаний, назначаем нормоконтролера
        controller_id = None
        if auto_status == 'Нет замечаний':
            cursor.execute('SELECT id FROM users WHERE role = "controller" LIMIT 1')
            controller = cursor.fetchone()
            if controller:
                controller_id = controller[0]
        
        # Обновляем запись в базе данных
        cursor.execute('''
            UPDATE documents 
            SET filename = ?, original_filename = ?, status = ?, 
                status_change_count = status_change_count + 1, last_status_change = CURRENT_TIMESTAMP,
                auto_check_result = ?, current_controller_id = ?
            WHERE id = ?
        ''', (new_file_path, filename, auto_status, str(result), controller_id, document_id))
        
        # Добавляем запись в историю
        user_name = f"{session['user_data']['first_name']} {session['user_data']['last_name']}"
        notes = request.form.get('notes', '')
        history_notes = f"Загружена исправленная версия документа. Автопроверка: {auto_status}."
        if notes:
            history_notes += f" Комментарий разработчика: {notes}"
            
        cursor.execute('''
            INSERT INTO document_status_history 
            (document_id, status, changed_by, changed_by_name, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (document_id, auto_status, session['user_id'], user_name, history_notes))
        
        # Удаляем старый файл
        if os.path.exists(old_file_path):
            os.remove(old_file_path)
            
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Исправленная версия документа успешно загружена. Статус: {auto_status}',
            'auto_status': auto_status
        })
        
    except Exception as e:
        # Удаляем новый файл в случае ошибки
        if 'new_file_path' in locals() and os.path.exists(new_file_path):
            os.remove(new_file_path)
        return jsonify({'error': f'Ошибка замены документа: {str(e)}'}), 500


# Добавьте эту функцию в app.py после функции get_controller_name

def get_document_violations(document_id):
    """Получение информации о нарушениях документа"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT auto_check_result FROM documents WHERE id = ?', (document_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            import ast
            try:
                # Парсим результат автоматической проверки
                check_result = ast.literal_eval(result[0])
                return check_result.get('violations', [])
            except:
                return []
        return []
    except Exception as e:
        print(f"Ошибка при получении информации о нарушениях: {e}")
        return []
# Добавьте этот маршрут в app.py

# Получение информации об ошибках документа
@app.route('/document_violations/<int:document_id>')
def document_violations(document_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    try:
        violations = get_document_violations(document_id)
        return jsonify({'success': True, 'violations': violations})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
# Выход из системы
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    print("🎯 NormControl с системой хранения файлов запущен!")
    print("📁 Файлы сохраняются в папку 'storage'")
    print("🔐 Доступны регистрация и вход")
    app.run(host='0.0.0.0', port=5000, debug=True)