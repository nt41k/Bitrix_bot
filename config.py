"""
Configuration for Cargonovo Automation.
All constants, field mappings, and credentials in one place.
"""

import os

# API Configuration
VIBE_KEY = os.environ.get("VIBE_KEY", "")
VIBE_BASE_URL = os.environ.get("VIBE_BASE_URL", "https://vibecode.bitrix24.tech/v1")
BITRIX_WEBHOOK = "https://cargonovo.bitrix24.ru/rest/376/6z3h7d8fcrjdc6um/"
PORTAL = "cargonovo.bitrix24.ru"

# Chat IDs
CHAT_WORKFLOW = 2954      # "Тесты новой технологии" - workflow notifications
CHAT_REPORTS = 2386       # Reports and summaries

# Additional workflow chats where bot commands are accepted
WORKFLOW_CHATS = [2954, 2670, 2678, 2680, 2674, 2682, 2684, 2676]

# CRM Configuration
CATEGORY_ID_LOGISTICS = 6
CATEGORY_ID_TEST = 28

# Sheet-to-category mapping (which pipeline/category deals from each sheet go to)
SHEET_TO_CATEGORY = {
    "Новороссийск": CATEGORY_ID_LOGISTICS,
    "Машины": CATEGORY_ID_LOGISTICS,
    "ФГБУ": CATEGORY_ID_LOGISTICS,
    "Экспорт": CATEGORY_ID_LOGISTICS,
    "Самолет": CATEGORY_ID_LOGISTICS,
    "ФизЛица": CATEGORY_ID_LOGISTICS,
    "TESTLIST": CATEGORY_ID_TEST,
}

# Disk folder parent for new deal folders (TEMP NEW)
DEAL_FOLDER_PARENT_ID = "336656"

# File paths
STATE_FILE = "/opt/hermes/scripts/cargonovo_automation/state.json"
LOG_FILE = "/opt/hermes/scripts/cargonovo_automation/automation.log"

# Module intervals (seconds)
MODULE_INTERVALS = {
    "crm_watcher": 60,      # 1 minute
    "google_sync": 60,      # 1 minute
    "chat_bot": 60,         # 1 minute
    "file_processor": 60,   # 1 minute
    "chat_router": 120,     # 2 minutes
}

# CRM Watcher: skip deals created less than this many seconds ago
# (prevents race conditions with google_sync writing initial fields)
CRM_WATCHER_NEW_DEAL_DELAY = 300  # 5 minutes

# SAFETY: Disable Google Sheets writeback by default
# Set to True only when you explicitly want CRM changes written back to Google Sheets
# When False, crm_watcher detects changes but does NOT write them to Google Sheets
ENABLE_GOOGLE_WRITEBACK = True

# CRM Field Labels (human-readable)
FIELD_LABELS = {
    "id": "ID",
    "title": "НАИМЕНОВАНИЕ ТОВАРА",
    "comments": "КОММЕНТАРИИ",
    "movedTime": "ДАТА",
    "assignedById": "ОТВЕТСТВЕННЫЙ",
    "ufCrm_1779183200329": "ВЕС, МЕСТА",
    "ufCrm_1778644764972": "ДОКУМЕНТЫ С",
    "ufCrm_1778644669716": "ДОКУМЕНТЫ Т",
    "ufCrm_1778644848141": "КОММЕНТАРИЙ Д",
    "ufCrm_1778644783031": "КОММЕНТАРИЙ С",
    "ufCrm_1778644690029": "КОММЕНТАРИЙ Т",
    "ufCrm_1779183188628": "ЛИНИЯ",
    "ufCrm_1778645007478": "НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)",
    "ufCrm_1778645029465": "НОМЕР ТРАНСПОРТНОГО СРЕДСТВА",
    "ufCrm_1779183164129": "СУДНО",
    "ufCrm_1779183153041": "ТИП КОНТ",
    "ufCrm_1778644747983": "ФОТО С",
    "ufCrm_1778644648399": "ФОТО Т",
    "ufCrm_1778643492672": "ФОТО Э",
    "ufCrm_1779923617716": "№ДТ Д",
    "ufCrm_1779917649707": "FOLDERID",
    "ufCrm_1778644832407": "ДОКУМЕНТ Д",
    "ufCrm_1778643555517": "ДОКУМЕНТ Э",
    "ufCrm_1778643584339": "КОММЕНТАРИЙ Э",
    "ufCrm_1780368582410": "ПЕРВОНАЧАЛЬНЫЕ ДОКУМЕНТЫ (ССЫЛКА)",
    "ufCrm_1779183176187": "ПОРТ/СВХ",
    "ufCrm_1778645069931": "НАИМЕНОВАНИЕ ТОВАРА",
    "ufCrm_1780372039815": "ПРИБЫТИЕ",
    "ufCrm_1780372467238": "АКТ КФК",
    "ufCrm_1778644690029": "ТРАНСПОРТ",
    "ufCrm_1781073228008": "КОММЕНТАРИЙ ДЛЯ ЭКСПЕДИТОРА",
    "ufCrm_1780431825434": "КЛИЕНТ",
    "ufCrm_1780432042075": "ДАТА",
    # Google Sync fields
    "ufCrm_1781078096027": "КОНТЕЙНЕР",
    "ufCrm_1782314579640": "ВЫГРУЖЕН",
    "ufCrm_1782314589744": "ПОГРУЖЕН",
    "ufCrm_1781072926227": "НОМЕР ДТ",
    "ufCrm_1781072936759": "ИТС",
    "ufCrm_1781072966654": "ЗАЯВКА/ПИСЬМО",
    "ufCrm_1781072984455": "В РАБОТЕ (ОЖИДАЕМ АКФК) / АКТ",
    "ufCrm_1781072997607": "ПОЛУЧИЛИ ЗАКЛЮЧЕНИЕ",
    "ufCrm_1781073011050": "ВЫПУСК АКФК / АКТ",
    "ufCrm_1781073046958": "ВЫВОЗ",
    "ufCrm_1781073053531": "СДАЧА",
    "ufCrm_1781073072116": "ПЕРЕВОЗЧИК",
    "ufCrm_1781073086218": "ВХОДЯЩАЯ СТОИМОСТЬ",
    "ufCrm_1781073258998": "КОММЕНТАРИЙ ДЛЯ ТРАНСПОРТА",
    "ufCrm_1781073238734": "КОММЕНТАРИЙ ДЛЯ ДЕКЛАРАНТА",
    "ufCrm_1781073247394": "КОММЕНТАРИЙ ДЛЯ СКЛАДА",
}

