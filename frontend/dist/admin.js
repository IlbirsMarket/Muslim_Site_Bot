(() => {
  'use strict';
  const $=s=>document.querySelector(s),Store=window.MuslimStore,API=window.MuslimAPI;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=n=>`${new Intl.NumberFormat('ru-RU').format(n||0)} сом`;
  const list=data=>Array.isArray(data)?data:data?.results||[];
  const icon=window.MuslimIcons.render;
  const roles={owner:'Программист',programmer:'Программист',chef:'Шеф',admin:'Админ',cook:'Повар',waiter:'Официант',user:'Пользователь',blocked:'Заблокирован'};
  const views=[['orders','orders','Заказы'],['menu','menu','Меню'],['tables','tables','Столы и QR'],['users','users','Пользователи и роли'],['reports','reports','Отчёты'],['settings','settings','Настройки'],...(API.enabled?[['api','api','Проверка API']]:[])];
  let live=false,state,me,view='orders',orderFilter='all',menuFilter='all',query='',userFilter='all',reportPeriod='day',reportDate=Store.today(),loadSequence=0,cache={},confirmation,editorImage='',uploadFile=null,editingId=null,toastTimer;
  const editor=$('#editor-dialog');
  document.body.classList.toggle('api-mode',API.enabled);
  function paintControls(root=document){
    root.querySelectorAll('[data-icon]').forEach(element=>{element.innerHTML=icon(element.dataset.icon);});
    const rules=[
      ['[data-edit-dish]:not([data-edit-dish="new"]),[data-edit-table]','edit'],
      ['[data-edit-dish="new"],[data-add-table],#add-size','plus'],
      ['[data-delete-dish],[data-delete-table]','trash'],
      ['[data-close],[data-remove-size]','close'],
      ['[data-reload]','refresh'],
      ['[data-download-qr],[data-download-all-qr],[data-download-checks]','download'],
      ['[data-print-qr]','print'],
      ['[data-export-report]',live?'download':'print'],
      ['[data-export-csv]','file'],
      ['#dish-form [type="submit"],button[form="settings-form"],#table-form .form-footer .primary','save'],
      ['#reason-form [type="submit"]','close'],
      ['[data-call-done],#confirm-action','check'],
      ['#logout','logout'],
      ['#demo-login,#login-form [type="submit"]','logout']
    ];
    function apply(button,name){
      if(button.querySelector('.ui-icon'))return;
      button.textContent=button.textContent.replace(/^[+↻✎×]\s*|\s*↗$/g,'').trim();
      button.insertAdjacentHTML('afterbegin',icon(name));
    }
    rules.forEach(([selector,name])=>root.querySelectorAll(selector).forEach(button=>apply(button,name)));
    root.querySelectorAll('[data-order]').forEach(button=>apply(button,({claim:'users',cooking:'check',accept:'check',cook:'chef',ready:'checked',completed:'checked',complete:'checked',send:'truck',cancelled:'close',reject:'close',cancel:'close'})[button.dataset.action]||'check'));
    root.querySelectorAll('.toolbar input[type="search"]').forEach(input=>{
      if(input.parentElement.classList.contains('search-control'))return;
      const wrapper=document.createElement('div');wrapper.className='search-control';input.before(wrapper);wrapper.append(input);wrapper.insertAdjacentHTML('afterbegin',icon('search'));
    });
  }
  function toast(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4000);}
  function confirm(title,message,action){$('#confirm-title').textContent=title;$('#confirm-message').textContent=message;confirmation=action;$('#confirm-dialog').showModal();}
  function heading(title,subtitle='',actions=''){return `<header class="page-heading"><div class="title-group"><h1>${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div><div class="actions">${actions}</div></header>`;}
  function pill(name,value,active,action){return `<button class="pill ${active?'active':''}" data-${action}="${esc(value)}" aria-pressed="${active}">${esc(name)}</button>`;}
  function toggle(name,checked,attrs=''){return `<label class="switch"><input type="checkbox" aria-label="${esc(name)}" ${checked?'checked':''} ${attrs}><span></span></label>`;}
  function field(label,name,value,type='text',extra=''){return `<label>${label}<input name="${name}" value="${esc(value)}" type="${type}" ${extra}></label>`;}
  function image(url,alt='',className='thumb'){return safeImage(url)?`<img class="${className}" src="${esc(mediaUrl(url))}" alt="${esc(alt)}">`:`<span class="${className} photo-placeholder" aria-hidden="true">${icon('image')}</span>`;}
  function safeImage(url){return typeof url==='string'&&(/^(https?:|data:image\/(png|jpeg|webp);base64,)/.test(url));}
  function mediaUrl(url){try{const u=new URL(url);if(API.enabled&&u.pathname.startsWith('/media/'))return '/backend'+u.pathname;}catch{/* Data URI. */}return url;}
  async function localChange(change,message){const next=Store.clone(state);await change(next);Store.save(next);state=next;toast(message);await render();}
  function canManageMenu(){return !live||['programmer','chef','admin'].includes(me?.role);}
  function canAccess(id){
    if(id==='api')return live&&['programmer','owner'].includes(me?.role);
    return !live||['programmer','chef','admin'].includes(me?.role)||['orders',...(me?.role==='cook'?['menu']:[])].includes(id);
  }
  function showLogin(message=''){
    ++loadSequence;live=false;me=null;cache={};
    document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
    $('#admin-shell').hidden=true;$('#login-screen').hidden=false;$('#content').innerHTML='';
    $('#login-form').elements.password.value='';$('#login-error').textContent=message;
  }
  function nav(){
    $('#navigation').innerHTML=views.filter(([id])=>canAccess(id)).map(([id,icon,name])=>`<button class="nav-button" data-view="${id}" ${view===id?'aria-current="page"':''}><span class="nav-icon" aria-hidden="true">${window.MuslimIcons.render(icon)}</span><span class="nav-label">${name}</span><span class="nav-label-short">${id==='users'?'Роли':id==='tables'?'Столы':name}</span>${id==='orders'&&cache.newCount?`<b class="nav-badge">${cache.newCount}</b>`:''}</button>`).join('');
  }
  async function enter(useAPI,user){
    live=useAPI;me=user;state=useAPI?null:Store.load();if(live&&me.role==='admin')reportPeriod='day';
    if(!live){try{sessionStorage.setItem('muslim-demo-open','1');}catch{/* Вход работает без сохранения сессии. */}}
    $('#login-screen').hidden=true;$('#admin-shell').hidden=false;
    $('#staff-name').textContent=live?(me.first_name||me.username):'Администратор';
    $('#staff-role').textContent=live?`Роль: ${me.role_display}`:'Демонстрационный режим';
    $('#environment-label').textContent=live?'Локальный API · данные с сервера':'Демо · изменения только в этом браузере · Telegram не подключён';
    const requested=location.hash.slice(1);view=views.some(v=>v[0]===requested)&&canAccess(requested)?requested:'orders';
    await render();
  }
  async function render(){
    if(!canAccess(view))view='orders';
    const sequence=++loadSequence;nav();location.hash=view;
    $('#content').innerHTML='<div class="loading">Загружаем…</div>';
    try{
      let html='';
      if(view==='orders')html=await ordersView();
      if(view==='menu')html=await menuView();
      if(view==='tables')html=await tablesView();
      if(view==='users')html=await usersView();
      if(view==='reports')html=await reportsView();
      if(view==='settings')html=await settingsView();
      if(view==='api')html=apiView();
      if(sequence===loadSequence){$('#content').innerHTML=html;nav();paintControls($('#content'));}
    }catch(error){if(sequence!==loadSequence)return;$('#content').innerHTML=heading(views.find(v=>v[0]===view)?.[2]||'Панель')+`<div class="panel"><h2>Не удалось загрузить раздел</h2><p class="error">${esc(error.message)}</p><p class="fine">${error.status===500?'Сервер вернул 500. Ошибку нужно исправить в API.':error.status===401?'Войдите повторно.':error.status===403?'У вашей роли нет доступа к этому разделу.':'Проверьте подключение и повторите.'}</p><br><button class="secondary" data-reload>Повторить</button></div>`;}
  }
  async function ordersView(){
    let orders,calls=[];
    if(live){const data=await Promise.all([API.request('/staff/orders/?active=true'),me.role==='cook'?Promise.resolve([]):API.request('/staff/table-calls/')]);orders=list(data[0]);calls=list(data[1]);}
    else orders=state.orders;
    cache.orders=orders;cache.newCount=orders.filter(o=>o.status==='new').length;
    const filtered=orders.filter(o=>orderFilter==='all'||(orderFilter==='delivery'?(live?o.kind==='delivery':o.type==='delivery'):(live?o.kind==='hall':o.type==='cafe')));
    const groups=[['new','Новые',['new']],['cooking','Готовятся',['accepted','cooking']],['ready','Готовы и в пути',['ready','on_the_way']]];
    const callHtml=calls.length?`<div class="notice">${calls.map(c=>`<div class="actions"><strong>${esc(c.table_name)}: ${esc(c.kind_display)}</strong><button class="secondary" data-call-done="${c.id}">Выполнено</button></div>`).join('')}</div>`:'';
    return heading('Заказы',live?`${orders.length} активных заказов`:'Примеры заказов из макета',`<div class="pills">${[['all','Все'],['cafe','Зал'],['delivery','Доставка']].map(([id,label])=>pill(label,id,orderFilter===id,'order-filter')).join('')}</div><button class="secondary" data-reload>↻ Обновить</button>`)+callHtml+`<div class="board">${groups.map(([id,label,statuses])=>{const items=filtered.filter(o=>statuses.includes(o.status));return `<section class="column"><h2 class="column-heading"><i class="dot ${id}"></i>${label}<span>${items.length}</span></h2>${items.map(orderCard).join('')||'<div class="empty">Здесь пока нет заказов</div>'}</section>`;}).join('')}</div>`;
  }
  function orderCard(o){
    const delivery=live?o.kind==='delivery':o.type==='delivery';
    const title=live?(o.table_name||o.kind_display):o.type==='cafe'?`Стол ${o.table}`:o.type==='pickup'?'С собой':'Доставка';
    const items=live?o.items.map(i=>({name:[i.dish_name,i.size_name].filter(Boolean).join(' '),qty:i.quantity})):o.items;
    const actions=live?(o.available_actions||[]):o.status==='new'?[{action:'cooking',label:'Принять'},{action:'cancelled',label:'Отменить',needs_reason:true}]:o.status==='cooking'?[{action:'ready',label:'Готов'},{action:'cancelled',label:'Отменить',needs_reason:true}]:[{action:'completed',label:delivery?'Доставлен':'Выдан'},{action:'cancelled',label:'Отменить',needs_reason:true}];
    return `<article class="order-card"><div class="order-top"><strong>№${o.number||o.id}</strong><span class="tag ${delivery?'delivery':''}">${esc(title)}</span><small>${live?esc(o.status_label):o.minutes+' мин'}</small></div><div class="order-items">${items.map(i=>`${esc(i.name)} × ${i.qty}`).join('<br>')}</div>${o.comment||o.note?`<p class="order-note">${esc(o.comment||o.note)}</p>`:''}<div class="order-bottom"><strong>${money(live?o.total:Store.orderTotal(o))}</strong><div class="actions">${actions.map(a=>`<button class="${a.needs_reason?'danger':'primary'}" data-order="${o.id}" data-action="${esc(a.action)}" data-reason="${Boolean(a.needs_reason)}">${esc(a.label)}</button>`).join('')}</div></div></article>`;
  }
  async function menuView(){
    if(live&&me.role==='cook'){const [categories,dishes]=await Promise.all([API.request('/menu/'),API.request('/admin/dishes/')]);cache.categories=list(categories);cache.dishes=list(dishes);cache.extras=[];}
    else if(live){const [categories,dishes,extras]=await Promise.all([API.request('/admin/categories/'),API.request('/admin/dishes/'),API.request('/admin/extras/')]);cache.categories=list(categories);cache.dishes=list(dishes);cache.extras=list(extras);}
    else {cache.categories=state.menu.categories;cache.dishes=state.menu.dishes;cache.extras=state.menu.extras;}
    const rows=cache.dishes.filter(d=>(menuFilter==='all'||String(d.category)===menuFilter)&&`${d.name} ${d.description}`.toLowerCase().includes(query.toLowerCase()));
    const categories=[{id:'all',name:'Все'},...cache.categories];
    return heading('Меню',live?'Каталог с локального API':'Изменения видны в меню гостей в этом браузере',`${canManageMenu()?'<button class="primary" data-edit-dish="new">+ Добавить блюдо</button>':''}`)+`<div class="toolbar"><div class="pills">${categories.map(c=>pill(c.name,String(c.id),menuFilter===String(c.id),'menu-filter')).join('')}</div><input id="menu-search" type="search" aria-label="Поиск блюд" placeholder="Поиск блюда" value="${esc(query)}"></div><div class="data-wrap"><table class="data-table"><thead><tr><th>Блюдо</th><th class="category-col">Категория</th><th>Цена</th><th>В наличии</th><th>Действия</th></tr></thead><tbody>${rows.map(d=>`<tr><td><div class="dish-cell">${image(d.photo||d.image)}<div><strong>${esc(d.name)}</strong><p class="description">${esc(d.description)}</p></div></div></td><td class="category-col">${esc(cache.categories.find(c=>c.id===d.category)?.name||d.category_name||'')}</td><td>${live?(d.sizes?.length?d.sizes.map(s=>s.price).join(' / '):d.price):d.prices.join(' / ')} сом</td><td>${toggle(`В наличии: ${d.name}`,live?d.is_available:d.available,`data-availability="${d.id}"`)}</td><td>${canManageMenu()?`<div class="row-actions"><button class="icon-button" data-edit-dish="${d.id}" aria-label="Редактировать: ${esc(d.name)}">✎</button><button class="danger icon-button" data-delete-dish="${d.id}" aria-label="Удалить: ${esc(d.name)}">×</button></div>`:'<span class="fine">Только наличие</span>'}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Блюда не найдены</td></tr>'}</tbody></table></div>`;
  }
  function editDish(id){
    const d=id==='new'?null:cache.dishes.find(d=>String(d.id)===String(id));editingId=d?.id??null;editorImage=d?.image||'';uploadFile=null;
    const sizes=d?(live?(d.sizes||[]):d.prices.map((p,i)=>({name:d.sizes?.[i]||(d.category==='pizza'?`${[25,30,35][i]} см`:'Порция'),price:p}))):[];
    $('#editor-title').textContent=d?d.name:'Новое блюдо';
    $('#editor-content').innerHTML=`<form id="dish-form"><div class="image-editor"><div id="image-preview">${image(d?.photo||d?.image)}</div><div class="photo-upload"><label class="upload-button">${icon('upload')}<span id="photo-button-label">${d?.photo||d?.image?'Заменить фото':'Добавить фото'}</span><input id="dish-photo" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Загрузить фото блюда" aria-describedby="photo-help photo-status"></label><small class="fine photo-file-name" id="photo-help">PNG, JPG, WebP · до 2 МБ</small><span id="photo-status" class="photo-status" role="status" aria-live="polite"></span></div></div>${field('Название','name',d?.name||'','text','required maxlength="100"')}<label>Описание<textarea name="description" maxlength="500">${esc(d?.description||'')}</textarea></label><label>Категория<select name="category">${cache.categories.map(c=>`<option value="${c.id}" ${d?.category===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>${field('Основная цена, сом','price',live?(d?.price||0):(d?.prices[0]||0),'number','min="0" max="1000000" required step="1"')}<fieldset><legend>Размеры и цены</legend><div id="size-rows">${sizes.map(sizeRow).join('')}</div><button class="secondary" type="button" id="add-size">+ Добавить размер</button></fieldset>${live?`<fieldset><legend>Добавки</legend>${cache.extras.map(e=>`<label class="setting-line">${esc(e.name)} · ${money(e.price)}<input style="width:18px" name="extra" type="checkbox" value="${e.id}" ${d?.extras?.includes(e.id)?'checked':''}></label>`).join('')}</fieldset>`:''}<div class="setting-line">В наличии${toggle('В наличии',d?(live?d.is_available:d.available):true,'name="available"')}</div><p class="fine">${live?'Изменения сохраняются на сервере.':'Изменения сохраняются только в этом браузере.'}</p><p id="editor-error" class="error" role="alert"></p><footer class="form-footer"><button class="primary" type="submit">Сохранить</button>${d?`<button class="danger" type="button" data-delete-dish="${d.id}">Удалить</button>`:''}</footer></form>`;paintControls(editor);editor.showModal();
  }
  function syncBasePrice(){paintControls(editor);const field=$('#dish-form [name=price]');if(field)field.closest('label').hidden=$('#size-rows').children.length>0;}
  function sizeRow(s={name:'',price:0}){return `<div class="sizes-row" data-size-id="${s.id||''}"><input name="sizeName" aria-label="Название размера" value="${esc(s.name)}" maxlength="30" required><input name="sizePrice" aria-label="Цена размера" value="${s.price}" type="number" min="1" max="1000000" step="1" required><button class="icon-button" type="button" data-remove-size aria-label="Удалить размер">×</button></div>`;}
  async function saveDish(form){
    const values=new FormData(form),rows=[...form.querySelectorAll('.sizes-row')].map(row=>({id:row.dataset.sizeId?Number(row.dataset.sizeId):null,name:row.querySelector('[name=sizeName]').value.trim(),price:Number(row.querySelector('[name=sizePrice]').value)}));
    const name=String(values.get('name')).trim(),description=String(values.get('description')).trim(),available=values.has('available');
    if(!name)throw new Error('Укажите название блюда.');
    if(!rows.length&&Number(values.get('price'))<=0)throw new Error('Укажите цену или добавьте размер.');
    if(live){
      const payload={name,description,category:Number(values.get('category')),price:Number(values.get('price')),is_available:available,extras:values.getAll('extra').map(Number)};
      const d=await API.request(editingId?`/admin/dishes/${editingId}/`:'/admin/dishes/',{method:editingId?'PATCH':'POST',body:payload});
      // Сохраняем ID сразу: повторная попытка не создаст второе блюдо.
      const oldSizes=cache.dishes.find(item=>item.id===editingId)?.sizes||[];editingId=d.id;
      try{
        for(const [position,row] of rows.entries()){
          const saved=await API.request(row.id?`/admin/sizes/${row.id}/`:'/admin/sizes/',{method:row.id?'PATCH':'POST',body:{dish:d.id,name:row.name,price:row.price,position}});
          if(saved?.id){row.id=saved.id;form.querySelectorAll('.sizes-row')[position].dataset.sizeId=String(saved.id);}
        }
        for(const old of oldSizes.filter(s=>!rows.some(r=>r.id===s.id)))await API.request(`/admin/sizes/${old.id}/`,{method:'DELETE'});
        if(uploadFile){const data=new FormData();data.append('photo',uploadFile);await API.request(`/admin/dishes/${d.id}/`,{method:'PATCH',body:data});}
      }catch(error){throw new Error('Блюдо сохранено, но часть размеров или фото не сохранилась: '+error.message+'. Закройте редактор и откройте блюдо повторно.');}
    }else{
      const next=Store.clone(state);const id=editingId||`dish-${Date.now()}`;
      const d={id,category:String(values.get('category')),name,description,prices:rows.length?rows.map(r=>r.price):[Number(values.get('price'))],sizes:rows.length?rows.map(r=>r.name):['Порция'],available,image:editorImage};
      const i=next.menu.dishes.findIndex(d=>d.id===id);if(i<0)next.menu.dishes.push(d);else next.menu.dishes[i]=d;Store.save(next);state=next;
    }
    editor.close();toast('Блюдо сохранено');await render();
  }
  async function tablesView(){
    cache.tables=live?list(await API.request('/admin/tables/')):state.tables;
    return heading('Столы и QR-коды',`${cache.tables.length} столов`,`${live?'<button class="secondary" data-download-all-qr>Скачать QR (PDF)</button>':'<button class="secondary" data-print-qr>Печать QR / PDF</button>'}<button class="primary" data-add-table>+ Добавить стол</button>`)+(!live?'<p class="notice">QR открывает гостевое меню с номером стола. Адрес меню для печати QR можно изменить в настройках.</p>':'')+`<div class="qr-grid">${cache.tables.map(t=>{
      const url=tableUrl(t),id=live?t.id:t.number,occupied=live?t.active_orders:state.orders.filter(o=>o.table===t.number).length;
      return `<article class="qr-card"><header class="qr-top"><h2>${esc(t.name||(t.number?`Стол ${t.number}`:'Доставка'))}</h2><span class="tag ${occupied?'delivery':''}">${occupied?'Заказов: '+occupied:'Свободен'}</span></header>${qrSvg(url)}<a class="qr-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a><div class="actions"><button class="primary" data-download-qr="${id}">Скачать QR</button><button class="secondary" data-edit-table="${id}">Изменить</button></div></article>`;
    }).join('')}</div>`;
  }
  function tableUrl(t){if(live){const url=new URL('./',location.href);url.searchParams.set('token',t.token);return url.href;}const url=new URL(state.settings.menuUrl);url.searchParams.set('table',t.number);return url.href;}
  function qrSvg(url){const qr=qrcode(0,'M');qr.addData(url);qr.make();return qr.createSvgTag({cellSize:4,margin:16,scalable:true}).replace('<svg ','<svg role="img" aria-label="QR-код меню" ');}
  function editTable(id){const t=id==='new'?null:cache.tables.find(t=>String(live?t.id:t.number)===String(id));editingId=live?t?.id:t?.number;$('#editor-title').textContent=t?'Настройки стола':'Новый стол';$('#editor-content').innerHTML=`<form id="table-form">${field('Название','name',t?.name||'','text','maxlength="50" required')}${field('Номер','number',t?.number||'','number','min="1" max="999" required')}${live?`<label>Тип<select name="kind"><option value="hall">Зал</option><option value="delivery" ${t?.kind==='delivery'?'selected':''}>Доставка</option></select></label>`:''}<p class="fine">${live?'QR сервера связан с секретным токеном.':'Для QR используется адрес гостевого меню из настроек.'}</p><p id="editor-error" class="error"></p><footer class="form-footer"><button class="primary">Сохранить</button>${t?`<button type="button" class="danger" data-delete-table="${live?t.id:t.number}">Удалить</button>`:''}</footer></form>`;paintControls(editor);editor.showModal();}
  async function usersView(){
    if(live){const [users,allowed,audit]=await Promise.all([API.request('/admin/staff/'),API.request('/admin/staff/roles/'),API.request('/admin/staff/role-log/')]);cache.users=list(users);cache.roles=list(allowed);cache.audit=list(audit);}
    else{cache.users=state.users;cache.roles=['admin','cook','user'].map(value=>({value,label:roles[value]}));cache.audit=state.audit;}
    const users=cache.users.filter(u=>(userFilter==='all'||u.role===userFilter)&&`${u.name||u.first_name||''} ${u.handle||u.username}`.toLowerCase().includes(query.toLowerCase()));
    const filters=['all',...new Set(cache.users.map(u=>u.role))];
    return heading('Пользователи и роли',live?'Права проверяются сервером':'Демо-роли не предоставляют настоящий доступ')+`<div class="toolbar"><div class="pills">${filters.map(r=>pill(r==='all'?`Все · ${cache.users.length}`:roles[r],r,userFilter===r,'user-filter')).join('')}</div><input id="user-search" type="search" aria-label="Поиск пользователей" placeholder="Имя или логин" value="${esc(query)}"></div><div class="users-layout"><div class="data-wrap"><table class="data-table"><thead><tr><th>Пользователь</th><th>Роль</th><th class="category-col">Статус</th></tr></thead><tbody>${users.map(u=>{const name=u.name||u.first_name||u.username,roleOptions=cache.roles.some(r=>r.value===u.role)?cache.roles:[{value:u.role,label:roles[u.role]},...cache.roles];return `<tr><td><div class="user-cell"><span class="avatar">${esc(name[0])}</span><div><strong>${esc(name)}</strong><small>@${esc(u.handle||u.username)}</small></div></div></td><td><select class="role-select" data-role-user="${u.id}" aria-label="Роль: ${esc(name)}" ${(live?!u.can_edit||u.id===me.id:u.role==='owner')?'disabled':''}>${roleOptions.map(r=>`<option value="${r.value}" ${r.value===u.role?'selected':''}>${esc(r.label)}</option>`).join('')}</select></td><td class="category-col">${live?u.is_active?'Активен':'Отключён':u.role==='blocked'?'Отключён':'Активен'}</td></tr>`;}).join('')||'<tr><td colspan="3" class="empty">Пользователи не найдены</td></tr>'}</tbody></table></div><aside class="panel"><h2>История смены ролей</h2>${cache.audit.slice().reverse().slice(0,20).map(a=>`<div class="audit-row"><strong>${esc(a.user_name||a.name)}</strong><br>${esc(a.old_role_display||roles[a.from])} → ${esc(a.new_role_display||roles[a.to])}<small>${esc(a.created_at||a.at)}</small></div>`).join('')||'<p class="fine">Пока нет изменений ролей</p>'}</aside></div>`;
  }
  async function reportsView(){
    const actions=`<button class="secondary" data-export-report>${live?'Скачать PDF':'Печать / PDF'}</button><button class="secondary" data-export-csv>${live?'JSON':'CSV'}</button>`;
    const top=heading('Отчёты',live?'Данные с API':'Демонстрационные данные',actions)+`<div class="toolbar"><div class="pills">${pill('За день','day',reportPeriod==='day','report-period')}${!live||['chef','programmer'].includes(me?.role)?pill('За 45 дней','period',reportPeriod==='period','report-period'):''}</div>${reportPeriod==='day'?`<input class="report-date" type="date" id="report-date" value="${reportDate}" max="${Store.today()}" aria-label="Дата отчёта">`:`<span class="fine">${Store.dayOffset(Store.today(),-44)} — ${Store.today()}</span>`}</div>`;
    if(live){
      try{cache.report=await API.request(reportPeriod==='day'?`/admin/reports/day/?date=${reportDate}`:'/admin/reports/period/');
        return top+`<div class="panel"><h2>Отчёт API</h2><pre class="raw-report">${esc(JSON.stringify(cache.report,null,2))}</pre></div>`;
      }catch(error){cache.report=null;return top+`<div class="panel"><h2>Отчёт недоступен</h2><p class="error">${esc(error.message)}</p><br><p class="fine">${error.status===500?'API вернул 500. Данные не подменены примерами. Ошибка зарегистрирована в разделе «Проверка API».':'Проверьте подключение к API.'}</p></div>`;}
    }
    const start=reportPeriod==='day'?reportDate:Store.dayOffset(Store.today(),-44),end=reportPeriod==='day'?reportDate:Store.today();
    const rows=state.history.filter(o=>o.date>=start&&o.date<=end),completed=rows.filter(o=>o.status==='completed'),revenue=completed.reduce((s,o)=>s+Store.orderTotal(o),0),cancelled=rows.filter(o=>o.status==='cancelled').length;
    const products=new Map();completed.forEach(o=>o.items.forEach(i=>{const p=products.get(i.name)||{name:i.name,qty:0,sum:0};p.qty+=i.qty;p.sum+=i.qty*i.price;products.set(i.name,p);}));
    const ranked=[...products.values()].sort((a,b)=>b.sum-a.sum);cache.reportRows=ranked;
    const points=reportPeriod==='day'?Array.from({length:13},(_,i)=>({label:`${i+10}`,sum:completed.filter(o=>o.hour===i+10).reduce((s,o)=>s+Store.orderTotal(o),0)})):Array.from({length:45},(_,i)=>{const day=Store.dayOffset(start,i);return {label:day.slice(8),sum:completed.filter(o=>o.date===day).reduce((s,o)=>s+Store.orderTotal(o),0)};});
    const max=Math.max(1,...points.map(p=>p.sum));
    return top+`<div class="stats"><article class="stat"><span>Выручка</span><strong>${money(revenue)}</strong><small>Завершённые заказы</small></article><article class="stat"><span>Заказы</span><strong>${completed.length}</strong><small>За выбранный период</small></article><article class="stat"><span>Средний чек</span><strong>${money(completed.length?Math.round(revenue/completed.length):0)}</strong><small>Выручка / заказы</small></article><article class="stat"><span>Отменено</span><strong>${cancelled}</strong><small>Не входят в выручку</small></article></div><section class="panel chart-panel"><h2>Выручка ${reportPeriod==='day'?'по часам':'по дням'}, сом</h2><div class="chart ${reportPeriod==='period'?'period':''}" role="img" aria-label="График выручки">${points.map(p=>`<div class="bar-group" title="${p.label}: ${money(p.sum)}"><div class="bar" style="height:${p.sum/max*100}%"></div>${reportPeriod==='day'||Number(p.label)%5===0?`<small>${p.label}${reportPeriod==='day'?':00':''}</small>`:''}</div>`).join('')}</div></section><div class="data-wrap"><table class="data-table"><thead><tr><th>Блюдо</th><th>Продано</th><th>Выручка</th><th class="category-col">Доля</th></tr></thead><tbody>${ranked.map(p=>`<tr><td>${esc(p.name)}</td><td>${p.qty}</td><td>${money(p.sum)}</td><td class="category-col"><div class="progress"><span style="width:${p.sum/(ranked[0]?.sum||1)*100}%"></span></div></td></tr>`).join('')||'<tr><td colspan="4" class="empty">Нет заказов за выбранный день</td></tr>'}</tbody></table></div>`;
  }
  async function settingsView(){
    const s=live?await API.request('/admin/cafe/'):state.settings;cache.settings=s;
    const get=(remote,local)=>live?s[remote]:s[local];
    return heading('Настройки','',`<button class="primary" type="submit" form="settings-form">Сохранить</button>`)+`<form id="settings-form"><div class="settings-grid"><section class="panel"><h2>Приём заказов</h2><div class="setting-line">Принимать заказы с сайта${toggle('Принимать заказы',get('is_accepting_orders','acceptOrders'),'name="acceptOrders"')}</div><div class="setting-line">Принимать доставку${toggle('Принимать доставку',get('is_delivery_enabled','acceptDelivery'),'name="acceptDelivery"')}</div><div class="two-fields">${field('Открываемся','opens',get('opens_at','opens')?.slice(0,5),'time','required')}${field('Закрываемся','closes',get('closes_at','closes')?.slice(0,5),'time','required')}</div></section><section class="panel"><h2>Доставка</h2><div class="three-fields">${field('Мин. сумма, сом','deliveryMin',get('delivery_min_sum','deliveryMin'),'number','min="0" max="1000000" required')}${field('Стоимость, сом','deliveryFee',get('delivery_fee','deliveryFee'),'number','min="0" max="1000000" required')}${field('Время, мин','deliveryTime',get('delivery_time','deliveryTime'),'text','maxlength="50" required')}</div>${field('Бесплатная доставка от, сом (0 — нет)','freeFrom',get('free_delivery_from','freeFrom'),'number','min="0" max="1000000" required')}</section><section class="panel"><h2>Контакты кафе</h2>${field('Адрес','address',s.address,'text','maxlength="200"')}${field('Телефон','phone',s.phone,'tel','maxlength="30"')}</section><section class="panel"><h2>Telegram</h2><p class="fine">Telegram пока не подключён. Уведомления и отправка отчётов в группу будут доступны после подключения бота.</p><div class="setting-line">Отчёт в группу${toggle('Отчёт в Telegram',false,'disabled')}</div><p class="fine">Время работы и параметры доставки сохраняются ${live?'на сервере':'только в этом браузере'}.</p></section>${live?'':`<section class="panel"><h2>Ссылка меню для QR</h2>${field('Адрес гостевого меню','menuUrl',s.menuUrl,'url','required maxlength="400"')}<p class="fine">Для печати QR укажите опубликованный адрес сайта, доступный гостям.</p></section>`}</div><p id="settings-error" class="error" role="alert"></p></form>`;
  }
  function apiView(){
    return heading('Проверка API',API.enabled?'Локальное подключение через сайт':'Доступно при локальном запуске')+`<p class="notice">Проверка выполняет чтение данных и заведомо некорректные запросы без создания заказов. Изменения проверяются через соответствующие разделы панели.</p><div class="api-toolbar"><button class="primary" data-run-checks ${API.enabled?'':'disabled'}>Проверить методы</button><button class="secondary" data-download-checks>Скачать результаты</button><span class="fine">${live?'Проверка с вашей ролью':API.hasSession()?'Есть сессия API':'Без авторизации'}</span></div><div class="data-wrap"><table class="data-table connection-results"><thead><tr><th>Метод</th><th>Путь</th><th>Статус</th><th>Время</th></tr></thead><tbody id="api-results">${resultRows()}</tbody></table></div>`;
  }
  function resultRows(){return API.results.map(r=>`<tr><td>${r.method}</td><td>${esc(r.path)}</td><td class="${Number(r.status)<400?'http-ok':'http-error'}">${r.status}</td><td>${r.elapsed} мс</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Нажмите «Проверить методы»</td></tr>';}
  async function runChecks(){
    if(!canAccess('api'))throw new Error('Проверка API доступна только программисту.');
    const button=$('[data-run-checks]');button.disabled=true;
    const paths=['/cafe/','/menu/','/auth/me/','/admin/cafe/','/admin/categories/','/admin/dishes/','/admin/extras/','/admin/sizes/','/admin/tables/','/admin/staff/','/admin/staff/roles/','/staff/orders/?active=true','/staff/table-calls/','/admin/reports/day/','/admin/reports/period/','/admin/reports/periods/'];
    for(const path of paths){try{await API.request(path);}catch{/* Ошибка отображается в журнале. */}}
    try{await API.request('/orders/',{method:'POST',body:{},auth:false});}catch{/* Ожидаем 400. */}
    try{await API.request('/table-calls/',{method:'POST',body:{},auth:false});}catch{/* Ожидаем 400. */}
    if(button.isConnected)button.disabled=false;toast('Проверка завершена. HTTP 400 у пустых запросов — ожидаемая валидация.');
  }
  function download(name,content,type='text/plain;charset=utf-8'){const blob=content instanceof Blob?content:new Blob([content],{type});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function act(button){
    if(button.dataset.view){view=button.dataset.view;query='';await render();return;}
    if(button.hasAttribute('data-reload')){await render();return;}
    if(button.hasAttribute('data-close')){button.closest('dialog').close();return;}
    if(button.dataset.orderFilter){orderFilter=button.dataset.orderFilter;await render();return;}
    if(button.dataset.menuFilter){menuFilter=button.dataset.menuFilter;await render();return;}
    if(button.dataset.userFilter){userFilter=button.dataset.userFilter;await render();return;}
    if(button.dataset.reportPeriod){reportPeriod=button.dataset.reportPeriod;await render();return;}
    if(button.dataset.editDish){if(!canManageMenu())throw new Error('Для этой роли доступно только изменение наличия.');editDish(button.dataset.editDish);syncBasePrice();return;}
    if(button.id==='add-size'){if($('#size-rows').children.length>=3){toast('Максимум три варианта размера');return;}$('#size-rows').insertAdjacentHTML('beforeend',sizeRow());syncBasePrice();return;}
    if(button.hasAttribute('data-remove-size')){button.closest('.sizes-row').remove();syncBasePrice();return;}
    if(button.dataset.deleteDish){const id=button.dataset.deleteDish,d=cache.dishes.find(d=>String(d.id)===id);confirm('Удалить блюдо?',`«${d.name}» будет удалено ${live?'с сервера':'из локального меню'}.`,async()=>{if(live)await API.request(`/admin/dishes/${id}/`,{method:'DELETE'});else await localChange(s=>{s.menu.dishes=s.menu.dishes.filter(d=>d.id!==id);},'Блюдо удалено');editor.close();await render();});return;}
    if(button.dataset.order){const id=Number(button.dataset.order),action=button.dataset.action;const perform=async reason=>{if(live)await API.orderAction(id,action,reason);else await localChange(s=>Store.transition(s,id,action),'Статус обновлён');await render();};
      if(button.dataset.reason==='true'){reasonDialog('Причина отмены',reason=>perform(reason));}else await perform('');return;
    }
    if(button.dataset.callDone){await API.request(`/staff/table-calls/${button.dataset.callDone}/done/`,{method:'POST',body:{}});await render();return;}
    if(button.hasAttribute('data-add-table')){editTable('new');return;}
    if(button.dataset.editTable){editTable(button.dataset.editTable);return;}
    if(button.dataset.deleteTable){const id=button.dataset.deleteTable;if(!live&&state.orders.some(o=>String(o.table)===id))throw new Error('Сначала завершите или отмените заказы этого стола.');confirm('Удалить стол?',live?'Напечатанный QR этого стола перестанет работать.':'Стол будет удалён из локального списка.',async()=>{if(live)await API.request(`/admin/tables/${id}/`,{method:'DELETE'});else await localChange(s=>{s.tables=s.tables.filter(t=>String(t.number)!==id);},'Стол удалён');editor.close();await render();});return;}
    if(button.dataset.downloadQr){const id=button.dataset.downloadQr,t=cache.tables.find(t=>String(live?t.id:t.number)===id);if(live)download(`Муслим-QR-${t.number||'доставка'}.png`,await API.request(`/admin/tables/${id}/qr/`,{binary:true}));else download(`Муслим-стол-${id}.svg`,qrSvg(tableUrl(t)),'image/svg+xml');return;}
    if(button.hasAttribute('data-download-all-qr')){download('Муслим-QR.pdf',await API.request('/admin/tables/qr-pdf/',{binary:true}));return;}
    if(button.hasAttribute('data-print-qr')){$('#print-area').innerHTML='<h1>Муслим — столы и QR</h1>'+$('.qr-grid').outerHTML;$('#print-area').querySelectorAll('.actions').forEach(e=>e.remove());window.print();return;}
    if(button.hasAttribute('data-export-report')){if(live){download('Муслим-отчёт.pdf',await API.request(reportPeriod==='day'?`/admin/reports/day/pdf/?date=${reportDate}`:'/admin/reports/period/pdf/',{binary:true}));}else{$('#print-area').innerHTML='<h1>Муслим — отчёт (демонстрационные данные)</h1>'+$('#content').innerHTML;$('#print-area').querySelectorAll('button,input,.toolbar').forEach(e=>e.remove());window.print();}return;}
    if(button.hasAttribute('data-export-csv')){if(live){if(!cache.report)throw new Error('Отчёт не загружен. Сервер вернул ошибку.');download('Муслим-отчёт.json',JSON.stringify(cache.report,null,2),'application/json');}else download('Муслим-демо-отчёт.csv','\uFEFFБлюдо;Количество;Сумма\n'+(cache.reportRows||[]).map(p=>`"${p.name.replaceAll('"','""')}";${p.qty};${p.sum}`).join('\n'),'text/csv;charset=utf-8');return;}
    if(button.hasAttribute('data-run-checks')){await runChecks();return;}
    if(button.hasAttribute('data-download-checks')){if(!canAccess('api'))throw new Error('Проверка API доступна только программисту.');download('Муслим-проверка-API.json',JSON.stringify(API.results,null,2),'application/json');return;}
  }
  function reasonDialog(title,handler){$('#editor-title').textContent=title;$('#editor-content').innerHTML='<form id="reason-form"><label>Причина<textarea name="reason" maxlength="255" required></textarea></label><p id="editor-error" class="error"></p><button class="danger" type="submit">Отменить заказ</button></form>';cache.reasonHandler=handler;paintControls(editor);editor.showModal();}
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button||button.disabled)return;if(button.id==='confirm-action'||button.id==='demo-login'||button.id==='logout'||button.id==='session-logout')return;if(button.form&&button.type==='submit')return;button.disabled=true;act(button).catch(error=>toast(error.message)).finally(()=>{if(button.isConnected)button.disabled=false;});});
  $('#confirm-action').addEventListener('click',async event=>{const b=event.currentTarget;b.disabled=true;try{await confirmation();$('#confirm-dialog').close();}catch(error){toast(error.message);}finally{b.disabled=false;}});
  document.addEventListener('input',event=>{if(event.target.id==='menu-search'||event.target.id==='user-search'){query=event.target.value;const focused=event.target.id;const cursor=event.target.selectionStart;clearTimeout(cache.searchTimer);cache.searchTimer=setTimeout(async()=>{await render();const input=$('#'+focused);if(input){input.focus();try{input.setSelectionRange(cursor,cursor);}catch{/* Search may not support selection. */}}},180);}});
  document.addEventListener('change',async event=>{const input=event.target;
    try{
      if(input.id==='report-date'){reportDate=input.value||Store.today();await render();}
      if(input.dataset.availability){const id=input.dataset.availability;input.disabled=true;if(live)await API.request(me.role==='cook'?`/admin/dishes/${id}/toggle-available/`:`/admin/dishes/${id}/`,{method:me.role==='cook'?'POST':'PATCH',body:me.role==='cook'?{}:{is_available:input.checked}});else await localChange(s=>{s.menu.dishes.find(d=>d.id===id).available=input.checked;},'Наличие обновлено');await render();}
      if(input.dataset.roleUser){const id=input.dataset.roleUser,role=input.value,u=cache.users.find(u=>String(u.id)===id);confirm('Изменить роль?',`${u.name||u.first_name||u.username}: ${roles[u.role]} → ${roles[role]}. ${live?'Права изменятся на сервере.':'Это локальный пример.'}`,async()=>{if(live)await API.request(`/admin/staff/${id}/set-role/`,{method:'POST',body:{role}});else await localChange(s=>{const u=s.users.find(u=>u.id===id);s.audit.push({name:u.name,from:u.role,to:role,at:new Date().toLocaleString('ru-RU')});u.role=role;},'Роль изменена');await render();});input.value=u.role;}
      if(input.id==='dish-photo'){const file=input.files[0];if(!file)return;$('#photo-status').textContent='';$('#photo-status').classList.remove('error');if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024)throw new Error('Нужно фото PNG, JPG или WebP до 2 МБ.');uploadFile=file;input.disabled=true;input.closest('.upload-button').setAttribute('aria-busy','true');const url=URL.createObjectURL(file);try{const photo=new Image();photo.src=url;await photo.decode();const canvas=document.createElement('canvas'),scale=Math.min(1,700/Math.max(photo.width,photo.height));canvas.width=Math.round(photo.width*scale);canvas.height=Math.round(photo.height*scale);canvas.getContext('2d').drawImage(photo,0,0,canvas.width,canvas.height);editorImage=canvas.toDataURL('image/jpeg',.8);$('#image-preview').innerHTML=image(editorImage);$('#photo-button-label').textContent='Заменить фото';$('#photo-help').textContent=file.name;$('#photo-help').title=file.name;$('#photo-status').textContent='Фото готово. Нажмите «Сохранить», чтобы применить.';}finally{URL.revokeObjectURL(url);}}
    }catch(error){toast(error.message);if(input.dataset.availability)await render();if(input.id==='dish-photo'){input.value='';uploadFile=null;if($('#photo-status')){$('#photo-status').textContent=error.message;$('#photo-status').classList.add('error');}}}finally{input.disabled=false;if(input.id==='dish-photo')input.closest('.upload-button')?.removeAttribute('aria-busy');}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['dish-form','table-form','settings-form','reason-form'].includes(form.id))return;event.preventDefault();const submit=form.querySelector('[type=submit]')||form.querySelector('.primary');if(submit)submit.disabled=true;
    try{
      if(form.id==='dish-form')await saveDish(form);
      if(form.id==='table-form'){const values=new FormData(form),payload={name:String(values.get('name')).trim(),number:Number(values.get('number'))};if(!payload.name)throw new Error('Укажите название стола.');if(live)await API.request(editingId?`/admin/tables/${editingId}/`:'/admin/tables/',{method:editingId?'PATCH':'POST',body:{...payload,kind:values.get('kind')}});else await localChange(s=>{if(s.tables.some(t=>t.number===payload.number&&t.number!==editingId))throw new Error('Стол с таким номером уже существует.');s.orders.forEach(o=>{if(o.table===editingId)o.table=payload.number;});s.tables=s.tables.filter(t=>t.number!==editingId);s.tables.push(payload);s.tables.sort((a,b)=>a.number-b.number);},'Стол сохранён');editor.close();await render();}
      if(form.id==='settings-form'){const values=new FormData(form),s={acceptOrders:values.has('acceptOrders'),acceptDelivery:values.has('acceptDelivery'),opens:String(values.get('opens')),closes:String(values.get('closes')),deliveryMin:Number(values.get('deliveryMin')),deliveryFee:Number(values.get('deliveryFee')),deliveryTime:String(values.get('deliveryTime')).trim(),freeFrom:Number(values.get('freeFrom')),address:String(values.get('address')).trim(),phone:String(values.get('phone')).trim()};if(live)await API.request('/admin/cafe/',{method:'PATCH',body:{is_accepting_orders:s.acceptOrders,is_delivery_enabled:s.acceptDelivery,opens_at:s.opens,closes_at:s.closes,delivery_min_sum:s.deliveryMin,delivery_fee:s.deliveryFee,delivery_time:s.deliveryTime,free_delivery_from:s.freeFrom,address:s.address,phone:s.phone}});else await localChange(next=>Object.assign(next.settings,s,{menuUrl:String(values.get('menuUrl'))}),'Настройки сохранены');toast('Настройки сохранены');}
      if(form.id==='reason-form'){const reason=new FormData(form).get('reason').trim();if(!reason)throw new Error('Укажите причину отмены.');await cache.reasonHandler(reason);editor.close();}
    }catch(error){const target=form.querySelector('.error');if(target)target.textContent=error.message;else toast(error.message);}finally{if(submit)submit.disabled=false;}
  });
  $('#login-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;$('#login-error').textContent='';try{if(!API.enabled)throw new Error('Запустите локальную версию сайта для подключения к API.');const data=new FormData(form),user=await API.login(String(data.get('username')).trim(),String(data.get('password')));form.reset();await enter(true,user);}catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}});
  $('#demo-login').addEventListener('click',()=>enter(false,null).catch(error=>toast(error.message)));
  function logout(){API.logout();try{sessionStorage.removeItem('muslim-demo-open');}catch{/* Нет сохранённой демо-сессии. */}location.hash='';showLogin();}
  $('#logout').addEventListener('click',logout);
  $('#session-logout').addEventListener('click',logout);
  window.addEventListener('muslim-session-expired',()=>{if(live)showLogin('Сессия истекла. Войдите повторно.');});
  window.addEventListener('muslim-api-result',()=>{if(view==='api'&&$('#api-results'))$('#api-results').innerHTML=resultRows();});
  $('#login-description').textContent=API.enabled?'Войдите под своей учётной записью локального API.':'Панель без базы данных. Вы можете проверить все разделы на демонстрационных данных.';
  if(!API.enabled){
    $('#login-form').hidden=true;$('.divider').hidden=true;
    $('#login-description').textContent='Для работы с локальным API откройте локальную версию сайта. Здесь также доступен демонстрационный режим.';
    const localUrl=window.MUSLIM_CONFIG?.localAppUrl;
    if(localUrl){const link=document.createElement('a');link.className='primary local-api-link';link.href=new URL('/admin',localUrl).href;link.textContent='Открыть с API';$('#login-description').after(link);}
  }
  paintControls(document);
  if(API.enabled&&API.hasSession())API.request('/auth/me/').then(user=>enter(true,user)).catch(error=>{$('#login-error').textContent=error.message;});
  if(!API.enabled){try{if(sessionStorage.getItem('muslim-demo-open')==='1')enter(false,null).catch(error=>toast(error.message));}catch{/* Показываем начальный экран. */}}
})();
