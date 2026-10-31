(() => {
  'use strict';
  const $=s=>document.querySelector(s),Store=window.MuslimStore,API=window.MuslimAPI;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=n=>`${new Intl.NumberFormat('ru-RU').format(n||0)} сом`;
  const list=data=>Array.isArray(data)?data:data?.results||[];
  const icon=window.MuslimIcons.render;
  const roles={owner:'Программист',programmer:'Программист',chef:'Шеф',admin:'Админ',cook:'Повар',waiter:'Официант',courier:'Курьер',user:'Пользователь',blocked:'Заблокирован'};
  const views=[['orders','orders','Заказы'],['menu','menu','Блюда и категории'],['tables','tables','Столы и QR'],['users','users','Пользователи и роли'],['reports','reports','Отчёты'],['settings','settings','Настройки'],...(API.enabled?[['api','api','Проверка API']]:[])];
  let live=false,state,me,view='orders',orderFilter='all',menuFilter='all',menuTab='cats',query='',userFilter='all',reportPeriod='day',reportScope='branch',reportDate=Store.today(),loadSequence=0,cache={},confirmation,editorImage='',uploadFile=null,editingId=null,toastTimer;
  const editor=$('#editor-dialog');
  document.body.classList.toggle('api-mode',API.enabled);
  function paintControls(root=document){
    root.querySelectorAll('[data-icon]').forEach(element=>{element.innerHTML=icon(element.dataset.icon);});
    const rules=[
      ['[data-edit-dish]:not([data-edit-dish="new"]),[data-edit-table],[data-edit-staff]','edit'],
      ['[data-edit-dish="new"],[data-add-table],[data-add-staff],#add-size,[data-add-category]','plus'],
      ['[data-cancel-category]','close'],
      ['[data-close-table]','check'],
      ['[data-add-table]','plus'],
      ['[data-delete-dish],[data-delete-table],[data-delete-staff],[data-delete-category]','trash'],
      ['[data-edit-category]','edit'],
      ['[data-regenerate-qr],[data-regenerate-bot-qr]','refresh'],
      ['[data-close],[data-remove-size]','close'],
      ['[data-reload]','refresh'],
      ['[data-download-qr],[data-download-bot-qr],[data-download-all-qr],[data-download-checks]','download'],
      ['[data-print-qr]','print'],
      ['[data-export-report]',live?'download':'print'],
      ['[data-export-csv]','file'],
      ['#dish-form [type="submit"],button[form="settings-form"],#table-form .form-footer .primary,#staff-form .form-footer .primary','save'],
      ['#reason-form [type="submit"]','close'],
      ['[data-call-done],#confirm-action','check'],
      ['#logout','logout'],
      ['#login-form [type="submit"]','logout']
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
  // kind: hall (в кафе, зелёный) / takeaway (с собой, жёлтый) / delivery (доставка, красный) / pickup (самовывоз, оранжевый)
  function toast(message,kind=''){$('#toast').textContent=message;$('#toast').className='toast'+(kind?' kind-'+kind:'');$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4000);}
  function confirm(title,message,action){$('#confirm-title').textContent=title;$('#confirm-message').textContent=message;confirmation=action;$('#confirm-dialog').showModal();}
  // Время «14:05» из даты сервера
  function clock(iso){try{return new Date(iso).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});}catch{return '';}}
  function heading(title,subtitle='',actions=''){return `<header class="page-heading"><div class="title-group"><h1>${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div><div class="actions">${actions}</div></header>`;}
  function pill(name,value,active,action){return `<button class="pill ${active?'active':''}" data-${action}="${esc(value)}" aria-pressed="${active}">${esc(name)}</button>`;}
  function toggle(name,checked,attrs=''){return `<label class="switch"><input type="checkbox" aria-label="${esc(name)}" ${checked?'checked':''} ${attrs}><span></span></label>`;}
  function field(label,name,value,type='text',extra=''){return `<label>${label}<input name="${name}" value="${esc(value)}" type="${type}" ${extra}></label>`;}
  function image(url,alt='',className='thumb'){return safeImage(url)?`<img class="${className}" src="${esc(mediaUrl(url))}" alt="${esc(alt)}">`:`<span class="${className} photo-placeholder" aria-hidden="true">${icon('image')}</span>`;}
  function safeImage(url){return typeof url==='string'&&(/^(https?:|data:image\/(png|jpeg|webp);base64,)/.test(url));}
  function mediaUrl(url){try{const u=new URL(url);if(API.enabled&&u.pathname.startsWith('/media/'))return '/backend'+u.pathname;}catch{/* Data URI. */}return url;}
  async function localChange(change,message){const next=Store.clone(state);await change(next);Store.save(next);state=next;toast(message);await render();}
  // ===== Филиалы: шеф и программист переключают филиал, остальные работают только в своём =====
  function multiBranch(){return live&&(me?.branches||[]).length>1;}                                   // видит больше одного филиала
  function currentBranch(){const list=me?.branches||[];return list.find(b=>String(b.id)===String(API.branch()))||list[0]||null;}
  function branchName(){return live?(multiBranch()?currentBranch()?.name:me?.branch_name)||'':'';}
  function paintBranch(){                                                                            // переключатель в верхней полосе
    const current=currentBranch(),html=multiBranch()?me.branches.map(b=>`<button type="button" data-branch="${b.id}" aria-pressed="${String(b.id)===String(current?.id)}">${esc(b.name)}</button>`).join(''):'';
    const side=$('#branch-switch-side');if(side){side.hidden=!html;side.innerHTML=html;}                       // компьютер и широкий планшет: в левом зелёном меню
    const fab=$('#branch-fab');                                                                                  // телефон и узкий планшет: плавающая кнопка
    if(fab){const list=me?.branches||[],at=list.findIndex(b=>String(b.id)===String(current?.id)),next=list[(at+1)%Math.max(list.length,1)];
      fab.hidden=!html;
      if(html&&next){fab.dataset.branch=next.id;fab.setAttribute('aria-label',`Сменить филиал: сейчас «${current?.name}», открыть «${next.name}»`);fab.innerHTML=`<span aria-hidden="true">⇄</span>Сменить<span class="fab-branch">${esc(current?.name||'')}</span>`;}}
    $('#environment-label').textContent=live?`Панель кафе «Муслим»${branchName()?' · '+branchName():''}`:'Демо · изменения только в этом браузере · Telegram не подключён';
    const guestLink=$('.environment-actions a');if(guestLink)guestLink.href=live&&currentBranch()?`./?branch=${currentBranch().id}`:'./';   // «Меню гостей» — меню этого филиала
  }
  function canManageMenu(){return !live||['programmer','chef','admin'].includes(me?.role);}
  function canAccess(id){
    if(id==='api')return live&&['programmer','owner'].includes(me?.role);
    return !live||['programmer','chef','admin'].includes(me?.role)||['orders',...(me?.role==='cook'?['menu']:[]),...(me?.role==='waiter'?['tables']:[])].includes(id);   // официант видит столы, повар — блюда (стоп-лист)
  }
  function showLogin(message=''){
    stopWatch();   // вышли — уведомления больше не нужны
    ++loadSequence;live=false;me=null;cache={};
    document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
    $('#admin-shell').hidden=true;$('#login-screen').hidden=false;$('#content').innerHTML='';
    $('#login-form').elements.password.value='';$('#login-error').textContent=message;
  }
  function nav(){
    $('#navigation').innerHTML=views.filter(([id])=>canAccess(id)).map(([id,icon,name])=>`<button class="nav-button" data-view="${id}" ${view===id?'aria-current="page"':''}><span class="nav-icon" aria-hidden="true">${window.MuslimIcons.render(icon)}</span><span class="nav-label">${name}</span><span class="nav-label-short">${id==='users'?'Роли':id==='tables'?'Столы':id==='menu'?'Блюда':name}</span>${id==='orders'&&cache.newCount?`<b class="nav-badge">${cache.newCount}</b>`:''}</button>`).join('');
  }
  async function enter(useAPI,user){
    live=useAPI;me=user;state=useAPI?null:Store.load();if(live&&me.role==='admin')reportPeriod='day';
    if(!live){try{sessionStorage.setItem('muslim-demo-open','1');}catch{/* Вход работает без сохранения сессии. */}}
    $('#login-screen').hidden=true;$('#admin-shell').hidden=false;
    $('#staff-name').textContent=live?(me.first_name||me.username):'Администратор';
    $('#staff-role').textContent=live?`Роль: ${me.role_display}`:'Демонстрационный режим';
    if(live)API.setBranch(multiBranch()?currentBranch()?.id:null);   // шеф — последний выбранный филиал, остальные — свой (сервер)
    paintBranch();
    const requested=location.hash.slice(1);view=views.some(v=>v[0]===requested)&&canAccess(requested)?requested:'orders';
    await render();
    paintTelegram();   // кнопка «Привязать Telegram»
    startWatch();   // следим за новыми заказами и вызовами
  }
  async function render(quiet=false){   // quiet=true — тихое обновление, без надписи «Загружаем…»
    if(!canAccess(view))view='orders';
    const sequence=++loadSequence;nav();location.hash=view;
    if(!quiet)$('#content').innerHTML='<div class="loading">Загружаем…</div>';
    try{
      let html='';
      if(view==='orders')html=await ordersView();
      if(view==='menu')html=await menuView();
      if(view==='tables')html=await tablesView();
      if(view==='users')html=await usersView();
      if(view==='reports')html=await reportsView();
      if(view==='settings')html=await settingsView();
      if(view==='api')html=apiView();
      if(sequence===loadSequence){$('#content').innerHTML=html;nav();paintControls($('#content'));filterRows();const tabs=$('.floor-tabs'),open=tabs?.querySelector('[aria-selected=true]');if(tabs&&open)tabs.scrollLeft=Math.max(0,open.offsetLeft-(tabs.clientWidth-open.offsetWidth)/2);}   // открытая вкладка этажа всегда видна (на телефоне ряд прокручивается)
    }catch(error){if(sequence!==loadSequence)return;$('#content').innerHTML=heading(views.find(v=>v[0]===view)?.[2]||'Панель')+`<div class="panel"><h2>Не удалось загрузить раздел</h2><p class="error">${esc(error.message)}</p><p class="fine">${error.status===500?'Сервер вернул 500. Ошибку нужно исправить в API.':error.status===401?'Войдите повторно.':error.status===403?'У вашей роли нет доступа к этому разделу.':'Проверьте подключение и повторите.'}</p><br><button class="secondary" data-reload>Повторить</button></div>`;}
  }
  async function ordersView(){
    let orders,calls=[];
    if(live){const data=await Promise.all([API.request('/staff/orders/?active=true'),seesCalls()?API.request('/staff/table-calls/'):Promise.resolve([])]);orders=list(data[0]);calls=list(data[1]);}
    else orders=state.orders;
    cache.orders=orders;cache.newCount=waitingCount(orders);if(live)remember(orders,calls);   // то, что уже на экране, не «новое»
    const filtered=orders.filter(o=>orderFilter==='all'||kindOf(o)===orderFilter);   // фильтр по типу: в кафе / с собой / доставка / самовывоз
    const groups=live&&me.role==='courier'
      ?[['cooking','Готовятся',['accepted','cooking']],['ready','Готовы к выдаче',['ready']],['way','В пути',['on_the_way']]]   // курьер: свои колонки
      :[['new','Новые',['new']],['cooking','Готовятся',['accepted','cooking']],['ready','Готовы и в пути',['ready','on_the_way']]];
    const callHtml=calls.length?`<div class="notice">${calls.map(c=>`<div class="actions"><strong>${esc(c.table_name)}: ${esc(c.kind_display)}</strong><button class="secondary" data-call-done="${c.id}">Выполнено</button></div>`).join('')}</div>`:'';
    return heading('Заказы',live?`${orders.length} активных заказов`:'Примеры заказов из макета',`<div class="pills order-pills">${orderFilters().map(([id,label])=>pill(label,id,orderFilter===id,'order-filter')).join('')}</div><button class="secondary" data-reload>↻ Обновить</button>`)+callHtml+`<div class="board">${groups.map(([id,label,statuses])=>{const items=filtered.filter(o=>statuses.includes(o.status));return `<section class="column"><h2 class="column-heading"><i class="dot ${id}"></i>${label}<span>${items.length}</span></h2>${items.map(orderCard).join('')||'<div class="empty">Здесь пока нет заказов</div>'}</section>`;}).join('')}</div>`;
  }
  // Четыре типа заказа: в кафе (зелёный), с собой (жёлтый), доставка (красный), самовывоз (оранжевый)
  const KIND_ICON={hall:'tables',takeaway:'bag',delivery:'truck',pickup:'store'};
  const KIND_NAME={hall:'В кафе',takeaway:'С собой',delivery:'Доставка',pickup:'Самовывоз'};
  function kindOf(o){return live?o.kind:o.type==='cafe'?'hall':o.type;}
  // Вызовы со столов видят официант и администрация (повару и курьеру они не нужны)
  function seesCalls(){return ['programmer','chef','admin','waiter'].includes(me?.role);}
  // Сколько заказов ждут реакции этого сотрудника (цифра в меню и во вкладке)
  function waitingCount(orders){
    if(live&&me.role==='cook')return orders.filter(o=>o.status==='accepted').length;                      // повар: ждут кухню
    if(live&&me.role==='courier')return orders.filter(o=>!o.claimed_by_name&&o.status!=='on_the_way').length;   // курьер: никто не взял
    return orders.filter(o=>o.status==='new').length;
  }
  const phoneLink=p=>`tel:${String(p).replace(/[^\d+]/g,'')}`;
  // Данные гостя в карточке: имя, телефон, адрес, оплата, кто взял
  function orderInfo(o){
    if(!live)return '';
    const kind=o.kind,rows=[];
    const row=(name,html)=>rows.push(`<div class="info-row">${icon(name)}<span>${html}</span></div>`);
    if(kind==='delivery'||kind==='pickup'){
      if(o.customer_name)row('user',esc(o.customer_name));
      if(o.phone)row('phone',`<a href="${esc(phoneLink(o.phone))}">${esc(o.phone)}</a>`);
    }
    if(kind==='delivery'){
      const address=[o.address,o.apartment&&`кв. ${o.apartment}`,o.entrance&&`подъезд ${o.entrance}`,o.floor&&`этаж ${o.floor}`].filter(Boolean).join(', ');
      if(address)row('pin',esc(address));
      if(o.courier_comment)row('note',`Курьеру: ${esc(o.courier_comment)}`);
    }
    if(kind==='delivery'||kind==='pickup')row('wallet',`${esc(o.payment_display||'')}${o.change_from?` · сдача с ${money(o.change_from)}`:''}`);
    if(o.claimed_by_name)row(kind==='delivery'?'truck':'users',`${kind==='delivery'?'Курьер':'Стол взял(а)'}: ${esc(o.claimed_by_name)}`);
    return rows.length?`<div class="order-info">${rows.join('')}</div>`:'';
  }
  // Фильтры над заказами: официант видит только заказы со столов, повар и админ — все
  function orderFilters(){if(live&&me.role==='courier')return [];const kinds=live&&me.role==='waiter'?['hall','takeaway']:['hall','takeaway','delivery','pickup'];if(!live)kinds.splice(1,1);if(orderFilter!=='all'&&!kinds.includes(orderFilter))orderFilter='all';return [['all','Все'],...kinds.map(k=>[k,KIND_NAME[k]])];}
  function orderCard(o){
    const delivery=live?o.kind==='delivery':o.type==='delivery';
    const kind=kindOf(o);
    const title=live?(kind==='delivery'||kind==='pickup'?KIND_NAME[kind]:`${o.table_name||''}${kind==='takeaway'?' · с собой':''}`.trim()||o.kind_display):o.type==='cafe'?`Стол ${o.table}`:o.type==='pickup'?'Самовывоз':'Доставка';
    const items=live?o.items.map(i=>({name:[i.dish_name,i.size_name].filter(Boolean).join(' '),qty:i.quantity})):o.items;
    const actions=live?(o.available_actions||[]):o.status==='new'?[{action:'cooking',label:'Принять'},{action:'cancelled',label:'Отменить',needs_reason:true}]:o.status==='cooking'?[{action:'ready',label:'Готов'},{action:'cancelled',label:'Отменить',needs_reason:true}]:[{action:'completed',label:delivery?'Доставлен':'Выдан'},{action:'cancelled',label:'Отменить',needs_reason:true}];
    return `<article class="order-card kind-${kind}"><div class="order-top"><strong>№${o.number||o.id}</strong><span class="tag kind-tag">${icon(KIND_ICON[kind]||'tables')}${esc(title)}</span><small>${live?`${esc(clock(o.created_at))} · ${esc(o.status_label)}`:o.minutes+' мин'}</small></div>${kind==='takeaway'?'<p class="takeaway-mark">С СОБОЙ — упаковать</p>':''}${orderInfo(o)}<div class="order-items">${items.map(i=>`${esc(i.name)} × ${i.qty}`).join('<br>')}</div>${o.comment||o.note?`<p class="order-note">${esc(o.comment||o.note)}</p>`:''}<div class="order-bottom"><strong>${money(live?o.total:Store.orderTotal(o))}</strong><div class="actions">${actions.map(a=>`<button class="${a.needs_reason||a.action==='reject'?'danger':'primary'}" data-order="${o.id}" data-number="${o.number||o.id}" data-kind="${esc(kind)}" data-action="${esc(a.action)}" data-reason="${Boolean(a.needs_reason)}">${esc(a.label)}</button>`).join('')}</div></div></article>`;
  }
  // ===== Блюда и категории =====
  // Компьютер и планшет: слева категории (порядок, видимость, переименовать, удалить), справа блюда.
  // Телефон: переключатель «Блюда | Категории». Повар видит только блюда (стоп-лист).
  async function menuView(){
    if(!live||me.role==='cook')return dishListView();
    const [catData,dishData,extraData]=await Promise.all([API.request('/admin/categories/'),API.request('/admin/dishes/'),API.request('/admin/extras/')]);
    cache.categories=list(catData);cache.dishes=list(dishData);cache.extras=list(extraData);
    if(menuFilter!=='all'&&!cache.categories.some(c=>String(c.id)===menuFilter))menuFilter='all';
    const tabs=`<div class="seg-tabs" role="tablist" aria-label="Что показать"><button role="tab" data-menu-tab="cats" aria-selected="${menuTab==='cats'}">Категории · ${cache.categories.length}</button><button role="tab" data-menu-tab="dishes" aria-selected="${menuTab==='dishes'}">Блюда · ${cache.dishes.length}</button></div>`;
    const catRow=c=>{const n=c.dishes_count||0,count=n?`${n} ${plural(n,'блюдо','блюда','блюд')}`:'Пусто';return `<li class="cat-row ${String(c.id)===menuFilter?'selected':''} ${c.is_active?'':'hidden-cat'}" data-cat-id="${c.id}"><button type="button" class="drag-handle" data-drag-cat aria-label="Перетащить «${esc(c.name)}»" title="Потяните, чтобы поменять порядок">${icon('grip')}</button><button type="button" class="cat-select" data-menu-filter="${c.id}"><strong>${esc(c.name)}</strong><small>${count}${c.is_active?'':' · скрыта от гостей'}</small></button>${toggle(`Видна гостям: ${c.name}`,c.is_active,`data-cat-visible="${c.id}"`)}<button type="button" class="icon-button" data-edit-category="${c.id}" aria-label="Переименовать «${esc(c.name)}»"></button><button type="button" class="danger icon-button" data-delete-category="${c.id}" aria-label="Удалить «${esc(c.name)}»" ${n?'disabled title="Сначала перенесите или удалите блюда"':''}></button></li>`;};
    const cats=`<section class="panel cat-panel" aria-labelledby="cats-title"><div class="cat-head"><h2 id="cats-title">Категории <span class="fine">${cache.categories.length}</span></h2><button type="button" class="secondary add-cat-small" data-add-category>Категория</button></div><form id="new-category" class="new-category" hidden><label for="new-cat-name">Название новой категории</label><div><input id="new-cat-name" name="name" maxlength="100" required placeholder="Например, Супы"><button class="cat-ok" type="submit" aria-label="Сохранить категорию" title="Сохранить">${icon('check')}</button><button type="button" class="cat-cancel" data-cancel-category aria-label="Отмена" title="Отмена"></button></div><p class="error" role="alert"></p></form><p class="fine">Потяните за ⋮⋮, чтобы поменять порядок в меню гостей. Удалить можно только пустую категорию.</p><ul class="cat-list" id="cat-list"><li class="cat-row ${menuFilter==='all'?'selected':''}"><span class="drag-space"></span><button type="button" class="cat-select" data-menu-filter="all"><strong>Все блюда</strong><small>${cache.dishes.length} ${plural(cache.dishes.length,'блюдо','блюда','блюд')}</small></button></li>${cache.categories.map(catRow).join('')}</ul></section>`;
    const selected=cache.categories.find(c=>String(c.id)===menuFilter);
    const rows=cache.dishes.map(d=>`<tr data-search="${esc(`${d.name} ${d.description||''}`.toLowerCase())}" data-cat="${d.category}" data-dish-id="${d.id}"><td class="drag-col"><button type="button" class="drag-handle" data-drag-dish aria-label="Перетащить «${esc(d.name)}»" title="Потяните, чтобы поменять порядок">${icon('grip')}</button></td><td><div class="dish-cell">${image(d.photo||d.image)}<div><strong>${esc(d.name)}</strong><p class="description">${esc(d.description)}</p></div></div></td><td class="category-col">${esc(cache.categories.find(c=>c.id===d.category)?.name||d.category_name||'')}</td><td>${d.sizes?.length?d.sizes.map(s=>s.price).join(' / '):d.price} сом</td><td>${toggle(`В наличии: ${d.name}`,d.is_available,`data-availability="${d.id}"`)}</td><td><div class="row-actions"><button class="icon-button" data-edit-dish="${d.id}" aria-label="Изменить: ${esc(d.name)}">✎</button><button class="danger icon-button" data-delete-dish="${d.id}" aria-label="Удалить: ${esc(d.name)}">×</button></div></td></tr>`).join('');
    const dishes=`<section class="dish-panel" aria-labelledby="dishes-title"><div class="dish-head"><h2 id="dishes-title">${esc(selected?.name||'Все блюда')}</h2><input id="menu-search" type="search" aria-label="Поиск по всем блюдам" placeholder="Поиск по всем блюдам" value="${esc(query)}"></div><p class="fine sort-hint" id="dish-sort-hint"></p><div class="data-wrap"><table class="data-table" id="dish-table"><thead><tr><th class="drag-col"><span class="sr-only">Порядок</span></th><th>Блюдо</th><th class="category-col">Категория</th><th>Цена</th><th>В наличии</th><th>Действия</th></tr></thead><tbody>${rows||'<tr><td colspan="6" class="empty">Блюд пока нет — нажмите «Добавить блюдо»</td></tr>'}</tbody></table></div></section>`;
    return heading('Блюда и категории','Гости видят изменения сразу','<button class="primary" data-edit-dish="new">Добавить блюдо</button><button class="primary heading-add-cat" data-add-category>Добавить категорию</button>')+tabs+`<div class="menu-layout tab-${menuTab}">${cats}${dishes}</div>`;
  }
  // Выбрали категорию: показываем её блюда без загрузки с сервера
  function applyMenuFilter(){
    document.querySelectorAll('#cat-list .cat-row').forEach(row=>row.classList.toggle('selected',(row.dataset.catId||'all')===menuFilter));
    const c=cache.categories?.find(c=>String(c.id)===menuFilter);if($('#dishes-title'))$('#dishes-title').textContent=c?.name||'Все блюда';
    filterRows();
  }
  // Окно «Категория»: название, видна ли гостям, удалить
  function editCategory(id){
    const c=cache.categories.find(c=>String(c.id)===String(id));if(!c)return;editingId=c.id;
    $('#editor-title').textContent=`Категория «${c.name}»`;
    $('#editor-content').innerHTML=`<form id="category-form">${field('Название','name',c.name,'text','maxlength="100" required')}<label class="check-line"><input type="checkbox" name="is_active" ${c.is_active?'checked':''}>Видна гостям</label><p class="fine">${c.dishes_count?`В категории ${c.dishes_count} ${plural(c.dishes_count,'блюдо','блюда','блюд')}. Удалить её можно, когда она станет пустой.`:'Категория пустая — её можно удалить.'}</p><p id="editor-error" class="error"></p><footer class="form-footer"><button class="primary" type="submit">Сохранить</button>${c.dishes_count?'':`<button type="button" class="danger" data-delete-category="${c.id}">Удалить</button>`}</footer></form>`;
    paintControls(editor);editor.showModal();
  }
  // Повар и демо-режим: простой список блюд (как раньше)
  async function dishListView(){
    if(live&&me.role==='cook'){const [categories,dishes]=await Promise.all([API.request('/menu/'),API.request('/admin/dishes/')]);cache.categories=list(categories);cache.dishes=list(dishes);cache.extras=[];}
    else if(live){const [categories,dishes,extras]=await Promise.all([API.request('/admin/categories/'),API.request('/admin/dishes/'),API.request('/admin/extras/')]);cache.categories=list(categories);cache.dishes=list(dishes);cache.extras=list(extras);}
    else {cache.categories=state.menu.categories;cache.dishes=state.menu.dishes;cache.extras=state.menu.extras;}
    const rows=cache.dishes.filter(d=>menuFilter==='all'||String(d.category)===menuFilter);   // поиск фильтрует строки на месте (filterRows)
    const categories=[{id:'all',name:'Все'},...cache.categories];
    return heading('Блюда',live?'Наличие блюд (стоп-лист)':'Изменения видны в меню гостей в этом браузере',`${canManageMenu()?'<button class="primary" data-edit-dish="new">+ Добавить блюдо</button>':''}`)+`<div class="toolbar"><div class="pills">${categories.map(c=>pill(c.name,String(c.id),menuFilter===String(c.id),'menu-filter')).join('')}</div><input id="menu-search" type="search" aria-label="Поиск блюд" placeholder="Поиск блюда" value="${esc(query)}"></div><div class="data-wrap"><table class="data-table"><thead><tr><th>Блюдо</th><th class="category-col">Категория</th><th>Цена</th><th>В наличии</th><th>Действия</th></tr></thead><tbody>${rows.map(d=>`<tr data-search="${esc(`${d.name} ${d.description||''}`.toLowerCase())}"><td><div class="dish-cell">${image(d.photo||d.image)}<div><strong>${esc(d.name)}</strong><p class="description">${esc(d.description)}</p></div></div></td><td class="category-col">${esc(cache.categories.find(c=>c.id===d.category)?.name||d.category_name||'')}</td><td>${live?(d.sizes?.length?d.sizes.map(s=>s.price).join(' / '):d.price):d.prices.join(' / ')} сом</td><td>${toggle(`В наличии: ${d.name}`,live?d.is_available:d.available,`data-availability="${d.id}"`)}</td><td>${canManageMenu()?`<div class="row-actions"><button class="icon-button" data-edit-dish="${d.id}" aria-label="Редактировать: ${esc(d.name)}">✎</button><button class="danger icon-button" data-delete-dish="${d.id}" aria-label="Удалить: ${esc(d.name)}">×</button></div>`:'<span class="fine">Только наличие</span>'}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Блюда не найдены</td></tr>'}</tbody></table></div>`;
  }
  function editDish(id){
    const d=id==='new'?null:cache.dishes.find(d=>String(d.id)===String(id));editingId=d?.id??null;editorImage=d?.image||'';uploadFile=null;
    const sizes=d?(live?(d.sizes||[]):d.prices.map((p,i)=>({name:d.sizes?.[i]||(d.category==='pizza'?`${[25,30,35][i]} см`:'Порция'),price:p}))):[];
    $('#editor-title').textContent=d?d.name:'Новое блюдо';
    $('#editor-content').innerHTML=`<form id="dish-form"><div class="image-editor"><div id="image-preview">${image(d?.photo||d?.image)}</div><div class="photo-upload"><label class="upload-button">${icon('upload')}<span id="photo-button-label">${d?.photo||d?.image?'Заменить фото':'Добавить фото'}</span><input id="dish-photo" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Загрузить фото блюда" aria-describedby="photo-help photo-status"></label><small class="fine photo-file-name" id="photo-help">PNG, JPG, WebP · до 2 МБ</small><span id="photo-status" class="photo-status" role="status" aria-live="polite"></span></div></div>${field('Название','name',d?.name||'','text','required maxlength="100"')}<label>Описание<textarea name="description" maxlength="500">${esc(d?.description||'')}</textarea></label><label>Категория<select name="category">${cache.categories.map(c=>`<option value="${c.id}" ${(d?d.category===c.id:String(c.id)===menuFilter)?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>${field('Основная цена, сом','price',live?(d?.price||0):(d?.prices[0]||0),'number','min="0" max="1000000" required step="1"')}<fieldset><legend>Размеры и цены</legend><div id="size-rows">${sizes.map(sizeRow).join('')}</div><button class="secondary" type="button" id="add-size">+ Добавить размер</button></fieldset>${live?`<fieldset><legend>Добавки</legend>${cache.extras.map(e=>`<label class="setting-line">${esc(e.name)} · ${money(e.price)}<input style="width:18px" name="extra" type="checkbox" value="${e.id}" ${d?.extras?.includes(e.id)?'checked':''}></label>`).join('')}</fieldset>`:''}<div class="setting-line">В наличии${toggle('В наличии',d?(live?d.is_available:d.available):true,'name="available"')}</div><p class="fine">${live?'Изменения сохраняются на сервере.':'Изменения сохраняются только в этом браузере.'}</p><p id="editor-error" class="error" role="alert"></p><footer class="form-footer"><button class="primary" type="submit">Сохранить</button>${d?`<button class="danger" type="button" data-delete-dish="${d.id}">Удалить</button>`:''}</footer></form>`;paintControls(editor);editor.showModal();
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
  // ===== Столы и QR =====
  // Официант: плитки столов со статусом и кнопкой «Освободить стол».
  // Админ, шеф, программист: QR «Доставка» (всегда один) + столы: скачать / обновить QR / удалить / освободить.
  async function tablesView(){
    if(!live)return demoTablesView();
    const waiter=me.role==='waiter';
    const [tableData,floorData]=await Promise.all([API.request(waiter?'/staff/tables/':'/admin/tables/'),waiter?[]:API.request('/admin/floors/')]);
    cache.tables=list(tableData);cache.floors=list(floorData);                            // столы и этажи филиала
    const halls=cache.tables.filter(t=>(t.kind||'hall')==='hall'),busy=halls.filter(t=>t.occupied_since).length;
    const subtitle=`${halls.length} ${plural(halls.length,'стол','стола','столов')} · занято ${busy}`;
    const onFloor=f=>halls.filter(t=>(t.floor||1)===f);                                    // столы одного этажа
    const floors=waiter?[...new Set(halls.map(t=>t.floor||1))].sort((a,b)=>a-b):cache.floors.map(f=>f.number);   // официанту — этажи, где есть столы
    if(waiter)return heading('Столы',subtitle)+(floors.length?floors:[1]).map(f=>`<section class="floor-block"><h2 class="floor-title">${f} этаж <span class="fine">${onFloor(f).filter(t=>t.occupied_since).length} из ${onFloor(f).length} занято</span></h2><div class="table-tiles">${onFloor(f).map(tableTile).join('')||'<div class="empty">На этом этаже столов нет</div>'}</div></section>`).join('');
    const delivery=cache.tables.find(t=>t.kind==='delivery');
    // Вкладки: «Доставка», «1 этаж», «2 этаж», … и кнопка «+ Этаж» (этажи у филиала свои)
    if(tablesFloor!=='delivery'&&!floors.includes(tablesFloor))tablesFloor=floors[0]||1;     // этаж удалили или другой филиал
    const tab=(id,label,count)=>`<button role="tab" data-floor-tab="${id}" aria-selected="${String(tablesFloor)===String(id)}">${label}${count===null?'':` <span>${count}</span>`}</button>`;
    const tabs=`<div class="floor-bar"><div class="floor-tabs" role="tablist" aria-label="Что показать">${tab('delivery','Доставка / ТГ-бот',null)}${floors.map(f=>tab(f,`${f} этаж`,onFloor(f).length)).join('')}</div><button type="button" class="secondary add-floor" data-add-floor>+ Этаж</button></div>`;
    const onDelivery=tablesFloor==='delivery';
    const openFloor=cache.floors.find(f=>f.number===tablesFloor);                         // открытый этаж (для «Удалить этаж»)
    const deleteFloor=openFloor?.can_delete?`<button type="button" class="secondary danger-text" data-delete-floor="${openFloor.id}">Удалить ${openFloor.number} этаж</button>`:'';
    const floorTables=onDelivery?[]:onFloor(tablesFloor);                                   // столы открытого этажа
    const body=onDelivery
      ?`<div class="qr-grid single">${delivery?deliveryCard(delivery)+botCard(delivery):''}</div>`
      :`<div class="qr-grid floor-grid">${floorTables.map(tableCard).join('')}</div>${floorTables.length?'':`<div class="empty floor-empty"><p>На ${tablesFloor} этаже столов пока нет. Нажмите «Добавить стол» — появится «Стол 1 · ${tablesFloor} этаж».</p>${deleteFloor}</div>`}`;
    return heading('Столы и QR-коды',subtitle,`<button class="secondary" data-download-all-qr>Скачать все QR (PDF)</button>${onDelivery?'':`<button class="primary" data-add-table>Добавить стол на ${tablesFloor} этаж</button>`}`)+tabs+body;
  }
  let tablesFloor=1;                                                                        // какой этаж открыт в «Столах и QR»
  function plural(n,one,few,many){const m=n%10,h=n%100;return m===1&&h!==11?one:m>=2&&m<=4&&(h<12||h>14)?few:many;}
  function tableStatus(t){return t.occupied_since?`Занят с ${clock(t.occupied_since)}`:t.active_orders?`Новый заказ`:'Свободен';}
  function freeButton(t){return t.occupied_since?`<button class="secondary" data-close-table="${t.id}">Освободить стол</button>`:'';}
  function tableTile(t){return `<article class="table-tile ${t.occupied_since?'busy':''}"><strong>${esc(t.name)}</strong><span class="tag">${tableStatus(t)}</span>${t.active_orders?`<small>Заказов в работе: ${t.active_orders}</small>`:''}${freeButton(t)}</article>`;}
  // Карточка «Telegram-бот» (голубая рамка): QR ведёт гостя в бот сразу в меню этого филиала. Создаётся сама
  function botCard(t){const url=t.bot_url||'';return `<article class="qr-card kind-bot"><header class="qr-top"><h2>Telegram-бот</h2><span class="tag kind-tag">${icon('telegram')}Telegram</span></header>${url?`<div class="qr-image">${qrSvg(url)}</div><a class="qr-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a><p class="fine qr-note">Гость сканирует — открывается бот с меню этого филиала: фото блюд, корзина, доставка.</p><div class="actions qr-actions"><button class="primary" data-download-bot-qr="${t.id}">Скачать QR</button><button class="secondary" data-regenerate-bot-qr="${t.id}">Обновить QR</button></div>`:`<p class="fine qr-note">Бот ещё не подключён: впишите TELEGRAM_GUEST_BOT_USERNAME в .env на сервере и перезапустите сайт — QR появится здесь сам.</p>`}</article>`;}
  // Карточка «Доставка»: свой секретный QR (как у стола). Удалить нельзя, перевыпустить — можно
  function deliveryCard(t){const url=tableUrl(t);return `<article class="qr-card kind-delivery"><header class="qr-top"><h2>Доставка</h2><span class="tag kind-tag">${icon('truck')}Всегда одна</span></header><div class="qr-image">${qrSvg(url)}</div><a class="qr-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a><p class="fine qr-note">QR для доставки и самовывоза. Без QR сайт показывает только меню.${t.active_orders?` В работе: ${t.active_orders}.`:''}</p><div class="actions qr-actions"><button class="primary" data-download-qr="${t.id}">Скачать QR</button><button class="secondary" data-regenerate-qr="${t.id}">Обновить QR</button></div></article>`;}
  // Карточка стола: под QR всегда 4 одинаковые кнопки (2×2). Недоступная — серая, но остаётся на месте
  function tableCard(t){const url=tableUrl(t),busy=Boolean(t.occupied_since),locked=busy||t.active_orders>0;
    return `<article class="qr-card ${busy?'busy':''}"><header class="qr-top"><h2>${esc(t.name)}</h2><span class="tag ${busy||t.active_orders?'delivery':''}">${tableStatus(t)}</span></header><div class="qr-image">${qrSvg(url)}</div><a class="qr-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a><div class="actions qr-actions">
      <button class="primary" data-download-qr="${t.id}">Скачать QR</button>
      <button class="secondary" data-regenerate-qr="${t.id}">Обновить QR</button>
      <button class="secondary" data-close-table="${t.id}" aria-label="Освободить ${esc(t.name)}" ${busy?'':'disabled title="Стол и так свободен"'}>Освободить</button>
      <button class="danger" data-delete-table="${t.id}" aria-label="Удалить ${esc(t.name)}" ${locked?'disabled title="Сначала освободите стол и завершите его заказы"':''}>Удалить</button></div></article>`;}
  // Демо-режим без сервера (как было)
  async function demoTablesView(){
    cache.tables=live?list(await API.request('/admin/tables/')):state.tables;
    return heading('Столы и QR-коды',`${cache.tables.length} столов`,`${live?'<button class="secondary" data-download-all-qr>Скачать QR (PDF)</button>':'<button class="secondary" data-print-qr>Печать QR / PDF</button>'}<button class="primary" data-add-table>+ Добавить стол или доставку</button>`)+(!live?'<p class="notice">QR открывает гостевое меню с номером стола. Адрес меню для печати QR можно изменить в настройках.</p>':'')+`<div class="qr-grid">${cache.tables.map(t=>{
      const url=tableUrl(t),id=live?t.id:t.number,occupied=live?t.active_orders:state.orders.filter(o=>o.table===t.number).length;
      const busy=live&&t.kind==='hall'&&Boolean(t.occupied_since);   // стол занят, пока официант не нажмёт «Гости ушли»
      const tag=!live?(occupied?'Заказов: '+occupied:'Свободен'):t.kind==='delivery'?(occupied?'Заказов: '+occupied:'Нет заказов'):busy?`Занят с ${clock(t.occupied_since)}`:occupied?'Заказов: '+occupied:'Свободен';
      return `<article class="qr-card"><header class="qr-top"><h2>${esc(t.name||(t.number?`Стол ${t.number}`:'Доставка'))}</h2><span class="tag ${busy||occupied?'delivery':''}">${tag}</span></header>${qrSvg(url)}<a class="qr-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a><div class="actions"><button class="primary" data-download-qr="${id}">Скачать QR</button><button class="secondary" data-edit-table="${id}">Изменить</button>${busy?`<button class="secondary" data-close-table="${t.id}">Гости ушли</button>`:''}</div></article>`;
    }).join('')}</div>`;
  }
  // QR-адрес: и у стола, и у доставки — меню с секретным токеном
  function tableUrl(t){if(live){const url=new URL('./',location.href);url.searchParams.set('token',t.token);return url.href;}const url=new URL(state.settings.menuUrl);url.searchParams.set('table',t.number);return url.href;}
  function qrSvg(url){const qr=qrcode(0,'M');qr.addData(url);qr.make();return qr.createSvgTag({cellSize:4,margin:16,scalable:true}).replace('<svg ','<svg role="img" aria-label="QR-код меню" ');}
  function editTable(id){const t=id==='new'?null:cache.tables.find(t=>String(live?t.id:t.number)===String(id));editingId=live?t?.id:t?.number;
    $('#editor-title').textContent=t?'Настройки стола':'Новый стол';$('#editor-content').innerHTML=`<form id="table-form">${field('Название','name',t?.name||'','text','maxlength="50" required')}${field('Номер','number',t?.number||'','number','min="1" max="999" required')}<p class="fine">Для QR используется адрес гостевого меню из настроек.</p><p id="editor-error" class="error"></p><footer class="form-footer"><button class="primary">Сохранить</button>${t?`<button type="button" class="danger" data-delete-table="${t.number}">Удалить</button>`:''}</footer></form>`;paintControls(editor);editor.showModal();}
  async function usersView(){
    if(live){const [users,allowed,audit]=await Promise.all([API.request('/admin/staff/'),API.request('/admin/staff/roles/'),API.request('/admin/staff/role-log/')]);cache.users=list(users);cache.roles=list(allowed);cache.audit=list(audit);}
    else{cache.users=state.users;cache.roles=['admin','cook','user'].map(value=>({value,label:roles[value]}));cache.audit=state.audit;}
    const users=cache.users.filter(u=>userFilter==='all'||u.role===userFilter);   // поиск фильтрует строки на месте (filterRows)
    const filters=['all',...new Set(cache.users.map(u=>u.role))];
    const addButton=live&&cache.roles.length?'<button class="primary" data-add-staff>Добавить сотрудника</button>':'';   // кнопка есть у программиста, шефа и админа
    return heading('Пользователи и роли',live?'Права проверяются сервером':'Демо-роли не предоставляют настоящий доступ',addButton)+`<div class="toolbar"><div class="pills">${filters.map(r=>pill(r==='all'?`Все · ${cache.users.length}`:roles[r],r,userFilter===r,'user-filter')).join('')}</div><input id="user-search" type="search" aria-label="Поиск пользователей" placeholder="Имя или логин" value="${esc(query)}"></div><div class="users-layout"><div class="data-wrap"><table class="data-table"><thead><tr><th>Пользователь</th><th>Роль</th><th class="category-col">Статус</th><th aria-label="Действия"></th></tr></thead><tbody>${users.map(u=>{const name=u.name||u.first_name||u.username,roleOptions=cache.roles.some(r=>r.value===u.role)?cache.roles:[{value:u.role,label:roles[u.role]},...cache.roles];return `<tr data-search="${esc(`${name} ${u.username||u.handle||''} ${u.email||''}`.toLowerCase())}"><td><div class="user-cell"><span class="avatar">${esc(name[0])}</span><div><strong>${esc(name)}</strong><small>@${esc(u.handle||u.username)}${u.email?' · '+esc(u.email):''}</small></div></div></td><td><select class="role-select" data-role-user="${u.id}" aria-label="Роль: ${esc(name)}" ${(live?!u.can_edit||u.id===me.id:u.role==='owner')?'disabled':''}>${roleOptions.map(r=>`<option value="${r.value}" ${r.value===u.role?'selected':''}>${esc(r.label)}</option>`).join('')}</select></td><td class="category-col">${live?u.is_active?'Активен':'Отключён':u.role==='blocked'?'Отключён':'Активен'}</td><td>${live&&u.can_edit&&u.id!==me.id?`<div class="row-actions"><button class="icon-button" data-edit-staff="${u.id}" aria-label="Изменить: ${esc(name)}" title="Изменить сотрудника"></button><button class="icon-button danger" data-delete-staff="${u.id}" aria-label="Удалить: ${esc(name)}" title="Удалить сотрудника"></button></div>`:''}</td></tr>`;}).join('')||'<tr><td colspan="4" class="empty">Пользователи не найдены</td></tr>'}</tbody></table></div><aside class="panel"><h2>История смены ролей</h2>${cache.audit.slice().reverse().slice(0,20).map(a=>`<div class="audit-row"><strong>${esc(a.user_name||a.name)}</strong><br>${esc(a.old_role_display||roles[a.from])} → ${esc(a.new_role_display||roles[a.to])}<small>${esc(a.created_at||a.at)}</small></div>`).join('')||'<p class="fine">Пока нет изменений ролей</p>'}</aside></div>`;
  }
  // Окно «Изменить сотрудника»: старший меняет данные младшего (права ещё раз проверяет сервер)
  function editStaff(id){
    const u=cache.users.find(u=>String(u.id)===String(id));if(!u)return;editingId=u.id;
    const roleOptions=cache.roles.some(r=>r.value===u.role)?cache.roles:[{value:u.role,label:u.role_display||roles[u.role]},...cache.roles];
    $('#editor-title').textContent='Изменить сотрудника';
    $('#editor-content').innerHTML=`<form id="staff-edit-form">
      <div class="two-fields">${field('Имя','first_name',u.first_name||'','text','maxlength="150" required')}${field('Фамилия','last_name',u.last_name||'','text','maxlength="150"')}</div>
      <label>Роль<select name="role" required>${roleOptions.map(r=>`<option value="${esc(r.value)}" ${r.value===u.role?'selected':''}>${esc(r.label)}</option>`).join('')}</select></label>
      ${field('Логин','username',u.username||'','text','maxlength="150" required autocomplete="off" autocapitalize="none" spellcheck="false"')}
      ${field('Email','email',u.email||'','email','maxlength="254" autocomplete="off" placeholder="Можно оставить пустым"')}
      <div class="two-fields">${field('Телефон','phone',u.phone||'','tel','maxlength="20" placeholder="+996"')}${field('Telegram ID','telegram_id',u.telegram_id||'','number','min="1" placeholder="Для бота"')}</div>
      <div class="setting-line">Активен (может входить)${toggle('Активен',u.is_active!==false,'name="is_active"')}</div>
      <div class="two-fields">${field('Новый пароль','password','','password','minlength="10" autocomplete="new-password" placeholder="Не менять"')}${field('Повторите пароль','password2','','password','minlength="10" autocomplete="new-password"')}</div>
      <p class="fine">Новый пароль, другая роль или блокировка сразу выводят сотрудника из панели на всех устройствах (и из Telegram-бота — при новом пароле или блокировке). Имя, телефон и email можно менять спокойно.</p>
      <p id="editor-error" class="error"></p>
      <footer class="form-footer"><button class="primary" type="submit">Сохранить</button></footer>
    </form>`;
    paintControls(editor);editor.showModal();
  }
  // Сохранение «Изменить сотрудника»: данные → роль (если поменяли) → пароль (если ввели)
  async function saveStaffEdit(form){
    const v=new FormData(form),text=name=>String(v.get(name)||'').trim(),u=cache.users.find(u=>u.id===editingId);
    const password=String(v.get('password')||'');
    if(password||String(v.get('password2')||'')){if(password!==String(v.get('password2')))throw new Error('Пароли не совпадают.');}
    const tg=text('telegram_id');
    await API.request(`/admin/staff/${editingId}/`,{method:'PATCH',body:{
      first_name:text('first_name'),last_name:text('last_name'),username:text('username'),email:text('email').toLowerCase(),
      phone:text('phone'),telegram_id:tg?Number(tg):null,is_active:v.has('is_active'),
    }});
    if(text('role')&&text('role')!==u?.role)await API.request(`/admin/staff/${editingId}/set-role/`,{method:'POST',body:{role:text('role')}});
    if(password)await API.request(`/admin/staff/${editingId}/set-password/`,{method:'POST',body:{password}});
    editor.close();toast(`Сотрудник «${text('first_name')||text('username')}» сохранён`);await render();
  }
  // Окно «Новый сотрудник». Роли в списке — только те, что сервер разрешает назначать
  function addStaff(){
    $('#editor-title').textContent='Новый сотрудник';
    $('#editor-content').innerHTML=`<form id="staff-form">
      <div class="two-fields">${field('Имя','first_name','','text','maxlength="150" required')}${field('Фамилия','last_name','','text','maxlength="150"')}</div>
      <label>Роль<select name="role" required>${cache.roles.map(r=>`<option value="${esc(r.value)}">${esc(r.label)}</option>`).join('')}</select></label>
      ${field('Логин','username','','text','maxlength="150" required autocomplete="off" autocapitalize="none" spellcheck="false" pattern="[A-Za-z0-9@.+_\\-]+" title="Латинские буквы, цифры и символы @ . + - _"')}
      ${field('Email','email','','email','maxlength="254" autocomplete="off" placeholder="Можно оставить пустым"')}
      <div class="two-fields">${field('Телефон','phone','','tel','maxlength="20" placeholder="+996"')}${field('Telegram ID','telegram_id','','number','min="1" placeholder="Для бота"')}</div>
      <div class="two-fields">${field('Пароль','password','','password','minlength="10" required autocomplete="new-password"')}${field('Повторите пароль','password2','','password','minlength="10" required autocomplete="new-password"')}</div>
      <p class="fine">${multiBranch()?`Сотрудник будет работать в филиале «${esc(branchName())}» (шеф — во всех). `:''}Логин или email и пароль передайте сотруднику лично. Он сможет войти сразу.</p>
      <p id="editor-error" class="error"></p>
      <footer class="form-footer"><button class="primary" type="submit">Добавить</button></footer>
    </form>`;
    paintControls(editor);editor.showModal();
  }
  // Отправка формы «Новый сотрудник» на сервер
  async function saveStaff(form){
    const v=new FormData(form),text=name=>String(v.get(name)||'').trim();
    if(String(v.get('password'))!==String(v.get('password2')))throw new Error('Пароли не совпадают.');
    const tg=text('telegram_id');
    await API.request('/admin/staff/',{method:'POST',body:{
      first_name:text('first_name'),last_name:text('last_name'),role:text('role'),
      username:text('username'),email:text('email').toLowerCase(),phone:text('phone'),
      telegram_id:tg?Number(tg):null,password:String(v.get('password'))
    }});
    editor.close();toast(`Сотрудник ${text('first_name')} добавлен`);await render();
  }
  // ===== Уведомления: раз в 10 секунд спрашиваем сервер, не появилось ли что-то новое =====
  // Официант (и админ): новый заказ, «Позвать официанта», «Попросить счёт», заказ готов.
  // Повар: заказ подтверждён официантом — пора готовить.
  let watchTimer=null,seen=null;
  const WATCH_EVERY=10000;                                      // 10 секунд
  function startWatch(){stopWatch();if(!live)return;watch();watchTimer=setInterval(watch,WATCH_EVERY);paintBell();}
  function stopWatch(){clearInterval(watchTimer);watchTimer=null;seen=null;MuslimNotify.title(0);}
  // Запоминаем, что сотрудник уже видел (чтобы не звенеть повторно)
  function remember(orders,calls){seen={orders:new Map(orders.map(o=>[o.id,o.status])),calls:new Set(calls.map(c=>c.id)),key:orders.map(o=>o.id+':'+o.status).join(',')+'|'+calls.map(c=>c.id).join(',')};}
  // Человек сейчас что-то вводит — не перерисовываем страницу у него под руками
  function typing(){const el=document.activeElement;return Boolean(el&&$('#content').contains(el)&&/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName));}
  async function watch(){
    if(!live)return;
    const role=me.role,isCook=role==='cook',isCourier=role==='courier',isBoss=['programmer','chef','admin'].includes(role);
    let orders,calls;
    try{const data=await Promise.all([API.request('/staff/orders/?active=true'),seesCalls()?API.request('/staff/table-calls/'):[]]);orders=list(data[0]);calls=list(data[1]);}
    catch{return;}                                              // нет связи — попробуем через 10 секунд
    if(!live)return;                                            // пока ждали ответ, сотрудник вышел
    const place=o=>o.kind==='delivery'||o.kind==='pickup'?KIND_NAME[o.kind]:(o.table_name||'');   // «Стол 3» / «Доставка» / «Самовывоз»
    const events=[],kinds=[],before=seen;
    if(before){
      for(const o of orders){
        const was=before.orders.get(o.id);if(was===o.status)continue;              // ничего не поменялось
        const tail=o.kind==='takeaway'?' · с собой':'';
        if(isCourier){                                                             // курьер: новая доставка и «готово, забирайте»
          if(was===undefined){events.push(`Новая доставка №${o.number}${o.address?' · '+o.address:''}`);kinds.push('delivery');}
          else if(o.status==='ready'){events.push(`Готов к выдаче: заказ №${o.number}${o.address?' · '+o.address:''}`);kinds.push('delivery');}
          continue;
        }
        if(!isCook&&o.status==='new'&&was===undefined){events.push(`Новый заказ №${o.number} · ${place(o)}${tail}`);kinds.push(o.kind);}
        if(isCook&&o.status==='accepted'){events.push(`На кухню: заказ №${o.number} · ${place(o)}${tail}`);kinds.push(o.kind);}
        if(o.status==='ready'&&(role==='waiter'||(isBoss&&(o.kind==='delivery'||o.kind==='pickup')))){events.push(`Готов: заказ №${o.number} · ${place(o)}${tail}`);kinds.push(o.kind);}
      }
      for(const c of calls)if(!before.calls.has(c.id)){events.push(`${c.table_name}: ${c.kind_display}`);kinds.push('hall');}  // «Стол 5: Попросить счёт»
    }
    remember(orders,calls);
    const waiting=waitingCount(orders);                                             // ждут реакции
    cache.newCount=waiting;nav();MuslimNotify.title(waiting+calls.length);           // цифра в меню и во вкладке
    if(events.length){MuslimNotify.alert(events);toast(events.slice(0,3).join(' · ')+(events.length>3?` и ещё ${events.length-3}`:''),kinds[0]);}
    if(before&&before.key!==seen.key&&['orders','tables'].includes(view)&&!document.querySelector('dialog[open]')&&!typing())await render(true);   // список сам обновился
  }
  // ===== Кнопка «Telegram» в верхней полосе: привязан ли Telegram (привязка — входом в боте), «Отвязать» =====
  function paintTelegram(){
    let b=$('#telegram-toggle');
    if(!b){b=document.createElement('button');b.type='button';b.id='telegram-toggle';$('#notify-toggle').before(b);}   // кнопка рядом со «Звук»
    b.hidden=!live;if(!live)return;
    const on=Boolean(me?.telegram_id);                                                  // уже привязан?
    b.innerHTML=icon('telegram')+`<span class="tg-long">${on?'Telegram ✓':'Telegram не привязан'}</span><span class="tg-short">${on?'TG ✓':'Telegram'}</span>`;
    b.classList.toggle('linked',on);b.setAttribute('aria-label',on?'Telegram привязан. Нажмите, чтобы отвязать':'Telegram не привязан. Как привязать');
  }
  async function telegramDialog(){
    const state=await API.request('/staff/telegram/');                                  // привязан ли Telegram и где бот
    me.telegram_id=state.telegram_id;paintTelegram();
    if(me.telegram_id){                                                                 // привязан — можно отвязать (например, сменил телефон)
      confirm('Отвязать Telegram?','Кнопки в Telegram-боте перестанут работать для вас. Чтобы привязать снова, войдите в боте своим логином и паролем.',async()=>{const next=await API.request('/staff/telegram/',{method:'DELETE'});me.telegram_id=next.telegram_id;paintTelegram();toast('Telegram отвязан');});
      return;
    }
    $('#editor-title').textContent='Telegram не привязан';                             // подсказка, как привязать
    $('#editor-content').innerHTML=`<div class="tg-link"><p>1. Откройте нашего бота${state.bot_username?` <b>@${esc(state.bot_username)}</b>`:''} в Telegram и нажмите <b>«Старт»</b>.<br>2. Нажмите «Войти» и введите <b>тот же логин и пароль</b>, что на сайте.<br>3. Готово — кнопки в группе будут работать для вас.</p>${state.bot_url?`<a class="primary wide" href="${esc(state.bot_url)}" target="_blank" rel="noopener">${icon('telegram')}Открыть бота</a>`:'<p class="fine">Бот ещё не настроен на сервере.</p>'}<p class="error" id="tg-status" role="status"></p><button type="button" class="secondary wide" id="telegram-check">${icon('refresh')}Проверить</button></div>`;
    editor.showModal();
  }
  async function telegramCheck(){                                                       // сотрудник вошёл в боте?
    const state=await API.request('/staff/telegram/');me.telegram_id=state.telegram_id;paintTelegram();
    if(me.telegram_id){editor.close();toast('Telegram привязан ✓ Теперь кнопки в боте работают для вас');}
    else $('#tg-status').textContent='Пока не привязан. Войдите в боте своим логином и паролем и нажмите «Проверить» снова.';
  }
  // Кнопка «Звук» в верхней полосе
  function paintBell(){const b=$('#notify-toggle');if(!b)return;b.hidden=!live;const on=MuslimNotify.enabled();b.setAttribute('aria-pressed',String(on));b.innerHTML=icon('bell')+`<span>${on?'Звук вкл':'Звук выкл'}</span>`;b.classList.toggle('muted',!on);}
  function reportBranch(){return multiBranch()&&reportScope==='all'?'all':undefined;}   // «Оба филиала» — только у шефа
  async function reportsView(){
    const actions=`<button class="secondary" data-export-report>${live?'Скачать PDF':'Печать / PDF'}</button><button class="secondary" data-export-csv>${live?'JSON':'CSV'}</button>`;
    const top=heading('Отчёты',live?'':'Демонстрационные данные',actions)+`<div class="toolbar"><div class="pills">${pill('За день','day',reportPeriod==='day','report-period')}${!live||['chef','programmer'].includes(me?.role)?pill('За 45 дней','period',reportPeriod==='period','report-period'):''}</div>${multiBranch()?`<div class="pills">${pill('Оба филиала',reportScope==='all'?'branch':'all',reportScope==='all','report-scope')}</div>`:''}${reportPeriod==='day'?`<input class="report-date" type="date" id="report-date" value="${reportDate}" max="${Store.today()}" aria-label="Дата отчёта">`:'<span class="fine">%RANGE%</span>'}</div>`;
    if(live){
      try{cache.report=await API.request(reportPeriod==='day'?`/admin/reports/day/?date=${reportDate}`:'/admin/reports/period/',{branch:reportBranch()});
        const p=cache.report.period;                                    // настоящие даты текущего периода с сервера
        return top.replace('%RANGE%',p?`${shortDate(p.start_date)}.${p.start_date.slice(0,4)} — ${shortDate(p.end_date)}.${p.end_date.slice(0,4)}`:'')+liveReport(cache.report,reportPeriod==='period'?await loadArchive():[]);
      }catch(error){cache.report=null;return top.replace('%RANGE%','')+`<div class="panel"><h2>Отчёт недоступен</h2><p class="error">${esc(error.message)}</p><br><p class="fine">${error.status===500?'API вернул 500. Данные не подменены примерами. Ошибка зарегистрирована в разделе «Проверка API».':'Проверьте подключение к API.'}</p></div>`;}
    }
    const start=reportPeriod==='day'?reportDate:Store.dayOffset(Store.today(),-44),end=reportPeriod==='day'?reportDate:Store.today();
    const demoTop=top.replace('%RANGE%',`${start} — ${end}`);
    const rows=state.history.filter(o=>o.date>=start&&o.date<=end),completed=rows.filter(o=>o.status==='completed'),revenue=completed.reduce((s,o)=>s+Store.orderTotal(o),0),cancelled=rows.filter(o=>o.status==='cancelled').length;
    const products=new Map();completed.forEach(o=>o.items.forEach(i=>{const p=products.get(i.name)||{name:i.name,qty:0,sum:0};p.qty+=i.qty;p.sum+=i.qty*i.price;products.set(i.name,p);}));
    const ranked=[...products.values()].sort((a,b)=>b.sum-a.sum);cache.reportRows=ranked;
    const points=reportPeriod==='day'?Array.from({length:13},(_,i)=>({label:`${i+10}`,sum:completed.filter(o=>o.hour===i+10).reduce((s,o)=>s+Store.orderTotal(o),0)})):Array.from({length:45},(_,i)=>{const day=Store.dayOffset(start,i);return {label:day.slice(8),sum:completed.filter(o=>o.date===day).reduce((s,o)=>s+Store.orderTotal(o),0)};});
    const max=Math.max(1,...points.map(p=>p.sum));
    return demoTop+`<div class="report"><div class="stats"><article class="stat"><span>Выручка</span><strong>${money(revenue)}</strong><small>Завершённые заказы</small></article><article class="stat"><span>Заказы</span><strong>${completed.length}</strong><small>За выбранный период</small></article><article class="stat"><span>Средний чек</span><strong>${money(completed.length?Math.round(revenue/completed.length):0)}</strong><small>Выручка / заказы</small></article><article class="stat"><span>Отменено</span><strong>${cancelled}</strong><small>Не входят в выручку</small></article></div><section class="panel chart-panel"><h2>Выручка ${reportPeriod==='day'?'по часам':'по дням'}, сом</h2><div class="chart ${reportPeriod==='period'?'period':''}" role="img" aria-label="График выручки">${points.map(p=>`<button type="button" class="bar-group" data-bar="${esc(`${p.label}: ${money(p.sum)}`)}" title="${p.label}: ${money(p.sum)}"><span class="bar" style="height:${p.sum/max*100}%"></span>${reportPeriod==='day'||Number(p.label)%5===0?`<small>${p.label}${reportPeriod==='day'?':00':''}</small>`:''}</button>`).join('')}</div></section><div class="data-wrap"><table class="data-table"><thead><tr><th>Блюдо</th><th>Продано</th><th>Выручка</th><th class="category-col">Доля</th></tr></thead><tbody>${ranked.map(p=>`<tr><td>${esc(p.name)}</td><td>${p.qty}</td><td>${money(p.sum)}</td><td class="category-col"><div class="progress"><span style="width:${p.sum/(ranked[0]?.sum||1)*100}%"></span></div></td></tr>`).join('')||'<tr><td colspan="4" class="empty">Нет заказов за выбранный день</td></tr>'}</tbody></table></div></div>`;
  }
  // Архив закрытых периодов по 45 дней. Ошибка — просто пустой архив.
  async function loadArchive(){
    try{return await API.request('/admin/reports/periods/',{branch:reportBranch()});}catch{return [];}
  }

  // Отчёт с сервера. Раскладка: плитки → график + «откуда выручка» → оплата + топ блюд → отмены + архив.
  // Между всеми блоками одинаковый зазор (задаётся в admin.css, класс .report).
  const KIND_COLOR={hall:'hall',takeaway:'take',delivery:'deliv',pickup:'pick',cash:'hall',card:'take'};   // цвет полоски по типу
  const shortDate=iso=>`${String(iso).slice(8,10)}.${String(iso).slice(5,7)}`;                       // 2026-10-12 → 12.10
  function liveReport(r,archive){
    const isDay=reportPeriod==='day';                                   // за день или за 45 дней
    const pct=r.compare?.change_percent;                                // изменение к прошлому, %
    const trend=pct==null?'Сравнивать не с чем':`${pct>=0?'▲':'▼'} ${Math.abs(pct)}% ${isDay?'к этому дню прошлой недели':'к прошлому периоду'}`;

    // Точки графика: по часам (день) или по дням (45 дней)
    const points=isDay
      ?(r.by_hour||[]).map(h=>({title:h.label,short:h.label,sum:h.revenue,count:h.count}))
      :(r.by_day||[]).map((d,i)=>({title:shortDate(d.date),short:i%5===0?shortDate(d.date):'',sum:d.revenue,count:d.count}));
    const max=Math.max(1,...points.map(p=>p.sum));                     // самый высокий столбик = 100%
    const best=points.reduce((b,p)=>p.sum>(b?b.sum:0)?p:b,null);         // лучший день или час

    // 1. Плашка периода (только 45 дней)
    const p=r.period;
    const banner=p?`<section class="panel report-period"><div><h2>Период ${esc(shortDate(p.start_date))} — ${esc(shortDate(p.end_date))}</h2><p class="fine">День ${p.day_number} из ${p.days_total}. ${esc(shortDate(p.next_start))} начнётся новый период, этот уйдёт в архив PDF.</p></div><div class="progress"><span style="width:${p.day_number/p.days_total*100}%"></span></div></section>`:'';

    // 2. Четыре плитки
    const tile=(name,value,note,cls='')=>`<article class="stat ${cls}"><span>${name}</span><strong>${value}</strong><small>${note}</small></article>`;
    const stats=`<div class="stats">${tile('Выручка',money(r.revenue),trend,pct==null?'':pct>=0?'up':'down')}${tile('Заказы',r.orders_count,isDay?`Завершены · в работе: ${r.in_progress_count}`:`Отменено: ${r.cancelled_count} · в работе: ${r.in_progress_count}`)}${tile('Средний чек',money(r.avg_check),'Выручка / заказы')}${isDay?tile('Отменено',r.cancelled_count,'Не входят в выручку'):tile('Лучший день',best?money(best.sum):'—',best?`${best.title} · ${best.count} зак.`:'Пока нет продаж')}</div>`;

    // 3. График. Нажмите на столбик — сверху появится сумма (на телефоне подсказка при наведении не работает)
    const chart=`<section class="panel chart-panel wide"><div class="panel-head"><h2>Выручка ${isDay?'по часам':'по дням'}</h2><span class="fine" id="chart-readout">Нажмите на столбик, чтобы увидеть сумму</span></div><div class="chart-scroll"><div class="chart ${isDay?'':'period'}" role="img" aria-label="График выручки">${points.map(pt=>`<button type="button" class="bar-group ${best&&pt===best?'best':''}" data-bar="${esc(`${pt.title}: ${money(pt.sum)} · ${pt.count} зак.`)}" title="${esc(pt.title)}: ${money(pt.sum)}"><span class="bar" style="height:${pt.sum/max*100}%"></span>${pt.short?`<small>${esc(pt.short)}</small>`:''}</button>`).join('')}</div></div></section>`;

    // 4. Разбивка: «Откуда выручка» (цвета типов заказа) и «Оплата»
    const split=(title,obj)=>{
      const items=Object.entries(obj||{}),total=items.reduce((s,[,i])=>s+i.revenue,0);
      return `<section class="panel split-panel"><h2>${title}</h2>${items.map(([key,i])=>`<div class="split-row"><div class="split-line"><span><i class="dot-${KIND_COLOR[key]||'hall'}"></i>${esc(i.label)} <small>· ${i.count} зак.</small></span><strong>${money(i.revenue)}</strong></div><div class="progress"><span class="fill-${KIND_COLOR[key]||'hall'}" style="width:${total?i.revenue/total*100:0}%"></span></div></div>`).join('')}</section>`;
    };

    // 5. Топ блюд
    const top=r.top_dishes||[],topMax=top[0]?.revenue||1;
    const topBlock=`<section class="panel wide top-panel"><h2>Топ блюд</h2>${top.length?`<ol class="top-list">${top.map((d,i)=>`<li><span class="rank">${i+1}</span><div class="top-main"><div class="split-line"><strong>${esc(d.name)}</strong><strong>${money(d.revenue)}</strong></div><div class="split-line"><small>${d.quantity} шт.</small><small>${Math.round(d.revenue/(r.revenue||1)*100)}% выручки</small></div><div class="progress"><span style="width:${d.revenue/topMax*100}%"></span></div></div></li>`).join('')}</ol>`:`<p class="empty">Нет завершённых заказов за ${isDay?'этот день':'этот период'}</p>`}</section>`;

    // 6. Причины отмен (если были) и архив прошлых периодов (только 45 дней)
    const reasons=(r.cancel_reasons||[]).length?`<section class="panel reasons-panel"><h2>Причины отмен</h2>${r.cancel_reasons.map(c=>`<div class="split-line list-line"><span>${esc(c.reason)}</span><strong>${c.count}</strong></div>`).join('')}</section>`:'';
    const archiveBlock=isDay?'':`<section class="panel ${reasons?'wide':'full'}"><h2>Архив прошлых периодов</h2>${
      archive.length?archive.map(a=>`<div class="split-line list-line"><span><strong>${esc(shortDate(a.start_date))} — ${esc(shortDate(a.end_date))}</strong><br><small class="fine">${money(a.revenue)} · ${a.orders_count} заказов</small></span>${a.has_pdf?`<button class="secondary" data-archive-pdf="${a.id}">PDF</button>`:''}</div>`).join('')
      :'<p class="fine">Пока пусто: первый период ещё не закончился.</p>'}</section>`;

    // Раскладка рядами, без пустот: плитки → график во всю ширину → карточки одинаковой высоты → топ блюд → архив
    const cards=[split('Откуда выручка',r.by_kind),split('Оплата',r.by_payment),reasons].filter(Boolean);
    return `<div class="report">${banner}${stats}${chart}<div class="report-cards cards-${cards.length}">${cards.join('')}</div>${topBlock}${archiveBlock}</div>`;
  }
  async function settingsView(){
    const s=live?await API.request('/admin/cafe/'):state.settings;cache.settings=s;
    const get=(remote,local)=>live?s[remote]:s[local];
    return heading('Настройки','',`<button class="primary" type="submit" form="settings-form">Сохранить</button>`)+`<form id="settings-form"><div class="settings-grid"><section class="panel"><h2>Приём заказов</h2><div class="setting-line">Принимать заказы с сайта${toggle('Принимать заказы',get('is_accepting_orders','acceptOrders'),'name="acceptOrders"')}</div><div class="setting-line">Принимать доставку${toggle('Принимать доставку',get('is_delivery_enabled','acceptDelivery'),'name="acceptDelivery"')}</div><div class="two-fields">${field('Открываемся','opens',get('opens_at','opens')?.slice(0,5),'time','required')}${field('Закрываемся','closes',get('closes_at','closes')?.slice(0,5),'time','required')}</div></section><section class="panel"><h2>Доставка</h2><div class="three-fields">${field('Мин. сумма, сом','deliveryMin',get('delivery_min_sum','deliveryMin'),'number','min="0" max="1000000" required')}${field('Стоимость, сом','deliveryFee',get('delivery_fee','deliveryFee'),'number','min="0" max="1000000" required')}${field('Время, мин','deliveryTime',get('delivery_time','deliveryTime'),'text','maxlength="50" required')}</div>${field('Бесплатная доставка от, сом (0 — нет)','freeFrom',get('free_delivery_from','freeFrom'),'number','min="0" max="1000000" required')}</section><section class="panel"><h2>${multiBranch()?'Филиал и контакты':'Контакты кафе'}</h2>${multiBranch()?field('Название филиала','branchName',s.branch_name,'text','maxlength="60" required'):''}${field('Адрес','address',s.address,'text','maxlength="200"')}${field('Телефон','phone',s.phone,'tel','maxlength="30"')}</section><section class="panel"><h2>Telegram</h2><p class="fine">Telegram пока не подключён. Уведомления и отправка отчётов в группу будут доступны после подключения бота.</p><div class="setting-line">Отчёт в группу${toggle('Отчёт в Telegram',false,'disabled')}</div><p class="fine">Время работы и параметры доставки сохраняются ${live?'на сервере':'только в этом браузере'}.</p></section>${live?'':`<section class="panel"><h2>Ссылка меню для QR</h2>${field('Адрес гостевого меню','menuUrl',s.menuUrl,'url','required maxlength="400"')}<p class="fine">Для печати QR укажите опубликованный адрес сайта, доступный гостям.</p></section>`}</div><p id="settings-error" class="error" role="alert"></p></form>`;
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
    if(button.id==='telegram-toggle'){await telegramDialog();return;}   // привязать / отвязать Telegram
    if(button.id==='telegram-check'){await telegramCheck();return;}     // проверить привязку
    if(button.id==='notify-toggle'){const on=!MuslimNotify.enabled();MuslimNotify.setEnabled(on);if(on){MuslimNotify.unlock();await MuslimNotify.askPermission();MuslimNotify.beep();}paintBell();toast(on?'Уведомления включены':'Уведомления выключены');return;}
    if(button.dataset.branch){if(String(button.dataset.branch)===String(currentBranch()?.id))return;API.setBranch(button.dataset.branch);cache={};menuFilter='all';tablesFloor='delivery';paintBranch();toast(`Филиал: ${branchName()}`);await render();startWatch();return;}   // другой филиал: всё панели — по нему
    if(button.hasAttribute('data-reload')){await render();return;}
    if(button.dataset.floorTab){tablesFloor=button.dataset.floorTab==='delivery'?'delivery':Number(button.dataset.floorTab);await render(true);return;}   // вкладка: доставка или этаж
    if(button.hasAttribute('data-add-category')){const form=$('#new-category');if(!form)return;form.hidden=false;form.querySelector('.error').textContent='';$('#new-cat-name').focus();return;}   // «+ Категория»: поле названия сверху списка
    if(button.hasAttribute('data-cancel-category')){const form=$('#new-category');form.reset();form.hidden=true;return;}
    if(button.dataset.bar){const out=$('#chart-readout');if(out)out.textContent=button.dataset.bar;document.querySelectorAll('.bar-group.picked').forEach(b=>b.classList.remove('picked'));button.classList.add('picked');return;}   // столбик графика
    if(button.hasAttribute('data-close')){button.closest('dialog').close();return;}
    if(button.dataset.orderFilter){orderFilter=button.dataset.orderFilter;await render();return;}
    if(button.dataset.menuFilter){menuFilter=button.dataset.menuFilter;if($('.menu-layout')){menuTab='dishes';$('.menu-layout').className='menu-layout tab-dishes';document.querySelectorAll('[data-menu-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.menuTab==='dishes')));applyMenuFilter();}else await render();return;}
    if(button.dataset.menuTab){menuTab=button.dataset.menuTab;$('.menu-layout').className=`menu-layout tab-${menuTab}`;document.querySelectorAll('[data-menu-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===button)));return;}   // телефон: «Блюда | Категории»
    if(button.dataset.editCategory){editCategory(button.dataset.editCategory);return;}
    if(button.dataset.userFilter){userFilter=button.dataset.userFilter;await render();return;}
    if(button.dataset.reportPeriod){reportPeriod=button.dataset.reportPeriod;await render();return;}
    if(button.dataset.reportScope){reportScope=button.dataset.reportScope;await render();return;}   // шеф: «Оба филиала» включить / выключить
    // «Добавить сотрудника» и «Удалить сотрудника»
    if(button.hasAttribute('data-add-staff')){addStaff();return;}
    if(button.dataset.editStaff){editStaff(button.dataset.editStaff);return;}
    if(button.dataset.deleteStaff){const id=button.dataset.deleteStaff,u=cache.users.find(u=>String(u.id)===id),name=u.first_name||u.username;confirm('Удалить сотрудника?',`${name} (${roles[u.role]||u.role_display}) будет удалён навсегда и больше не сможет войти. Его заказы останутся в истории, но без имени.`,async()=>{await API.request(`/admin/staff/${id}/`,{method:'DELETE'});toast(`${name} удалён`);await render();});return;}
    // Кнопка «PDF» в архиве прошлых периодов
    if(button.dataset.archivePdf){download(`Муслим-период-${button.dataset.archivePdf}.pdf`,await API.request(`/admin/reports/periods/${button.dataset.archivePdf}/pdf/`,{binary:true,branch:reportBranch()}));return;}
    if(button.dataset.editDish){if(!canManageMenu())throw new Error('Для этой роли доступно только изменение наличия.');editDish(button.dataset.editDish);syncBasePrice();return;}
    if(button.id==='add-size'){if($('#size-rows').children.length>=3){toast('Максимум три варианта размера');return;}$('#size-rows').insertAdjacentHTML('beforeend',sizeRow());syncBasePrice();return;}
    if(button.hasAttribute('data-remove-size')){button.closest('.sizes-row').remove();syncBasePrice();return;}
    if(button.dataset.deleteDish){const id=button.dataset.deleteDish,d=cache.dishes.find(d=>String(d.id)===id);confirm('Удалить блюдо?',`«${d.name}» будет удалено ${live?'с сервера':'из локального меню'}.`,async()=>{if(live){await API.request(`/admin/dishes/${id}/`,{method:'DELETE'});toast(`«${d.name}» удалено`);}else await localChange(s=>{s.menu.dishes=s.menu.dishes.filter(d=>d.id!==id);},'Блюдо удалено');editor.close();await render();});return;}
    if(button.dataset.order){const id=Number(button.dataset.order),action=button.dataset.action,label=button.textContent.trim(),number=button.dataset.number||id;
      const perform=async reason=>{if(live){await API.orderAction(id,action,reason);toast(`Заказ №${number}: ${({claim:'вы взяли его',accept:'подтверждён',reject:'отклонён',cancel:'отменён',cook:'готовится',ready:'готов',send:'в пути'})[action]||label.toLowerCase()}`,button.dataset.kind);}else await localChange(s=>Store.transition(s,id,action),'Статус обновлён');await render();};
      if(live&&action==='reject'){const site=['delivery','pickup'].includes(button.dataset.kind);reasonDialog(`Отклонить заказ №${number}?`,reason=>perform(reason),site?'Кафе не смогло принять заказ':'Официант не подтвердил заказ со стола','Отклонить заказ');return;}
      if(button.dataset.reason==='true'){reasonDialog(`Отменить заказ №${number}?`,reason=>perform(reason));}else await perform('');return;
    }
    if(button.dataset.callDone){await API.request(`/staff/table-calls/${button.dataset.callDone}/done/`,{method:'POST',body:{}});await render();return;}
    if(button.hasAttribute('data-add-floor')){const f=await API.request('/admin/floors/',{method:'POST',body:{}});tablesFloor=f.number;toast(`${f.number} этаж добавлен`);await render(true);return;}   // «+ Этаж»: следующий номер, сразу открываем
    if(button.dataset.deleteFloor){const f=(cache.floors||[]).find(f=>String(f.id)===button.dataset.deleteFloor);confirm(`Удалить ${f?.number} этаж?`,'На этаже нет столов. Вкладка этажа исчезнет.',async()=>{await API.request(`/admin/floors/${button.dataset.deleteFloor}/`,{method:'DELETE'});tablesFloor=(f?.number||2)-1;toast(`${f?.number} этаж удалён`);await render(true);});return;}
    if(button.hasAttribute('data-add-table')){if(!live){editTable('new');return;}const t=await API.request('/admin/tables/',{method:'POST',body:{floor:tablesFloor}});toast(`${t.name} добавлен`);await render(true);return;}   // сразу «Стол N», без формы
    if(button.dataset.regenerateQr){const id=button.dataset.regenerateQr,t=cache.tables.find(t=>String(t.id)===id);confirm(`Обновить QR: ${t?.name||'стол'}?`,t?.kind==='delivery'?'Старый QR доставки перестанет работать — замените его везде, где он напечатан или опубликован.':'Старый QR этого стола перестанет работать — распечатайте и поставьте новый.',async()=>{await API.request(`/admin/tables/${id}/regenerate-qr/`,{method:'POST',body:{}});toast('QR обновлён. Скачайте новый.');await render(true);});return;}
    // «Гости ушли»: стол свободен, телефоны гостей больше не доверенные
    // «Освободить стол»: гости ушли — стол свободен, телефоны гостей больше не доверенные
    if(button.dataset.closeTable){const id=button.dataset.closeTable,t=(cache.tables||[]).find(t=>String(t.id)===id),name=t?.name||'Стол',left=t?.active_orders||0;confirm(`Освободить ${name}?`,`Нажимайте, когда гости ушли. Следующий заказ с этого стола снова подтвердит официант.${left?` Внимание: у стола ещё ${left} незавершённых заказ(а).`:''}`,async()=>{await API.request(`/staff/tables/${id}/close-visit/`,{method:'POST',body:{}});toast(`${name} свободен`);await render(true);});return;}
    if(button.dataset.deleteCategory){const id=button.dataset.deleteCategory,c=cache.categories.find(c=>String(c.id)===id);confirm('Удалить категорию?',`«${c?.name||''}» будет удалена. Если в ней есть блюда, сервер не даст удалить — сначала перенесите их.`,async()=>{try{await API.request(`/admin/categories/${id}/`,{method:'DELETE'});toast('Категория удалена');if(editor.open)editor.close();await render(true);}catch(error){toast(error.message);}});return;}
    if(button.dataset.editTable){editTable(button.dataset.editTable);return;}
    if(button.dataset.deleteTable){const id=button.dataset.deleteTable;if(!live&&state.orders.some(o=>String(o.table)===id))throw new Error('Сначала завершите или отмените заказы этого стола.');confirm('Удалить стол?',live?'Напечатанный QR этого стола перестанет работать. Номер освободится для нового стола.':'Стол будет удалён из локального списка.',async()=>{if(live){const t=cache.tables.find(t=>String(t.id)===id);await API.request(`/admin/tables/${id}/`,{method:'DELETE'});toast(`${t?.name||'Стол'} удалён`);}else await localChange(s=>{s.tables=s.tables.filter(t=>String(t.number)!==id);},'Стол удалён');editor.close();await render();});return;}
    if(button.dataset.regenerateBotQr){const id=button.dataset.regenerateBotQr;confirm('Обновить QR Telegram-бота?','Старый QR бота этого филиала перестанет работать — замените его везде, где он напечатан или опубликован.',async()=>{await API.request(`/admin/tables/${id}/regenerate-bot-qr/`,{method:'POST',body:{}});toast('QR бота обновлён. Скачайте новый.');await render(true);});return;}   // новый код ссылки на бота
    if(button.dataset.downloadBotQr){download('Муслим-QR-telegram-бот.png',await API.request(`/admin/tables/${button.dataset.downloadBotQr}/bot-qr/`,{binary:true}));return;}   // QR гостевого бота
    if(button.dataset.downloadQr){const id=button.dataset.downloadQr,t=cache.tables.find(t=>String(live?t.id:t.number)===id);if(live)download(`Муслим-QR-${t.number||'доставка'}.png`,await API.request(`/admin/tables/${id}/qr/`,{binary:true}));else download(`Муслим-стол-${id}.svg`,qrSvg(tableUrl(t)),'image/svg+xml');return;}
    if(button.hasAttribute('data-download-all-qr')){download('Муслим-QR.pdf',await API.request('/admin/tables/qr-pdf/',{binary:true}));return;}
    if(button.hasAttribute('data-print-qr')){$('#print-area').innerHTML='<h1>Муслим — столы и QR</h1>'+$('.qr-grid').outerHTML;$('#print-area').querySelectorAll('.actions').forEach(e=>e.remove());window.print();return;}
    if(button.hasAttribute('data-export-report')){if(live){download(`Муслим-отчёт-${reportScope==='all'?'оба-филиала':branchName()}.pdf`,await API.request(reportPeriod==='day'?`/admin/reports/day/pdf/?date=${reportDate}`:'/admin/reports/period/pdf/',{binary:true,branch:reportBranch()}));}else{$('#print-area').innerHTML='<h1>Муслим — отчёт (демонстрационные данные)</h1>'+$('#content').innerHTML;$('#print-area').querySelectorAll('button,input,.toolbar').forEach(e=>e.remove());window.print();}return;}
    if(button.hasAttribute('data-export-csv')){if(live){if(!cache.report)throw new Error('Отчёт не загружен. Сервер вернул ошибку.');download('Муслим-отчёт.json',JSON.stringify(cache.report,null,2),'application/json');}else download('Муслим-демо-отчёт.csv','\uFEFFБлюдо;Количество;Сумма\n'+(cache.reportRows||[]).map(p=>`"${p.name.replaceAll('"','""')}";${p.qty};${p.sum}`).join('\n'),'text/csv;charset=utf-8');return;}
    if(button.hasAttribute('data-run-checks')){await runChecks();return;}
    if(button.hasAttribute('data-download-checks')){if(!canAccess('api'))throw new Error('Проверка API доступна только программисту.');download('Муслим-проверка-API.json',JSON.stringify(API.results,null,2),'application/json');return;}
  }
  // Окно «Причина»: для отмены пишем сами, для отклонения причина уже подставлена (можно поменять). Гость увидит её в своём заказе
  function reasonDialog(title,handler,preset='',submit='Отменить заказ'){$('#editor-title').textContent=title;$('#editor-content').innerHTML=`<form id="reason-form"><label>Причина (её увидит гость)<textarea name="reason" maxlength="255" required>${esc(preset)}</textarea></label><p id="editor-error" class="error"></p><button class="danger" type="submit">${esc(submit)}</button></form>`;cache.reasonHandler=handler;paintControls(editor);editor.showModal();}
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button||button.disabled)return;if(button.id==='confirm-action'||button.id==='demo-login'||button.id==='logout'||button.id==='session-logout')return;if(button.form&&button.type==='submit')return;button.disabled=true;act(button).catch(error=>toast(error.message)).finally(()=>{if(button.isConnected)button.disabled=false;});});
  $('#confirm-action').addEventListener('click',async event=>{const b=event.currentTarget;b.disabled=true;try{await confirmation();$('#confirm-dialog').close();}catch(error){toast(error.message);}finally{b.disabled=false;}});
  // ===== Перетаскивание как в iPhone (категории и блюда одной категории) =====
  // Строка «приподнимается» и едет за пальцем, соседи плавно расступаются. Отпустили — строка остаётся там, где её оставили,
  // и порядок сразу сохраняется на сервере. Ошибка связи — строка возвращается на место. У края экрана список прокручивается сам.
  document.addEventListener('pointerdown',event=>{
    const handle=event.target.closest('[data-drag-cat],[data-drag-dish]');if(!handle||!live||event.button>0)return;
    const isDish=handle.hasAttribute('data-drag-dish');
    const row=handle.closest(isDish?'tr':'.cat-row'),box=row.parentElement;
    // Кого можно двигать: видимые строки категорий или видимые блюда той же категории
    const rows=[...box.children].filter(r=>!r.hidden&&(isDish?r.dataset.dishId&&r.dataset.cat===row.dataset.cat:r.dataset.catId));
    if(rows.length<2)return;
    event.preventDefault();
    const from=rows.indexOf(row),startY=event.clientY+scrollY;               // откуда тащим (в координатах страницы)
    const rects=rows.map(r=>{const b=r.getBoundingClientRect();return {top:b.top+scrollY,height:b.height};});
    const mids=rects.map(b=>b.top+b.height/2);                               // середины строк
    const step=from<rows.length-1?rects[from+1].top-rects[from].top:rects[from].top-rects[from-1].top;   // высота строки + зазор
    const nextSibling=row.nextSibling;                                       // чтобы вернуть строку при ошибке
    let pointerY=event.clientY,target=from,frame=0;
    row.classList.add('lifted');rows.forEach(r=>{if(r!==row)r.classList.add('shifting');});
    function place(){                                                        // двигаем строку и раздвигаем соседей
      const dy=pointerY+scrollY-startY,center=mids[from]+dy;
      target=from;
      for(let i=0;i<from;i++)if(center<mids[i]){target=i;break;}              // уехали вверх
      for(let i=rows.length-1;i>from;i--)if(center>mids[i]){target=i;break;}  // уехали вниз
      row.style.transform=`translateY(${dy}px)`;
      rows.forEach((r,i)=>{if(r===row)return;const shift=i>=target&&i<from?step:i<=target&&i>from?-step:0;r.style.transform=shift?`translateY(${shift}px)`:'';});
    }
    function autoScroll(){                                                   // у верхнего или нижнего края — прокручиваем
      const bottomBar=innerWidth<=550?80:0,edge=70;
      const speed=pointerY<edge?-Math.ceil((edge-pointerY)/6):pointerY>innerHeight-bottomBar-edge?Math.ceil((pointerY-(innerHeight-bottomBar-edge))/6):0;
      if(speed){scrollBy(0,speed);place();}
      frame=requestAnimationFrame(autoScroll);
    }
    const move=e=>{pointerY=e.clientY;place();};
    const up=async()=>{
      document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',up);cancelAnimationFrame(frame);
      const before=row.getBoundingClientRect().top;                           // где строку отпустили
      rows.forEach(r=>{r.classList.remove('shifting');r.style.transform='';});
      if(target!==from){if(target>from)rows[target].after(row);else rows[target].before(row);}   // ставим строку на новое место
      const after=row.getBoundingClientRect().top;
      row.style.transform=`translateY(${before-after}px)`;row.getBoundingClientRect();   // плавно «опускаем» строку в её ячейку
      row.classList.add('settling');row.style.transform='';
      setTimeout(()=>row.classList.remove('lifted','settling'),220);
      if(target===from)return;                                               // порядок не поменялся
      const order=rows.filter(r=>r!==row);order.splice(target,0,row);
      try{
        if(isDish){
          const category=Number(row.dataset.cat),ids=order.map(r=>Number(r.dataset.dishId));
          await API.request('/admin/dishes/reorder/',{method:'POST',body:{category,ids}});
          ids.forEach((id,i)=>{const d=cache.dishes.find(d=>d.id===id);if(d)d.position=(i+1)*10;});   // запоминаем новый порядок
        }else{
          const ids=order.map(r=>Number(r.dataset.catId));
          await API.request('/admin/categories/reorder/',{method:'POST',body:{ids}});
          cache.categories.sort((a,b)=>ids.indexOf(a.id)-ids.indexOf(b.id));          // кэш в новом порядке
        }
        toast('Порядок сохранён — гости видят его сразу');
      }catch(error){box.insertBefore(row,nextSibling);toast(error.message);}  // не сохранилось — возвращаем строку на место
    };
    document.addEventListener('pointermove',move);document.addEventListener('pointerup',up);document.addEventListener('pointercancel',up);   // слушаем весь документ
    frame=requestAnimationFrame(autoScroll);
  });
  // Поиск: прячем неподходящие строки прямо на странице — без запросов к серверу и без мигания
  function filterRows(){
    const q=query.trim().toLowerCase(),rows=[...document.querySelectorAll('#content [data-search]')];if(!rows.length)return;
    let shown=0;rows.forEach(row=>{const inCat=row.dataset.cat===undefined||menuFilter==='all'||row.dataset.cat===menuFilter;const ok=q?row.dataset.search.includes(q):inCat;row.hidden=!ok;if(ok)shown++;});   // поиск — по всем блюдам, без поиска — выбранная категория
    let empty=$('#search-empty');if(!empty){empty=document.createElement('p');empty.id='search-empty';empty.className='empty';empty.textContent='Ничего не найдено';rows[0].closest('.data-wrap')?.after(empty);}
    empty.hidden=shown>0;
    sortMode(q);
  }
  // Ручки ⋮⋮ у блюд видны, только когда выбрана одна категория и нет поиска
  function sortMode(q){
    const table=$('#dish-table'),hint=$('#dish-sort-hint');if(!table)return;
    const on=menuFilter!=='all'&&!q;
    table.classList.toggle('sorting',on);
    if(hint)hint.textContent=q?'':on?'Потяните за ⋮⋮, чтобы поменять порядок блюд в этой категории':'Чтобы поменять порядок блюд, выберите категорию';
  }
  document.addEventListener('input',event=>{
    if(event.target.id==='menu-search'||event.target.id==='user-search'){query=event.target.value;filterRows();}
  });
  document.addEventListener('change',async event=>{const input=event.target;
    try{
      if(input.id==='report-date'){reportDate=input.value||Store.today();await render();}
      if(input.dataset.catVisible){input.disabled=true;await API.request(`/admin/categories/${input.dataset.catVisible}/`,{method:'PATCH',body:{is_active:input.checked}});toast(input.checked?'Категория снова видна гостям':'Категория скрыта от гостей');await render(true);return;}
      if(input.dataset.availability){const id=input.dataset.availability;input.disabled=true;if(live)await API.request(me.role==='cook'?`/admin/dishes/${id}/toggle-available/`:`/admin/dishes/${id}/`,{method:me.role==='cook'?'POST':'PATCH',body:me.role==='cook'?{}:{is_available:input.checked}});if(live){const d=cache.dishes.find(d=>String(d.id)===String(id));toast(`«${d?.name||'Блюдо'}» ${input.checked?'снова в наличии':'— нет в наличии'}`);}else await localChange(s=>{s.menu.dishes.find(d=>d.id===id).available=input.checked;},'Наличие обновлено');await render();}
      if(input.dataset.roleUser){const id=input.dataset.roleUser,role=input.value,u=cache.users.find(u=>String(u.id)===id);confirm('Изменить роль?',`${u.name||u.first_name||u.username}: ${roles[u.role]} → ${roles[role]}. ${live?'Права изменятся на сервере.':'Это локальный пример.'}`,async()=>{if(live)await API.request(`/admin/staff/${id}/set-role/`,{method:'POST',body:{role}});else await localChange(s=>{const u=s.users.find(u=>u.id===id);s.audit.push({name:u.name,from:u.role,to:role,at:new Date().toLocaleString('ru-RU')});u.role=role;},'Роль изменена');await render();});input.value=u.role;}
      if(input.id==='dish-photo'){const file=input.files[0];if(!file)return;$('#photo-status').textContent='';$('#photo-status').classList.remove('error');if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024)throw new Error('Нужно фото PNG, JPG или WebP до 2 МБ.');uploadFile=file;input.disabled=true;input.closest('.upload-button').setAttribute('aria-busy','true');const url=URL.createObjectURL(file);try{const photo=new Image();photo.src=url;await photo.decode();const canvas=document.createElement('canvas'),scale=Math.min(1,700/Math.max(photo.width,photo.height));canvas.width=Math.round(photo.width*scale);canvas.height=Math.round(photo.height*scale);canvas.getContext('2d').drawImage(photo,0,0,canvas.width,canvas.height);editorImage=canvas.toDataURL('image/jpeg',.8);$('#image-preview').innerHTML=image(editorImage);$('#photo-button-label').textContent='Заменить фото';$('#photo-help').textContent=file.name;$('#photo-help').title=file.name;$('#photo-status').textContent='Фото готово. Нажмите «Сохранить», чтобы применить.';}finally{URL.revokeObjectURL(url);}}
    }catch(error){toast(error.message);if(input.dataset.availability)await render();if(input.id==='dish-photo'){input.value='';uploadFile=null;if($('#photo-status')){$('#photo-status').textContent=error.message;$('#photo-status').classList.add('error');}}}finally{input.disabled=false;if(input.id==='dish-photo')input.closest('.upload-button')?.removeAttribute('aria-busy');}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['dish-form','table-form','settings-form','reason-form','staff-form','staff-edit-form'].includes(form.id)&&!['new-category','category-form'].includes(form.id))return;event.preventDefault();const submit=form.querySelector('[type=submit]')||form.querySelector('.primary');if(submit)submit.disabled=true;
    try{
      if(form.id==='dish-form')await saveDish(form);
      if(form.id==='staff-form')await saveStaff(form);   // новый сотрудник
      if(form.id==='staff-edit-form')await saveStaffEdit(form);   // «Изменить сотрудника»
      if(form.id==='new-category'){const name=String(new FormData(form).get('name')).trim();await API.request('/admin/categories/',{method:'POST',body:{name}});toast(`Категория «${name}» добавлена`);await render(true);}   // новая категория — в конец списка
      if(form.id==='category-form'){const v=new FormData(form);await API.request(`/admin/categories/${editingId}/`,{method:'PATCH',body:{name:String(v.get('name')).trim(),is_active:v.has('is_active')}});editor.close();toast('Категория сохранена');await render(true);}
      if(form.id==='table-form'&&!live){const values=new FormData(form),payload={name:String(values.get('name')).trim(),number:Number(values.get('number'))};if(!payload.name)throw new Error('Укажите название стола.');await localChange(s=>{if(s.tables.some(t=>t.number===payload.number&&t.number!==editingId))throw new Error('Стол с таким номером уже существует.');s.orders.forEach(o=>{if(o.table===editingId)o.table=payload.number;});s.tables=s.tables.filter(t=>t.number!==editingId);s.tables.push(payload);s.tables.sort((a,b)=>a.number-b.number);},'Стол сохранён');editor.close();await render();}
      if(form.id==='settings-form'){const values=new FormData(form),s={acceptOrders:values.has('acceptOrders'),acceptDelivery:values.has('acceptDelivery'),opens:String(values.get('opens')),closes:String(values.get('closes')),deliveryMin:Number(values.get('deliveryMin')),deliveryFee:Number(values.get('deliveryFee')),deliveryTime:String(values.get('deliveryTime')).trim(),freeFrom:Number(values.get('freeFrom')),address:String(values.get('address')).trim(),phone:String(values.get('phone')).trim()};if(live)await API.request('/admin/cafe/',{method:'PATCH',body:{is_accepting_orders:s.acceptOrders,is_delivery_enabled:s.acceptDelivery,opens_at:s.opens,closes_at:s.closes,delivery_min_sum:s.deliveryMin,delivery_fee:s.deliveryFee,delivery_time:s.deliveryTime,free_delivery_from:s.freeFrom,address:s.address,phone:s.phone,...(values.has('branchName')?{branch_name:String(values.get('branchName')).trim()}:{})}});if(live&&values.has('branchName')){me=await API.request('/auth/me/');paintBranch();}if(!live)await localChange(next=>Object.assign(next.settings,s,{menuUrl:String(values.get('menuUrl'))}),'Настройки сохранены');toast('Настройки сохранены');}
      if(form.id==='reason-form'){const reason=new FormData(form).get('reason').trim();if(!reason)throw new Error('Укажите причину отмены.');await cache.reasonHandler(reason);editor.close();}
    }catch(error){const target=form.querySelector('.error')||form.closest('dialog')?.querySelector('.error');if(target)target.textContent=error.message;else toast(error.message);}finally{if(submit)submit.disabled=false;}
  });
  $('#login-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;$('#login-error').textContent='';try{if(!API.enabled)throw new Error('Запустите локальную версию сайта для подключения к API.');const data=new FormData(form),user=await API.login(String(data.get('username')).trim(),String(data.get('password')),data.has('remember'));form.reset();await enter(true,user);}catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}});
  function logout(){API.logout();try{sessionStorage.removeItem('muslim-demo-open');}catch{/* Нет сохранённой демо-сессии. */}location.hash='';showLogin();}
  $('#logout').addEventListener('click',logout);
  $('#session-logout').addEventListener('click',logout);
  window.addEventListener('muslim-session-expired',()=>{if(live)showLogin('Сессия истекла. Войдите повторно.');});
  window.addEventListener('muslim-api-result',()=>{if(view==='api'&&$('#api-results'))$('#api-results').innerHTML=resultRows();});
  $('#login-description').textContent=API.enabled?'Войдите по email или логину, который выдал администратор.':'Панель без базы данных. Вы можете проверить все разделы на демонстрационных данных.';
  if(!API.enabled){
    $('#login-form').hidden=true;
    $('#login-description').textContent='Сервер не подключён. Откройте панель с запущенным сервером, чтобы войти.';
    const localUrl=window.MUSLIM_CONFIG?.localAppUrl;
    if(localUrl){const link=document.createElement('a');link.className='primary local-api-link';link.href=new URL('/admin',localUrl).href;link.textContent='Открыть с API';$('#login-description').after(link);}
  }
  paintControls(document);
  // Вход сохранён — не показываем форму входа, пока сервер проверяет сессию (иначе она мелькает)
  if(API.enabled&&API.hasSession()){$('#login-screen').hidden=true;API.request('/auth/me/').then(user=>enter(true,user)).catch(error=>showLogin(error.message));}
})();
