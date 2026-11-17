"""本地业务页面交互。"""

def detail_fragment(item):
    return '<button id="month-next">下一月</button><output id="month">十一月</output><button id="day-open">打开单日抽屉</button><aside id="day"></aside><script>document.querySelector(\'#month-next\').onclick=()=>document.querySelector(\'#month\').textContent=\'十二月\';document.querySelector(\'#day-open\').onclick=()=>document.querySelector(\'#day\').textContent=document.querySelector(\'#month\').textContent+\'：市集日程\';</script>'
