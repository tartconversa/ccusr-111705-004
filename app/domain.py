"""非遗市集摊位与活动日程的变更采集：目录卡片既有数据约定。"""
import re

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
