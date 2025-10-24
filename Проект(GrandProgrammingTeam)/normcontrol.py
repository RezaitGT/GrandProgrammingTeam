from flask import Blueprint, jsonify, request
import os
import uuid
from werkzeug.utils import secure_filename
from itog import doc_analyzer, rule_engine, allowed_file

# Создаем Blueprint для нормоконтроля
normcontrol_bp = Blueprint('normcontrol', __name__)

@normcontrol_bp.route('/analyze', methods=['POST'])
def analyze_document():
    """Эндпоинт для анализа документа"""
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
        
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': 'Требуется PDF-файл'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join('uploads', f"{uuid.uuid4()}_{filename}")
    file.save(file_path)
    
    try:
        text_data = doc_analyzer.extract_text_from_pdf(file_path)
        document_data = {'text_data': text_data}
        result = rule_engine.run_all_checks(document_data)
        
        os.remove(file_path)
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'error': f'Ошибка анализа: {str(e)}'}), 500