from flask import Flask, render_template, request, jsonify
import os
import uuid
import io
from werkzeug.utils import secure_filename
import re
from datetime import datetime
from PIL import Image

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
# CONFIG - Новые правила из ТЗ
# =============================================================================
class Config:
    TZ_RULES = {
        "title_block": {
            "rule_1.1.1": "Проверка заполнения основной надписи в части заполнения графы 1 (наименования изделия и наименования документа, если этому документу присвоен код и соответствие этого кода наименованию документа)",
            "rule_1.1.2": "Проверка расположения технических требований над основной надписью и не выход их за ширину равную 185 мм"
        }
    }

# =============================================================================
# DOCUMENT ANALYZER
# =============================================================================
class DocumentAnalyzer:
    """
    Анализатор PDF документов для проверки требований ТЗ
    """
    
    def __init__(self):
        # Словари кодов документов из ТЗ
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
        Основной метод извлечения текста из PDF
        """
        print(f"\n🔍 ИЗВЛЕЧЕНИЕ ТЕКСТА ИЗ PDF")
        print("=" * 80)
        
        text_data = self._try_extraction_methods(pdf_path)
        self._print_detailed_content(text_data)
        
        print("=" * 80)
        print("✅ ИЗВЛЕЧЕНИЕ ТЕКСТА ЗАВЕРШЕНО")
        print("=" * 80)
        
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
            
            # Анализ текстовых блоков для проверки ширины
            text_blocks = page.get_text("dict")["blocks"]
            for block in text_blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            block_data = {
                                'text': span['text'],
                                'bbox': span['bbox'],
                                'size': span['size'],
                                'font': span['font'],
                            }
                            page_data['blocks'].append(block_data)
            
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
            'extraction_method': 'None'
        }

# =============================================================================
# RULE ENGINE - ТОЛЬКО ПРОВЕРКИ ИЗ ТЗ
# =============================================================================
class RuleEngine:
    def __init__(self):
        self.tz_rules = Config.TZ_RULES
        self.document_analyzer = DocumentAnalyzer()
        
    def check_title_block_requirements(self, text_data: dict) -> list:
        """
        1.1.1 Проверка заполнения основной надписи - графа 1
        """
        print(f"\n🔍 ПРОВЕРКА 1.1.1: ОСНОВНАЯ НАДПИСЬ - ГРАФА 1")
        print("=" * 60)
        
        violations = []
        all_text = ""
        for page in text_data.get('pages', []):
            all_text += page.get('text', '') + "\n"
        
        # Поиск кода документа (формат: РНАТ.301276.001СБ)
        document_code_match = re.search(r'[А-Я]{2,4}\.[0-9]+\.[0-9]+([А-Я]{2,3})', all_text)
        
        if document_code_match:
            found_code = document_code_match.group(1)
            print(f"✅ Найден код документа: {found_code}")
            
            # Проверка соответствия кода и наименования
            code_check = self._check_document_code_compliance(all_text, found_code)
            if code_check:
                violations.append(code_check)
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
        
        print("=" * 60)
        return violations
    
    def _check_document_code_compliance(self, text: str, found_code: str) -> dict:
        """Проверка соответствия кода документа и его наименования"""
        all_codes = self.document_analyzer.get_all_document_codes()
        
        if found_code in all_codes:
            expected_name = all_codes[found_code]
            print(f"✅ Ожидаемое наименование для кода {found_code}: {expected_name}")
            
            # Поиск наименования документа в тексте
            if expected_name.upper() not in text.upper():
                return {
                    'rule_id': '1.1.1_code_mismatch',
                    'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
                    'violation': f'Наименование документа не соответствует коду {found_code}',
                    'location': 'Основная надпись - графа 1',
                    'severity': 'high',
                    'recommendation': f'Измените наименование на "{expected_name}" или исправьте код документа'
                }
            else:
                print(f"✅ Наименование документа соответствует коду {found_code}")
        else:
            print(f"⚠️ Неизвестный код документа: {found_code}")
            return {
                'rule_id': '1.1.1_unknown_code',
                'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
                'violation': f'Неизвестный код документа: {found_code}',
                'location': 'Основная надпись - графа 1', 
                'severity': 'medium',
                'recommendation': 'Используйте код документа из установленного классификатора'
            }
        
        return None
    
    def _check_product_name(self, text: str) -> dict:
        """Проверка наличия наименования изделия"""
        product_patterns = [
            r'Наименование[:\s]*([^\n]+)',
            r'Изделие[:\s]*([^\n]+)',
            r'Обозначение[:\s]*([^\n]+)',
            r'^[А-Я][А-Яа-я\s]+$'
        ]
        
        product_name = None
        for pattern in product_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                product_name = match.group(1) if match.groups() else match.group(0)
                break
        
        if product_name and len(product_name.strip()) > 2:
            print(f"✅ Наименование изделия: {product_name.strip()}")
            return None
        else:
            print("❌ Наименование изделия не найдено")
            return {
                'rule_id': '1.1.1_product_name',
                'rule_text': self.tz_rules['title_block']['rule_1.1.1'],
                'violation': 'Наименование изделия не обнаружено',
                'location': 'Основная надпись - графа 1',
                'severity': 'high',
                'recommendation': 'Добавьте наименование изделия в основную надпись'
            }
    
    def check_technical_requirements_placement(self, text_data: dict) -> list:
        """
        1.1.2 Проверка расположения технических требований над основной надписью 
        и не выход их за ширину равную 185 мм
        """
        violations = []
        
        print(f"\n🔍 ПРОВЕРКА 1.1.2: РАСПОЛОЖЕНИЕ И ШИРИНА ТЕХНИЧЕСКИХ ТРЕБОВАНИЙ")
        print("=" * 60)
        
        # Ключевые слова для технических требований
        tech_requirements_keywords = [
            'Размеры для справок',
            'При монтаже руководствоваться',
            '1. Размеры для справок',
            '2. При монтаже руководствоваться'
        ]
        
        # Ключевые слова для основной надписи
        title_block_keywords = [
            'РНАТ.123456.00',
            'Изм. Ассо',
            '№ Фонд',
            'Подп. Дата', 
            'Генератор',
            'Монтажный чертеж',
            'Акта',
            'Актай',
            'AD "INISH Африкантаб"',
            'Масса',
            'Масштаб',
            'Изм.',
            'Лист',
            'докум.',
            'Подп.',
            'Дата',
            'Разраб.',
            'Пров.',
            'Т.контр.',
            'Н.контр.',
            'Утв.',
            'Инв.',
            'подл.',
            'дубл.',
            'Справ.',
            'Перв. примен.',
            'Копировал',
            'Формат',
            'CRC:',
            'ID версии:',
            'АО "ОКБМ Африкантов"'
        ]
        
        # Собираем все данные по страницам
        all_tech_req_data = []
        all_title_block_data = []
        
        for page in text_data.get('pages', []):
            page_text = page['text']
            lines = page_text.split('\n')
            
            print(f"\n📄 Анализ страницы {page['page_number']}:")
            
            # Поиск технических требований
            tech_req_found_on_page = False
            for i, line in enumerate(lines):
                line_clean = line.strip()
                if not line_clean:
                    continue
                    
                # Проверка на технические требования
                for keyword in tech_requirements_keywords:
                    if keyword in line_clean:
                        tech_req_data = {
                            'page': page['page_number'],
                            'line': i,
                            'text': line_clean,
                            'y_position': self._get_line_y_position(page, i, lines)
                        }
                        all_tech_req_data.append(tech_req_data)
                        tech_req_found_on_page = True
                        print(f"   ✅ Технические требования: строка {i+1} - '{line_clean}'")
                        break
            
            # Поиск основной надписи
            title_block_found_on_page = False
            for i, line in enumerate(lines):
                line_clean = line.strip()
                if not line_clean:
                    continue
                    
                # Проверка на основную надпись
                for keyword in title_block_keywords:
                    if keyword in line_clean:
                        title_block_data = {
                            'page': page['page_number'],
                            'line': i,
                            'text': line_clean,
                            'y_position': self._get_line_y_position(page, i, lines)
                        }
                        all_title_block_data.append(title_block_data)
                        title_block_found_on_page = True
                        print(f"   ✅ Основная надпись: строка {i+1} - '{line_clean}'")
                        break
            
            if not tech_req_found_on_page:
                print("   ℹ️ Технические требования не найдены на странице")
            if not title_block_found_on_page:
                print("   ℹ️ Основная надпись не найдена на странице")
        
        # Проверка расположения
        if all_tech_req_data and all_title_block_data:
            # Находим самые НИЖНИЕ технические требования (последние по расположению)
            lowest_tech_req = max(all_tech_req_data, key=lambda x: (x['page'], x['y_position']))
            # Находим самую ВЕРХНЮЮ основную надпись (первую по расположению)
            highest_title_block = min(all_title_block_data, key=lambda x: (x['page'], x['y_position']))
            
            print(f"\n   📍 АНАЛИЗ РАСПОЛОЖЕНИЯ:")
            print(f"      Последние тех.требования: стр. {lowest_tech_req['page']}, позиция Y: {lowest_tech_req['y_position']:.1f}")
            print(f"      Первая основная надпись: стр. {highest_title_block['page']}, позиция Y: {highest_title_block['y_position']:.1f}")
            
            # КРИТИЧЕСКО ИСПРАВЛЕНИЕ: Технические требования должны быть ВЫШЕ основной надписи
            # Это значит, что Y-позиция последних тех.требований должна быть МЕНЬШЕ Y-позиции первой основной надписи
            # (в системах координат PDF меньшие Y значения находятся ВЫШЕ на странице)
            
            if lowest_tech_req['page'] < highest_title_block['page']:
                # Технические требования на более ранней странице - ПРАВИЛЬНО
                print("   ✅ Технические требования расположены НАД основной надписью (на более ранней странице)")
            elif lowest_tech_req['page'] > highest_title_block['page']:
                # Технические требования на более поздней странице - НЕПРАВИЛЬНО
                violations.append({
                    'rule_id': '1.1.2_placement_page',
                    'rule_text': self.tz_rules['title_block']['rule_1.1.2'],
                    'violation': 'Технические требования расположены на странице после основной надписи',
                    'location': f'Страница {lowest_tech_req["page"]}',
                    'severity': 'medium',
                    'recommendation': 'Переместите технические требования на страницы перед основной надписью',
                    'details': f'Тех.требования на стр. {lowest_tech_req["page"]}, Основная надпись на стр. {highest_title_block["page"]}'
                })
                print("   ❌ Технические требования расположены ПОСЛЕ основной надписи")
            else:
                # На одной странице - сравниваем Y-позиции
                if lowest_tech_req['y_position'] < highest_title_block['y_position']:
                    print("   ✅ Технические требования расположены НАД основной надписью (на одной странице)")
                else:
                    violations.append({
                        'rule_id': '1.1.2_placement_line',
                        'rule_text': self.tz_rules['title_block']['rule_1.1.2'],
                        'violation': 'Технические требования расположены под основной надписью',
                        'location': f'Страница {lowest_tech_req["page"]}',
                        'severity': 'medium',
                        'recommendation': 'Переместите технические требования выше основной надписи',
                        'details': f'Тех.требования на позиции Y={lowest_tech_req["y_position"]:.1f}, Основная надпись на позиции Y={highest_title_block["y_position"]:.1f}'
                    })
                    print("   ❌ Технические требования расположены ПОД основной надписью")
        else:
            if not all_tech_req_data:
                print("\n   ℹ️ Технические требования не найдены в документе")
            if not all_title_block_data:
                print("\n   ⚠️ Основная надпись не найдена в документе")
                violations.append({
                    'rule_id': '1.1.2_no_title_block',
                    'rule_text': self.tz_rules['title_block']['rule_1.1.2'],
                    'violation': 'Основная надпись не обнаружена в документе',
                    'location': 'Документ',
                    'severity': 'high',
                    'recommendation': 'Добавьте основную надпись в соответствии с требованиями'
                })
        
        # Проверка ширины технических требований
        if all_tech_req_data:
            width_violations = self._check_technical_requirements_width(text_data, tech_requirements_keywords)
            violations.extend(width_violations)
        else:
            print("\n   ℹ️ Проверка ширины пропущена - технические требования не найдены")
        
        print("=" * 60)
        return violations
    
    def _get_line_y_position(self, page: dict, line_index: int, lines: list) -> float:
        """Получить Y-координату строки для точного определения положения"""
        # Если есть информация о блоках, используем её для точного позиционирования
        if 'blocks' in page and page['blocks']:
            target_text = lines[line_index].strip()
            for block in page['blocks']:
                block_text = block.get('text', '').strip()
                if target_text and target_text in block_text:
                    bbox = block.get('bbox', [])
                    if len(bbox) == 4:
                        # В PDF координаты: (x0, y0, x1, y1) где y0 - верхняя граница
                        return bbox[1]  # Y-координата верхней границы
        
        # Fallback - используем обратный индекс строки (чем выше строка, тем меньше значение)
        # Это имитирует PDF координаты где меньшие Y значения находятся выше
        total_lines = len(lines)
        return float(total_lines - line_index)
    
    def _check_technical_requirements_width(self, text_data: dict, tech_keywords: list) -> list:
        """Проверка ширины технических требований (185 мм максимум)"""
        violations = []
        
        POINTS_TO_MM = 0.3528
        MAX_ALLOWED_WIDTH_MM = 185
        
        print(f"\n📏 ПРОВЕРКА ШИРИНЫ ТЕХНИЧЕСКИХ ТРЕБОВАНИЙ (макс. {MAX_ALLOWED_WIDTH_MM} мм)")
        
        total_tech_blocks = 0
        wide_blocks_count = 0
        
        for page in text_data.get('pages', []):
            page_width_mm = page.get('width', 0) * POINTS_TO_MM if page.get('width') else 0
            
            print(f"\n   📄 Страница {page['page_number']}:")
            print(f"      Ширина страницы: {page_width_mm:.1f} мм")
            print(f"      Максимально допустимая ширина тех.требований: {MAX_ALLOWED_WIDTH_MM} мм")
            
            page_tech_blocks = 0
            page_wide_blocks = 0
            
            # Проверяем блоки с техническими требованиями
            for block in page.get('blocks', []):
                bbox = block.get('bbox', [])
                if len(bbox) == 4:
                    block_width_pt = bbox[2] - bbox[0]
                    block_width_mm = block_width_pt * POINTS_TO_MM
                    
                    block_text = block.get('text', '').strip()
                    if not block_text:
                        continue
                        
                    # Проверяем, является ли блок техническими требованиями
                    is_tech_block = any(keyword in block_text for keyword in tech_keywords)
                    
                    # Также проверяем пункты с цифрами (для неправильных файлов)
                    if not is_tech_block and re.search(r'^\d+[\.\*]\s+', block_text):
                        is_tech_block = True
                    
                    if is_tech_block:
                        page_tech_blocks += 1
                        total_tech_blocks += 1
                        
                        status_icon = "✅"
                        status_text = "в норме"
                        
                        if block_width_mm > MAX_ALLOWED_WIDTH_MM:
                            page_wide_blocks += 1
                            wide_blocks_count += 1
                            status_icon = "❌"
                            status_text = "ПРЕВЫШЕНА"
                            
                            violations.append({
                                'rule_id': '1.1.2_width',
                                'rule_text': self.tz_rules['title_block']['rule_1.1.2'],
                                'violation': f'Ширина технических требований превышает допустимую ({block_width_mm:.1f} мм > {MAX_ALLOWED_WIDTH_MM} мм)',
                                'location': f'Страница {page["page_number"]}',
                                'severity': 'medium',
                                'recommendation': f'Уменьшите ширину столбца технических требований до {MAX_ALLOWED_WIDTH_MM} мм',
                                'quote': block_text[:100] + '...' if len(block_text) > 100 else block_text
                            })
                        
                        print(f"      {status_icon} Тех.требования: ширина {block_width_mm:.1f} мм - {status_text}")
                        if len(block_text) > 50:
                            print(f"         Текст: '{block_text[:50]}...'")
                        else:
                            print(f"         Текст: '{block_text}'")
            
            if page_tech_blocks == 0:
                print("      ℹ️ Блоки технических требований не идентифицированы")
            else:
                print(f"      📊 На странице: блоков - {page_tech_blocks}, с нарушениями - {page_wide_blocks}")
        
        print(f"\n   📈 ОБЩИЕ РЕЗУЛЬТАТЫ ПРОВЕРКИ ШИРИНЫ:")
        print(f"      Всего проверено блоков: {total_tech_blocks}")
        print(f"      Блоков с нарушением ширины: {wide_blocks_count}")
        
        if wide_blocks_count == 0 and total_tech_blocks > 0:
            print("      🎉 Все блоки технических требований соответствуют требованиям по ширине!")
        
        return violations
    
    def run_all_checks(self, document_data: dict) -> dict:
        """Запуск всех проверок из ТЗ"""
        all_violations = []
        
        text_data = document_data.get('text_data', {})
        
        print("🎯 ЗАПУСК ПРОВЕРОК ИЗ ТЗ:")
        print("   1.1.1 - Основная надпись (код и наименование)")
        print("   1.1.2 - Технические требования (расположение и ширина)")
        print("=" * 60)
        
        # 🔴 ТОЛЬКО НОВЫЕ ПРОВЕРКИ ИЗ ТЗ
        all_violations.extend(self.check_title_block_requirements(text_data))
        all_violations.extend(self.check_technical_requirements_placement(text_data))
        
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
            'is_compliant': len(all_violations) == 0
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
        'detailed_issues': []
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
        '1.1.2_placement': 'Переместите технические требования выше основной надписи',
        '1.1.2_width': 'Уменьшите ширину столбца технических требований до 185 мм'
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
        print(f"📏 Размер файла: {os.path.getsize(file_path)} байт")
        
        try:
            print(f"🔍 Начало анализа файла: {filename}")
            
            # Step 1: Extract text using NEW analyzer
            print("📄 ВЫЗОВ extract_text_from_pdf...")
            text_data = doc_analyzer.extract_text_from_pdf(file_path)
            print("📄 extract_text_from_pdf завершен")
            
            # Prepare document data for rule checking
            document_data = {
                'text_data': text_data,
                'metadata': {
                    'filename': filename,
                    'analysis_date': datetime.now().isoformat(),
                    'total_pages': text_data.get('total_pages', 0)
                }
            }
            
            # Step 2: Run NEW rule checks only
            print("✅ Проверка правил из ТЗ...")
            analysis_result = rule_engine.run_all_checks(document_data)
            
            # Step 3: Generate "Red Pencil" report
            print("📊 Формирование отчета...")
            red_pencil_report = generate_red_pencil_report(analysis_result)
            
            # Clean up uploaded file
            os.remove(file_path)
            
            print(f"🎉 Анализ завершен. Замечаний: {len(analysis_result['violations'])}")
            
            return jsonify({
                'success': True,
                'analysis_result': analysis_result,
                'red_pencil_report': red_pencil_report,
                'document_metadata': document_data['metadata']
            })
            
        except Exception as e:
            print(f"❌ Ошибка анализа: {str(e)}")
            # Clean up on error
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
    print("   1.1.2 - Технические требования (расположение и ширина)")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)