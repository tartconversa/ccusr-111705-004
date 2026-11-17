import unittest
from playwright.sync_api import sync_playwright
from test_browser import BrowserBaselineTest
from app.site import DATA

class PortalInteractionTest(BrowserBaselineTest):
    def test_browser_business_interaction(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.origin + "detail?id=" + DATA["items"][0]["id"], wait_until="domcontentloaded")
                page.locator('#month-next').click();page.locator('#day-open').click();self.assertIn('十二月',page.locator('#day').inner_text());page.locator('#cancel').click();self.assertIn('已取消',page.locator('#day').inner_text())
            finally:
                browser.close()
