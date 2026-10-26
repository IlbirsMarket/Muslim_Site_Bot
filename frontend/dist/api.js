(() => {
  'use strict';
  const base = window.MUSLIM_CONFIG?.apiBase;
  const sessionKey='muslim-api-session:'+String(window.MUSLIM_CONFIG?.apiOrigin||base||'offline');
  let tokens = null, refreshPromise = null;
  try { const saved=JSON.parse(sessionStorage.getItem(sessionKey));if(typeof saved?.access==='string'&&typeof saved?.refresh==='string')tokens=saved; } catch { /* Нет сохранённой сессии. */ }
  const results=[];
  function session(value) { tokens=value; try { if(value) sessionStorage.setItem(sessionKey,JSON.stringify(value)); else sessionStorage.removeItem(sessionKey); } catch { /* Сессия продолжает работать в памяти. */ } }
  function expireSession(){session(null);window.dispatchEvent(new Event('muslim-session-expired'));}
  function record(path,method,status,elapsed) { results.unshift({path,method,status,elapsed,at:new Date().toISOString()}); results.splice(60); window.dispatchEvent(new Event('muslim-api-result')); }
  function errorMessage(body,status) {
    if (typeof body?.detail==='string') return body.detail;
    if (body && typeof body==='object') return Object.entries(body).map(([key,value])=>`${key}: ${Array.isArray(value)?value.join(', '):typeof value==='object'?JSON.stringify(value):value}`).join('; ').slice(0,1000);
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
      if (!refreshPromise) refreshPromise=request('/auth/refresh/',{method:'POST',body:{refresh:tokens.refresh},auth:false,retry:false}).then(data=>session({...tokens,...data})).catch(error=>{expireSession();throw error;}).finally(()=>{refreshPromise=null;});
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
  async function login(username,password) { const data=await request('/auth/login/',{method:'POST',body:{username,password},auth:false});if(typeof data?.access!=='string'||typeof data?.refresh!=='string')throw new Error('API не вернул токены входа.');session(data); try{return await request('/auth/me/');}catch(error){session(null);throw error;} }
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
    if(!tableToken)throw new Error('Для заказа откройте QR-код стола или доставки.');
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
    const payload={table_token:tableToken,device_key:deviceKey,comment:[comment,...notes].filter(Boolean).join('\n'),payment_method:fields.payment||'cash',items};
    if(mode!=='cafe')Object.assign(payload,{order_type:mode,customer_name:fields.customer||'',phone:fields.phone||'',address:fields.address||'',apartment:fields.apartment||'',entrance:fields.entrance||'',floor:fields.floor||'',courier_comment:fields.courierNote||''});
    return payload;
  }
  function orderAction(id,action,reason=''){
    if(!Number.isInteger(Number(id))||Number(id)<=0)throw new Error('Некорректный номер заказа.');
    if(action==='claim')return request(`/staff/orders/${id}/claim/`,{method:'POST',body:{}});
    if(!['accept','reject','cook','ready','send','complete','cancel'].includes(action))throw new Error('Недопустимое действие с заказом.');
    return request(`/staff/orders/${id}/status/`,{method:'POST',body:{action,reason}});
  }
  window.MuslimAPI={enabled:Boolean(base),request,login,logout:()=>session(null),hasSession:()=>Boolean(tokens?.access),normalizeMenu,orderPayload,orderAction,results};
})();
