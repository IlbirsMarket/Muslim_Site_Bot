(() => {
  'use strict';
  const base = window.MUSLIM_CONFIG?.apiBase;
  const sessionKey='muslim-api-session:'+String(window.MUSLIM_CONFIG?.apiOrigin||base||'offline');
  let tokens = null, refreshPromise = null;
  // Где храним вход: localStorage — «Запомнить меня» (переживает закрытие браузера), sessionStorage — до закрытия вкладки.
  let remembered=false;
  function storage(long){ try { return long?localStorage:sessionStorage; } catch { return null; } }
  // Сохранённый вход (сначала «Запомнить меня», потом вкладка): {tokens, long} или null.
  function savedSession(){ for (const long of [true,false]) { try { const saved=JSON.parse(storage(long)?.getItem(sessionKey));if(typeof saved?.access==='string'&&typeof saved?.refresh==='string')return {tokens:saved,long}; } catch { /* Нет сохранённой сессии. */ } } return null; }
  { const saved=savedSession(); if(saved){tokens=saved.tokens;remembered=saved.long;} }
  const results=[];
  // Сохраняем токены. remember=true/false меняет место хранения; без него (продление входа) — место прежнее.
  function session(value,remember) {
    if(remember!==undefined)remembered=Boolean(remember);
    tokens=value;
    for (const long of [true,false]) { if(value&&long===remembered)continue; try { storage(long)?.removeItem(sessionKey); } catch { /* Хранилище недоступно. */ } }   // стираем лишние копии (нужную — перезапишем)
    if(value){ try { storage(remembered)?.setItem(sessionKey,JSON.stringify(value)); } catch { /* Сессия продолжает работать в памяти. */ } }
  }
  function expireSession(){session(null);window.dispatchEvent(new Event('muslim-session-expired'));}
  // Другая вкладка продлила вход или вышла: берём её ключи или тоже выходим (иначе старый ключ уже отменён сервером).
  window.addEventListener('storage',event=>{ if(event.key!==sessionKey)return; const saved=savedSession(); if(saved){tokens=saved.tokens;remembered=saved.long;} else if(tokens){tokens=null;window.dispatchEvent(new Event('muslim-session-expired'));} });
  // Продление входа: сервер выдаёт новый ключ продления, старый перестаёт работать.
  async function refreshTokens(){
    const sent=tokens.refresh;
    try { const data=await request('/auth/refresh/',{method:'POST',body:{refresh:sent},auth:false,retry:false}); session({...tokens,...data}); }
    catch(error){ const saved=savedSession(); if(saved&&saved.tokens.refresh!==sent){tokens=saved.tokens;remembered=saved.long;return;} expireSession(); throw error; }   // соседняя вкладка уже продлила — берём её ключи
  }
  // «Выйти»: сразу забываем вход и просим сервер отменить ключ продления (если сеть пропала — вход всё равно забыт здесь).
  async function logout(){ const refresh=tokens?.refresh; session(null); if(!refresh||!base)return; try { await request('/auth/logout/',{method:'POST',body:{refresh},auth:false,retry:false}); } catch { /* Сервер недоступен: ключ сам истечёт. */ } }
  function record(path,method,status,elapsed) { results.unshift({path,method,status,elapsed,at:new Date().toISOString()}); results.splice(60); window.dispatchEvent(new Event('muslim-api-result')); }
  function errorMessage(body,status) {
    if (typeof body?.detail==='string') return body.detail;
    if (Array.isArray(body)) return body.join(' ');                // ошибка списком: ["Текст"]
    // Названия полей в ошибках по-русски: «email: …» → «Email: …»
    const labels={username:'Логин',email:'Email',password:'Пароль',role:'Роль',first_name:'Имя',last_name:'Фамилия',phone:'Телефон',telegram_id:'Telegram ID',
      name:'Название',price:'Цена',category:'Категория',description:'Описание',photo:'Фото',number:'Номер',customer_name:'Имя',address:'Адрес',reason:'Причина',
      opens_at:'Открываемся',closes_at:'Закрываемся',delivery_min_sum:'Мин. сумма',delivery_fee:'Стоимость доставки',free_delivery_from:'Бесплатная доставка от'};
    const hidden=['non_field_errors','items','action','ids','detail','table_token','order_type'];        // эти поля без подписи: текст ошибки и так понятен
    const flat=value=>Array.isArray(value)?value.map(flat).join(', '):value&&typeof value==='object'?Object.values(value).map(flat).join(', '):String(value);   // вложенные ошибки — в одну строку
    if (body && typeof body==='object') return Object.entries(body).map(([key,value])=>`${hidden.includes(key)?'':(labels[key]||key)+': '}${flat(value)}`).join('; ').slice(0,1000);
    return `Ошибка API (${status})`;
  }
  async function request(path,{method='GET',body,auth=true,binary=false,retry=true}={}) {
    if (!base) throw new Error('Локальный API доступен после запуска сайта на компьютере.');
    if (!path.startsWith('/')||path.startsWith('//')) throw new Error('Некорректный путь API.');
    const started=performance.now(),headers={Accept:binary?'*/*':'application/json'};
    if (auth&&tokens?.access) headers.Authorization=`Bearer ${tokens.access}`;
    const multipart=typeof FormData!=='undefined'&&body instanceof FormData;
    if (body!==undefined&&!multipart) headers['Content-Type']='application/json';
    let response;
    try { response=await fetch(base+path,{method,headers,body:body===undefined?undefined:multipart?body:JSON.stringify(body),credentials:'omit',signal:AbortSignal.timeout(20000)}); }
    catch { record(path,method,'NETWORK',Math.round(performance.now()-started)); throw new Error('API недоступен. Проверьте локальный сервер и подключение к сети.'); }
    record(path,method,response.status,Math.round(performance.now()-started));
    if (response.status===401&&auth&&tokens?.refresh&&retry) {
      if (!refreshPromise) refreshPromise=refreshTokens().finally(()=>{refreshPromise=null;});
      await refreshPromise;
      return request(path,{method,body,auth,binary,retry:false});
    }
    if (response.status===204) return null;
    if(response.status===401&&auth&&tokens)expireSession();
    if (response.ok&&binary){if(!/^(application\/pdf|image\/)/i.test(response.headers.get('content-type')||''))throw new Error('API вернул неверный формат файла.');return response.blob();}
    const text=await response.text(); let data;
    try { data=text?JSON.parse(text):null; } catch { data=null; }
    if (!response.ok) { const error=new Error(errorMessage(data,response.status)); error.status=response.status; error.data=data; throw error; }
    if (!data&&text) throw new Error('API вернул неожиданный формат ответа.');
    return data;
  }
  // Вход: username — это email или логин; remember — галочка «Запомнить меня».
  async function login(username,password,remember=false) { const data=await request('/auth/login/',{method:'POST',body:{username,password,remember:Boolean(remember)},auth:false});if(typeof data?.access!=='string'||typeof data?.refresh!=='string')throw new Error('API не вернул токены входа.');session({access:data.access,refresh:data.refresh},remember); try{return await request('/auth/me/');}catch(error){session(null);throw error;} }
  function normalizeMenu(rows) {
    if (!Array.isArray(rows)) throw new Error('В ответе меню ожидался список категорий.');
    const extras=new Map(),dishes=[];
    const categories=rows.map(c=>({id:`api-${c.id}`,apiId:c.id,name:c.name}));
    rows.forEach(category=>(category.dishes||[]).forEach(d=>{
      const availableExtras=Array.isArray(d.extras)?d.extras:[];
      availableExtras.forEach(e=>extras.set(`api-${e.id}`,{id:`api-${e.id}`,apiId:e.id,name:e.name,price:Number(e.price)}));
      dishes.push({id:`api-${d.id}`,apiId:d.id,category:`api-${category.id}`,name:d.name,description:d.description||'',image:d.photo||'',prices:d.sizes?.length?d.sizes.map(s=>Number(s.price)):[Number(d.price)],sizes:d.sizes?.length?d.sizes.map(s=>s.name):null,sizeIds:d.sizes?.map(s=>s.id)||[],extraIds:availableExtras.map(e=>`api-${e.id}`),available:d.is_available!==false});
    }));
    return {categories,dishes,extras:[...extras.values()]};
  }
  function orderPayload({menu,cart,tableToken,deviceKey,mode,fields={},comment=''}){
    if(!cart.length)throw new Error('Корзина пуста.');
    const notes=[];
    const items=cart.map(item=>{
      const dish=menu.dishes.find(d=>d.id===item.id);
      if(!dish?.available)throw new Error('Блюдо больше недоступно. Обновите меню.');
      if(!Number.isInteger(item.qty)||item.qty<1||item.qty>50)throw new Error('Количество блюда — от 1 до 50.');
      if(!Number.isInteger(item.size)||item.size<0||item.size>=dish.prices.length)throw new Error('Выберите доступный размер.');
      const extra_ids=item.extras.map(id=>{const e=menu.extras.find(e=>e.id===id);if(!e||!dish.extraIds.includes(id))throw new Error('Добавка недоступна для этого блюда.');return e.apiId;});
      if(item.comment)notes.push(`${dish.name}: ${item.comment}`);
      return {dish_id:dish.apiId,size_id:dish.sizeIds?.[item.size]||null,extra_ids,quantity:item.qty};
    });
    const payload={device_key:deviceKey,comment:[comment,...notes].filter(Boolean).join('\n'),payment_method:fields.payment||'cash',items};
    if(tableToken)payload.table_token=tableToken;                 // без токена — заказ с главной страницы (доставка)
    if(mode==='takeaway')payload.order_type='takeaway';           // со стола «с собой»: контакты не нужны
    if(mode==='pickup')Object.assign(payload,{order_type:'pickup',customer_name:fields.customer||'',phone:fields.phone||''});   // самовывоз: только имя и телефон
    if(mode==='delivery')Object.assign(payload,{order_type:'delivery',customer_name:fields.customer||'',phone:fields.phone||'',address:fields.address||'',apartment:fields.apartment||'',entrance:fields.entrance||'',floor:fields.floor||'',courier_comment:fields.courierNote||''});
    return payload;
  }
  function orderAction(id,action,reason=''){
    if(!Number.isInteger(Number(id))||Number(id)<=0)throw new Error('Некорректный номер заказа.');
    if(action==='claim')return request(`/staff/orders/${id}/claim/`,{method:'POST',body:{}});
    if(!['accept','reject','cook','ready','send','complete','cancel'].includes(action))throw new Error('Недопустимое действие с заказом.');
    return request(`/staff/orders/${id}/status/`,{method:'POST',body:{action,reason}});
  }
  window.MuslimAPI={enabled:Boolean(base),request,login,logout,hasSession:()=>Boolean(tokens?.access),normalizeMenu,orderPayload,orderAction,results};
})();