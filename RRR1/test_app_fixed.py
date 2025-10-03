from flask import Flask, render_template, request, jsonify
import os
import uuid
import io
from werkzeug.utils import secure_filename
import re
from datetime import datetime
from PIL import Image
from typing import List, Dict, Any

# Попробуем импортировать PyMuPDF, если нет - используем pdfplumber
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
    print("✅ PyMuPDF доступен")
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("⚠️ PyMuPDF не установлен, используется pdfplumber")

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
    print("✅ PDFPlumber доступен")
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    print("⚠️ PDFPlumber не установлен")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = 'normcontrol-secret-key-2024'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# =============================================================================
# CONFIG - Правила из ТЗ
# =============================================================================
class Config:
    TZ_RULES = {
        "title_block": {
            "rule_1.1.1": "Проверка заполнения основной надписи в части заполнения графы 1 (наименования изделия и наименования документа, если этому документу присвоен код и соответствие этого кода наименованию документа)",
            "rule_1.1.3": "Проверка наличия указанных буквенных обозначений в технических требованиях и на поле чертежа",
            "rule_1.1.4": "Проверка наличия '*', '**', '***' в технических требованиях чертежа и на его поле (любой формат и на любом листе чертежа)"
        }
    }

# =============================================================================
# DOCUMENT ANALYZER - УЛУЧШЕННАЯ ВЕРСИЯ С РАЗБИВКОЙ НА БЛОКИ
# =============================================================================
class DocumentAnalyzer:
    """
    Анализатор PDF документов для проверки требований ТЗ
    """
    
    def __init__(self):
        # Полный словарь кодов документов из ТЗ
        self.document_codes = {
            # Чертежи
            'СБ': 'Сборочный чертеж',
            'ВО': 'Чертеж общего вида', 
            'ТЧ': 'Теоретический чертеж',
            'ГЧ': 'Габаритный чертеж',
            'МЭ': 'Электромонтажный чертеж',
            'МЧ': 'Монтажный чертеж',
            'УЧ': 'Упаковочный чертеж',
            
            # Ведомости
            'ВС': 'Ведомость спецификаций',
            'ВД': 'Ведомость ссылочных документов',
            'ВП': 'Ведомость покупных изделий',
            'ВИ': 'Ведомость разрешения применения покупных изделий',
            'ДП': 'Ведомость держателей подлинников',
            'ПТ': 'Ведомость технического предложения',
            'ЭП': 'Ведомость эскизного проекта',
            'ТП': 'Ведомость технического проекта',
            'ВДЭ': 'Ведомость электронных документов',
            
            # Техническая документация
            'ПЗ': 'Пояснительная записка',
            'ТУ': 'Технические условия',
            'ПМ': 'Программа и методика испытаний',
            'ТБ': 'Таблицы',
            'РР': 'Расчеты',
            'РЭ': 'Руководство по эксплуатации',
            'ИМ': 'Инструкция по монтажу, пуску, регулированию и обкатке изделия',
            'ФО': 'Формуляр',
            'ПС': 'Паспорт',
            'ЭТ': 'Этикетка',
            'КИ': 'Каталог изделия',
            'НЗЧ': 'Нормы расхода запасных частей',
            'НМ': 'Нормы расхода материалов',
            'ЗИ': 'Ведомость ЗИП',
            'УП': 'Учебно-технические плакаты',
            'ИС': 'Инструкции эксплуатационные специальные',
            'ВЭ': 'Ведомость эксплуатационных документов',
            
            # Ремонтная документация
            'РК': 'Руководство по ремонту',
            'РС': 'Руководство по ремонту',
            'УК': 'Технические условия на ремонт',
            'УС': 'Технические условия на ремонт',
            'ЗК': 'Нормы расхода запасных частей на ремонт',
            'ЗС': 'Нормы расхода запасных частей на ремонт',
            'МК': 'Нормы расхода материалов на ремонт',
            'МС': 'Нормы расхода материалов на ремонт',
            'ЗИК': 'Ведомость ЗИП на ремонт',
            'ЗИС': 'Ведомость ЗИП на ремонт',
            'ВРК': 'Ведомость документов для ремонта',
            'ВРС': 'Ведомость документов для ремонта'
        }
        
        self.scheme_codes = {
            # Электрические схемы
            'Э1': 'Схема электрическая структурная',
            'Э2': 'Схема электрическая функциональная', 
            'Э3': 'Схема электрическая принципиальная',
            'Э4': 'Схема электрическая соединений',
            'Э5': 'Схема электрическая подключения',
            'Э6': 'Схема электрическая общая',
            'Э7': 'Схема электрическая расположения',
            
            # Гидравлические схемы
            'Г1': 'Схема гидравлическая структурная',
            'Г3': 'Схема гидравлическая принципиальная',
            'Г4': 'Схема гидравлическая соединения',
            
            # Пневматические схемы
            'П1': 'Схема пневматическая структурная',
            'П3': 'Схема пневматическая принципиальная', 
            'П4': 'Схема пневматическая соединения',
            
            # Газовые схемы
            'Х1': 'Схема газовая структурная',
            'Х3': 'Схема газовая принципиальная',
            'Х4': 'Схема газовая соединения',
            
            # Кинематические схемы
            'К1': 'Схема кинематическая структурная',
            'К2': 'Схема кинематическая функциональная',
            'К3': 'Схема кинематическая принципиальная',
            
            # Вакуумные схемы
            'В1': 'Схема вакуумная структурная',
            'В3': 'Схема вакуумная принципиальная',
            'В4': 'Схема вакуумная соединений',
            
            # Оптические схемы
            'Л3': 'Схема оптическая принципиальная',
            
            # Энергетические схемы
            'Р1': 'Схема энергетическая структурная',
            'Р2': 'Схема энергетическая функциональная',
            'Р3': 'Схема энергетическая принципиальная',
            'Р4': 'Схема энергетическая соединений',
            'Р5': 'Схема энергетическая подключения',
            'Р6': 'Схема энергетическая общая',
            'Р7': 'Схема энергетическая расположения'
        }
    
    def get_all_document_codes(self) -> dict:
        """Возвращает все коды документов для проверки"""
        return {**self.document_codes, **self.scheme_codes}
    
    def extract_text_from_pdf(self, pdf_path: str) -> dict:
        """
        Основной метод извлечения текста из PDF с разбивкой на блоки
        """
        print(f"\n🔍 ИЗВЛЕЧЕНИЕ ТЕКСТА ИЗ PDF С РАЗБИВКОЙ НА БЛОКИ")
        print("=" * 80)
        
        text_data = self._try_extraction_methods(pdf_path)
        
        # РАЗБИВАЕМ НА БЛОКИ
        text_data = self._split_into_blocks(text_data)
        
        self._print_detailed_content(text_data)
        
        print("=" * 80)
        print("✅ ИЗВЛЕЧЕНИЕ ТЕКСТА С РАЗБИВКОЙ НА БЛОКИ ЗАВЕРШЕНО")
        print("=" * 80)
        
        return text_data
    
    def _split_into_blocks(self, text_data: dict) -> dict:
        """
        Разбивает текст на блоки: чертеж, описание, структура
        """
        print("\n📋 РАЗБИВКА ДОКУМЕНТА НА БЛОКИ:")
    
        all_text = ""
        for page in text_data.get('pages', []):
            all_text += page.get('text', '') + "\n"
    
        # Инициализируем блоки
        drawing_block = ""
        description_block = ""
        structure_block = ""
    
        lines = all_text.split('\n')
    
        # Находим индексы ключевых маркеров
        massa_index = -1
        id_version_index = -1
    
        for i, line in enumerate(lines):
            line_clean = line.strip()
        
            if "Масса" in line_clean and massa_index == -1:
                massa_index = i
                print(f"📍 Найден маркер 'Масса' в строке {i + 1}")
        
            if "ID версии:" in line_clean and id_version_index == -1:
                id_version_index = i
                print(f"📍 Найден маркер 'ID версии:' в строке {i + 1}")
    
        # Распределяем по блокам
        if massa_index != -1 and id_version_index != -1:
            # Чертеж: всё ДО "Масса"
            drawing_block = "\n".join(lines[:massa_index]).strip()
        
            # Структура: между "Масса" и "ID версии:"
            structure_block = "\n".join(lines[massa_index:id_version_index]).strip()
        
            # Описание: всё ПОСЛЕ "ID версии:"
            description_block = "\n".join(lines[id_version_index:]).strip()
        
            print("✅ Успешное разделение на все три блока")
        
        elif massa_index != -1:
            # Есть только "Масса", но нет "ID версии:"
            drawing_block = "\n".join(lines[:massa_index]).strip()
            structure_block = "\n".join(lines[massa_index:]).strip()
            print("⚠️ Маркер 'ID версии:' не найден, описание пустое")
        
        elif id_version_index != -1:
            # Есть только "ID версии:", но нет "Масса"
            drawing_block = "\n".join(lines[:id_version_index]).strip()
            description_block = "\n".join(lines[id_version_index:]).strip()
            print("⚠️ Маркер 'Масса' не найден, структура пустая")
        
        else:
            # Нет маркеров - весь текст в чертеж
            drawing_block = all_text.strip()
            print("⚠️ Маркеры 'Масса' и 'ID версии:' не найдены")
    
        # Добавляем блоки в text_data
        text_data['blocks'] = {
            'drawing': drawing_block,
            'description': description_block,
            'structure': structure_block
        }
    
        # Статистика по блокам
        print(f"📊 СТАТИСТИКА БЛОКОВ:")
        print(f"   Чертеж: {len(drawing_block)} символов, {len(drawing_block.split())} слов")
        print(f"   Описание: {len(description_block)} символов, {len(description_block.split())} слов") 
        print(f"   Структура: {len(structure_block)} символов, {len(structure_block.split())} слов")
    
        # Показываем содержимое блоков для отладки
        if drawing_block:
            print(f"\n📐 СОДЕРЖИМОЕ ЧЕРТЕЖА (первые 200 символов):")
            print(f"   {drawing_block[:200]}...")
    
        if structure_block:
            print(f"\n🏗️ СОДЕРЖИМОЕ СТРУКТУРЫ (первые 200 символов):")
            print(f"   {structure_block[:200]}...")
    
        if description_block:
            print(f"\n📝 СОДЕРЖИМОЕ ОПИСАНИЯ (первые 200 символов):")
            print(f"   {description_block[:200]}...")
    
        return text_data
    
    def _try_extraction_methods(self, pdf_path: str) -> dict:
        """Попробовать разные методы извлечения текста"""
        methods = [
            ("PyMuPDF", self._extract_with_pymupdf),
            ("PDFPlumber", self._extract_with_pdfplumber),
        ]
        
        for method_name, method_func in methods:
            print(f"🔄 Попытка метода: {method_name}")
            try:
                text_data = method_func(pdf_path)
                if self._has_significant_text(text_data):
                    print(f"✅ {method_name} успешно извлек текст")
                    return text_data
            except Exception as e:
                print(f"❌ {method_name} ошибка: {e}")
        
        print("❌ Методы извлечения текста не сработали")
        return self._create_empty_text_data()
    
    def _extract_with_pymupdf(self, pdf_path: str) -> dict:
        """Извлечение текста с использованием PyMuPDF"""
        doc = fitz.open(pdf_path)
        text_data = {
            'pages': [],
            'metadata': doc.metadata,
            'total_pages': doc.page_count,
            'extraction_method': 'PyMuPDF'
        }
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            
            page_data = {
                'page_number': page_num + 1,
                'text': text,
                'blocks': [],
                'width': page.rect.width,
                'height': page.rect.height,
            }
            
            text_data['pages'].append(page_data)
        
        doc.close()
        return text_data
    
    def _extract_with_pdfplumber(self, pdf_path: str) -> dict:
        """Извлечение текста с использованием PDFPlumber"""
        text_data = {
            'pages': [],
            'total_pages': 0,
            'extraction_method': 'PDFPlumber'
        }
        
        with pdfplumber.open(pdf_path) as pdf:
            text_data['total_pages'] = len(pdf.pages)
            text_data['metadata'] = {
                'producer': getattr(pdf.metadata, 'producer', ''),
                'creator': getattr(pdf.metadata, 'creator', ''),
            }
            
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                
                page_data = {
                    'page_number': page_num + 1,
                    'text': text,
                    'blocks': [],
                    'width': page.width,
                    'height': page.height,
                }
                text_data['pages'].append(page_data)
        
        return text_data
    
    def _print_detailed_content(self, text_data: dict):
        """Вывод всего содержимого PDF"""
        print(f"📊 ОБЩАЯ ИНФОРМАЦИЯ:")
        print(f"   Страниц: {text_data.get('total_pages', 0)}")
        
        for page in text_data.get('pages', []):
            page_text = page.get('text', '').strip()
            
            print(f"\n📄 СТРАНИЦА {page['page_number']}:")
            print("-" * 60)
            
            if page_text:
                print(page_text)
            else:
                print("[ТЕКСТ ОТСУТСТВУЕТ]")
            
            print("-" * 60)
    
    def _has_significant_text(self, text_data: dict) -> bool:
        """Проверка наличия значимого текста"""
        total_chars = 0
        for page in text_data.get('pages', []):
            total_chars += len(page.get('text', ''))
        return total_chars > 10
    
    def _create_empty_text_data(self) -> dict:
        """Создание пустой структуры данных"""
        return {
            'pages': [],
            'total_pages': 0,
            'metadata': {},
            'extraction_method': 'None',
            'blocks': {
                'drawing': '',
                'description': '', 
                'structure': ''
            }
        }

