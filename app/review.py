"""只审阅已观察的详情入口与日历巡查结果，不把候选记录当作已完成的业务。"""
from .domain import split_business_key


def review_entries(entries):
    calendar = {}
    for entry in entries:
        key = entry['detail_fact']['business_key']
        calendar.setdefault(key, []).append({'event': entry['id'], 'source': entry['source'],
                                             'stall_state': 'not_observed', 'month_complete': False})
    return calendar


def _normalize_runs(runs):
    if runs is None:
        return []
    if isinstance(runs, dict):
        return [runs]
    return list(runs)


def review_calendar(runs, catalog_items=None):
    """把巡查结果按月份汇总成运营视图。

    一个月份只有在所有活动 × 该月全部日期都有权威事实（无缺口）时才标记为
    published；只要存在缺口或未走完的日期，该月就是 draft，并列出缺口，
    运营看到的是带缺口的草稿而不是已发布的全月档期。

    每条事实带 trace：月份卡片 → 单日抽屉 → 摊位弹窗三层来源与状态，
    活动与摊位归属可从日历导航一路追溯到当日详情。
    """
    runs = _normalize_runs(runs)
    catalog_items = catalog_items or []
    catalog_by_id = {item['id']: item for item in catalog_items}

    months, days_by_month, events = [], set(), set()
    facts_by_key, gaps, run_ids = {}, [], []
    for run in runs:
        run_ids.append(run.get('run_id'))
        for month in run.get('months', []):
            if month not in months:
                months.append(month)
        for day in run.get('days', []):
            days_by_month.add(day)
        events.add(run['event'])
        for fact in run.get('observations', []):
            facts_by_key[fact['business_key']] = fact
        gaps.extend(run.get('gaps', []))

    month_views = {}
    for month in months:
        expected_days = sorted(days_by_month)
        month_facts, missing, covered = [], [], set()
        for event in sorted(events):
            for day in expected_days:
                key = f'{event}:{month}:{day}'
                fact = facts_by_key.get(key)
                if fact is None:
                    missing.append({'event': event, 'month': month, 'day': day,
                                    'reason': 'not-observed'})
                else:
                    month_facts.append(fact)
                    covered.add((event, day))
        for gap in gaps:
            if gap['month'] != month:
                continue
            slot = (gap['event'], gap['day'])
            if slot in covered:
                continue
            if any(item['event'] == gap['event'] and item['day'] == gap['day']
                   for item in missing):
                index = next(i for i, item in enumerate(missing)
                             if item['event'] == gap['event'] and item['day'] == gap['day'])
                missing[index] = {'event': gap['event'], 'month': gap['month'],
                                  'day': gap['day'], 'reason': gap['reason']}
            else:
                missing.append({'event': gap['event'], 'month': gap['month'],
                                'day': gap['day'], 'reason': gap['reason']})
        month_views[month] = {
            'status': 'published' if not missing else 'draft',
            'month_complete': not missing,
            'expected_days': expected_days,
            'observed': len(month_facts),
            'missing': missing,
            'facts': month_facts,
        }

    trace = []
    for key in sorted(facts_by_key):
        fact = facts_by_key[key]
        parts = split_business_key(key)
        catalog_item = catalog_by_id.get(fact['event'])
        trace.append({
            'business_key': key,
            'event': parts['event'],
            'month': parts['month'],
            'day': parts['day'],
            'state': fact['state'],
            'stall_label': fact['stall'].get('stall_label'),
            'chain': {
                'month_card': {
                    'available': catalog_item is not None,
                    'source': (catalog_item.get('href') if catalog_item else None),
                    'summary': (catalog_item.get('summary') if catalog_item else None),
                },
                'day_drawer': {'state': fact['drawer'].get('state'),
                               'stalls_text': fact['drawer'].get('stalls_text')},
                'stall_popup': {'state': fact['stall'].get('state'),
                                'stall_label': fact['stall'].get('stall_label')},
            },
            'source': fact['source'],
            'run_id': fact.get('run_id'),
        })

    return {
        'run_ids': [run_id for run_id in run_ids if run_id],
        'months': month_views,
        'overall_status': 'published' if months and all(
            view['month_complete'] for view in month_views.values()) else 'draft',
        'trace': trace,
        'gaps': gaps,
    }
