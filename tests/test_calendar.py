"""日历巡查领域规则、收据状态机与月份审阅的确定性测试（不启动浏览器）。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.domain import (
    StaleObservation,
    business_key,
    parse_drawer_text,
    parse_stall_text,
    interpret_calendar_observation,
    decide_fact_update,
)
from app.records import (
    save_calendar_observations,
    read_calendar_facts,
    read_calendar_visits,
)
from app.review import review_calendar, review_entries

EVENT = 'heritage-11'


def observation(month='十一月', day='十七日', state='scheduled',
                stall_label='盘扣手作 / A 区', stalls_text='3 个摊位',
                observed_at=1000.0, seq=1, run_id='run-1',
                source='http://127.0.0.1:9/detail?id=heritage-11'):
    if state == 'cancelled':
        drawer = {'month': month, 'state': 'cancelled', 'stalls_text': None,
                  'raw': f'{month}：京绣工坊已取消'}
        stall = {'month': month, 'day': day, 'state': 'cancelled',
                 'stall_label': None, 'raw': f'{month}/{day}：已撤场'}
    else:
        drawer = {'month': month, 'state': 'scheduled', 'stalls_text': stalls_text,
                  'raw': f'{month}：盘扣市集 · {stalls_text}'}
        stall = {'month': month, 'day': day, 'state': 'scheduled',
                 'stall_label': stall_label, 'raw': f'{month}/{day}：{stall_label}'}
    return {'business_key': business_key(EVENT, month, day), 'event': EVENT,
            'month': month, 'day': day, 'state': state, 'drawer': drawer,
            'stall': stall, 'source': source, 'run_id': run_id,
            'observed_at': observed_at, 'seq': seq}


def run(observations, gaps=(), run_id='run-1', months=('十一月', '十二月'),
        days=('十七日', '十八日'), event=EVENT):
    return {'run_id': run_id, 'event': event, 'months': list(months),
            'days': list(days), 'observations': list(observations),
            'gaps': list(gaps),
            'source': f'http://127.0.0.1:9/detail?id={event}'}


class SignalParsingTest(unittest.TestCase):
    def test_stall_text_carries_month_day_and_label(self):
        parsed = parse_stall_text('十一月/十七日：盘扣手作 / A 区')
        self.assertEqual(parsed['month'], '十一月')
        self.assertEqual(parsed['day'], '十七日')
        self.assertEqual(parsed['state'], 'scheduled')
        self.assertEqual(parsed['stall_label'], '盘扣手作 / A 区')

    def test_loading_and_blank_are_transient_not_facts(self):
        self.assertIsNone(parse_stall_text(''))
        self.assertIsNone(parse_stall_text('   '))
        self.assertIsNone(parse_stall_text('摊位读取中'))
        self.assertIsNone(parse_drawer_text('读取中'))

    def test_cancelled_markers_become_cancelled_state(self):
        self.assertEqual(parse_stall_text('十一月/十七日：已撤场')['state'], 'cancelled')
        self.assertEqual(parse_drawer_text('十一月：京绣工坊已取消')['state'], 'cancelled')

    def test_text_without_navigation_prefix_is_stale(self):
        with self.assertRaises(StaleObservation):
            parse_stall_text('盘扣手作 / A 区')
        with self.assertRaises(StaleObservation):
            parse_drawer_text('盘扣市集 · 3 个摊位')


class CalendarObservationTest(unittest.TestCase):
    def _interpret(self, drawer_text, stall_text, month='十一月', day='十七日'):
        return interpret_calendar_observation(
            EVENT, month, day, drawer_text, stall_text,
            source='src', run_id='r', observed_at=1.0, seq=1)

    def test_fresh_drawer_and_stall_trace_to_business_key(self):
        fact = self._interpret('十一月：盘扣市集 · 3 个摊位',
                               '十一月/十七日：盘扣手作 / A 区')
        self.assertEqual(fact['business_key'], 'heritage-11:十一月:十七日')
        self.assertEqual(fact['drawer']['stalls_text'], '3 个摊位')
        self.assertEqual(fact['stall']['stall_label'], '盘扣手作 / A 区')
        self.assertEqual(fact['state'], 'scheduled')

    def test_same_event_on_different_dates_and_months_gets_distinct_keys(self):
        keys = {
            self._interpret(f'{m}：盘扣市集 · 3 个摊位',
                            f'{m}/{d}：盘扣手作 / A 区', m, d)['business_key']
            for m in ('十一月', '十二月') for d in ('十七日', '十八日')}
        self.assertEqual(len(keys), 4)

    def test_stale_stall_from_other_month_is_rejected_as_gap(self):
        with self.assertRaises(StaleObservation):
            self._interpret('十二月：盘扣市集 · 3 个摊位',
                            '十一月/十七日：盘扣手作 / A 区',
                            month='十二月', day='十七日')

    def test_stale_stall_from_other_day_is_rejected_as_gap(self):
        with self.assertRaises(StaleObservation):
            self._interpret('十一月：盘扣市集 · 3 个摊位',
                            '十一月/十八日：京绣工坊 / B 区',
                            month='十一月', day='十七日')

    def test_blank_popup_is_not_observed_but_never_cancelled(self):
        fact = self._interpret('十一月：盘扣市集 · 3 个摊位', '')
        self.assertEqual(fact['state'], 'scheduled')
        self.assertEqual(fact['stall']['state'], 'not_observed')

    def test_both_layers_blank_means_the_day_was_not_reached(self):
        self.assertIsNone(self._interpret('', ''))

    def test_either_layer_cancelling_marks_the_fact_cancelled(self):
        fact = self._interpret('十一月：京绣工坊已取消', '十一月/十七日：已撤场')
        self.assertEqual(fact['state'], 'cancelled')


class FactStateMachineTest(unittest.TestCase):
    def test_first_observation_inserts(self):
        self.assertEqual(decide_fact_update(None, observation())[0], 'insert')

    def test_identical_rerun_is_kept_without_new_revision(self):
        fact = observation()
        action, reason = decide_fact_update(fact, observation(observed_at=2000.0, seq=5))
        self.assertEqual((action, reason), ('keep', 'unchanged-rerun'))

    def test_changed_stall_label_revises_and_keeps_history_in_visits(self):
        action, reason = decide_fact_update(
            observation(), observation(stall_label='新剪纸摊位 / C 区', observed_at=2000.0))
        self.assertEqual((action, reason), ('revise', 'content-changed'))

    def test_cancelled_fact_cannot_be_resurrected_by_later_rerun(self):
        cancelled = observation(state='cancelled', observed_at=1000.0)
        action, reason = decide_fact_update(cancelled, observation(observed_at=2000.0))
        self.assertEqual(action, 'reject')
        self.assertEqual(reason, 'cancelled-not-resurrected-by-rerun')

    def test_older_observation_cannot_overwrite_newer_fact(self):
        newer = observation(observed_at=3000.0)
        action, _ = decide_fact_update(newer, observation(observed_at=2000.0))
        self.assertEqual(action, 'reject')


class CalendarReceiptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'calendar.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_full_walk_publishes_facts_and_visits_are_append_only(self):
        stats = save_calendar_observations(
            self.db, run([observation(m, d, observed_at=1.0)
                          for m in ('十一月', '十二月') for d in ('十七日', '十八日')]))
        self.assertEqual(stats['inserted'], 4)
        self.assertEqual(stats['visits'], 4)
        facts = read_calendar_facts(self.db)
        self.assertEqual({f['business_key'] for f in facts},
                         {f'{EVENT}:{m}:{d}' for m in ('十一月', '十二月')
                          for d in ('十七日', '十八日')})
        self.assertTrue(all(f['state'] == 'scheduled' for f in facts))

    def test_rerun_keeps_cancelled_fact_and_records_rejection(self):
        key = business_key(EVENT, '十一月', '十七日')
        first = run([observation(state='cancelled', observed_at=1000.0,
                                 run_id='run-cancel')],
                    run_id='run-cancel', months=('十一月',), days=('十七日',))
        self.assertEqual(save_calendar_observations(self.db, first)['inserted'], 1)
        second = run([observation(observed_at=2000.0, run_id='run-2', seq=9)],
                     run_id='run-2', months=('十一月',), days=('十七日',))
        stats = save_calendar_observations(self.db, second)
        self.assertEqual(stats['rejected'], 1)
        self.assertEqual(stats['inserted'], 0)
        facts = read_calendar_facts(self.db)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['state'], 'cancelled')
        visits = read_calendar_visits(self.db)
        self.assertEqual([v['run_id'] for v in visits], ['run-cancel', 'run-2'])
        self.assertEqual([v['business_key'] for v in visits], [key, key])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                'SELECT DISTINCT action FROM calendar_visits WHERE run_id=?',
                ('run-2',)).fetchone()[0], 'reject')

    def test_modification_creates_revision_but_visits_keep_both_versions(self):
        save_calendar_observations(
            self.db, run([observation(observed_at=1000.0)], run_id='run-1',
                         months=('十一月',), days=('十七日',)))
        save_calendar_observations(
            self.db, run([observation(stall_label='新剪纸摊位 / C 区',
                                      observed_at=2000.0, run_id='run-2', seq=2)],
                         run_id='run-2', months=('十一月',), days=('十七日',)))
        facts = read_calendar_facts(self.db)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['stall']['stall_label'], '新剪纸摊位 / C 区')
        with sqlite3.connect(self.db) as db:
            revision = db.execute(
                'SELECT revision FROM calendar_facts').fetchone()[0]
            visit_count = db.execute('SELECT count(*) FROM calendar_visits').fetchone()[0]
        self.assertEqual(revision, 2)
        self.assertEqual(visit_count, 2)

    def test_idempotent_rerun_does_not_duplicate_facts_or_visits_state(self):
        payload = run([observation(observed_at=1000.0)],
                      months=('十一月',), days=('十七日',))
        save_calendar_observations(self.db, payload)
        stats = save_calendar_observations(
            self.db, run([observation(observed_at=2000.0, run_id='run-2', seq=3)],
                         run_id='run-2', months=('十一月',), days=('十七日',)))
        self.assertEqual(stats['kept'], 1)
        self.assertEqual(len(read_calendar_facts(self.db)), 1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT revision FROM calendar_facts').fetchone()[0], 1)


class ReviewTest(unittest.TestCase):
    CATALOG = [{'id': EVENT, 'name': '盘扣市集',
                'summary': '十一月十七日 · 3 个摊位', 'href': f'/detail?id={EVENT}'}]

    def test_partial_walk_is_draft_with_explicit_gaps_not_full_month(self):
        partial = run([observation('十一月', '十七日')],
                      gaps=[{'event': EVENT, 'month': '十一月', 'day': '十八日',
                             'reason': 'not-observed'}],
                      months=('十一月',), days=('十七日', '十八日'))
        view = review_calendar(partial, self.CATALOG)
        self.assertEqual(view['overall_status'], 'draft')
        november = view['months']['十一月']
        self.assertFalse(november['month_complete'])
        self.assertEqual(november['status'], 'draft')
        self.assertEqual(november['missing'],
                         [{'event': EVENT, 'month': '十一月', 'day': '十八日',
                           'reason': 'not-observed'}])

    def test_complete_walk_is_published(self):
        full = run([observation(m, d) for m in ('十一月', '十二月')
                    for d in ('十七日', '十八日')])
        view = review_calendar(full, self.CATALOG)
        self.assertEqual(view['overall_status'], 'published')
        self.assertTrue(all(m['month_complete'] for m in view['months'].values()))

    def test_stale_cache_gap_keeps_month_in_draft(self):
        stale = run([observation('十一月', '十七日')],
                    gaps=[{'event': EVENT, 'month': '十一月', 'day': '十八日',
                           'reason': 'stale-cache', 'detail': 'x'}],
                    months=('十一月',), days=('十七日', '十八日'))
        view = review_calendar(stale, self.CATALOG)
        self.assertEqual(view['months']['十一月']['status'], 'draft')
        self.assertEqual(view['months']['十一月']['missing'][0]['reason'], 'stale-cache')

    def test_trace_links_month_card_drawer_and_popup(self):
        view = review_calendar(run([observation()], months=('十一月',),
                                   days=('十七日',)), self.CATALOG)
        chain = view['trace'][0]['chain']
        self.assertTrue(chain['month_card']['available'])
        self.assertEqual(chain['month_card']['summary'], '十一月十七日 · 3 个摊位')
        self.assertEqual(chain['day_drawer']['stalls_text'], '3 个摊位')
        self.assertEqual(chain['stall_popup']['stall_label'], '盘扣手作 / A 区')

    def test_legacy_review_entries_still_returns_not_observed(self):
        legacy = review_entries([
            {'id': EVENT, 'source': 'src',
             'detail_fact': {'business_key': f'{EVENT}:十一月:十七日'}}])
        self.assertIn('not_observed', str(legacy))


if __name__ == '__main__':
    unittest.main()