# =============================================================================
# RULE ENGINE - ОБНОВЛЕННАЯ ВЕРСИЯ БЕЗ 1.1.2
# =============================================================================
class RuleEngine:
    def __init__(self):
        self.tz_rules = Config.TZ_RULES
        self.document_analyzer = DocumentAnalyzer()
        
    def check_title_block_requirements(self, text_data: dict) -> list:
        """
        1.1.1 Проверка заполнения основной надписи в части заполнения графы 1
        (наименования изделия и наименования документа, если этому документу присвоен код 
        и соответствие этого кода наименованию документа)
        """
        print(f"\n🔍 ПРОВЕРКА 1.1.1: ОСНОВНАЯ НАДПИСЬ - ГРАФА 1")
        print("=" * 60)
        
        violations = []
        all_text = ""
        for page in text_data.get('pages', []):
            all_text += page.get('text', '') + "\n"
        
        print(f"📊 Анализ текста: {len(all_text)} символов")
        
        # Поиск кода документа в формате РНАТ.301276.001СБ или АБВГ.123456.002
        document_code_match = re.search(r'[А-Я]{2,4}\.[0-9]+\.[0-9]+([А-Я]{2,3})', all_text)
        
        if document_code_match:
            full_code = document_code_match.group(0)
            found_code = document_code_match.group(1)
            print(f"✅ Найден код документа: {full_code}")
            print(f"✅ Идентификатор кода: {found_code}")
            
            # Проверка соответствия кода и наименования
            code_check = self._check_document_code_compliance(all_text, found_code, full_code)
            if code_check:
                violations.append(code_check)
        else:
            # Попробуем найти код без суффикса
            document_code_match = re.search(r'[А-Я]{2,4}\.[0-9]+\.[0-9]+', all_text)
            if document_code_match:
                full_code = document_code_match.group(0)
                print(f"✅ Найден код документа (без суффикса): {full_code}")
                print("⚠️ Суффикс кода не найден, проверка соответствия невозможна")
            else:
                print("❌ Код документа не найден")
                violations.append({
                    'rule_id': '1.1.1_code_missing',
                    'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
                    'violation': 'Код документа не обнаружен в основной надписи',
                    'location': 'Основная надпись - графа 1',
                    'severity': 'high',
                    'recommendation': 'Добавьте код документа в формате: РНАТ.301276.001СБ'
                })
        
        # Проверка наличия наименования изделия
        product_name_check = self._check_product_name(all_text)
        if product_name_check:
            violations.append(product_name_check)
        
        print(f"✅ Проверка 1.1.1 завершена. Нарушений: {len(violations)}")
        print("=" * 60)
        return violations
    
    def _check_document_code_compliance(self, text: str, found_code: str, full_code: str) -> dict:
        """Проверка соответствия кода документа и его наименования"""
        all_codes = self.document_analyzer.get_all_document_codes()
        
        if found_code in all_codes:
            expected_name = all_codes[found_code]
            print(f"✅ Ожидаемое наименование для кода {found_code}: {expected_name}")
            
            # Поиск наименования документа в тексте
            name_found = False
            for name_variant in [expected_name, expected_name.replace('ая', 'ая').replace('ий', 'ий')]:
                if name_variant.upper() in text.upper():
                    name_found = True
                    print(f"✅ Наименование документа найдено: {name_variant}")
                    break
            
            if not name_found:
                return {
                    'rule_id': '1.1.1_code_mismatch',
                    'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
                    'violation': f'Наименование документа не соответствует коду {found_code}',
                    'location': 'Основная надпись - графа 1',
                    'severity': 'high',
                    'recommendation': f'Измените наименование на "{expected_name}" или исправьте код документа',
                    'details': f'Код: {full_code}, ожидаемое наименование: {expected_name}'
                }
        else:
            print(f"⚠️ Неизвестный код документа: {found_code}")
            return {
                'rule_id': '1.1.1_unknown_code',
                'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
                'violation': f'Неизвестный код документа: {found_code}',
                'location': 'Основная надпись - графа 1', 
                'severity': 'medium',
                'recommendation': 'Используйте код документа из установленного классификатора',
                'details': f'Обнаружен код: {full_code}'
            }
        
        return None
    
    def _check_product_name(self, text: str) -> dict:
        """Проверка наличия наименования изделия"""
        # Ищем наименование изделия в тексте (обычно находится рядом с кодом)
        lines = text.split('\n')
        for i, line in enumerate(lines):
            line_clean = line.strip()
            # Пропускаем служебные строки
            if any(marker in line_clean for marker in ['Масса', 'Масштаб', 'Лист', 'Изм.', '№ докум.', 'Разраб.', 'Пров.']):
                continue
            
            # Ищем строку с потенциальным наименованием изделия
            if (len(line_clean) > 5 and 
                not re.search(r'\d', line_clean) and  # без цифр
                not re.search(r'[А-Я]{2,4}\.\d+\.\d+', line_clean) and  # не код документа
                line_clean not in ['', 'АО "ОКБМ Африкантов"', 'Инв. № подл.', 'Подп. и дата']):
                print(f"✅ Наименование изделия найдено: '{line_clean}'")
                return None
        
        print("❌ Наименование изделия не найдено")
        return {
            'rule_id': '1.1.1_product_name',
            'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
            'violation': 'Наименование изделия не обнаружено',
            'location': 'Основная надпись - графа 1',
            'severity': 'high',
            'recommendation': 'Добавьте наименование изделия в основную надпись'
        }

    def check_letter_designations_consistency(self, text_data: dict) -> list:
        """
        1.1.3 Проверка наличия указанных буквенных обозначений в технических требованиях и на поле чертежа
        ВСЕ заглавные буквы из чертежа должны быть как отдельно стоящие в описании
        """
        print(f"\n🔍 ПРОВЕРКА 1.1.3: БУКВЕННЫЕ ОБОЗНАЧЕНИЯ")
        print("=" * 60)
        
        violations = []
        
        # Используем блоки для проверки
        drawing_block = text_data.get('blocks', {}).get('drawing', '')
        description_block = text_data.get('blocks', {}).get('description', '')
        
        print(f"📊 Анализ блоков:")
        print(f"   Чертеж: {len(drawing_block)} символов")
        print(f"   Описание: {len(description_block)} символов")
        
        # Ищем ВСЕ заглавные буквы в блоке чертежа
        capital_letters_in_drawing = self._find_all_capital_letters(drawing_block)
        print(f"✅ Заглавные буквы на чертеже: {', '.join(capital_letters_in_drawing) if capital_letters_in_drawing else 'не найдены'}")
        
        # Ищем только ОТДЕЛЬНО СТОЯЩИЕ заглавные буквы в блоке описания
        standalone_letters_in_description = self._find_standalone_capital_letters(description_block)
        print(f"✅ Отдельно стоящие буквы в описании: {', '.join(standalone_letters_in_description) if standalone_letters_in_description else 'не найдены'}")
        
        # Если в чертеже нет заглавных букв - проверка пройдена
        if not capital_letters_in_drawing:
            print("✅ Заглавные буквы не найдены в чертеже - проверка пройдена")
            return violations
        
        # Если в описании нет отдельно стоящих букв, но в чертеже есть - ошибка
        if not standalone_letters_in_description:
            print(f"❌ В чертеже есть заглавные буквы, но в описании нет отдельно стоящих букв: {', '.join(capital_letters_in_drawing)}")
            violations.append({
                'rule_id': '1.1.3_no_standalone_letters_in_description',
                'rule_text': self.tz_rules['title_block']['rule_1.1.3'],
                'violation': f'В чертеже присутствуют заглавные буквы, но в описании отсутствуют отдельно стоящие буквенные обозначения',
                'location': 'Блок описания',
                'severity': 'medium',
                'recommendation': 'Добавьте в описание отдельно стоящие буквенные обозначения для всех заглавных букв из чертежа',
                'details': f'Заглавные буквы в чертеже: {", ".join(capital_letters_in_drawing)}'
            })
            return violations
        
        # Проверяем, что ВСЕ заглавные буквы из чертежа есть в описании как отдельно стоящие
        print(f"\n🔍 ПРОВЕРКА СОВПАДЕНИЯ БУКВ:")
        
        drawing_letters_set = set(capital_letters_in_drawing)
        description_letters_set = set(standalone_letters_in_description)
        
        # Находим буквы, которые есть в чертеже, но отсутствуют в описании
        missing_in_description = drawing_letters_set - description_letters_set
        common_letters = drawing_letters_set & description_letters_set
        
        if not missing_in_description:
            print(f"✅ Все заглавные буквы из чертежа присутствуют в описании как отдельно стоящие: {', '.join(sorted(common_letters))}")
        else:
            print(f"❌ Некоторые заглавные буквы из чертежа отсутствуют в описании как отдельно стоящие!")
            print(f"   Отсутствуют в описании: {', '.join(sorted(missing_in_description))}")
            print(f"   Присутствуют в обоих: {', '.join(sorted(common_letters)) if common_letters else 'нет'}")
            print(f"   Все отдельно стоящие в описании: {', '.join(sorted(description_letters_set))}")
            
            violations.append({
                'rule_id': '1.1.3_letters_missing_in_description',
                'rule_text': self.tz_rules['title_block']['rule_1.1.3'],
                'violation': f'Некоторые заглавные буквы из чертежа отсутствуют в описании как отдельно стоящие обозначения',
                'location': 'Блок описания',
                'severity': 'medium',
                'recommendation': 'Добавьте в описание отдельно стоящие буквенные обозначения для всех заглавных букв из чертежа',
                'details': f'Отсутствуют в описании: {", ".join(sorted(missing_in_description))}; Присутствуют: {", ".join(sorted(common_letters)) if common_letters else "нет"}'
            })
        
        print(f"✅ Проверка 1.1.3 завершена. Нарушений: {len(violations)}")
        print("=" * 60)
        return violations

    def check_asterisk_consistency(self, text_data: dict) -> list:
        """
        1.1.4 Проверка наличия '*', '**', '***' в технических требованиях чертежа и на его поле
        Должны совпадать ТИПЫ звездочек в блоках чертежа и описания
        """
        print(f"\n🔍 ПРОВЕРКА 1.1.4: ЗВЕЗДОЧКИ (*, **, ***)")
        print("=" * 60)
        
        violations = []
        
        # Используем блоки для проверки
        drawing_block = text_data.get('blocks', {}).get('drawing', '')
        description_block = text_data.get('blocks', {}).get('description', '')
        
        print(f"📊 Анализ блоков:")
        print(f"   Чертеж: {len(drawing_block)} символов")
        print(f"   Описание: {len(description_block)} символов")
        
        # Ищем звездочки в блоке чертежа
        asterisks_in_drawing = self._find_asterisks_by_type(drawing_block)
        print(f"✅ Звездочки на чертеже: {asterisks_in_drawing}")
        
        # Ищем звездочки в блоке описания
        asterisks_in_description = self._find_asterisks_by_type(description_block)
        print(f"✅ Звездочки в описании: {asterisks_in_description}")
        
        # Показываем детальную информацию о найденных звездочках
        print(f"\n🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ЗВЕЗДОЧЕК:")
        
        # Анализируем КАКИЕ типы звездочек используются в каждом блоке
        drawing_types_used = [ast_type for ast_type, count in asterisks_in_drawing.items() if count > 0]
        description_types_used = [ast_type for ast_type, count in asterisks_in_description.items() if count > 0]
        
        print(f"   Типы звездочек на чертеже: {', '.join(drawing_types_used) if drawing_types_used else 'нет'}")
        print(f"   Типы звездочек в описании: {', '.join(description_types_used) if description_types_used else 'нет'}")
        
        # Если звездочек нет вообще в обоих блоках - проверка пройдена
        if not drawing_types_used and not description_types_used:
            print("✅ Звездочки не обнаружены в обоих блоках - проверка пройдена")
            return violations
        
        # Проверяем СОВМЕСТИМОСТЬ типов звездочек
        print(f"\n🔍 ПРОВЕРКА СОВМЕСТИМОСТИ ТИПОВ:")
        
        # Если используются разные типы звездочек - ошибка
        if drawing_types_used and description_types_used:
            # Преобразуем в множества для сравнения
            drawing_set = set(drawing_types_used)
            description_set = set(description_types_used)
            
            if drawing_set == description_set:
                print(f"✅ Типы звездочек совпадают: {', '.join(drawing_types_used)}")
            else:
                print(f"❌ Типы звездочек НЕ совпадают!")
                print(f"   На чертеже: {', '.join(drawing_types_used)}")
                print(f"   В описании: {', '.join(description_types_used)}")
                
                violations.append({
                    'rule_id': '1.1.4_type_mismatch',
                    'rule_text': self.tz_rules['title_block']['rule_1.1.4'],
                    'violation': f'Типы звездочек не совпадают между чертежом и описанием',
                    'location': 'Блоки чертежа и описания',
                    'severity': 'medium',
                    'recommendation': 'Убедитесь, что используются одинаковые типы звездочек (*, **, ***) в чертеже и описании',
                    'details': f'На чертеже: {", ".join(drawing_types_used)}; В описании: {", ".join(description_types_used)}'
                })
        
        # Проверяем случаи, когда звездочки есть только в одном блоке
        elif drawing_types_used and not description_types_used:
            print(f"❌ Звездочки есть на чертеже, но отсутствуют в описании: {', '.join(drawing_types_used)}")
            violations.append({
                'rule_id': '1.1.4_asterisks_only_in_drawing',
                'rule_text': self.tz_rules['title_block']['rule_1.1.4'],
                'violation': f'Звездочки присутствуют на чертеже, но отсутствуют в описании',
                'location': 'Блок описания',
                'severity': 'medium',
                'recommendation': 'Добавьте звездочки в описание или удалите их с чертежа',
                'details': f'Типы звездочек на чертеже: {", ".join(drawing_types_used)}'
            })
        
        elif description_types_used and not drawing_types_used:
            print(f"❌ Звездочки есть в описании, но отсутствуют на чертеже: {', '.join(description_types_used)}")
            violations.append({
                'rule_id': '1.1.4_asterisks_only_in_description',
                'rule_text': self.tz_rules['title_block']['rule_1.1.4'],
                'violation': f'Звездочки присутствуют в описании, но отсутствуют на чертеже',
                'location': 'Блок чертежа',
                'severity': 'medium',
                'recommendation': 'Добавьте звездочки на чертеж или удалите их из описания',
                'details': f'Типы звездочек в описании: {", ".join(description_types_used)}'
            })
        
        print(f"\n📋 ИТОГИ ПРОВЕРКИ 1.1.4")
        print(f"   Найдено нарушений: {len(violations)}")
        print(f"   Статус: {'НЕ СООТВЕТСТВУЕТ' if violations else 'СООТВЕТСТВУЕТ'}")
        
        print("=" * 60)
        return violations

    def _find_all_capital_letters(self, text: str) -> List[str]:
        """
        Поиск ВСЕХ заглавных букв в тексте (любых)
        """
        if not text:
            return []
        
        # Ищем все заглавные русские и латинские буквы
        capital_letters = re.findall(r'[А-ЯA-Z]', text)
        
        # Фильтруем слишком распространенные буквы, которые обычно не являются обозначениями
        common_text_letters = {'И',  'Н', 'О', 'С',  'К', 'I', 'Е', 'Т', 'Р', 'М', 'П', 'Л', 'Д', 'Г', 'У',  'Ы', 'Я', 'З', 'Й', 'Ф', 'Х', 'Ц', 'Ч', 'Ш', 'Щ', 'Ъ', 'Ь', 'Э', 'Ю'}
        
        filtered_letters = [letter for letter in capital_letters if letter not in common_text_letters]
        
        return sorted(list(set(filtered_letters)))  # Убираем дубликаты

    def _find_standalone_capital_letters(self, text: str) -> List[str]:
        """
        Поиск только ОТДЕЛЬНО СТОЯЩИХ заглавных букв в тексте
        """
        found_letters = set()
        
        if not text:
            return []
        
        # 1. Буква между пробелами: " A ", " B " (но не как часть слова)
        standalone_pattern1 = r'(?<!\w)[А-ЯA-Z](?!\w)'
        matches1 = re.findall(standalone_pattern1, f" {text} ")
        for letter in matches1:
            if len(letter) == 1:
                found_letters.add(letter)
        
        # 2. Буква в скобках: "(A)", "(B)"
        bracket_pattern = r'\(([А-ЯA-Z])\)'
        matches2 = re.findall(bracket_pattern, text)
        for letter in matches2:
            if len(letter) == 1:
                found_letters.add(letter)
        
        # 3. Буква с точкой: "A.", "B." (но не как часть слова)
        dot_pattern = r'(?<!\w)[А-ЯA-Z]\.'
        matches3 = re.findall(dot_pattern, text)
        for match in matches3:
            letter = match.replace('.', '')
            if len(letter) == 1:
                found_letters.add(letter)
        
        # Фильтруем слишком распространенные буквы
        common_text_letters = {'И',  'Н', 'О', 'С',  'К', 'I', 'Е', 'Т', 'Р', 'М', 'П', 'Л', 'Д', 'Г', 'У',  'Ы', 'Я', 'З', 'Й', 'Ф', 'Х', 'Ц', 'Ч', 'Ш', 'Щ', 'Ъ', 'Ь', 'Э', 'Ю'}
        filtered_letters = {letter for letter in found_letters if letter not in common_text_letters}
        
        return sorted(list(filtered_letters))

    def _find_asterisks_by_type(self, text: str) -> dict:
        """Поиск звездочек по типам с учетом контекста"""
        if not text:
            return {'single': 0, 'double': 0, 'triple': 0}
        
        # Используем lookahead и lookbehind чтобы различать типы звездочек
        single_asterisks = len(re.findall(r'(?<!\*)\*(?!\*)', text))
        double_asterisks = len(re.findall(r'(?<!\*)\*\*(?!\*)', text))  
        triple_asterisks = len(re.findall(r'(?<!\*)\*\*\*(?!\*)', text))
        
        return {
            'single': single_asterisks,
            'double': double_asterisks,
            'triple': triple_asterisks
        }
    
    def run_all_checks(self, document_data: dict) -> dict:
        """Запуск всех проверок из ТЗ"""
        all_violations = []
        
        text_data = document_data.get('text_data', {})
        
        print("🎯 ЗАПУСК ПРОВЕРОК ИЗ ТЗ:")
        print("   1.1.1 - Основная надпись (код и наименование)")
        print("   1.1.3 - Буквенные обозначения (согласованность)")
        print("   1.1.4 - Звездочки (*, **, ***) (совпадение)")
        print("=" * 60)
        
        # ВСЕ ПРОВЕРКИ ИЗ ТЗ
        all_violations.extend(self.check_title_block_requirements(text_data))
        all_violations.extend(self.check_letter_designations_consistency(text_data))
        all_violations.extend(self.check_asterisk_consistency(text_data))
        
        # Статистика
        stats = {
            'total_violations': len(all_violations),
            'high_severity': len([v for v in all_violations if v['severity'] == 'high']),
            'medium_severity': len([v for v in all_violations if v['severity'] == 'medium']),
            'low_severity': len([v for v in all_violations if v['severity'] == 'low'])
        }
        
        print(f"\n📊 ИТОГИ ПРОВЕРКИ:")
        print(f"   Всего нарушений: {stats['total_violations']}")
        print(f"   Высокая важность: {stats['high_severity']}")
        print(f"   Средняя важность: {stats['medium_severity']}")
        print(f"   Низкая важность: {stats['low_severity']}")
        
        # Детальная информация о нарушениях
        if all_violations:
            print(f"\n📋 ДЕТАЛИЗАЦИЯ НАРУШЕНИЙ:")
            for i, violation in enumerate(all_violations, 1):
                print(f"   {i}. [{violation['severity'].upper()}] {violation['violation']}")
                if 'details' in violation:
                    print(f"      📍 {violation['details']}")
        else:
            print(f"\n🎉 Документ соответствует всем проверяемым требованиям ТЗ!")
        
        return {
            'violations': all_violations,
            'statistics': stats,
            'is_compliant': len(all_violations) == 0,
            'blocks_info': text_data.get('blocks', {})
        }

