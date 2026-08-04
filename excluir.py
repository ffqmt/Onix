from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

chrome_options = Options()
chrome_options.add_argument("--start-maximized")

service = Service(
    r"C:\Onix\Onix\OnixWeb\rpautomation\dependencias\chromedriver\chromedriver.exe"
)

driver = webdriver.Chrome(service=service, options=chrome_options)

driver.get("https://www.google.com")

input("Chrome abriu. Pressione ENTER para fechar...")
driver.quit()
