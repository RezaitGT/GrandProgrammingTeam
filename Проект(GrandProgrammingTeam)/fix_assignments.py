import sqlite3

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
            print("❌ Нет нормоконтролеров в системе!")
            return
        
        print(f"📋 Найдено документов: {len(documents)}")
        print(f"👥 Найдено нормоконтролеров: {len(controllers)}")
        
        # Распределяем документы по кругу между нормоконтролерами
        for i, doc in enumerate(documents):
            controller_id = controllers[i % len(controllers)][0]
            cursor.execute('''
                UPDATE documents 
                SET current_controller_id = ?
                WHERE id = ?
            ''', (controller_id, doc[0]))
            print(f"✅ Документ {doc[0]} назначен нормоконтролеру {controller_id}")
        
        conn.commit()
        conn.close()
        print(f"🎉 Перераспределено {len(documents)} документов между {len(controllers)} нормоконтролерами")
        
    except Exception as e:
        print(f"❌ Ошибка при перераспределении: {e}")

if __name__ == '__main__':
    print("🔄 Перераспределение документов между нормоконтролерами...")
    reassign_all_documents()
    print("✅ Готово!")