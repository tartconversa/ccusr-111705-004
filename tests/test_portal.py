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
                page.locator('#month-next').click();page.locator('#day-open').click();self.assertEqual(page.locator('#day').inner_text(),'十二月：市集日程')
            finally:
                browser.close()
