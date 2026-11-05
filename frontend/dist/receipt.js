// Чеки для чекового аппарата 80 мм: «ЗАКАЗ» (после подтверждения), «СЧЕТ» (без оплаты) и чек об оплате.
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
    if(job.kind==='order'){                                                                   // «ЗАКАЗ»
      return head+row(`Дата: ${esc(p.date)}`,`Время: ${esc(p.time)}`)+`<div>Место: ${esc(p.place)}</div>`
        +(p.waiter?`<div>Официант: ${esc(p.waiter)}</div>`:'')+(p.accepted_by?`<div>Принял: ${esc(p.accepted_by)}</div>`:'')+guest(p)
        +line+items(p.items)+line
        +(p.comment?`<div>Комментарий: ${esc(p.comment)}</div>${line}`:'')
        +(p.takeaway?`<div class="c b">!! УПАКОВАТЬ С СОБОЙ !!</div>${line}`:'')
        +(p.delivery_fee?row('Блюда:',sum(p.subtotal))+row('Доставка:',sum(p.delivery_fee)):'')
        +row(p.delivery_fee||p.kind==='pickup'?'ИТОГО':'СУММА ЗАКАЗА',`= ${sum(p.total)}`,'big')
        +`<div class="c note">${esc(p.note||'')}</div>`;
    }
    const pay=p.payment;                                                                      // «СЧЕТ»: счёт или чек об оплате
    return head+`<div>Дата: ${esc(p.date)}</div><div>Открыт: ${esc(p.opened)}${p.closed?`&nbsp;&nbsp;&nbsp;Закрыт: ${esc(p.closed)}`:''}</div>`
      +`<div>Место: ${esc(p.place)}</div><div>Официант: ${esc(p.waiter)}</div>${guest(p)}`
      +line+'<div class="c">Наименования блюд и товаров</div>'+line+items(p.items)+line
      +(p.delivery_fee?row('Доставка:',sum(p.delivery_fee)):'')
      +row('','ВСЕГО: '+sum(p.total))+line
      +row(pay?'ИТОГО К ОПЛАТЕ':'К ОПЛАТЕ',`= ${sum(p.total)}`,'big')+line
      +(pay?`<div>ОПЛАТА:</div>${pay.cash?row('&nbsp;&nbsp;Взнос: Наличные',sum(pay.cash)):''}${pay.card?row('&nbsp;&nbsp;Взнос: Карта',sum(pay.card)):''}`
        +(pay.received!=null?row('&nbsp;&nbsp;Получено',sum(pay.received))+row('&nbsp;&nbsp;Сдача',sum(pay.change)):'')
        +`<div class="c b thanks">${esc(p.thanks||'')}</div>`
        :`<div class="c note">${esc(p.note||'')}</div>`);
  }

  // Страница чека: ширина бумаги 80 мм (печатная область ~72 мм)
  function html(job){
    return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Чек</title><style>
      @page{size:80mm auto;margin:0}
      *{box-sizing:border-box}
      body{margin:0;padding:3mm 4mm 8mm;width:80mm;font:12px/1.35 "Courier New",monospace;color:#000}
      .row{display:flex;justify-content:space-between;gap:6px}.c{text-align:center}.b{font-weight:700}
      .big{font-size:15px;font-weight:700;margin:2px 0}.sub{padding-left:16px}.item{margin:2px 0}
      .line{border-top:1px dashed #000;margin:5px 0}.note{margin-top:8px}.thanks{margin-top:10px;font-size:13px}
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
    return {id:0,kind:'order',payload:{title:'ЗАКАЗ',number:0,branch,date:new Date().toLocaleDateString('ru-RU'),time:new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),
      place:'ПРОБНЫЙ ЧЕК',items:[{name:'Плов',extras:[],qty:2,price:380,sum:760},{name:'Чай чёрный',extras:[],qty:1,price:80,sum:80}],total:840,subtotal:840,delivery_fee:0,note:'Принтер работает'}};
  }

  window.MuslimReceipt={html,print,sample};
})();
