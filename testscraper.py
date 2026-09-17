from bs4 import BeautifulSoup
import bs4
import playwright
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://example.com")
    content = page.content()
    soup = bs4.BeautifulSoup(content, 'html.parser')
    
    # Example: Extracting all links from the page
    links = [a['href'] for a in soup.find_all('a', href=True)]
    print(links)
    
    browser.close()