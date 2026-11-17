"""真实 Chromium 巡查本地门户的端到端测试：日历导航 → 单日抽屉 → 摊位弹窗。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_browser import BrowserBaselineTest
from app.site import DATA
from app.capture import read_calendar
from app.records import (
    save_calendar_observations,
    read_calendar_facts,
    read_calendar_visits,
)
from app.review import review_calendar


class CalendarPatrolTest(BrowserBaselineTest):
    EVENT = DATA['items'][0]['id']

    def test_full_walk_traces_every_day_through_drawer_and_popup(self):
        run = read_calendar(self.origin, self.EVENT, run_id='full')
        self.assertEqual(run['months'], ['十一月', '十二月'])
        self.assertEqual(run['days'], ['十七日', '十八日'])
        self.assertEqual(len(run['plan']), 4)
        self.assertEqual(run['gaps'], [])
        labels = {(fact['month'], fact['day']): fact['stall']['stall_label']
                  for fact in run['observations']}
        self.assertEqual(labels[('十一月', '十七日')], '盘扣手作 / A 区')
        self.assertEqual(labels[('十一月', '十八日')], '京绣工坊 / B 区')
        for fact in run['observations']:
            self.assertEqual(fact['drawer']['state'], 'scheduled')
            self.assertEqual(fact['stall']['state'], 'scheduled')
            self.assertIn(self.EVENT, fact['source'])

    def test_same_event_repeating_across_dates_has_distinct_business_keys(self):
        run = read_calendar(self.origin, self.EVENT, run_id='keys')
        keys = {fact['business_key'] for fact in run['observations']}
        self.assertEqual(len(keys), 4)
        self.assertIn(f'{self.EVENT}:十一月:十七日', keys)
        self.assertIn(f'{self.EVENT}:十二月:十八日', keys)

    def test_cross_month_navigation_clears_popup_and_new_fact_is_fresh(self):
        run = read_calendar(
            self.origin, self.EVENT, run_id='cross',
            plan=[{'month': '十一月', 'day': '十七日'},
                  {'month': '十二月', 'day': '十八日'}])
        december = next(fact for fact in run['observations'] if fact['month'] == '十二月')
        self.assertEqual(december['stall']['raw'], '十二月/十八日：京绣工坊 / B 区')
        self.assertEqual(december['drawer']['month'], '十二月')
        self.assertEqual(run['gaps'], [])

    def test_cancelled_slot_is_recorded_and_survives_a_fresh_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'cancel.sqlite3'
            first = read_calendar(
                self.origin, self.EVENT, run_id='cancel-run',
                plan=[{'month': '十一月', 'day': '十七日', 'cancel': True}])
            self.assertEqual(first['observations'][0]['state'], 'cancelled')
            save_calendar_observations(database, first)
            # 全新浏览器上下文重跑同一日期：门户脚本里的撤场标志本应重置，
            # 但收据状态机必须拒绝在档观察复活已撤场摊位。
            rerun = read_calendar(
                self.origin, self.EVENT, run_id='rerun',
                plan=[{'month': '十一月', 'day': '十七日'}])
            self.assertEqual(rerun['observations'][0]['state'], 'scheduled')
            stats = save_calendar_observations(database, rerun)
            self.assertEqual(stats['rejected'], 1)
            facts = read_calendar_facts(database)
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0]['state'], 'cancelled')
            with sqlite3.connect(database) as db:
                actions = [row[0] for row in db.execute(
                    'SELECT action FROM calendar_visits ORDER BY visit_id')]
            self.assertEqual(actions, ['insert', 'reject'])

    def test_modified_stall_revises_fact_while_visit_history_is_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'modify.sqlite3'
            save_calendar_observations(database, read_calendar(
                self.origin, self.EVENT, run_id='v1',
                plan=[{'month': '十一月', 'day': '十七日'}]))
            facts = read_calendar_facts(database)
            original = facts[0]['stall']['stall_label']
            # 用收据层模拟运营更正摊位归属：旧版本保留在访问表，事实表升版本。
            changed = dict(facts[0])
            changed['stall'] = dict(changed['stall'], stall_label='剪纸新摊位 / C 区')
            changed['observed_at'] = facts[0]['observed_at'] + 10
            changed['run_id'] = 'v2'
            stats = save_calendar_observations(
                database, {'run_id': 'v2', 'event': self.EVENT,
                           'months': ['十一月'], 'days': ['十七日'],
                           'observations': [changed], 'gaps': []})
            self.assertEqual(stats['revised'], 1)
            revised = read_calendar_facts(database)[0]
            self.assertEqual(revised['stall']['stall_label'], '剪纸新摊位 / C 区')
            self.assertNotEqual(revised['stall']['stall_label'], original)
            visits = read_calendar_visits(database)
            self.assertEqual(len(visits), 2)
            self.assertEqual(visits[0]['stall']['stall_label'], original)

    def test_partial_walk_is_reviewed_as_draft_with_gaps(self):
        partial = read_calendar(
            self.origin, self.EVENT, run_id='partial',
            plan=[{'month': '十一月', 'day': '十七日'}])
        catalog = [{'id': self.EVENT, 'name': DATA['items'][0]['name'],
                    'summary': DATA['items'][0]['summary'],
                    'href': f'/detail?id={self.EVENT}'}]
        view = review_calendar(partial, catalog)
        self.assertEqual(view['overall_status'], 'draft')
        november = view['months']['十一月']
        self.assertFalse(november['month_complete'])
        missing_days = {item['day'] for item in november['missing']}
        self.assertIn('十八日', missing_days)
        chain = view['trace'][0]['chain']
        self.assertTrue(chain['month_card']['available'])
        self.assertEqual(chain['day_drawer']['stalls_text'], '3 个摊位')
        self.assertEqual(chain['stall_popup']['stall_label'], '盘扣手作 / A 区')

    def test_complete_walk_reviews_as_published_full_month(self):
        view = review_calendar(read_calendar(self.origin, self.EVENT, run_id='done'))
        self.assertEqual(view['overall_status'], 'published')
        for month_view in view['months'].values():
            self.assertTrue(month_view['month_complete'])
            self.assertEqual(month_view['missing'], [])

    def test_stale_cross_month_popup_is_recorded_as_gap_not_old_schedule(self):
        from playwright.sync_api import sync_playwright
        from app.domain import interpret_calendar_observation, StaleObservation
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                # 在门户脚本运行前禁用定时器，使弹窗重绘不会发生，
                # 稳定复现公告板截图里残留上一月内容的缓存场景。
                context.add_init_script('window.setTimeout = () => 0;')
                page = context.new_page()
                page.goto(f'{self.origin}detail?id={self.EVENT}',
                          wait_until='domcontentloaded')
                page.locator('#month-next').click()
                page.locator('#day-open').click()
                page.locator('#stall-open').click()
                # 处理器先同步写入“读取中”，重绘定时器已被禁用；
                # 此时塞入公告板截图里残留的上一月弹窗内容。
                page.evaluate(
                    "() => document.querySelector('#stall-detail').textContent"
                    " = '十一月/十七日：盘扣手作 / A 区'")
                page.wait_for_timeout(100)
                self.assertEqual(
                    page.locator('#stall-detail').inner_text(),
                    '十一月/十七日：盘扣手作 / A 区')
                # 解释器与生产巡查同源：前缀对不上即按缺口处理，不落旧安排。
                with self.assertRaises(StaleObservation):
                    interpret_calendar_observation(
                        self.EVENT, '十二月', '十七日',
                        page.locator('#day').inner_text(),
                        page.locator('#stall-detail').inner_text(),
                        source=page.url, run_id='stale', observed_at=1.0, seq=1)
            finally:
                browser.close()

    def test_calendar_origin_is_restricted_to_loopback(self):
        with self.assertRaises(ValueError):
            read_calendar('https://example.com/', self.EVENT)


if __name__ == '__main__':
    unittest.main()
