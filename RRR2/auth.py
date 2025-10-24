import sqlite3
import hashlib
import os
from datetime import datetime

class AuthSystem:
    def __init__(self, db_path='users.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('developer', 'controller')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица документов с расширенной информацией
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                developer_id INTEGER NOT NULL,
                developer_name TEXT NOT NULL,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'На проверке',
                auto_check_result TEXT,
                developer_correction_time INTEGER DEFAULT 0, -- в часах
                controller_review_time INTEGER DEFAULT 0, -- в часах
                status_change_count INTEGER DEFAULT 0,
                current_controller_id INTEGER,
                last_status_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (developer_id) REFERENCES users (id),
                FOREIGN KEY (current_controller_id) REFERENCES users (id)
            )
        ''')
        
        # Таблица истории статусов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                changed_by INTEGER NOT NULL,
                changed_by_name TEXT NOT NULL,
                change_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (document_id) REFERENCES documents (id),
                FOREIGN KEY (changed_by) REFERENCES users (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def hash_password(self, password):
        """Хеширование пароля"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def register_user(self, username, password, email, first_name, last_name, role):
        """Регистрация нового пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            hashed_password = self.hash_password(password)
            
            cursor.execute('''
                INSERT INTO users (username, password, email, first_name, last_name, role)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (username, hashed_password, email, first_name, last_name, role))
            
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            
            return {'success': True, 'user_id': user_id}
            
        except sqlite3.IntegrityError as e:
            return {'success': False, 'error': 'Пользователь с таким логином или email уже существует'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def login_user(self, username, password):
        """Авторизация пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            hashed_password = self.hash_password(password)
            
            cursor.execute('''
                SELECT id, username, email, first_name, last_name, role 
                FROM users 
                WHERE username = ? AND password = ?
            ''', (username, hashed_password))
            
            user = cursor.fetchone()
            conn.close()
            
            if user:
                return {
                    'success': True,
                    'user': {
                        'id': user[0],
                        'username': user[1],
                        'email': user[2],
                        'first_name': user[3],
                        'last_name': user[4],
                        'role': user[5]
                    }
                }
            else:
                return {'success': False, 'error': 'Неверный логин или пароль'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def add_document(self, filename, original_filename, developer_id, developer_name, auto_check_result):
        """Добавление нового документа"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Определяем начальный статус на основе результатов автоматической проверки
            # Если есть замечания - ставим "Требует доработки", если нет - "Нет замечаний"
            has_violations = 'high' in auto_check_result or 'medium' in auto_check_result
            initial_status = 'Требует доработки' if has_violations else 'Нет замечаний'
            
            cursor.execute('''
                INSERT INTO documents 
                (filename, original_filename, developer_id, developer_name, auto_check_result, status, status_change_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (filename, original_filename, developer_id, developer_name, auto_check_result, initial_status))
            
            document_id = cursor.lastrowid
            
            # Добавляем запись в историю статусов
            cursor.execute('''
                INSERT INTO document_status_history 
                (document_id, status, changed_by, changed_by_name, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (document_id, initial_status, developer_id, developer_name, 'Документ загружен'))
            
            conn.commit()
            conn.close()
            
            return {'success': True, 'document_id': document_id}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def update_document_status(self, document_id, new_status, user_id, user_name, notes=None):
        """Обновление статуса документа"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Получаем текущий статус и время последнего изменения
            cursor.execute('SELECT status, last_status_change FROM documents WHERE id = ?', (document_id,))
            result = cursor.fetchone()
            current_status = result[0]
            last_status_change = result[1]
            
            # Обновляем документ
            cursor.execute('''
                UPDATE documents 
                SET status = ?, status_change_count = status_change_count + 1, last_status_change = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_status, document_id))
            
            # Добавляем запись в историю
            cursor.execute('''
                INSERT INTO document_status_history 
                (document_id, status, changed_by, changed_by_name, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (document_id, new_status, user_id, user_name, notes))
            
            # Вычисляем время в ЧАСАХ с дробной частью
            if current_status == 'Требует доработки' and new_status == 'Исправлено':
                cursor.execute('''
                    SELECT (julianday(CURRENT_TIMESTAMP) - julianday(?)) * 24
                ''', (last_status_change,))
                correction_hours = cursor.fetchone()[0]
                cursor.execute('''
                    UPDATE documents SET developer_correction_time = ?
                    WHERE id = ?
                ''', (correction_hours, document_id))
            
            # Если нормоконтролер отклоняет документ - ставим статус "Требует доработки"
            if new_status == 'Отклонено':
                cursor.execute('''
                    SELECT (julianday(CURRENT_TIMESTAMP) - julianday(?)) * 24
                ''', (last_status_change,))
                review_hours = cursor.fetchone()[0]
                cursor.execute('''
                    UPDATE documents SET controller_review_time = ?, current_controller_id = ?, status = 'Требует доработки'
                    WHERE id = ?
                ''', (review_hours, user_id, document_id))
                
                # Добавляем автоматическую запись в историю о возврате разработчику
                cursor.execute('''
                    INSERT INTO document_status_history 
                    (document_id, status, changed_by, changed_by_name, notes)
                    VALUES (?, ?, ?, ?, ?)
                ''', (document_id, 'Требует доработки', user_id, user_name, 'Документ отклонен и требует повторной загрузки'))
            
            # Если нормоконтролер согласовывает или снимает документ
            elif new_status in ['Согласовано', 'Снято']:
                cursor.execute('''
                    SELECT (julianday(CURRENT_TIMESTAMP) - julianday(?)) * 24
                ''', (last_status_change,))
                review_hours = cursor.fetchone()[0]
                cursor.execute('''
                    UPDATE documents SET controller_review_time = ?, current_controller_id = ?
                    WHERE id = ?
                ''', (review_hours, user_id, document_id))
            
            conn.commit()
            conn.close()
            
            return {'success': True}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    def get_user_documents(self, user_id, user_role):
        """Получение документов пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if user_role == 'developer':
                # Разработчик видит все свои документы
                cursor.execute('''
                    SELECT * FROM documents 
                    WHERE developer_id = ? 
                    ORDER BY upload_date DESC
                ''', (user_id,))
            else:  # controller
                # Нормоконтролёр видит ВСЕ документы со статусами "Нет замечаний" и "Исправлено"
                # (не только те, что ему назначены)
                cursor.execute('''
                    SELECT * FROM documents 
                    WHERE status IN ('Нет замечаний', 'Исправлено')
                    ORDER BY upload_date DESC
                ''')
            
            documents = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'id': doc[0],
                    'filename': doc[1],
                    'original_filename': doc[2],
                    'developer_id': doc[3],
                    'developer_name': doc[4],
                    'upload_date': doc[5],
                    'status': doc[6],
                    'auto_check_result': doc[7],
                    'developer_correction_time': doc[8],
                    'controller_review_time': doc[9],
                    'status_change_count': doc[10],
                    'current_controller_id': doc[11],
                    'last_status_change': doc[12]
                }
                for doc in documents
            ]
        except Exception as e:
            print(f"Ошибка при получении документов: {e}")
            return []
    def get_document_status_history(self, document_id):
        """Получение истории статусов документа"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT status, changed_by_name, change_date, notes 
                FROM document_status_history 
                WHERE document_id = ? 
                ORDER BY change_date
            ''', (document_id,))
            
            history = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'status': item[0],
                    'changed_by': item[1],
                    'change_date': item[2],
                    'notes': item[3]
                }
                for item in history
            ]
        except Exception as e:
            print(f"Ошибка при получении истории: {e}")
            return []

# Создаем глобальный экземпляр системы аутентификации
auth_system = AuthSystem()