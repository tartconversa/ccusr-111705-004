"""使用真实 Chromium 浏览公开目录；日历巡查沿月份导航追溯单日抽屉与摊位弹窗。

所有页面只允许访问环回来源。巡查每次打开全新浏览器上下文，不携带上一轮的
页面状态；抽屉/弹窗的新鲜度以其自带的月份/日期前缀与当前导航比对为准，
跨月缓存与“读取中”一律记为缺口，而不是落为旧安排。
"""
import time
from urllib.parse import urlsplit, urlunsplit, urlencode
from playwright.sync_api import sync_playwright
from .domain import (
    interpret_card,
    interpret_entry,
    interpret_calendar_observation,
    StaleObservation,
)

LOCAL_HOSTS = ('127.0.0.1', 'localhost')


def _local_origin(origin):
    parts = urlsplit(origin)
    if parts.hostname not in LOCAL_HOSTS or parts.scheme != 'http':
        raise ValueError('只允许本地演练来源')
    return parts


def read_catalog(origin):
    _local_origin(origin)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(origin, wait_until='domcontentloaded')
            if not page.locator('main').count():
                raise ValueError('来源目录未加载')
            items = page.locator('.card').evaluate_all('(nodes) => nodes.map(n => ({id:n.dataset.key,name:n.querySelector("h2").textContent,summary:n.querySelector("p").textContent,href:n.querySelector("a").getAttribute("href")}))')
            return [{'source': page.url, **item, 'catalog_fact': interpret_card(item)} for item in items]
        finally:
            browser.close()


def read_detail_entry(origin, item_id, selection=None):
    parts = urlsplit(origin)
    if parts.hostname not in LOCAL_HOSTS or parts.scheme != 'http':
        raise ValueError('local origins only')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(origin, wait_until='domcontentloaded')
            card = page.locator(f'.card[data-key="{item_id}"]')
            if card.count() != 1:
                raise ValueError('card identity is not unique')
            catalog = {'id': item_id, 'summary': card.locator('p').inner_text()}
            card.locator('a').click()
            if page.locator('main').get_attribute('data-key') != item_id:
                raise ValueError('detail identity differs from catalog')
            if selection is not None:
                if selection == '十二月':
                    page.locator('#month-next').click()
            catalog_fact = interpret_card(catalog)
            entry_signal = {'month': page.locator('#month').inner_text(), 'day': page.locator('#calendar-day').input_value(), 'event': page.locator('main').get_attribute('data-key')}
            return {'id': item_id, 'source': page.url, 'catalog_fact': catalog_fact,
                    'opening_summary': page.locator('#summary').inner_text(),
                    'detail_fact': interpret_entry(catalog_fact, entry_signal)}
        finally:
            browser.close()


def _detail_url(origin, item_id):
    parts = _local_origin(origin)
    query = urlencode([('id', item_id)])
    return urlunsplit((parts.scheme, parts.netloc, '/detail', query, ''))


def _wait_for_text(locator, *, timeout=1500, interval=30):
    """轮询元素文本；超时返回最终文本，由调用方按过渡态/缺口处理。"""
    deadline = time.monotonic() + timeout / 1000.0
    while True:
        text = locator.inner_text()
        if text and text.strip():
            return text
        if time.monotonic() >= deadline:
            return text
        page = locator.page
        page.wait_for_timeout(interval)


def _poll_drawer(locator, timeout=1500, interval=30):
    """抽屉会先被脚本清空再渲染，等待其出现非空内容，超时返回当前文本。"""
    return _wait_for_text(locator, timeout=timeout, interval=interval)


def _poll_stall(locator, timeout=1500, interval=30):
    deadline = time.monotonic() + timeout / 1000.0
    while True:
        text = locator.inner_text()
        if text and text.strip() and '读取中' not in text and '核对中' not in text:
            return text
        if time.monotonic() >= deadline:
            return text
        locator.page.wait_for_timeout(interval)


def _wait_month_change(page, previous, *, timeout=1000, interval=25):
    """轮询月份输出直到其离开 previous；超时返回 False。"""
    deadline = time.monotonic() + timeout / 1000.0
    while page.locator('#month').inner_text() == previous:
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(interval)
    return True


