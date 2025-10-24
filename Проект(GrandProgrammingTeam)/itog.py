from flask import Flask, render_template, request, jsonify
import os
import uuid
from werkzeug.utils import secure_filename
import re
from datetime import datetime
import fitz  # PyMuPDF
import math

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = 'normcontrol-secret-key-2024'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# =============================================================================
# CONFIGURATION
# =============================================================================
class Config:
    DOCUMENT_CODES = {
        'СБ': 'Сборочный чертеж',
        'ВО': 'Чертеж общего вида', 
        'ТЧ': 'Теоретический чертеж',
        'ГЧ': 'Габаритный чертеж',
        'МЭ': 'Электромонтажный чертеж',
        'МЧ': 'Монтажный чертеж',
        'УЧ': 'Упаковочный чертеж',
        'ВС': 'Ведомость спецификаций',
        'Э3': 'Схема электрическая принципиальная',
        'Э4': 'Схема электрическая соединений', 
        'Э5': 'Схема электрическая подключения'
    }

    TOLERANCE_SYMBOLS = ['⏊', '⊥', '∥', '∠', '○', '⌒', '⏋']
    BASE_SEPARATOR = '—'

# =============================================================================
# PRECISE DOCUMENT ANALYZER
# =============================================================================
class DocumentAnalyzer:
    def extract_text_from_pdf(self, pdf_path: str) -> dict:
        """Точное извлечение текста с детальным анализом"""
        try:
            doc = fitz.open(pdf_path)
            text_data = {'pages': [], 'total_pages': doc.page_count}
            
            # Сначала извлекаем техтребования с первой страницы
            first_page_tech_requirements = ""
            if doc.page_count > 0:
                first_page = doc[0]
                first_page_text = first_page.get_text("text", sort=True)
                first_page_dict = first_page.get_text("dict", sort=True)
                first_page_width = first_page.rect.width
                first_page_height = first_page.rect.height
                
                first_page_tech_requirements = self._extract_tech_requirements_improved(
                    first_page_dict, first_page_text, first_page_width, first_page_height
                )['text']
                
                print(f"\n📋 ТЕХТРЕБОВАНИЯ С ПЕРВОЙ СТРАНИЦЫ:")
                print(f"'{first_page_tech_requirements[:200]}...'")
            
            # Анализируем все страницы
            for page_num in range(doc.page_count):
                page = doc[page_num]
                
                raw_text = page.get_text("text", sort=True)
                text_dict = page.get_text("dict", sort=True)
                width = page.rect.width
                height = page.rect.height
                drawings = page.get_drawings()
                
                print(f"\n📄 СТРАНИЦА {page_num + 1} ({width}x{height})")
                print("=" * 50)
                
                # Детальный анализ страницы
                try:
                    analysis = self._analyze_page_details(
                        text_dict, raw_text, width, height, drawings, page, 
                        first_page_tech_requirements if page_num == 0 else "",
                        page_num + 1
                    )
                except Exception as e:
                    print(f"❌ ОШИБКА при анализе страницы {page_num + 1}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return {'pages': [], 'total_pages': 0, 'error': str(e)}
                
                text_data['pages'].append({
                    'page_number': page_num + 1,
                    'width': width,
                    'height': height,
                    'raw_text': raw_text,
                    'text_dict': text_dict,
                    'drawings': drawings,
                    'analysis': analysis
                })
            
            doc.close()
            
            # Сохраняем техтребования с первой страницы для всех страниц
            text_data['first_page_tech_requirements'] = first_page_tech_requirements
            return text_data
        except Exception as e:
            return {'pages': [], 'total_pages': 0, 'error': str(e)}

    def _analyze_page_details(self, text_dict: dict, raw_text: str, width: float, height: float, 
                            drawings: list, page, first_page_tech_requirements: str = "", page_num: int = 1) -> dict:
        """Детальный анализ страницы"""
        analysis = {
            'title_block': self._extract_title_block_improved(text_dict, width, height),
            'drawing_area': self._extract_drawing_area_improved(text_dict, width, height),
            'tech_requirements': {'text': '', 'lines': [], 'spans': []},  # Пустые техтребования для всех страниц кроме первой
            'found_elements': {
                'codes': [],
                'letters': [],
                'asterisks': {'single': [], 'double': [], 'triple': []},
                'dimensions': [],
                'tolerances': [],
                'bases': [],
                'arrows': [],
                'lines': []
            }
        }
        
        # Для первой страницы используем оригинальные техтребования
        if page_num == 1:
            analysis['tech_requirements'] = self._extract_tech_requirements_improved(text_dict, raw_text, width, height)
        else:
            # Для остальных страниц используем техтребования с первой страницы
            analysis['tech_requirements'] = {
                'text': first_page_tech_requirements,
                'lines': first_page_tech_requirements.split('\n') if first_page_tech_requirements else [],
                'spans': []
            }
        
        # Объединяем весь текст для анализа элементов
        all_text = analysis['title_block']['text'] + " " + analysis['drawing_area']['text']
        analysis['found_elements'] = self._analyze_elements(
            all_text, 
            first_page_tech_requirements,  # Всегда используем техтребования с первой страницы
            page_num
        )
        
        # Анализируем графические элементы
        analysis['graphic_analysis'] = self._analyze_graphic_elements(drawings, text_dict, page)
        
        # Детальная диагностика
        self._print_detailed_diagnostics(analysis, width, height, page_num)
        
        return analysis

    def _extract_title_block_improved(self, text_dict: dict, width: float, height: float) -> dict:
        """Улучшенное извлечение основной надписи"""
        title_spans = []
        title_text = ""
        
        # Основная надпись обычно находится в правом нижнем углу (ГОСТ 2.104-2006)
        title_block_area = {
            'x_min': width * 0.6,   # Правая часть страницы
            'x_max': width,
            'y_min': height * 0.7,  # Нижняя часть страницы  
            'y_max': height
        }
        
        print(f"📍 Поиск основной надписи в области: {title_block_area}")
        
        for block in text_dict.get('blocks', []):
            if block['type'] == 0:  # Текстовый блок
                for line in block['lines']:
                    for span in line['spans']:
                        bbox = span['bbox']
                        span_center_x = (bbox[0] + bbox[2]) / 2
                        span_center_y = (bbox[1] + bbox[3]) / 2
                        
                        # Проверяем, находится ли span в области основной надписи
                        if (title_block_area['x_min'] <= span_center_x <= title_block_area['x_max'] and
                            title_block_area['y_min'] <= span_center_y <= title_block_area['y_max']):
                            
                            text = span.get('text', '').strip()
                            if text:
                                title_spans.append({
                                    'text': text,
                                    'bbox': bbox,
                                    'position': (span_center_x, span_center_y)
                                })
                                title_text += text + " "
                                print(f"  📍 Найден текст основной надписи: '{text}' в позиции ({span_center_x:.1f}, {span_center_y:.1f})")
        
        return {'text': title_text.strip(), 'spans': title_spans}

    def _extract_drawing_area_improved(self, text_dict: dict, width: float, height: float) -> dict:
        """Улучшенное извлечение поля чертежа"""
        drawing_spans = []
        drawing_text = ""
        
        # Область технических требований (правая часть страницы) - УВЕЛИЧЕНА
        tech_requirements_area = {
            'x_min': width * 0.55,   # УВЕЛИЧЕНО: было 0.6
            'x_max': width,
            'y_min': 0,
            'y_max': height * 0.65   # УВЕЛИЧЕНО: было 0.6
        }
        
        # Область основной надписи (правый нижний угол)
        title_block_area = {
            'x_min': width * 0.6,
            'x_max': width, 
            'y_min': height * 0.7,
            'y_max': height
        }
        
        print(f"📍 Поиск поля чертежа (исключая техтребования и основную надпись)")
        
        for block in text_dict.get('blocks', []):
            if block['type'] == 0:
                for line in block['lines']:
                    for span in line['spans']:
                        bbox = span['bbox']
                        span_center_x = (bbox[0] + bbox[2]) / 2
                        span_center_y = (bbox[1] + bbox[3]) / 2
                        
                        # Исключаем технические требования и основную надпись
                        in_tech_area = (tech_requirements_area['x_min'] <= span_center_x <= tech_requirements_area['x_max'] and
                                      tech_requirements_area['y_min'] <= span_center_y <= tech_requirements_area['y_max'])
                        
                        in_title_area = (title_block_area['x_min'] <= span_center_x <= title_block_area['x_max'] and
                                       title_block_area['y_min'] <= span_center_y <= title_block_area['y_max'])
                        
                        if not in_tech_area and not in_title_area:
                            text = span.get('text', '').strip()
                            if text:
                                drawing_spans.append({
                                    'text': text,
                                    'bbox': bbox,
                                    'position': (span_center_x, span_center_y)
                                })
                                drawing_text += text + " "
        
        return {'text': drawing_text.strip(), 'spans': drawing_spans}

    def _extract_tech_requirements_improved(self, text_dict: dict, raw_text: str, width: float, height: float) -> dict:
        """Улучшенное извлечение технических требований - ПРАВАЯ ЧАСТЬ СТРАНИЦЫ"""
        tech_spans = []
        tech_text = ""
        tech_lines = []
        
        # ОБЛАСТЬ ТЕХНИЧЕСКИХ ТРЕБОВАНИЙ - ПРАВАЯ ЧАСТЬ СТРАНИЦЫ
        tech_requirements_area = {
            'x_min': width * 0.55,
            'x_max': width,
            'y_min': 0, 
            'y_max': height * 0.65
        }
        
        print(f"📍 Поиск технических требований в области: {tech_requirements_area}")
        
        # Собираем ВСЕ текстовые элементы из области техтребований
        all_tech_texts = []
        
        for block in text_dict.get('blocks', []):
            if block['type'] == 0:
                for line in block['lines']:
                    for span in line['spans']:
                        bbox = span['bbox']
                        span_center_x = (bbox[0] + bbox[2]) / 2
                        span_center_y = (bbox[1] + bbox[3]) / 2
                        
                        # Проверяем, находится ли span в области технических требований
                        if (tech_requirements_area['x_min'] <= span_center_x <= tech_requirements_area['x_max'] and
                            tech_requirements_area['y_min'] <= span_center_y <= tech_requirements_area['y_max']):
                            
                            text = span.get('text', '').strip()
                            if text:  # Сохраняем ВСЕ тексты, даже короткие
                                tech_spans.append({
                                    'text': text,
                                    'bbox': bbox,
                                    'position': (span_center_x, span_center_y)
                                })
                                all_tech_texts.append({
                                    'text': text,
                                    'y_position': span_center_y
                                })
                                print(f"  📍 Найден текст в области техтребований: '{text}' в позиции ({span_center_x:.1f}, {span_center_y:.1f})")
        
        # Сортируем тексты по вертикальной позиции (сверху вниз)
        all_tech_texts.sort(key=lambda x: x['y_position'])
        
        # Формируем полный текст техтребований
        for item in all_tech_texts:
            tech_text += item['text'] + "\n"
            tech_lines.append(item['text'])
        
        print(f"📍 Собрано текстов в области техтребований: {len(all_tech_texts)}")
        print(f"📍 Полный текст техтребований: '{tech_text[:100]}...'")
        
        # Если не нашли достаточно текста, используем улучшенный поиск по содержанию
        if len(tech_text.strip()) < 10:
            print("📍 Мало текста в области техтребований, поиск по содержанию...")
            content_tech_text = self._find_tech_requirements_by_content(raw_text)
            if content_tech_text:
                tech_lines = content_tech_text.split('\n')
                tech_text = content_tech_text
                print(f"📍 Найдены техтребования по содержанию: {len(tech_lines)} строк")
        
        return {'text': tech_text.strip(), 'lines': tech_lines, 'spans': tech_spans}


    def _find_tech_requirements_by_content(self, raw_text: str) -> str:
        """Улучшенный поиск технических требований по содержанию"""
        lines = raw_text.split('\n')
        tech_lines = []
        in_tech_section = False
        tech_section_started = False
        
        # Ключевые слова для поиска технических требований
        tech_start_keywords = [
            'размеры', 'обработать', 'поверхность', 'допуск', 'шероховатость',
            'технические', 'требования', '1 *', '2 *', '3 *', '1.', '2.', '3.'
        ]
        
        tech_content_keywords = [
            'размер', 'обработ', 'поверхност', 'допуск', 'шероховатость',
            'покрытие', 'защит', 'качество', 'точность', 'сборк', 'свар'
        ]
        
        end_keywords = ['примечания', 'литература', 'таблица', 'рисунок', '---']
        
        for i, line in enumerate(lines):
            clean_line = line.strip()
            if not clean_line:
                continue
            
            # Проверяем начало технических требований
            if not in_tech_section:
                # Ищем начало по ключевым словам или нумерации
                if (any(keyword in clean_line.lower() for keyword in tech_start_keywords) or
                    re.match(r'^\d+[\.\*\)]\s', clean_line) or
                    re.match(r'^\d+\s*[\.\*\)]\s', clean_line)):
                    
                    # Проверяем, что это действительно техническое содержание
                    has_tech_content = any(keyword in clean_line.lower() for keyword in tech_content_keywords)
                    if has_tech_content or re.match(r'^\d+[\.\*\)]\s', clean_line):
                        in_tech_section = True
                        tech_section_started = True
                        print(f"📍 Начало техтребований найдено: '{clean_line}'")
            
            # Если мы в разделе технических требований
            if in_tech_section:
                # Проверяем конец раздела
                if any(end_keyword in clean_line.lower() for end_keyword in end_keywords):
                    print(f"📍 Конец техтребований: '{clean_line}'")
                    break
                
                # Добавляем строку если она имеет техническое содержание или является частью нумерованного списка
                if (any(keyword in clean_line.lower() for keyword in tech_content_keywords) or
                    re.match(r'^\d+[\.\*\)]\s', clean_line) or
                    re.match(r'^[•\-\*]\s', clean_line) or
                    tech_section_started):
                    
                    tech_lines.append(clean_line)
                    
                    # Если это начало следующего раздела после длинного пробела, прекращаем
                    if (len(tech_lines) > 3 and 
                        len(clean_line) < 20 and 
                        not any(keyword in clean_line.lower() for keyword in tech_content_keywords) and
                        not re.match(r'^\d+[\.\*\)]\s', clean_line)):
                        break
        
        tech_text = "\n".join(tech_lines)
        
        # Проверяем, что нашли достаточно технического содержания
        if tech_text and len(tech_text) > 10:
            tech_word_count = sum(1 for keyword in tech_content_keywords if keyword in tech_text.lower())
            if tech_word_count >= 1:  # Хотя бы одно техническое ключевое слово
                return tech_text
        
        return ""

    def _analyze_elements(self, drawing_text: str, tech_text: str, page_num: int) -> dict:
        """Анализ найденных элементов с улучшенной обработкой"""
        elements = {
            'codes': [],
            'letters': [],
            'asterisks': {'single': [], 'double': [], 'triple': []},
            'dimensions': [],
            'tolerances': [],
            'bases': [],
            'arrows': [],
            'lines': [],
            'roughness': {'drawing': [], 'tech': []}  # ДОБАВЛЯЕМ ШЕРОХОВАТОСТИ
        }
        
        print(f"\n🔍 АНАЛИЗ ЭЛЕМЕНТОВ СТРАНИЦЫ {page_num}:")
        print(f"   Общий текст: {len(drawing_text)} символов")
        print(f"   Техтребования: '{tech_text[:100]}...'")  # Показываем начало текста
        
        # Извлекаем шероховатости из обоих источников
        drawing_roughness = self._extract_roughness_from_text(drawing_text)
        tech_roughness = self._extract_roughness_from_text(tech_text)
        
        elements['roughness'] = {
            'drawing': drawing_roughness,
            'tech': tech_roughness
        }
        
        print(f"   Шероховатости на чертеже: {drawing_roughness}")
        print(f"   Шероховатости в техтребованиях: {tech_roughness}")
        
        # Коды документов
        code_patterns = [
            r'[А-ЯA-Z]{2,4}[\.\-]\d+[\.\-]\d+[А-ЯA-Z]{2,3}',
            r'[А-ЯA-Z]{2,4}\d+\.\d+[А-ЯA-Z]{2,3}',
        ]
        
        for pattern in code_patterns:
            found_codes = re.findall(pattern, drawing_text, re.IGNORECASE)
            elements['codes'].extend(found_codes)
            if found_codes:
                print(f"   📄 Найдены коды: {found_codes}")
        
        # УЛУЧШЕННЫЙ ПОИСК БУКВ - ищем отдельно стоящие заглавные буквы
        drawing_letters = self._find_standalone_letters(drawing_text)
        tech_letters = self._find_standalone_letters(tech_text)
        
        elements['letters'] = drawing_letters
        elements['tech_letters'] = tech_letters
        
        if drawing_letters:
            print(f"   🔤 Найдены буквенные обозначения на чертеже: {drawing_letters}")
        if tech_letters:
            print(f"   🔤 Найдены буквенные обозначения в техтребованиях: {tech_letters}")
        
        # УЛУЧШЕННЫЙ ПОИСК ЗВЕЗДОЧЕК - исключаем дублирование
        all_asterisks = re.findall(r'\d+\*+|\*+\d+', drawing_text)
        
        # Разделяем по типам звездочек
        for ast in all_asterisks:
            if '***' in ast:
                elements['asterisks']['triple'].append(ast)
            elif '**' in ast:
                elements['asterisks']['double'].append(ast)
            elif '*' in ast:
                elements['asterisks']['single'].append(ast)
        
        # Убираем дубликаты
        for ast_type in elements['asterisks']:
            elements['asterisks'][ast_type] = list(set(elements['asterisks'][ast_type]))
        
        # Выводим результаты
        for ast_type in ['single', 'double', 'triple']:
            if elements['asterisks'][ast_type]:
                ast_name = self._get_asterisk_name(ast_type)
                print(f"   ⭐ {ast_name}: {elements['asterisks'][ast_type]}")
        
        # Размеры - улучшенный поиск
        dimension_patterns = [
            r'\d+[.,]?\d*\s*[ммсм]',  # с единицами измерения
            r'\d+[.,]?\d*\s*°',        # явные угловые
            r'[±]?\d+[.,]?\d*',        # числовые значения
            r'R\d+[.,]?\d*',           # радиусы
            r'⌀\d+[.,]?\d*',          # диаметры
            r'\d+\s*град',             # "45 град"
            r'\d+\s*deg',              # англ. вариант
        ]
        all_dimensions = []
        for pattern in dimension_patterns:
            dimensions = re.findall(pattern, drawing_text, re.IGNORECASE)
            all_dimensions.extend(dimensions)
        
        elements['dimensions'] = list(set(all_dimensions))
        
        if elements['dimensions']:
            print(f"   📏 Найдены размеры ({len(elements['dimensions'])} шт): {elements['dimensions'][:10]}")
        
        # Допуски и базы
        for symbol in Config.TOLERANCE_SYMBOLS:
            if symbol in drawing_text:
                elements['tolerances'].append(symbol)
                print(f"   ⚙️ Найден символ допуска: {symbol}")
                base_matches = re.findall(f'{re.escape(symbol)}[\\s]*([A-Z{Config.BASE_SEPARATOR}]+)', drawing_text)
                if base_matches:
                    elements['bases'].extend(base_matches)
                    print(f"   🎯 Найдены базы для {symbol}: {base_matches}")
        
        return elements
    
    def _extract_roughness_from_text(self, text: str) -> list:
        """Извлекает обозначения шероховатости из текста"""
        roughness_patterns = [
            r'R[az]\s*\d+[.,]?\d*',  # Ra 3.2, Rz 50
            r'R[az]\d+[.,]?\d*',     # Ra3.2, Rz50
            r'шероховатость\s*R[az]\s*\d+[.,]?\d*',  # шероховатость Ra 3.2
        ]
        
        found_roughness = []
        for pattern in roughness_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Нормализуем формат
                normalized = re.sub(r'\s+', ' ', match.strip())
                found_roughness.append(normalized)
        
        return list(set(found_roughness))  # Убираем дубликаты

    def _find_standalone_letters(self, text: str) -> list:
        """Поиск отдельно стоящих заглавных букв (не в составе слов или кодов)"""
        standalone_pattern = r'(?<!\w)[A-ZА-Я](?!\w)'
        all_letters = re.findall(standalone_pattern, text)
        
        common_drawing_letters = {'A', 'B', 'C', 'D', 'X', 'Y', 'Z', 'I', 'V', 'L', 'M', 'N', 'O', 'P', 'R', 'S', 'T','H','Т','Н'}
        
        dimension_letters = set()
        dimension_patterns = [r'R\d', r'⌀\d', r'[A-Z]\d', r'\d[A-Z]']
        for pattern in dimension_patterns:
            dimension_matches = re.findall(pattern, text)
            for match in dimension_matches:
                if len(match) == 2 and match[0].isalpha():
                    dimension_letters.add(match[0])
                elif len(match) == 2 and match[1].isalpha():
                    dimension_letters.add(match[1])
        
        filtered_letters = []
        for letter in all_letters:
            if (letter not in common_drawing_letters and 
                letter not in dimension_letters and
                letter not in filtered_letters):
                filtered_letters.append(letter)
        
        return filtered_letters

    def _analyze_graphic_elements(self, drawings: list, text_dict: dict, page) -> dict:
        """Анализ графических элементов (линий, стрелок)"""
        graphic_analysis = {
            'lines': [],
            'arrows': [],
            'dimension_lines': [],
            'extension_lines': [],
            'dimension_elements': [],
            'tolerance_frames': [],
            'dimension_texts': []
        }
        
        print(f"\n📐 АНАЛИЗ ГРАФИЧЕСКИХ ЭЛЕМЕНТОВ:")
        print(f"   Drawing objects: {len(drawings)}")
        
        # Анализируем линии из drawings
        for drawing in drawings:
            items = drawing.get('items', [])
            for item in items:
                if item[0] == 'l':  # line
                    line_data = {
                        'type': 'line',
                        'start': item[1],
                        'end': item[2],
                        'length': self._calculate_distance(item[1], item[2]),
                        'angle': self._calculate_angle(item[1], item[2]),
                        'color': item[3] if len(item) > 3 else (0, 0, 0),
                        'width': item[4] if len(item) > 4 else 1.0
                    }
                    graphic_analysis['lines'].append(line_data)
                    
                    # Определяем стрелки (короткие линии под углом)
                    if 2 <= line_data['length'] <= 8:
                        if 50 <= abs(line_data['angle']) <= 70 or 110 <= abs(line_data['angle']) <= 130:
                            graphic_analysis['arrows'].append(line_data)
        
        print(f"   📏 Линий: {len(graphic_analysis['lines'])}")
        print(f"   🏹 Стрелок: {len(graphic_analysis['arrows'])}")
        
        # Анализируем текстовые элементы для определения размерных линий
        for block in text_dict.get('blocks', []):
            if block['type'] == 0:
                for line in block['lines']:
                    for span in line['spans']:
                        text = span.get('text', '').strip()
                        if not text:
                            continue
                        bbox = span['bbox']
                        position = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]

                        is_numeric = bool(re.search(r'\d', text))
                        if not is_numeric:
                            continue

                        core_text = re.sub(r'[\*\s]+$', '', text)
                        if not core_text:
                            continue

                        is_dimension = bool(re.match(
                            r'^[±]?\d+[.,]?\d*[°ммсмR⌀]?$|'
                            r'^R\d+[.,]?\d*$|'
                            r'^⌀\d+[.,]?\d*$|'
                            r'^\d+[.,]?\d*\s*°$|'
                            r'^\d+\s*(град|deg)$',
                            core_text, re.IGNORECASE
                        ))

                        if not is_dimension:
                            continue

                        is_angular = any(ind in text.lower() for ind in ['°', 'град', 'deg', 'угол', '∠'])

                        text_data = {
                            'text': text,
                            'position': position,
                            'rotation': span.get('rot', 0),
                            'font_size': span.get('size', 10),
                            'bbox': bbox,
                            'is_angular': is_angular
                        }
                        graphic_analysis['dimension_texts'].append(text_data)

                        if any(symbol in text for symbol in Config.TOLERANCE_SYMBOLS):
                            graphic_analysis['tolerance_frames'].append({
                                'text': text,
                                'position': position,
                                'rotation': span.get('rot', 0),
                                'bbox': bbox
                            })
        
        print(f"   🔢 Размерных чисел: {len(graphic_analysis['dimension_texts'])}")
        print(f"   ⚙️ Рамок допусков: {len(graphic_analysis['tolerance_frames'])}")
        
        graphic_analysis['dimension_elements'] = self._analyze_dimension_elements(
            graphic_analysis['lines'], 
            graphic_analysis['dimension_texts']
        )
        
        return graphic_analysis

    def _analyze_dimension_elements(self, lines, dimension_texts):
        """Анализ размерных элементов с fallback по ориентации текста"""
        dimension_elements = []
        for text_elem in dimension_texts:
            nearby_lines = []
            shelf_lines = []
            dimension_direction = None

            for line in lines:
                distance = self._distance_to_line(line['start'], line['end'], text_elem['position'])
                if distance < 20:
                    nearby_lines.append(line)
                if distance <= 8 and (abs(line['angle']) < 15 or abs(line['angle'] - 180) < 15):
                    shelf_lines.append(line)

            if nearby_lines:
                closest_line = min(nearby_lines, key=lambda l: self._distance_to_line(l['start'], l['end'], text_elem['position']))
                dimension_direction = closest_line['angle']
            else:
                dimension_direction = text_elem['rotation']

            dimension_elements.append({
                'text': text_elem['text'],
                'position': text_elem['position'],
                'rotation': text_elem['rotation'],
                'font_size': text_elem['font_size'],
                'nearby_lines': nearby_lines,
                'shelf_lines': shelf_lines,
                'dimension_direction': dimension_direction,
                'is_angular': text_elem.get('is_angular', False),
                'bbox': text_elem.get('bbox', [])
            })
        return dimension_elements

    def _is_in_30_degree_zone(self, angle):
        """Проверяет, находится ли угол в зоне 30° от горизонтали или вертикали"""
        if angle is None:
            return False
        
        normalized_angle = angle % 180
        horizontal_zone = (0 <= normalized_angle <= 30) or (150 <= normalized_angle <= 180)
        vertical_zone = 60 <= normalized_angle <= 120
        
        return horizontal_zone or vertical_zone

    def _is_text_horizontal(self, rotation):
        """Проверяет, является ли текст горизонтальным"""
        return abs(rotation) < 10 or abs(rotation - 180) < 10

    def _calculate_distance(self, point1, point2):
        """Вычисление расстояния между двумя точками"""
        return math.sqrt((point2[0] - point1[0])**2 + (point2[1] - point1[1])**2)

    def _calculate_angle(self, point1, point2):
        """Вычисление угла линии в диапазоне [0, 180]"""
        dx = point2[0] - point1[0]
        dy = point2[1] - point1[1]
        if dx == 0:
            return 90
        angle = math.degrees(math.atan2(dy, dx))
        return angle if angle >= 0 else angle + 180

    def _distance_to_line(self, line_start, line_end, point):
        """Расстояние от точки до линии"""
        x1, y1 = line_start
        x2, y2 = line_end
        x0, y0 = point
        
        numerator = abs((y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1)
        denominator = math.sqrt((y2-y1)**2 + (x2-x1)**2)
        
        return numerator / denominator if denominator != 0 else float('inf')

    def _print_detailed_diagnostics(self, analysis: dict, width: float, height: float, page_num: int=1):
        """Детальная диагностика найденных элементов"""
        print(f"\n📊 ДЕТАЛЬНАЯ ДИАГНОСТИКА СТРАНИЦЫ {page_num}:")
        print(f"   📋 ОСНОВНАЯ НАДПИСЬ: '{analysis['title_block']['text'][:100]}...'")
        print(f"   📋 ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ: '{analysis['tech_requirements']['text'][:100]}...'")
        print(f"   📋 ПОЛЕ ЧЕРТЕЖА: {len(analysis['drawing_area']['text'])} символов")
        
        elements = analysis['found_elements']
        print(f"   🔍 НАЙДЕНО:")
        print(f"      • Кодов: {len(elements['codes'])}")
        print(f"      • Букв на чертеже: {len(elements['letters'])}")
        print(f"      • Букв в техтребованиях: {len(elements.get('tech_letters', []))}")
        print(f"      • Размеров: {len(elements['dimensions'])}")
        print(f"      • Допусков: {len(elements['tolerances'])}")
        print(f"      • Баз: {len(elements['bases'])}")
        total_asterisks = sum(len(v) for v in elements['asterisks'].values())
        print(f"      • Звездочек: {total_asterisks}")

    def _get_asterisk_name(self, ast_type: str) -> str:
        names = {
            'single': 'Одинарные звездочки (*)',
            'double': 'Двойные звездочки (**)', 
            'triple': 'Тройные звездочки (***)'
        }
        return names.get(ast_type, ast_type)

# =============================================================================
# PRECISE RULE ENGINE (с улучшенными проверками 1.1.5 и 1.1.6)
# =============================================================================
class PreciseRuleEngine:
    def __init__(self):
        self.document_codes = Config.DOCUMENT_CODES

    def run_all_checks(self, document_data: dict) -> dict:
        """ТОЧНЫЕ проверки с конкретными сообщениями"""
        text_data = document_data['text_data']
        
        if not text_data.get('pages'):
            return self._empty_result()

        violations = []
        
        # Получаем техтребования с первой страницы
        first_page_tech_requirements = text_data.get('first_page_tech_requirements', '')
        
        print(f"\n📋 ОБЩИЕ ТЕХТРЕБОВАНИЯ С ПЕРВОЙ СТРАНИЦЫ:")
        print(f"'{first_page_tech_requirements[:200]}...'")
        
        for page in text_data['pages']:
            analysis = page['analysis']
            page_num = page['page_number']
            
            print(f"\n🔍 ПРОВЕРКА СТРАНИЦЫ {page_num}:")
            
            # 1.1.1 - Конкретная проверка кода
            violations.extend(self._check_1_1_1_precise(page, analysis))
            
            # 1.1.3 - УЛУЧШЕННАЯ проверка буквенных обозначений (используем техтребования с первой страницы)
            violations.extend(self._check_1_1_3_precise(page, analysis, first_page_tech_requirements))
            
            # 1.1.4 - УЛУЧШЕННАЯ проверка звездочек (используем техтребования с первой страницы)
            violations.extend(self._check_1_1_4_precise(page, analysis, first_page_tech_requirements))
            
            # 1.1.5 - УЛУЧШЕННАЯ проверка размеров в зоне 30°
            violations.extend(self._check_1_1_5_precise(page, analysis))
            
            # 1.1.6 - УЛУЧШЕННАЯ проверка угловых размеров
            violations.extend(self._check_1_1_6_precise(page, analysis))
            
            # 1.1.8 - Точная проверка обозначений баз
            violations.extend(self._check_1_1_8_precise(page, analysis))

            # НОВАЯ ПРОВЕРКА 1.1.9
            violations.extend(self._check_1_1_9_precise(page, analysis, first_page_tech_requirements))

        
        
        print(f"\n📈 ИТОГО НАРУШЕНИЙ: {len(violations)}")
        
        stats = {
            'total_violations': len(violations),
            'high_severity': len([v for v in violations if v['severity'] == 'high']),
            'medium_severity': len([v for v in violations if v['severity'] == 'medium']),
            'low_severity': len([v for v in violations if v['severity'] == 'low'])
        }

        return {
            'violations': violations,
            'statistics': stats,
            'is_compliant': len([v for v in violations if v['severity'] in ['high', 'medium']]) == 0
        }

    def _check_1_1_1_precise(self, page: dict, analysis: dict) -> list:
        """1.1.1 - КОНКРЕТНАЯ проверка основной надписи (без дублирования)"""
        violations = []
        page_num = page['page_number']
        title_text = analysis['title_block']['text']
        found_codes = analysis['found_elements']['codes']
        
        print(f"   1.1.1 Основная надпись: '{title_text[:50]}...'")
        print(f"   1.1.1 Найдены коды: {found_codes}")
        
        # Убираем дубликаты кодов
        unique_codes = list(set(found_codes))
        print(f"   1.1.1 Уникальные коды: {unique_codes}")
        
        if not unique_codes:
            violations.append({
                'rule_id': '1.1.1',
                'rule_text': 'Проверка заполнения основной надписи: код документа',
                'violation': 'В основной надписи НЕ НАЙДЕН код документа',
                'location': f'Страница {page_num}, основная надпись',
                'severity': 'high',
                'recommendation': 'Добавьте код документа в формате: ОРГАНИЗАЦИЯ.НОМЕР.ВЕРСИЯТИП'
            })
            return violations
        
        # Проверяем только уникальные коды
        for code in unique_codes:
            doc_type_match = re.search(r'[А-ЯA-Z]{2,3}$', code)
            if not doc_type_match:
                violations.append({
                    'rule_id': '1.1.1',
                    'rule_text': 'Проверка заполнения основной надписи: формат кода',
                    'violation': f'Код "{code}" имеет нестандартный формат',
                    'location': f'Страница {page_num}',
                    'severity': 'high',
                    'recommendation': 'Используйте формат с 2-3 буквами типа в конце'
                })
                continue
            
            doc_type = doc_type_match.group()
            
            if doc_type not in self.document_codes:
                violations.append({
                    'rule_id': '1.1.1',
                    'rule_text': 'Проверка заполнения основной надписи: тип документа',
                    'violation': f'Тип документа "{doc_type}" в коде "{code}" НЕ СУЩЕСТВУЕТ в классификаторе',
                    'location': f'Страница {page_num}, код: {code}',
                    'severity': 'high',
                    'recommendation': f'Используйте существующие типы: {", ".join(self.document_codes.keys())}'
                })
                continue
            
            expected_name = self.document_codes[doc_type]
            
            if expected_name.lower() not in title_text.lower():
                violations.append({
                    'rule_id': '1.1.1',
                    'rule_text': 'Проверка заполнения основной надписи: соответствие кода и наименования',
                    'violation': f'Код "{code}" указывает на "{expected_name}", но в основной надписи это НЕ УКАЗАНО',
                    'location': f'Страница {page_num}, основная надпись',
                    'severity': 'high',
                    'recommendation': f'Замените наименование в основной надписи на: "{expected_name}"'
                })
        
        return violations

    def _check_1_1_3_precise(self, page: dict, analysis: dict, first_page_tech_requirements: str) -> list:
        """1.1.3 - УЛУЧШЕННАЯ проверка буквенных обозначений (с использованием техтребований с первой страницы)"""
        violations = []
        page_num = page['page_number']
        drawing_letters = analysis['found_elements']['letters']
        
        # Используем техтребования с первой страницы для всех страниц
        tech_letters = self._find_standalone_letters(first_page_tech_requirements)
        
        print(f"   1.1.3 Буквы на чертеже (стр. {page_num}): {drawing_letters}")
        print(f"   1.1.3 Буквы в техтребованиях (с 1 стр.): {tech_letters}")
        
        # Если нет букв ни на чертеже, ни в техтребованиях - это не ошибка
        if not drawing_letters and not tech_letters:
            print(f"   1.1.3 Буквенные обозначения не используются - проверка пройдена")
            return violations
        
        # Случай 1: Буквы есть на чертеже, но нет раздела техтребований
        if drawing_letters and not first_page_tech_requirements.strip():
            violations.append({
                'rule_id': '1.1.3',
                'rule_text': 'Проверка согласованности буквенных обозначений',
                'violation': f'На чертеже есть буквы {", ".join(drawing_letters)}, но РАЗДЕЛА технических требований НЕТ для их пояснения',
                'location': f'Страница {page_num}',
                'severity': 'medium',
                'recommendation': 'Добавьте раздел "Технические требования" на первой странице с пояснениями для каждой буквы'
            })
            return violations
        
        # Случай 2: Буквы есть на чертеже, но отсутствуют в техтребованиях
        missing_in_tech = []
        for letter in drawing_letters:
            if letter not in tech_letters:
                missing_in_tech.append(letter)
        
        if missing_in_tech:
            violations.append({
                'rule_id': '1.1.3',
                'rule_text': 'Проверка согласованности буквенных обозначений',
                'violation': f'Буквы {", ".join(missing_in_tech)} ИСПОЛЬЗУЮТСЯ на чертеже (стр. {page_num}), но НЕ ПОЯСНЕНЫ в технических требованиях на первой странице',
                'location': f'Страница {page_num}, технические требования (стр. 1)',
                'severity': 'medium',
                'recommendation': f'Добавьте в технические требования на первой странице пояснения для букв: {", ".join(missing_in_tech)}'
            })
        
        # Случай 3: Буквы есть в техтребованиях, но отсутствуют на чертеже
        missing_in_drawing = []
        for letter in tech_letters:
            if letter not in drawing_letters:
                missing_in_drawing.append(letter)
        
        if missing_in_drawing:
            violations.append({
                'rule_id': '1.1.3',
                'rule_text': 'Проверка согласованности буквенных обозначений',
                'violation': f'Буквы {", ".join(missing_in_drawing)} УКАЗАНЫ в технических требованиях на первой странице, но НЕ ИСПОЛЬЗУЮТСЯ на чертеже (стр. {page_num})',
                'location': f'Страница {page_num}, поле чертежа',
                'severity': 'medium',
                'recommendation': f'Используйте буквы {", ".join(missing_in_drawing)} на чертеже или удалите их из технических требований на первой странице'
            })
        
        # Если все буквы согласованы
        if not missing_in_tech and not missing_in_drawing and (drawing_letters or tech_letters):
            print(f"   1.1.3 Все буквенные обозначения согласованы - проверка пройдена")
        
        return violations

    def _check_1_1_4_precise(self, page: dict, analysis: dict, first_page_tech_requirements: str) -> list:
        """1.1.4 - УЛУЧШЕННАЯ проверка звездочек (с использованием техтребований с первой страницы)"""
        violations = []
        page_num = page['page_number']
        asterisks = analysis['found_elements']['asterisks']
        
        found_any = False
        
        # Проверяем звездочки на чертеже
        for ast_type in ['single', 'double', 'triple']:
            ast_list = asterisks[ast_type]
            if ast_list:
                found_any = True
                ast_name = self._get_asterisk_name(ast_type)
                print(f"   1.1.4 Найдены {ast_name} на стр. {page_num}: {ast_list}")
                
                if not first_page_tech_requirements.strip():
                    violations.append({
                        'rule_id': '1.1.4',
                        'rule_text': 'Проверка звездочек',
                        'violation': f'{ast_name} {", ".join(ast_list)} есть на чертеже (стр. {page_num}), но РАЗДЕЛА технических требований НЕТ для их пояснения',
                        'location': f'Страница {page_num}, поле чертежа',
                        'severity': 'medium',
                        'recommendation': f'Добавьте раздел "Технические требования" на первой странице с пояснениями для {ast_name.lower()}'
                    })
                else:
                    tech_asterisks = self._count_tech_asterisks(first_page_tech_requirements, ast_type)
                    if tech_asterisks == 0:
                        violations.append({
                            'rule_id': '1.1.4',
                            'rule_text': 'Проверка звездочек',
                            'violation': f'{ast_name} {", ".join(ast_list)} есть на чертеже (стр. {page_num}), но ОТСУТСТВУЮТ в технических требованиях на первой странице',
                            'location': f'Страница {page_num}, технические требования (стр. 1)',
                            'severity': 'medium',
                            'recommendation': f'Добавьте в технические требования на первой странице пояснения для {ast_name.lower()}'
                        })
        
        # НОВАЯ ПРОВЕРКА: звездочки в техтребованиях без соответствующих размеров на чертеже
        for ast_type in ['single', 'double', 'triple']:
            tech_asterisks_count = self._count_tech_asterisks(first_page_tech_requirements, ast_type)
            drawing_asterisks_count = len(asterisks[ast_type])
            
            if tech_asterisks_count > 0 and drawing_asterisks_count == 0:
                ast_name = self._get_asterisk_name(ast_type)
                violations.append({
                    'rule_id': '1.1.4',
                    'rule_text': 'Проверка согласованности звездочек',
                    'violation': f'{ast_name} указаны в технических требованиях на первой странице, но отсутствуют на чертеже (стр. {page_num})',
                    'location': f'Страница {page_num}, технические требования (стр. 1)',
                    'severity': 'medium',
                    'recommendation': f'Добавьте на чертеж (стр. {page_num}) размеры с {ast_name.lower()} или удалите их из технических требований на первой странице'
                })
        
        if not found_any:
            print(f"   1.1.4 Звездочки не найдены на стр. {page_num}")
        
        return violations

    def _check_1_1_5_precise(self, page: dict, analysis: dict) -> list:
        """1.1.5 - Проверка размеров в зоне 30°: текст должен быть горизонтальным"""
        violations = []
        page_num = page['page_number']
        graphic_analysis = analysis['graphic_analysis']
        dimension_elements = graphic_analysis['dimension_elements']
        print(f"   1.1.5 Анализ размеров на стр. {page_num}: всего {len(dimension_elements)} элементов")
        
        if not dimension_elements:
            print(f"   1.1.5 Размерные элементы не найдены на стр. {page_num}")
            return violations

        analyzer = DocumentAnalyzer()
        for i, element in enumerate(dimension_elements):
            if element.get('is_angular', False):
                continue

            dimension_direction = element.get('dimension_direction')
            text_rotation = element.get('rotation', 0)
            position = element.get('position', [0, 0])
            
            if dimension_direction is None:
                dimension_direction = text_rotation

            in_zone = analyzer._is_in_30_degree_zone(dimension_direction)
            is_horizontal = analyzer._is_text_horizontal(text_rotation)
            
            print(f"      [{i+1}] Размер: '{element['text']}', направление: {dimension_direction:.1f}°, "
                  f"поворот текста: {text_rotation:.1f}°, в зоне 30°: {in_zone}, горизонтален: {is_horizontal}")

            if in_zone and not is_horizontal:
                violations.append({
                    'rule_id': '1.1.5',
                    'rule_text': 'Проверка простановки размеров на полке линии выноски при их попадании в зону 30°',
                    'violation': f'Размер "{element["text"]}" находится в зоне 30°, но текст не горизонтален (угол: {text_rotation:.1f}°)',
                    'location': f'Страница {page_num}, координаты ({position[0]:.1f}, {position[1]:.1f})',
                    'severity': 'medium',
                    'recommendation': 'В зоне 30° от горизонтали/вертикали размерные числа должны быть расположены горизонтально.'
                })
        return violations

    def _check_1_1_6_precise(self, page: dict, analysis: dict) -> list:
        """1.1.6 - Проверка угловых размеров в зоне 30°: текст должен быть горизонтальным"""
        violations = []
        page_num = page['page_number']
        graphic_analysis = analysis['graphic_analysis']
        dimension_elements = graphic_analysis['dimension_elements']
        print(f"   1.1.6 Анализ угловых размеров на стр. {page_num}: всего {len(dimension_elements)} элементов")
        
        if not dimension_elements:
            return violations

        analyzer = DocumentAnalyzer()
        angular_elements = [elem for elem in dimension_elements if elem.get('is_angular', False)]
        print(f"      Найдено угловых размеров на стр. {page_num}: {len(angular_elements)}")
        
        for i, element in enumerate(angular_elements):
            dimension_direction = element.get('dimension_direction')
            text_rotation = element.get('rotation', 0)
            position = element.get('position', [0, 0])
            
            if dimension_direction is None:
                dimension_direction = text_rotation

            in_zone = analyzer._is_in_30_degree_zone(dimension_direction)
            is_horizontal = analyzer._is_text_horizontal(text_rotation)
            
            print(f"      [{i+1}] Угловой размер: '{element['text']}', направление: {dimension_direction:.1f}°, "
                  f"поворот текста: {text_rotation:.1f}°, в зоне 30°: {in_zone}, горизонтален: {is_horizontal}")

            if in_zone and not is_horizontal:
                violations.append({
                    'rule_id': '1.1.6',
                    'rule_text': 'Проверка простановки угловых размеров на полке линии выноски при их попадании в зону 30°',
                    'violation': f'Угловой размер "{element["text"]}" находится в зоне 30°, но текст не горизонтален (угол: {text_rotation:.1f}°)',
                    'location': f'Страница {page_num}, координаты ({position[0]:.1f}, {position[1]:.1f})',
                    'severity': 'medium',
                    'recommendation': 'Угловые размеры в зоне 30° должны быть расположены горизонтально на полке линии-выноски.'
                })
        return violations

    def _check_1_1_8_precise(self, page: dict, analysis: dict) -> list:
        """1.1.8 - ТОЧНАЯ проверка обозначений баз"""
        return self.check_datum_letter_consistency(page, analysis)

    def check_datum_letter_consistency(self, page: dict, analysis: dict) -> list:
        """1.1.8 - Проверка наличия и соответствия буквенных обозначений баз"""
        violations = []
        page_num = page['page_number']
        
        print(f"   1.1.8 Проверка обозначений баз на стр. {page_num}")
        
        all_capital_letters = analysis['found_elements']['letters']
        print(f"   1.1.8 Все заглавные буквы на чертеже (стр. {page_num}): {all_capital_letters}")
        
        declared_bases = self._find_bases_by_surrounding_graphics(page, analysis, all_capital_letters)
        print(f"   1.1.8 Объявленные базы на чертеже (стр. {page_num}): {declared_bases}")
        
        if not declared_bases:
            print(f"   1.1.8 Базы не найдены на стр. {page_num} - проверка пройдена")
            return violations
        
        base_counts = {}
        for base in declared_bases:
            base_counts[base] = base_counts.get(base, 0) + 1
        
        print(f"   1.1.8 Количество баз по типам на стр. {page_num}: {base_counts}")
        
        bases_without_pairs = []
        for base_letter, count in base_counts.items():
            if count < 2:
                bases_without_pairs.append(base_letter)
        
        if bases_without_pairs:
            violations.append({
                'rule_id': '1.1.8',
                'rule_text': 'Проверка наличия и соответствия буквенных обозначений баз',
                'violation': f'Для баз {", ".join(bases_without_pairs)} найдено только по одному экземпляру на стр. {page_num}, требуется минимум два',
                'location': f'Страница {page_num}, поле чертежа',
                'severity': 'medium',
                'recommendation': f'Добавьте второй экземпляр для баз: {", ".join(bases_without_pairs)}'
            })
        else:
            print(f"   1.1.8 Все базы имеют пары на стр. {page_num} - проверка пройдена")
        
        return violations

    def _find_bases_by_surrounding_graphics(self, page: dict, analysis: dict, letters: list) -> list:
        """Ищет базы по наличию графических элементов вокруг букв"""
        bases = []
        text_dict = page.get('text_dict', {})
        drawings = page.get('drawings', [])
        
        print(f"   1.1.8 Анализ букв на наличие графического окружения")
        
        letter_instances = []
        for block in text_dict.get('blocks', []):
            if block['type'] == 0:
                for line in block['lines']:
                    for span in line['spans']:
                        text = span.get('text', '').strip()
                        bbox = span.get('bbox', [])
                        
                        if text in letters:
                            center_x = (bbox[0] + bbox[2]) / 2
                            center_y = (bbox[1] + bbox[3]) / 2
                            letter_instances.append({
                                'letter': text,
                                'position': (center_x, center_y),
                                'bbox': bbox
                            })
                            print(f"   1.1.8 Буква '{text}' в позиции ({center_x:.1f}, {center_y:.1f})")
        
        print(f"   1.1.8 Найдено экземпляров букв: {len(letter_instances)}")
        
        for instance in letter_instances:
            letter = instance['letter']
            position = instance['position']
            
            graphic_elements_count = self._count_nearby_graphic_elements(drawings, position, 20.0)
            
            print(f"   1.1.8 Буква '{letter}' в ({position[0]:.1f}, {position[1]:.1f}): {graphic_elements_count} графических элементов рядом")
            
            if graphic_elements_count > 0:
                bases.append(letter)
                print(f"   1.1.8 Буква '{letter}' признана базой")
        
        return bases

    def _count_nearby_graphic_elements(self, drawings: list, point: tuple, radius: float) -> int:
        """Считает графические элементы в радиусе от точки"""
        count = 0
        point_x, point_y = point
        
        for drawing in drawings:
            items = drawing.get('items', [])
            for item in items:
                if item[0] == 'l':
                    start = item[1]
                    end = item[2]
                    
                    dist_start = self._calculate_distance(start, point)
                    dist_end = self._calculate_distance(end, point)
                    dist_line = self._distance_to_line(start, end, point)
                    
                    if dist_start <= radius or dist_end <= radius or dist_line <= radius:
                        count += 1
                
                elif item[0] == 're':
                    rect = item[1]
                    center_rect = ((rect[0] + rect[2])/2, (rect[1] + rect[3])/2)
                    distance = self._calculate_distance(center_rect, point)
                    if distance <= radius:
                        count += 1
        
        return count

    def _calculate_distance(self, point1, point2):
        return math.sqrt((point2[0] - point1[0])**2 + (point2[1] - point1[1])**2)

    def _distance_to_line(self, line_start, line_end, point):
        x1, y1 = line_start
        x2, y2 = line_end
        x0, y0 = point
        
        numerator = abs((y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1)
        denominator = math.sqrt((y2-y1)**2 + (x2-x1)**2)
        
        return numerator / denominator if denominator != 0 else float('inf')

    def _find_standalone_letters(self, text: str) -> list:
        """Поиск отдельно стоящих заглавных букв"""
        standalone_pattern = r'(?<!\w)[A-ZА-Я](?!\w)'
        all_letters = re.findall(standalone_pattern, text)
        
        common_drawing_letters = {'A', 'B', 'C', 'D', 'X', 'Y', 'Z', 'I', 'V', 'L', 'M', 'N', 'O', 'P', 'R', 'S', 'T','H','Т','Н'}
        
        dimension_letters = set()
        dimension_patterns = [r'R\d', r'⌀\d', r'[A-Z]\d', r'\d[A-Z]']
        for pattern in dimension_patterns:
            dimension_matches = re.findall(pattern, text)
            for match in dimension_matches:
                if len(match) == 2 and match[0].isalpha():
                    dimension_letters.add(match[0])
                elif len(match) == 2 and match[1].isalpha():
                    dimension_letters.add(match[1])
        
        filtered_letters = []
        for letter in all_letters:
            if (letter not in common_drawing_letters and 
                letter not in dimension_letters and
                letter not in filtered_letters):
                filtered_letters.append(letter)
        
        return filtered_letters
    

    def _check_1_1_9_precise(self, page: dict, analysis: dict, first_page_tech_requirements: str) -> list:
        """1.1.9 - Проверка наличия знака √ в скобках в углу шероховатости"""
        violations = []
        page_num = page['page_number']
        
        roughness_data = analysis['found_elements'].get('roughness', {})
        drawing_roughness = roughness_data.get('drawing', [])
        tech_roughness = roughness_data.get('tech', [])
        
        # Случай: шероховатость есть И на чертеже, И в техтребованиях
        if drawing_roughness and tech_roughness:
            # Проверяем наличие ОБЕИХ скобок в техтребованиях (даже на разных строках)
            has_opening = '(' in first_page_tech_requirements
            has_closing = ')' in first_page_tech_requirements
            has_both_brackets = has_opening and has_closing
            
            if not has_both_brackets:
                violations.append({
                    'rule_id': '1.1.9',
                    'rule_text': 'Проверка наличия знака √ в скобках в углу шероховатости',
                    'violation': f'Шероховатость указана и на чертеже ({", ".join(drawing_roughness)}), '
                                 f'и в технических требованиях ({", ".join(tech_roughness)}), '
                                 f'но отсутствуют скобки "(...)" в техтребованиях',
                    'location': f'Страница {page_num}, технические требования',
                    'severity': 'medium',
                    'recommendation': 'Добавьте открывающую и закрывающую скобки в технические требования: "Ra 12,5 (√)" или хотя бы "Ra 12,5 (...)"'
                })
            else:
                print(f"   1.1.9 Скобки найдены — проверка пройдена")
        
        # Во всех остальных случаях — нарушения нет (пункт пройден успешно)
        return violations

    def _has_roughness_checkmark(self, tech_text: str) -> bool:
        """Проверяет наличие знака √ или пары скобок () в техтребованиях рядом с шероховатостью"""
        if not tech_text:
            return False
        
        # Убираем переносы строк, но сохраняем информацию о них для проверки скобок
        clean_text = tech_text.replace('\r', ' ')
        lines = tech_text.split('\n')
        full_text_no_newlines = ' '.join(lines)
        
        # Паттерны с явным √ или \sqrt
        explicit_patterns = [
            r'R[az]\s*\d+[.,]?\d*\s*\(√\)',
            r'R[az]\s*\d+[.,]?\d*\s*\(\\sqrt\)',
            r'R[az].*?√',
            r'R[az].*?\\sqrt',
        ]
        for pattern in explicit_patterns:
            if re.search(pattern, full_text_no_newlines, re.IGNORECASE):
                return True
        
        # 🔹 НОВАЯ ЛОГИКА: если есть "Ra ... (" и где-то дальше ")"
        # Ищем строку с "R[az] ... ("
        has_opening = False
        has_closing = False
        for line in lines:
            line_clean = line.strip()
            if re.search(r'R[az]\s*\d+[.,]?\d*\s*\(', line_clean, re.IGNORECASE):
                has_opening = True
            if ')' in line_clean:
                has_closing = True
        
        if has_opening and has_closing:
            print("   1.1.9 Обнаружены открывающая и закрывающая скобки → считаем, что √ присутствует")
            return True
        
        return False


    def _contains_checkmark_indicator(self, text: str) -> bool:
        """Проверяет строку на наличие индикаторов знака корня"""
        checkmark_indicators = [
            '√', '\\sqrt', 'v', 'V', '✔', '✓', '∨', '∧'
        ]
        
        for indicator in checkmark_indicators:
            if indicator in text:
                print(f"   1.1.9 Найден индикатор знака корня: '{indicator}' в тексте: '{text}'")
                return True
        
        return False


    def _get_asterisk_name(self, ast_type: str) -> str:
        names = {
            'single': 'Одинарные звездочки (*)',
            'double': 'Двойные звездочки (**)', 
            'triple': 'Тройные звездочки (***)'
        }
        return names.get(ast_type, ast_type)

    def _count_tech_asterisks(self, tech_text: str, ast_type: str) -> int:
        patterns = {
            'single': r'(?<!\*)\*(?!\*)',
            'double': r'(?<!\*)\*\*(?!\*)',
            'triple': r'(?<!\*)\*\*\*(?!\*)'
        }
        return len(re.findall(patterns[ast_type], tech_text))

    def _empty_result(self):
        return {
            'violations': [{
                'rule_id': 'no_data',
                'rule_text': 'Документ не содержит данных',
                'violation': 'Не удалось извлечь информацию из PDF',
                'location': 'Весь документ',
                'severity': 'high',
                'recommendation': 'Проверьте файл'
            }],
            'statistics': {'total_violations': 1, 'high_severity': 1, 'medium_severity': 0, 'low_severity': 0},
            'is_compliant': False
        }

# =============================================================================
# FLASK APPLICATION
# =============================================================================
doc_analyzer = DocumentAnalyzer()
rule_engine = PreciseRuleEngine()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_document():
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
        
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': 'Требуется PDF-файл'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{filename}")
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

if __name__ == '__main__':
    print("🎯 УЛУЧШЕННЫЙ NormControl запущен!")
    print("📋 Все 8 проверок с детальной диагностикой")
    print("🔍 Подробный вывод в консоль включен")
    app.run(host='0.0.0.0', port=5000, debug=True)