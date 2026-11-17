"""本地业务页面交互。"""

def detail_fragment(item):
    return "<button id=\"month-next\">下一月</button><output id=\"month\">十一月</output><button id=\"day-open\">打开单日抽屉</button><aside id=\"day\"></aside><button id=\"cancel\">模拟撤场</button><script>let month=document.querySelector('#month'),day=document.querySelector('#day');let cancelled=false;document.querySelector('#month-next').onclick=()=>{month.textContent='十二月';day.textContent=''};document.querySelector('#day-open').onclick=()=>day.textContent=month.textContent+'：'+(cancelled?'京绣工坊已取消':'盘扣市集 · 3 个摊位');document.querySelector('#cancel').onclick=()=>{cancelled=true;day.textContent='';document.querySelector('#day-open').click()};</script>"