# =============================================================================
# FLASK APP
# =============================================================================

# Initialize analyzers
doc_analyzer = DocumentAnalyzer()
rule_engine = RuleEngine()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf'}

def generate_red_pencil_report(analysis_result: dict) -> dict:
    """Генерация отчета 'Красный карандаш'"""
    violations = analysis_result.get('violations', [])
    
    report = {
        'summary': {
            'total_issues': len(violations),
            'compliance_status': 'СООТВЕТСТВУЕТ' if len(violations) == 0 else 'НЕ СООТВЕТСТВУЕТ',
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'detailed_issues': [],
        'blocks_info': analysis_result.get('blocks_info', {})
    }
    
    for i, violation in enumerate(violations, 1):
        issue = {
            'issue_number': i,
            'rule_reference': violation.get('rule_id', 'N/A'),
            'rule_text': violation.get('rule_text', 'N/A'),
            'violation_description': violation.get('violation', 'N/A'),
            'location': violation.get('location', 'N/A'),
            'quote': violation.get('quote', ''),
            'severity': violation.get('severity', 'medium').upper(),
            'recommendation': generate_recommendation(violation)
        }
        report['detailed_issues'].append(issue)
    
    return report

def generate_recommendation(violation: dict) -> str:
    """Генерация рекомендаций по исправлению"""
    rule_id = violation.get('rule_id', '')
    
    recommendations = {
        '1.1.1_code_missing': 'Добавьте код документа в формате: РНАТ.301276.001СБ',
        '1.1.1_code_mismatch': 'Измените наименование документа в соответствии с кодом',
        '1.1.1_unknown_code': 'Используйте код документа из установленного классификатора',
        '1.1.1_product_name': 'Добавьте наименование изделия в основную надпись',
        '1.1.3_letters_only_in_drawing': 'Добавьте буквенные обозначения в описание или удалите их с чертежа',
        '1.1.3_letters_only_in_description': 'Добавьте буквенные обозначения на чертеж или удалите их из описания',
        '1.1.3_letters_mismatch': 'Убедитесь, что все буквенные обозначения одинаковы в чертеже и описании',
        '1.1.4_single_mismatch': 'Убедитесь, что количество одиночных звездочек (*) одинаково в чертеже и описании',
        '1.1.4_double_mismatch': 'Убедитесь, что количество двойных звездочек (**) одинаково в чертеже и описании',
        '1.1.4_triple_mismatch': 'Убедитесь, что количество тройных звездочек (***) одинаково в чертеже и описании'
    }
    
    return recommendations.get(rule_id, 'Устраните выявленное несоответствие требованиям нормативной документации')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_document():
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{filename}")
        file.save(file_path)
        
        print(f"🔄 Файл сохранен: {file_path}")
        
        try:
            print(f"🔍 Начало анализа файла: {filename}")
            
            # Step 1: Extract text with blocks
            print("📄 ВЫЗОВ extract_text_from_pdf С РАЗБИВКОЙ НА БЛОКИ...")
            text_data = doc_analyzer.extract_text_from_pdf(file_path)
            print("📄 extract_text_from_pdf завершен")
            
            # Prepare document data
            document_data = {
                'text_data': text_data,
                'metadata': {
                    'filename': filename,
                    'analysis_date': datetime.now().isoformat(),
                    'total_pages': text_data.get('total_pages', 0)
                }
            }
            
            # Step 2: Run rule checks
            print("✅ Проверка правил из ТЗ...")
            analysis_result = rule_engine.run_all_checks(document_data)
            
            # Step 3: Generate report
            print("📊 Формирование отчета...")
            red_pencil_report = generate_red_pencil_report(analysis_result)
            
            # Clean up
            os.remove(file_path)
            
            print(f"🎉 Анализ завершен. Замечаний: {len(analysis_result['violations'])}")
            
            return jsonify({
                'success': True,
                'analysis_result': analysis_result,
                'red_pencil_report': red_pencil_report,
                'document_metadata': document_data['metadata'],
                'blocks_info': text_data.get('blocks', {})
            })
            
        except Exception as e:
            print(f"❌ Ошибка анализа: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'error': f'Ошибка анализа: {str(e)}'}), 500
    
    return jsonify({'error': 'Неверный тип файла. Разрешены только PDF.'}), 400

@app.route('/report', methods=['POST'])
def generate_report():
    data = request.get_json()
    red_pencil_report = data.get('red_pencil_report')
    
    if not red_pencil_report:
        return jsonify({'error': 'No report data provided'}), 400
    
    # Generate downloadable report
    report_text = generate_text_report(red_pencil_report)
    
    return jsonify({
        'report_text': report_text,
        'download_url': '/download/report.txt'
    })

def generate_text_report(red_pencil_report: dict) -> str:
    """Генерация текстового отчета"""
    report_lines = []
    
    summary = red_pencil_report.get('summary', {})
    report_lines.append("=" * 60)
    report_lines.append("ОТЧЕТ НОРМОКОНТРОЛЯ (ПО ТЗ)")
    report_lines.append("=" * 60)
    report_lines.append(f"Дата анализа: {summary.get('analysis_date', 'N/A')}")
    report_lines.append(f"Общее количество замечаний: {summary.get('total_issues', 0)}")
    report_lines.append(f"Статус соответствия: {summary.get('compliance_status', 'N/A')}")
    report_lines.append("")
    
    # Информация о блоках
    blocks_info = red_pencil_report.get('blocks_info', {})
    if blocks_info:
        report_lines.append("ИНФОРМАЦИЯ О БЛОКАХ ДОКУМЕНТА:")
        report_lines.append("-" * 40)
        report_lines.append(f"Чертеж: {len(blocks_info.get('drawing', ''))} символов")
        report_lines.append(f"Описание: {len(blocks_info.get('description', ''))} символов")
        report_lines.append(f"Структура: {len(blocks_info.get('structure', ''))} символов")
        report_lines.append("")
    
    issues = red_pencil_report.get('detailed_issues', [])
    if issues:
        report_lines.append("ДЕТАЛЬНЫЕ ЗАМЕЧАНИЯ:")
        report_lines.append("-" * 60)
        
        for issue in issues:
            report_lines.append(f"{issue['issue_number']}. [{issue['severity']}] {issue['violation_description']}")
            report_lines.append(f"   Местоположение: {issue['location']}")
            report_lines.append(f"   Нормативный документ: {issue['rule_reference']}")
            report_lines.append(f"   Требование: {issue['rule_text']}")
            if issue['quote']:
                report_lines.append(f"   Цитата: {issue['quote']}")
            report_lines.append(f"   Рекомендация: {issue['recommendation']}")
            report_lines.append("")
    else:
        report_lines.append("ЗАМЕЧАНИЙ НЕ ВЫЯВЛЕНО")
        report_lines.append("Документ соответствует установленным требованиям")
    
    report_lines.append("=" * 60)
    report_lines.append("Конец отчета")
    
    return "\n".join(report_lines)

if __name__ == '__main__':
    print("🚀 Starting NormControl System...")
    print("📊 Access the application at: http://localhost:5000")
    print("🔧 Debug mode: ON")
    print(f"📚 PDF processing: {'PyMuPDF' if PYMUPDF_AVAILABLE else 'PDFPlumber' if PDFPLUMBER_AVAILABLE else 'OCR only'}")
    print("✅ Проверяются только требования из ТЗ:")
    print("   1.1.1 - Основная надпись (код документа и наименование)")
    print("   1.1.3 - Буквенные обозначения (согласованность)")
    print("   1.1.4 - Звездочки (*, **, ***) (совпадение)")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)