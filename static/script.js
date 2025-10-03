let currentFileId = null;
let currentFilename = null;

document.getElementById('uploadForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    
    if (!file) {
        showError('Пожалуйста, выберите файл');
        return;
    }
    
    if (file.type !== 'application/pdf') {
        showError('Пожалуйста, выберите PDF файл');
        return;
    }
    
    await uploadAndAnalyze(file);
});

async function uploadAndAnalyze(file) {
    showProgress();
    
    try {
        // Step 1: Upload file
        updateProgress(0, 'Загрузка файла');
        const formData = new FormData();
        formData.append('file', file);
        
        const uploadResponse = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!uploadResponse.ok) {
            throw new Error('Ошибка загрузки файла');
        }
        
        const uploadResult = await uploadResponse.json();
        
        if (!uploadResult.file_id) {
            throw new Error('Ошибка загрузки файла');
        }
        
        currentFileId = uploadResult.file_id;
        currentFilename = uploadResult.filename;
        
        // Step 2: Analyze document
        updateProgress(20, 'Извлечение текста');
        const analysisResponse = await fetch('/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_id: currentFileId,
                filename: currentFilename
            })
        });
        
        if (!analysisResponse.ok) {
            const errorData = await analysisResponse.json();
            throw new Error(errorData.error || 'Ошибка анализа документа');
        }
        
        updateProgress(40, 'Анализ структуры');
        updateProgress(60, 'Проверка правил');
        updateProgress(80, 'Формирование отчета');
        
        const analysisResult = await analysisResponse.json();
        
        // Step 3: Display results
        updateProgress(100, 'Завершено');
        setTimeout(() => {
            showResults(analysisResult);
        }, 1000);
        
    } catch (error) {
        showError(error.message);
    }
}

function showProgress() {
    document.getElementById('uploadForm').style.display = 'none';
    document.getElementById('progressSection').style.display = 'block';
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'none';
}

function updateProgress(percent, step) {
    const progressFill = document.querySelector('.progress-fill');
    const steps = document.querySelectorAll('.step');
    
    progressFill.style.width = percent + '%';
    
    // Update active steps based on progress
    steps.forEach((step, index) => {
        const stepPercent = (index + 1) * 20;
        if (percent >= stepPercent) {
            step.classList.add('active');
        } else {
            step.classList.remove('active');
        }
    });
}

function showResults(result) {
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'block';
    
    const analysisResult = result.analysis_result;
    
    // Update summary
    document.getElementById('complianceStatus').textContent = 
        analysisResult.is_compliant ? 'СООТВЕТСТВУЕТ' : 'НЕ СООТВЕТСТВУЕТ';
    document.getElementById('complianceStatus').className = 
        analysisResult.is_compliant ? 'status compliant' : 'status non-compliant';
    
    document.getElementById('totalIssues').textContent = 
        analysisResult.statistics.total_violations;
    document.getElementById('criticalIssues').textContent = 
        analysisResult.statistics.high_severity;
    
    // Display violations
    const violationsContainer = document.getElementById('violationsContainer');
    violationsContainer.innerHTML = '';
    
    if (analysisResult.violations.length === 0) {
        violationsContainer.innerHTML = '<p>Замечаний не выявлено. Документ соответствует требованиям.</p>';
    } else {
        analysisResult.violations.forEach((violation, index) => {
            const violationElement = createViolationElement(violation, index + 1);
            violationsContainer.appendChild(violationElement);
        });
    }
    
    // Set up download button
    document.getElementById('downloadReport').onclick = () => {
        downloadReport(result.red_pencil_report);
    };
    
    // Set up new check button
    document.getElementById('newCheck').onclick = resetForm;
}

function createViolationElement(violation, number) {
    const div = document.createElement('div');
    div.className = `violation-item ${violation.severity}`;
    
    const severityClass = `severity-${violation.severity}`;
    const severityText = getSeverityText(violation.severity);
    
    div.innerHTML = `
        <div class="violation-header">
            <h4>Замечание ${number}: ${violation.violation}</h4>
            <span class="violation-severity ${severityClass}">${severityText}</span>
        </div>
        <div class="violation-location">
            <strong>Местоположение:</strong> ${violation.location}
        </div>
        <div class="violation-rule">
            <strong>Требование:</strong> ${violation.rule_text}
        </div>
        ${violation.quote ? `
        <div class="violation-quote">
            <strong>Цитата:</strong> "${violation.quote}"
        </div>
        ` : ''}
    `;
    
    return div;
}

function getSeverityText(severity) {
    const severityMap = {
        'high': 'КРИТИЧЕСКОЕ',
        'medium': 'СРЕДНЕЕ',
        'low': 'НИЗКОЕ'
    };
    return severityMap[severity] || 'НЕИЗВЕСТНО';
}

async function downloadReport(redPencilReport) {
    const response = await fetch('/report', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            red_pencil_report: redPencilReport
        })
    });
    
    if (response.ok) {
        const result = await response.json();
        
        // Create and download text file
        const blob = new Blob([result.report_text], { type: 'text/plain' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `normcontrol_report_${new Date().toISOString().split('T')[0]}.txt`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } else {
        alert('Ошибка при генерации отчета');
    }
}

function showError(message) {
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'block';
    document.getElementById('errorMessage').textContent = message;
}

function resetForm() {
    document.getElementById('uploadForm').style.display = 'block';
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'none';
    document.getElementById('fileInput').value = '';
    
    currentFileId = null;
    currentFilename = null;
}