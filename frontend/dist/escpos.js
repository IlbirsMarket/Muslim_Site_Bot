// Чеки командами ESC/POS — так печатают Трактир и 1С: встроенным шрифтом аппарата, чётко, без полей и сдвигов.
// Получает тот же чек (job), что и receipt.js, и возвращает байты для аппарата. Отправляет их программа печати.
(function(){
  const COLS=48;                                                  // 80-мм аппарат: 48 символов в строке (шрифт A)
  const ESC=0x1b,GS=0x1d;

  // Кириллица в кодировке аппарата: CP866 (ESC t 17) или Windows-1251 (ESC t 46)
  const RU='АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдежзийклмнопрстуфхцчшщъыьэюя';
  function encoder(page){
    const map={};
    for(let i=0;i<RU.length;i++){
      const ch=RU[i];
      if(page===46)map[ch]=0xC0+i;                                // 1251: А..я подряд с 0xC0
      else map[ch]=i<48?0x80+i:0xE0+(i-48);                       // 866: А..п с 0x80, р..я с 0xE0
    }
    if(page===46)Object.assign(map,{'Ё':0xA8,'ё':0xB8,'№':0xB9,'·':0xB7});
    else Object.assign(map,{'Ё':0xF0,'ё':0xF1,'№':0xFC,'·':0xFA});
    const same={'—':'-','–':'-','«':'"','»':'"','“':'"','”':'"','’':"'",'×':'x',' ':' '};   // похожие символы
    return text=>{
      const out=[];
      for(const raw of String(text)){
        const ch=same[raw]??raw,code=ch.charCodeAt(0);
        if(code<0x80)out.push(code);
        else if(map[ch]!==undefined)out.push(map[ch]);
        else out.push(0x3f);                                      // неизвестный знак (эмодзи и т.п.) — «?»
      }
      return out;
    };
  }

  // Строки чека: выравнивание, перенос слов, «слева — справа»
  const money=v=>`${Number(v||0).toLocaleString('ru-RU').replace(/[  ]/g,' ')},00`;   // 1730 → «1 730,00»
  function wrap(text,width){
    const words=String(text??'').split(/\s+/).filter(Boolean),lines=[];let cur='';
    for(let w of words){
      while(w.length>width){if(cur){lines.push(cur);cur='';}lines.push(w.slice(0,width));w=w.slice(width);}
      if(!cur)cur=w;else if(cur.length+1+w.length<=width)cur+=' '+w;else{lines.push(cur);cur=w;}
    }
    if(cur)lines.push(cur);
    return lines.length?lines:[''];
  }
  const lr=(left,right,cols=COLS)=>{const gap=Math.max(1,cols-left.length-right.length);return left+' '.repeat(gap)+right;};
  const dash=(cols=COLS)=>'-'.repeat(cols);

  function Builder(page){
    const enc=encoder(page),bytes=[ESC,0x40,ESC,0x74,page];          // сброс + кодовая страница
    const api={
      text(s,{align=0,bold=false,tall=false}={}){
        bytes.push(ESC,0x61,align,ESC,0x45,bold?1:0,GS,0x21,tall?0x01:0x00);   // выравнивание, жирный, двойная высота
        bytes.push(...enc(s),0x0a);return api;
      },
      center(s,o={}){return api.text(s,{...o,align:1});},
      right(s,o={}){return api.text(s,{...o,align:2});},
      line(){return api.text(dash());},
      feed(n=1){bytes.push(ESC,0x64,n);return api;},
      cut(){bytes.push(ESC,0x64,4,GS,0x56,0x42,0x00);return api;},     // подать бумагу и отрезать
      bytes:()=>Uint8Array.from(bytes),
    };
    return api;
  }

  // Поле «Метка: значение» как на бумажном чеке кафе (метки выровнены по двоеточию)
  function field(b,label,value){
    if(!value)return;
    const L=17,rest=COLS-L-2,parts=wrap(value,rest);
    parts.forEach((part,i)=>b.text((i?' '.repeat(L+2):(label+':').padStart(L+1)+' ')+part));
  }

  // Кассовый чек: СЧЕТ (после подтверждения / счёт / оплата)
  function cash(b,p,kind){
    const pay=p.payment,opened=kind==='order'?p.time:p.opened;
    b.center('КАФЕ "МУСЛИМ"').center(`СЧЕТ № ${p.number}`,{bold:true});
    if(/КОПИЯ/.test(p.title||''))b.center('КОПИЯ');
    b.line();
    field(b,'Дата',p.date);
    field(b,'Открыт',(opened||'')+(p.closed?`  Закрыт: ${p.closed}`:''));
    field(b,'Место',p.place);
    field(b,p.staff_role||'Официант',p.waiter||'-');
    field(b,'Гость',p.customer);field(b,'Тел',p.phone);field(b,'Адрес',p.address);field(b,'Курьеру',p.courier_comment);
    if(!pay)field(b,'Оплата',p.guest_payment);
    b.line().center('Наименования блюд и товаров').line();
    (p.items||[]).forEach((it,i)=>{
      wrap(`${i+1}. ${it.name}`,COLS).forEach(s=>b.text(s));
      if(it.extras?.length)wrap(`+ ${it.extras.join(', ')}`,COLS-4).forEach(s=>b.text('    '+s));
      b.text(lr(`      ${it.qty} * ${money(it.price)}`,`= ${money(it.sum)}`));
    });
    if(p.comment)wrap(`Комментарий: ${p.comment}`,COLS).forEach(s=>b.text(s));
    b.line();
    if(p.delivery_fee)b.right(`Доставка: ${money(p.delivery_fee)}`);
    b.right(`ВСЕГО: ${money(p.total)}`).line();
    b.right(`ИТОГО К ОПЛАТЕ = ${money(p.total)}`,{bold:true,tall:true}).line();
    if(pay){
      b.text('ОПЛАТА:');
      if(pay.cash)b.text(lr('     Взнос: Наличные',money(pay.cash)));
      if(pay.card)b.text(lr('     Взнос: Карта',money(pay.card)));
      if(pay.received!=null&&pay.change)b.text(lr('     Сдача',money(pay.change)));
    }
    b.center('ВСЕГДА МЫ РАДЫ ВАМ!!!',{bold:true});
  }

  // Кухонный чек: место и № заказа, кто принял, блюда крупно с количеством, без цен
  function kitchen(b,p){
    b.text(lr(String(p.place||''),`Заказ № ${p.number}`),{bold:true}).feed(1);
    b.center(`${String(p.staff_role||'').toUpperCase()}${p.waiter?': '+String(p.waiter).toUpperCase():''}`,{bold:true});
    b.center(`Дата: ${p.date} Время: ${p.time}`).line();
    (p.items||[]).forEach(it=>{
      const qty=String(it.qty),name=wrap(it.name,COLS-qty.length-2);
      name.forEach((s,i)=>b.text(i===name.length-1?lr(s,qty):s,{bold:true,tall:true}));
      if(it.extras?.length)wrap(`+ ${it.extras.join(', ')}`,COLS-2).forEach(s=>b.text('  '+s,{bold:true}));
      b.line();
    });
    if(p.comment){wrap(`Комментарий: ${p.comment}`,COLS).forEach(s=>b.text(s,{bold:true}));b.line();}
  }

  // Отчёт за смену
  function shift(b,p){
    const signed=n=>`${n<0?'-':''}${money(Math.abs(n))}`;
    b.center('КАФЕ "МУСЛИМ"');if(p.branch)b.center(p.branch);
    b.center(p.title||'ОТЧЁТ ЗА СМЕНУ',{bold:true}).line();
    b.text(`Дата: ${p.date}`).text(`Смена: ${p.opened} - ${p.closed}`).text(`Кассир: ${p.cashier}`);
    if(p.closed_by&&p.closed_by!==p.cashier)b.text(`Закрыл: ${p.closed_by}`);
    b.line().text(lr('Счетов оплачено',String(p.orders))).text(lr('Наличные',money(p.cash))).text(lr('Карта',money(p.card)))
      .text(lr('ВСЕГО',money(p.total)),{bold:true}).line()
      .text(lr('В кассе на начало',money(p.opening_cash))).text(lr('+ Наличные',money(p.cash)));
    if(p.cash_in)b.text(lr('+ Внесение',money(p.cash_in)));
    if(p.cash_out)b.text(lr('- Изъятие',money(p.cash_out)));
    b.text(lr('ДОЛЖНО БЫТЬ',money(p.expected)),{bold:true}).text(lr('ПО ФАКТУ',money(p.counted)))
      .text(lr('РАЗНИЦА',signed(p.difference)),{bold:true}).line().feed(1).text('Подпись кассира ____________');
  }

  // Готовые байты для аппарата
  function build(job,page=17){
    const b=Builder(page),p=job.payload||{};
    if(job.kind==='kitchen1'||job.kind==='kitchen2')kitchen(b,p);
    else if(job.kind==='shift')shift(b,p);
    else cash(b,p,job.kind);
    return b.cut().bytes();
  }

  // Байты → base64 (так их удобно передать программе печати)
  function toBase64(bytes){let s='';for(let i=0;i<bytes.length;i+=0x8000)s+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));return btoa(s);}

  window.MuslimEscpos={build,toBase64,COLS};
})();
