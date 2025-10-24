import sqlite3

def assign_controller_to_document(document_id, controller_id=None):
    """Назначение нормоконтролера документу"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        if not controller_id:
            # Находим случайного нормоконтролера
            cursor.execute('SELECT id FROM users WHERE role = "controller" LIMIT 1')
            controller = cursor.fetchone()
            if controller:
                controller_id = controller[0]
        
        if controller_id:
            cursor.execute('''
                UPDATE documents 
                SET current_controller_id = ?
                WHERE id = ?
            ''', (controller_id, document_id))
            conn.commit()
            print(f"Документ {document_id} назначен нормоконтролеру {controller_id}")
        else:
            print("Нет доступных нормоконтролеров")
        
        conn.close()
        return controller_id
        
    except Exception as e:
        print(f"Ошибка при назначении нормоконтролера: {e}")
        return None

def reassign_all_documents():
    """Перераспределение всех документов между нормоконтролерами"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        # Получаем все документы, ожидающие проверки
        cursor.execute('''
            SELECT id FROM documents 
            WHERE status IN ('Нет замечаний', 'Исправлено')
        ''')
        documents = cursor.fetchall()
        
        # Получаем всех нормоконтролеров
        cursor.execute('SELECT id FROM users WHERE role = "controller"')
        controllers = cursor.fetchall()
        
        if not controllers:
            print("Нет нормоконтролеров в системе")
            return
        
        # Распределяем документы по кругу между нормоконтролерами
        for i, doc in enumerate(documents):
            controller_id = controllers[i % len(controllers)][0]
            cursor.execute('''
                UPDATE documents 
                SET current_controller_id = ?
                WHERE id = ?
            ''', (controller_id, doc[0]))
        
        conn.commit()
        conn.close()
        print(f"Перераспределено {len(documents)} документов между {len(controllers)} нормоконтролерами")
        
    except Exception as e:
        print(f"Ошибка при перераспределении: {e}")