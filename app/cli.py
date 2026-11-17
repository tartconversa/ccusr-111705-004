"""公开目录与日历巡查采集演示。

用法：
  python -m app.cli                # 采集目录月份卡片
  python -m app.cli calendar <id>  # 沿日历导航巡查单日抽屉与摊位弹窗
"""
import json
import sys
from .capture import read_catalog, read_calendar


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    origin = 'http://127.0.0.1:8765/'
    if argv and argv[0] == 'calendar':
        if len(argv) < 2:
            raise SystemExit('用法：python -m app.cli calendar <活动 id>')
        result = read_calendar(origin, argv[1])
    else:
        result = read_catalog(origin)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
