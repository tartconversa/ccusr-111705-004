"""非遗市集摊位与活动日程的变更采集：页面信号与业务事实约定。

页面分三层出现：月份卡片（目录）、单日抽屉（#day）、摊位弹窗（#stall-detail）。
抽屉与弹窗是分步渲染的可见内容，可能处于“读取中”、跨月缓存或撤场状态，
本模块只把通过导航一致性校验的新鲜内容落为业务事实。
"""
import re

LOADING_MARKERS = ('读取中', '核对中')
CANCEL_MARKERS = ('已撤场', '已取消')

STALL_RE = re.compile(r'^(?P<month>[^/：]+)/(?P<day>[^：]+)：(?P<body>.+)$')
DRAWER_RE = re.compile(r'^(?P<month>[^/：]+)：(?P<body>.+)$')
STALLS_RE = re.compile(r'\d+\s*个摊位')


class StaleObservation(ValueError):
    """抽屉或弹窗自带的月份/日期前缀与当前日历导航不一致，属于跨月缓存。"""


class TransientObservation(ValueError):
    """内容仍是“读取中”等过渡态，不能落为事实。"""


def interpret_card(item):
    parts = item['summary'].split(' · ', 1)
    if len(parts) != 2:
        raise ValueError('卡片摘要格式无效')
    condition, observation = parts
    found = re.fullmatch(r"(?P<amount>\d+) 个摊位", observation)
    if not found:
        raise ValueError('卡片状态未识别')
    amount = found.group('amount')
    return {'kind': 'event', 'identity': item['id'], 'condition': condition, 'stalls_text': observation, 'stalls': int(amount) if amount.isdigit() else amount}


def interpret_entry(catalog_fact, signal):
    if signal['event'] != catalog_fact['identity']:
        raise ValueError('event identity mismatch')
    return {'business_key': f"{signal['event']}:{signal['month']}:{signal['day']}", 'month': signal['month'], 'day': signal['day']}


def business_key(event_id, month, day):
    """同名活动在不同日期重演时，业务键必须随月份/日期区分。"""
    return f'{event_id}:{month}:{day}'


def split_business_key(key):
    event_id, month, day = key.split(':', 2)
    return {'event': event_id, 'month': month, 'day': day}


def _is_transient(text):
    return not text or not text.strip() or any(marker in text for marker in LOADING_MARKERS)


def _classify_body(body):
    body = body.strip()
    if any(marker in body for marker in CANCEL_MARKERS):
        return 'cancelled', None
    return 'scheduled', body


def parse_stall_text(text):
    """解析摊位弹窗文本；空/读取中返回 None，前缀无法解析或对不上时抛 StaleObservation。"""
    if _is_transient(text):
        return None
    match = STALL_RE.match(text.strip())
    if not match:
        raise StaleObservation(f'摊位弹窗缺少月份/日期前缀：{text!r}')
    state, label = _classify_body(match.group('body'))
    return {'month': match.group('month'), 'day': match.group('day'),
            'state': state, 'stall_label': label, 'raw': text.strip()}


def parse_drawer_text(text):
    """解析单日抽屉文本；空/读取中返回 None，月份前缀无法解析时抛 StaleObservation。"""
    if _is_transient(text):
        return None
    match = DRAWER_RE.match(text.strip())
    if not match:
        raise StaleObservation(f'单日抽屉缺少月份前缀：{text!r}')
    body = match.group('body').strip()
    state, _ = _classify_body(body)
    stalls = STALLS_RE.search(body)
    return {'month': match.group('month'), 'state': state,
            'stalls_text': stalls.group(0) if stalls else None, 'raw': text.strip()}


def interpret_calendar_observation(event_id, month, day, drawer_text, stall_text, *,
                                   source, run_id, observed_at, seq):
    """把一次“月份→单日→摊位”导航读到的两层信号合并为业务事实。

    - 任一层为空白/读取中：该层记 not_observed，绝不把空白解释成撤场；
    - 任一层自带前缀与当前导航不符：抛 StaleObservation，由巡查记为缺口；
    - 两层都没有权威内容时返回 None，表示该日期尚未走到（草稿缺口）。
    """
    drawer = parse_drawer_text(drawer_text)
    stall = parse_stall_text(stall_text)
    if drawer is None and stall is None:
        return None
    if drawer is not None and drawer['month'] != month:
        raise StaleObservation(f'抽屉月份 {drawer["month"]} 与导航月份 {month} 不符')
    if stall is not None and (stall['month'] != month or stall['day'] != day):
        raise StaleObservation(
            f'弹窗日期 {stall["month"]}/{stall["day"]} 与导航 {month}/{day} 不符')
    layers = [layer for layer in (drawer, stall) if layer is not None]
    state = 'cancelled' if any(layer['state'] == 'cancelled' for layer in layers) else 'scheduled'
    return {
        'business_key': business_key(event_id, month, day),
        'event': event_id, 'month': month, 'day': day, 'state': state,
        'drawer': drawer or {'state': 'not_observed'},
        'stall': stall or {'state': 'not_observed'},
        'source': source, 'run_id': run_id, 'observed_at': observed_at, 'seq': seq,
    }


def decide_fact_update(stored, incoming):
    """决定一条新观察如何落到事实表，返回 (action, reason)。

    - insert：首次见到该业务键；
    - revise：摊位归属等内容发生变化，旧版本只保留在追加访问表中；
    - keep：与当前事实一致（典型的幂等重跑），不新增版本；
    - reject：已撤场的键被后续在档观察“复活”，或观察时间更旧——重跑不得覆盖取消与修改。
    """
    if stored is None:
        return 'insert', 'first-observation'
    if stored['business_key'] != incoming['business_key']:
        raise ValueError('business_key mismatch')
    if stored['state'] == 'cancelled' and incoming['state'] != 'cancelled':
        return 'reject', 'cancelled-not-resurrected-by-rerun'
    if incoming['observed_at'] < stored['observed_at']:
        return 'reject', 'older-than-current-fact'
    stored_stall = stored.get('stall', {})
    incoming_stall = incoming.get('stall', {})
    signature = (incoming['state'], incoming_stall.get('stall_label'),
                 incoming.get('drawer', {}).get('stalls_text'))
    stored_signature = (stored['state'], stored_stall.get('stall_label'),
                        stored.get('drawer', {}).get('stalls_text'))
    if signature == stored_signature:
        return 'keep', 'unchanged-rerun'
    return 'revise', 'content-changed'