def _discover_months(page):
    """沿“下一月”导航收集月份，回到上一月或月份不再变化即停止；切换会清空抽屉与弹窗。"""
    months = [page.locator('#month').inner_text()]
    while True:
        previous = page.locator('#month').inner_text()
        page.locator('#month-next').click()
        if not _wait_month_change(page, previous):
            break
        current = page.locator('#month').inner_text()
        if current in months:
            break
        months.append(current)
    return months


def _goto_month(page, target, known_months):
    """在已知月份序列内有界地前进到目标月份；目标不可达时显式失败而非空等。"""
    if target not in known_months:
        raise ValueError(f'未知月份：{target}')
    guard = 0
    while page.locator('#month').inner_text() != target:
        guard += 1
        if guard > len(known_months):
            raise ValueError(f'无法从当前月份导航到 {target}')
        previous = page.locator('#month').inner_text()
        page.locator('#month-next').click()
        if not _wait_month_change(page, previous):
            raise ValueError(
                f'月份导航停在 {page.locator("#month").inner_text()}，无法到达 {target}')


def read_calendar(origin, item_id, *, plan=None, run_id=None, timeout=1500):
    """从日历导航一路巡查到当日详情。

    plan 为 None 时走完全部月份 × 全部可选日期；否则按
    [{'month': 十一月, 'day': 十七日, 'cancel': False}, ...] 执行，
    运营在某个日期中断巡查时传入不完整 plan，结果即带缺口的草稿。

    返回 {'run_id', 'event', 'plan', 'months', 'observations', 'gaps'}：
    观察结果含 drawer/stall 两层；跨月缓存等不一致内容与未完成日期计入 gaps，
    绝不把空白或旧截图解释成在档安排。
    """
    url = _detail_url(origin, item_id)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded')
            if page.locator('main').get_attribute('data-key') != item_id:
                raise ValueError('detail identity differs from catalog')
            months = _discover_months(page)
            day_values = page.locator('#calendar-day option').evaluate_all(
                '(nodes) => nodes.map((n) => n.value)')
            # 发现阶段结束后页面停在最后一个月份；门户只能向前导航，重新加载
            # 详情页回到初始月份，并丢弃发现阶段残留的抽屉/弹窗缓存。
            page.goto(url, wait_until='domcontentloaded')
            if page.locator('main').get_attribute('data-key') != item_id:
                raise ValueError('detail identity differs from catalog')
            if plan is None:
                plan = [{'month': month, 'day': day, 'cancel': False}
                        for month in months for day in day_values]
            observations, gaps, seq = [], [], 0
            previous_month = None
            for step in plan:
                month, day = step['month'], step['day']
                if month not in months:
                    raise ValueError(f'未知月份：{month}')
                if day not in day_values:
                    raise ValueError(f'未知日期：{day}')
                if previous_month is not None and months.index(month) < months.index(previous_month):
                    raise ValueError('巡查计划只能沿月份导航向前，不能回退到更早的月份')
                previous_month = month
                _goto_month(page, month, months)
                page.locator('#calendar-day').select_option(day)
                if step.get('cancel'):
                    page.locator('#cancel').click()
                page.locator('#day-open').click()
                drawer_text = _poll_drawer(page.locator('#day'), timeout=timeout)
                page.locator('#stall-open').click()
                stall_text = _poll_stall(page.locator('#stall-detail'), timeout=timeout)
                observed_at = time.time()
                seq += 1
                try:
                    fact = interpret_calendar_observation(
                        item_id, month, day, drawer_text, stall_text,
                        source=page.url, run_id=run_id, observed_at=observed_at, seq=seq)
                except StaleObservation as exc:
                    gaps.append({'event': item_id, 'month': month, 'day': day,
                                 'reason': 'stale-cache', 'detail': str(exc),
                                 'drawer_text': drawer_text, 'stall_text': stall_text})
                    continue
                if fact is None:
                    gaps.append({'event': item_id, 'month': month, 'day': day,
                                 'reason': 'not-observed',
                                 'drawer_text': drawer_text, 'stall_text': stall_text})
                    continue
                observations.append(fact)
            return {'run_id': run_id, 'event': item_id, 'plan': plan,
                    'months': months, 'days': day_values,
                    'observations': observations, 'gaps': gaps,
                    'source': url}
        finally:
            browser.close()
