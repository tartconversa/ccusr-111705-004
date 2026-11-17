"""只审阅已观察的详情入口，不把候选记录当作已完成的业务。"""

def review_entries(entries):
    calendar = {}
    for entry in entries:
        key = entry['detail_fact']['business_key']
        calendar.setdefault(key, []).append({'event': entry['id'], 'source': entry['source'],
                                             'stall_state': 'not_observed', 'month_complete': False})
    return calendar