# Department IDs
DEPT_LOGISTICS = 24
DEPT_EXPEDITORS = 18
DEPT_DECLARANTS = 16
DEPT_WAREHOUSE = 20
DEPT_IT = 30
DEPT_TRANSPORT = 32

# Department folder names for file storage
DEPT_FOLDER_NAMES = {
    DEPT_DECLARANTS: "Декларанты",
    DEPT_EXPEDITORS: "Экспедиторы",
    DEPT_WAREHOUSE: "Склад",
    DEPT_LOGISTICS: "Логисты",
    DEPT_TRANSPORT: "Транспорт",
}

# Hashtag to department mapping for file processor
HASHTAG_TO_DEPT = {
    "склад": DEPT_WAREHOUSE,
    "warehouse": DEPT_WAREHOUSE,
    "транспорт": DEPT_TRANSPORT,
    "transport": DEPT_TRANSPORT,
    "декларанты": DEPT_DECLARANTS,
    "declarants": DEPT_DECLARANTS,
    "экспедиторы": DEPT_EXPEDITORS,
    "expeditors": DEPT_EXPEDITORS,
    "логисты": DEPT_LOGISTICS,
    "logistics": DEPT_LOGISTICS,
}

# Department name keywords for text parsing (without #)
DEPT_KEYWORDS = {
    "склад": DEPT_WAREHOUSE,
    "транспорт": DEPT_TRANSPORT,
    "декларанты": DEPT_DECLARANTS,
    "экспедиторы": DEPT_EXPEDITORS,
    "логисты": DEPT_LOGISTICS,
}

# Command-to-department mapping (which commands belong to which department)
COMMAND_TO_DEPT = {
    # Декларанты (16)
    "1": DEPT_DECLARANTS,   # Номер ДТ
    "2": DEPT_DECLARANTS,   # ИТС
    "3": DEPT_DECLARANTS,   # Комментарий от декларанта
    # Экспедиторы (18)
    "4": DEPT_EXPEDITORS,   # Заявка/Письмо
    "5": DEPT_EXPEDITORS,   # В работе (Ожидаем Акфк/Акт)
    "6": DEPT_EXPEDITORS,   # Получили заключение
    "7": DEPT_EXPEDITORS,   # Выпуск Акфк/Акт
    "8": DEPT_EXPEDITORS,   # Комментарий от экспедитора
    # Транспорт (32)
    "9": DEPT_TRANSPORT,    # Вывоз
    "10": DEPT_TRANSPORT,   # Сдача
    "11": DEPT_TRANSPORT,   # Перевозчик
    "12": DEPT_TRANSPORT,   # Входящая стоимость
    "13": DEPT_TRANSPORT,   # Комментарий от транспорта
    # Логисты (24)
    "14": DEPT_LOGISTICS,   # Комментарий для транспорта
    "15": DEPT_LOGISTICS,   # Комментарий для экспедитора
    "16": DEPT_LOGISTICS,   # Комментарий для декларанта
    "17": DEPT_LOGISTICS,   # Комментарий для склада
    # Склад (20)
    "18": DEPT_WAREHOUSE,   # Контейнер
    "19": DEPT_WAREHOUSE,   # Вес
    "20": DEPT_WAREHOUSE,   # Статус контейнера
}

