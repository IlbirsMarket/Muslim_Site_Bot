// Чеки для чекового аппарата 80 мм в виде старого чека кафе: после подтверждения, счёт без оплаты и чек об оплате.
// Сервер присылает данные чека (payload), здесь из них собирается страница и печатается в скрытой рамке.
// Если Chrome запущен с --kiosk-printing, чек выходит сразу, без окна печати.
(function(){
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const sum=value=>`${Number(value||0).toLocaleString('ru-RU').replace(/ /g,' ')},00`;   // 1730 → «1 730,00»
  const row=(left,right,cls='')=>`<div class="row ${cls}"><span>${left}</span><span>${right}</span></div>`;   // слева — справа
  const line='<div class="line"></div>';                                                         // пунктир

  // Позиции: «1. Плов» и ниже «2 * 380,00 = 760,00»
  function items(list){
    return (list||[]).map((it,i)=>`<div class="item"><div>${i+1}. ${esc(it.name)}</div>${it.extras?.length?`<div class="sub">+ ${esc(it.extras.join(', '))}</div>`:''}${row(`&nbsp;&nbsp;&nbsp;${it.qty} * ${sum(it.price)}`,`= ${sum(it.sum)}`)}</div>`).join('');
  }

  // Гость доставки / самовывоза
  function guest(p){
    return [p.customer&&`Гость: ${esc(p.customer)}`,p.phone&&`Тел: ${esc(p.phone)}`,p.address&&`Адрес: ${esc(p.address)}`,
      p.courier_comment&&`Курьеру: ${esc(p.courier_comment)}`,p.guest_payment&&`Оплата: ${esc(p.guest_payment)}`].filter(Boolean).map(t=>`<div>${t}</div>`).join('');
  }

  function body(job){
    const p=job.payload||{};
    const head=`<div class="c b">КАФЕ "МУСЛИМ"</div>${p.branch?`<div class="c">${esc(p.branch)}</div>`:''}<div class="c big">${esc(p.title)} N${esc(p.number)}</div>${line}`;
    if(job.kind==='shift'){                                                                   // «ОТЧЁТ ЗА СМЕНУ»
      const signed=n=>`${n<0?'−':''}${sum(Math.abs(n))}`;
      return `<div class="c b">КАФЕ "МУСЛИМ"</div>${p.branch?`<div class="c">${esc(p.branch)}</div>`:''}<div class="c big">${esc(p.title)}</div>${line}`
        +`<div>Дата: ${esc(p.date)}</div><div>Смена: ${esc(p.opened)} – ${esc(p.closed)}</div><div>Кассир: ${esc(p.cashier)}</div>${p.closed_by&&p.closed_by!==p.cashier?`<div>Закрыл: ${esc(p.closed_by)}</div>`:''}${line}`
        +row('Счетов оплачено',p.orders)+row('Наличные',sum(p.cash))+row('Карта',sum(p.card))+row('ВСЕГО',sum(p.total),'b')+line
        +row('В кассе на начало',sum(p.opening_cash))+row('+ Наличные',sum(p.cash))+(p.cash_in?row('+ Внесение',sum(p.cash_in)):'')+(p.cash_out?row('− Изъятие',sum(p.cash_out)):'')
        +row('ДОЛЖНО БЫТЬ',sum(p.expected),'b')+row('ПО ФАКТУ',sum(p.counted))+row('РАЗНИЦА',signed(p.difference),'b')+line
        +'<br><div>Подпись кассира ____________</div>';
    }
    // Чек как у кафе на бумаге: СЧЕТ N…, Дата / Открыт / Закрыт / Место / Официант, «Наименования блюд и товаров»,
    // позиции, ВСЕГО, ИТОГО К ОПЛАТЕ, ОПЛАТА: Взнос …, «ВСЕГДА МЫ РАДЫ ВАМ!!!». После подтверждения — тот же вид без оплаты
    const pay=p.payment;
    const field=(label,value)=>value?`<div class="f"><span>${label}:</span><span>${value}</span></div>`:'';
    const opened=job.kind==='order'?p.time:p.opened;
    const copy=/КОПИЯ/.test(p.title||'');
    return `<div class="c b">КАФЕ "МУСЛИМ"</div><div class="c title">СЧЕТ N${esc(p.number)}</div>${copy?'<div class="c">КОПИЯ</div>':''}${line}`
      +`<div class="fields">${field('Дата',esc(p.date))}${field('Открыт',esc(opened)+(p.closed?` Закрыт: ${esc(p.closed)}`:''))}${field('Место',esc(p.place))}${field(esc(p.staff_role||'Официант'),esc(p.waiter||'—'))}`
      +`${field('Гость',esc(p.customer))}${field('Тел',esc(p.phone))}${field('Адрес',esc(p.address))}${field('Курьеру',esc(p.courier_comment))}${!pay?field('Оплата',esc(p.guest_payment)):''}</div>`
      +line+'<div class="c b">Наименования блюд и товаров</div>'+line
      +(p.items||[]).map((it,i)=>`<div class="item"><div>${i+1}. ${esc(it.name)}</div>${it.extras?.length?`<div class="sub">+ ${esc(it.extras.join(', '))}</div>`:''}<div class="qty"><span>${it.qty} * ${sum(it.price)}</span><span>= ${sum(it.sum)}</span></div></div>`).join('')
      +(p.comment?`<div class="note">Комментарий: ${esc(p.comment)}</div>`:'')
      +line+(p.delivery_fee?`<div class="r">Доставка: ${sum(p.delivery_fee)}</div>`:'')
      +`<div class="r">ВСЕГО: ${sum(p.total)}</div>`+line
      +`<div class="r total">ИТОГО К ОПЛАТЕ = ${sum(p.total)}</div>`+line
      +(pay?`<div class="pay"><div>ОПЛАТА:</div>${pay.cash?`<div class="row"><span>Взнос: Наличные</span><span>${sum(pay.cash)}</span></div>`:''}${pay.card?`<div class="row"><span>Взнос: Карта</span><span>${sum(pay.card)}</span></div>`:''}${pay.received!=null&&pay.change?`<div class="row"><span>Сдача</span><span>${sum(pay.change)}</span></div>`:''}</div>`:'')
      +'<div class="c b thanks">ВСЕГДА МЫ РАДЫ ВАМ!!!</div>';
  }

  // Страница чека: ширина бумаги 80 мм (печатная область ~72 мм)
  function html(job){
    return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Чек</title><style>
      @page{size:80mm auto;margin:0}
      *{box-sizing:border-box}
      body{margin:0;padding:4mm 3mm 8mm;width:80mm;font:13px/1.4 "Courier New",Courier,monospace;color:#000}
      .row,.qty{display:flex;justify-content:space-between;gap:6px}.c{text-align:center}.b{font-weight:700}
      .title{font-size:16px;margin:2px 0 4px}
      .fields .f{display:grid;grid-template-columns:42% 58%;gap:0 6px}.fields .f span:first-child{text-align:right}
      .item{margin:6px 0}.qty{padding-left:30%}.sub{padding-left:16px}
      .r{text-align:right}.total{font-size:17px;font-weight:700;margin:3px 0}
      .line{border-top:1px dashed #000;margin:6px 0}.note{margin-top:6px}
      .pay{margin-top:4px}.pay .row{padding-left:22%}
      .thanks{margin-top:6px;font-size:13px}.big{font-size:15px;font-weight:700;margin:2px 0}
    </style></head><body>${body(job)}</body></html>`;
  }

  // Напечатать один чек. Ждём, пока Chrome отдаст его принтеру (или 2 секунды), потом убираем рамку
  function print(job){
    return new Promise(resolve=>{
      const frame=document.createElement('iframe');
      frame.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden';
      frame.srcdoc=html(job);
      const done=()=>{setTimeout(()=>{frame.remove();resolve();},300);};
      frame.onload=()=>{
        const win=frame.contentWindow;
        let finished=false;const finish=()=>{if(!finished){finished=true;done();}};
        win.addEventListener('afterprint',finish);
        setTimeout(finish,2000);
        try{win.focus();win.print();}catch{finish();}
      };
      document.body.append(frame);
    });
  }

  // Пробный чек — проверить принтер в «Настройках»
  function sample(branch){
    return {id:0,kind:'order',payload:{title:'СЧЕТ',number:0,branch,date:new Date().toLocaleDateString('ru-RU'),time:new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),
      place:'ПРОБНЫЙ ЧЕК',items:[{name:'Плов',extras:[],qty:2,price:380,sum:760},{name:'Чай чёрный',extras:[],qty:1,price:80,sum:80}],total:840,subtotal:840,delivery_fee:0,note:'Принтер работает'}};
  }

  window.MuslimReceipt={html,print,sample};
})();
