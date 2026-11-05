/*
  Мини-приложение Telegram: сайт открыт внутри Telegram по кнопке бота.
  Свой маленький «мост» к Telegram (без внешних скриптов — CSP сайта разрешает только свои файлы).
  Протокол — из документации Telegram (core.telegram.org/api/web-events):
    сайт → Telegram: TelegramWebviewProxy.postEvent (телефоны), window.external.notify (Windows), postMessage (web.telegram.org);
    Telegram → сайт: window.Telegram.WebView.receiveEvent(тип, данные) или message-событие.
  Что делает: разворачивает на весь экран, красит шапку в цвета кафе, кнопка «‹ Назад» закрывает открытое окно,
  отдаёт initData (кто открыл — для входа персонала и статусов гостю) и номер телефона гостя по его согласию.
  На обычном сайте ничего не меняет: MuslimTG.active = false.
*/
(() => {
  'use strict';
  const KEY='muslim-tg-params';
  // 1. Параметры запуска: Telegram кладёт их в адрес после «#». Запоминаем на вкладку и убираем из адреса (панель использует «#» для разделов).
  let params={};
  try { params=JSON.parse(sessionStorage.getItem(KEY)||'{}'); } catch { params={}; }
  const hash=new URLSearchParams(location.hash.slice(1));
  if(hash.get('tgWebAppData')||hash.get('tgWebAppPlatform')){
    params={data:hash.get('tgWebAppData')||'',version:hash.get('tgWebAppVersion')||'6.0',platform:hash.get('tgWebAppPlatform')||''};
    try { sessionStorage.setItem(KEY,JSON.stringify(params)); } catch { /* Без хранилища — работаем до перезагрузки. */ }
    history.replaceState(null,'',location.pathname+location.search);   // адрес без длинной строки Telegram
  }
  const initData=params.data||'';
  const active=Boolean(initData);
  let user=null;
  try { user=JSON.parse(new URLSearchParams(initData).get('user')||'null'); } catch { user=null; }

  // 2. Отправка команд в Telegram
  function postEvent(type,data={}){
    if(!active)return;
    try {
      if(window.TelegramWebviewProxy?.postEvent){window.TelegramWebviewProxy.postEvent(type,JSON.stringify(data));return;}   // Android / iOS
      if(window.external&&'notify' in window.external){window.external.notify(JSON.stringify({eventType:type,eventData:data}));return;}   // Windows
      if(window.parent!==window)window.parent.postMessage(JSON.stringify({eventType:type,eventData:data}),'https://web.telegram.org');   // веб-версия
    } catch { /* Старый Telegram — просто без этой функции. */ }
  }
  // 3. События от Telegram
  const listeners={};
  function on(type,fn){(listeners[type]||=[]).push(fn);}
  function off(type,fn){listeners[type]=(listeners[type]||[]).filter(f=>f!==fn);}
  function receive(type,data){(listeners[type]||[]).slice().forEach(fn=>{try{fn(data||{});}catch{/* Ошибка одного слушателя не мешает остальным. */}});}
  window.Telegram=window.Telegram||{};
  window.Telegram.WebView=Object.assign(window.Telegram.WebView||{},{receiveEvent:receive});
  window.TelegramGameProxy=Object.assign(window.TelegramGameProxy||{},{receiveEvent:receive});   // старые версии Telegram зовут так
  window.TelegramGameProxy_receiveEvent=receive;
  window.addEventListener('message',event=>{
    if(event.origin!=='https://web.telegram.org')return;          // только веб-версия Telegram
    try { const message=JSON.parse(event.data); if(message?.eventType)receive(message.eventType,message.eventData); } catch { /* Не наше сообщение. */ }
  });
  function wait(type,check=()=>true,ms=8000){                      // дождаться события (с ограничением по времени)
    return new Promise(resolve=>{const fn=data=>{if(!check(data))return;off(type,fn);clearTimeout(timer);resolve(data);};const timer=setTimeout(()=>{off(type,fn);resolve(null);},ms);on(type,fn);});
  }
  const atLeast=v=>{const [a,b]=String(params.version||'6.0').split('.').map(Number);const [x,y]=v.split('.').map(Number);return a>x||(a===x&&(b||0)>=y);};

  // 4. Номер телефона гостя: Telegram спрашивает разрешение, потом отдаёт контакт
  async function requestPhone(){
    if(!active||!atLeast('6.9'))return null;
    postEvent('web_app_request_phone');
    const answer=await wait('phone_requested',()=>true,30000);     // гость нажимает «Поделиться» или «Отмена» (полминуты на ответ)
    if(answer?.status!=='sent')return null;
    for(let attempt=0;attempt<3;attempt++){                        // контакт приходит не сразу
      const id=String(Date.now())+attempt;
      postEvent('web_app_invoke_custom_method',{req_id:id,method:'getRequestedContact',params:{}});
      const result=await wait('custom_method_invoked',data=>data?.req_id===id,2500);
      const text=typeof result?.result==='string'?result.result:'';
      if(text){try{const contact=JSON.parse(new URLSearchParams(text).get('contact')||'{}');if(contact.phone_number)return String(contact.phone_number).replace(/^(?!\+)/,'+');}catch{/* Попробуем ещё раз. */}}
      await new Promise(r=>setTimeout(r,700));
    }
    return null;
  }

  // 5. «‹ Назад» Telegram закрывает открытое окно сайта (блюдо, корзину, редактор…)
  function topDialog(){return [...document.querySelectorAll('dialog[open]')].pop()||null;}
  function syncBack(){postEvent('web_app_setup_back_button',{is_visible:Boolean(topDialog())});}
  on('back_button_pressed',()=>{const d=topDialog();if(!d)return;const close=d.querySelector('[data-close]');if(close)close.click();else d.close();setTimeout(syncBack,50);});

  if(active){
    document.documentElement.classList.add('in-telegram');
    postEvent('web_app_ready');                                    // сайт готов — Telegram убирает заставку
    postEvent('web_app_expand');                                   // на весь экран
    postEvent('web_app_set_header_color',{color:'#92CF16'});       // шапка Telegram — в зелёный цвет кафе
    postEvent('web_app_set_background_color',{color:'#f5f4ef'});
    postEvent('web_app_setup_swipe_behavior',{allow_vertical_swipe:false});   // свайп вниз не закрывает (списки листаются спокойно)
    const watch=()=>new MutationObserver(syncBack).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
    if(document.body)watch();else document.addEventListener('DOMContentLoaded',watch);
  }
  window.MuslimTG={active,initData,user,platform:params.platform||'',postEvent,requestPhone,close:()=>postEvent('web_app_close')};
})();