# Google Sync Configuration
APPS_SCRIPT_ENDPOINT = "https://script.google.com/macros/s/AKfycbyFUDk_boKSpgEZpfVc-UF6nOIsyTrLfGvelwzI6OD8riKO0ux1hwkoTfjnkNt9ViIx/exec"
SPREADSHEET_ID = "1W3I7b2u4iv3lAhP04ODWXjttcG_7CoS9w_PrfvKXL_A"

# Sheets to sync
GOOGLE_SHEETS = ["Новороссийск", "Машины", "ФГБУ", "Экспорт", "Самолет", "ФизЛица", "TESTLIST"]

# Google -> CRM field mapping
GOOGLE_TO_CRM = {
    "SHID": "UF_CRM_1779906375490",
    "КЛИЕНТ": "UF_CRM_1780431825434",
    "ПРИБЫТИЕ": "UF_CRM_1780372039815",
    "ДАТА": "UF_CRM_1780432042075",
    # "НОМЕР ТРАНСПОРТНОГО СРЕДСТВА (КОНТЕЙНЕР)" убран — контейнеры собираются в JSON отдельно
    "НАИМЕНОВАНИЕ ТОВАРА": "UF_CRM_1778645069931",
    "Тип КОНТ": "UF_CRM_1779183153041",
    "СУДНО": "UF_CRM_1779183164129",
    "ПОРТ/СВХ": "UF_CRM_1779183176187",
    "ЛИНИЯ": "UF_CRM_1779183188628",
    "ВЕС, МЕСТА": "UF_CRM_1779183200329",
}

# CRM -> Google writeback mapping (must match actual Google Sheets columns)
CRM_TO_GOOGLE = {
    "UF_CRM_1780368582410": "ДИСК ССЫЛКА",
    "UF_CRM_1781072926227": "№ ДТ",
    "UF_CRM_1781072936759": "ИТС",
    "UF_CRM_1778644848141": "ДЕКЛАРАНТ ",
    "UF_CRM_1781072966654": "ЗАЯВКА/ПИСЬМО",
    "UF_CRM_1781072984455": "В РАБОТЕ (ОЖИДАЕМ АКФК) / АКТ",
    "UF_CRM_1781072997607": "ПОЛУЧИЛИ ЗАКЛЮЧЕНИЕ",
    "UF_CRM_1781073011050": "ВЫПУСК АКФК / АКТ",
    "UF_CRM_1778643584339": "ЭКСПДЕДИТОР",
    "UF_CRM_1781073046958": "ВЫВОЗ",
    "UF_CRM_1781073053531": "СДАЧА",
    "UF_CRM_1781073072116": "ПЕРЕВОЗЧИК",
    "UF_CRM_1781073086218": "ВХОДЯЩАЯ СТОИМОСТЬ",
    "UF_CRM_1781073238734": "КОММЕНТАРИЙ ДЛЯ ДЕКЛАРАНТА",
    "UF_CRM_1778644690029": "ТРАНСПОРТ",
    "UF_CRM_1781073228008": "КОММЕНТАРИЙ ДЛЯ ЭКСПЕДИТОРА",
    "UF_CRM_1781073258998": "КОММЕНТАРИЙ ДЛЯ ТРАНСПОРТА",
    "UF_CRM_1782314579640": "ВЫГРУЖЕН",
    "UF_CRM_1782314589744": "ПОГРУЖЕН",
    "UF_CRM_1778644783031": "СКЛАД",
}

# Chat Bot command mapping
COMMAND_FIELDS = {
    "1": "ufCrm_1781072926227",
    "2": "ufCrm_1781072936759",
    "3": "ufCrm_1778644848141",
    "4": "ufCrm_1781072966654",
    "5": "ufCrm_1781072984455",
    "6": "ufCrm_1781072997607",
    "7": "ufCrm_1781073011050",
    "8": "ufCrm_1778643584339",
    "9": "ufCrm_1781073046958",
    "10": "ufCrm_1781073053531",
    "11": "ufCrm_1781073072116",
    "12": "ufCrm_1781073086218",
    "13": "ufCrm_1778644690029",
    "14": "ufCrm_1781073258998",
    "15": "ufCrm_1781073228008",
    "16": "ufCrm_1781073238734",
    "17": "ufCrm_1781073247394",
    "18": "ufCrm_1782314579640",  # ВЫГРУЖЕН
    "19": "ufCrm_1782314589744",  # ПОГРУЖЕН
    "20": "ufCrm_1778644783031",  # СКЛАД (КОММЕНТАРИЙ ДЛЯ СКЛАДА)
}

# Special routing for notifications
SPECIAL_CONFIG = {
    "ufCrm_1781073228008": {"chat": 2674, "mention": "@отдел"},
    "ufCrm_1778643584339": {"chat": 2670, "mention": "[CHAT=2684]ЗАПРОСЫ отдел продаж[/CHAT]"},
}
