"""本地业务页面交互。"""

def detail_fragment(item):
    return "<button id=\"month-next\">下一月</button><output id=\"month\">十一月</output><button id=\"day-open\">打开单日抽屉</button><aside id=\"day\"></aside><button id=\"cancel\">模拟撤场</button><script>let month=document.querySelector('#month'),day=document.querySelector('#day');let cancelled=false;document.querySelector('#month-next').onclick=()=>{month.textContent='十二月';day.textContent=''};document.querySelector('#day-open').onclick=()=>day.textContent=month.textContent+'：'+(cancelled?'京绣工坊已取消':'盘扣市集 · 3 个摊位');document.querySelector('#cancel').onclick=()=>{cancelled=true;day.textContent='';document.querySelector('#day-open').click()};</script>"

def source_extension(item):
    return f"""<label>日期<select id="calendar-day"><option>十七日</option><option>十八日</option></select></label><output id="stall-detail" data-event="{item['id']}"></output><button id="stall-open">查看摊位</button><script>(()=>{{
let selectedDay=document.querySelector('#calendar-day'),stall=document.querySelector('#stall-detail'),month=document.querySelector('#month');
let cancelled=false;document.querySelector('#month-next').addEventListener('click',()=>{{selectedDay.value='十七日';stall.textContent='';}});selectedDay.addEventListener('change',()=>stall.textContent='');
document.querySelector('#cancel').addEventListener('click',()=>{{cancelled=true;stall.textContent='';}});
document.querySelector('#stall-open').addEventListener('click',()=>{{let selectedMonth=month.textContent,day=selectedDay.value;stall.textContent='摊位读取中';setTimeout(()=>{{stall.textContent=selectedMonth+'/'+day+'：'+(cancelled?'已撤场':day==='十七日'?'盘扣手作 / A 区':'京绣工坊 / B 区');}},70)}});
}})();</script>"""
