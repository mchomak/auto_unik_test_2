from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time

# Путь к распакованному расширению (папка с manifest.json)
EXTENSION_PATH = "C:\\Users\\McHomak\\Downloads\\2.11.0_0"

def launch_browser_with_extension():
    """Запуск Chrome с расширением"""
    
    # Настройки Chrome
    options = Options()
    
    # Загрузка расширения
    options.add_argument(f'--load-extension={EXTENSION_PATH}')
    
    # Дополнительные настройки (опционально)
    options.add_argument('--disable-blink-features=AutomationControlled')  # Скрыть что это автоматизация
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Запуск браузера
    print("🚀 Запуск браузера с расширением...")
    driver = webdriver.Chrome(options=options)
    
    # Открываем страницу для теста
    driver.get("https://google.com")
    
    print("✅ Браузер запущен! Расширение загружено.")
    print("Окно останется открытым 30 секунд...")
    
    time.sleep(30)  # Держим браузер открытым
    
    # Закрываем браузер
    driver.quit()
    print("❌ Браузер закрыт")

if __name__ == "__main__":
    launch_browser_with_extension()