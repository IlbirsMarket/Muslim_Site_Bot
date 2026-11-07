(() => {
  'use strict';
  const $=s=>document.querySelector(s),Store=window.MuslimStore,API=window.MuslimAPI;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=n=>`${new Intl.NumberFormat('ru-RU').format(n||0)} сом`;
  const list=data=>Array.isArray(data)?data:data?.results||[];
  const icon=window.MuslimIcons.render;
  const roles={owner:'Программист',programmer:'Программист',chef:'Шеф',admin:'Админ',cook:'Повар',waiter:'Официант',courier:'Курьер',cashier:'Кассир',user:'Пользователь',blocked:'Заблокирован'};
  const views=[['cash','wallet','Касса'],['orders','orders','Заказы'],['quick','plus','Заказ за гостя'],['menu','menu','Блюда и категории'],['tables','tables','Столы и QR'],['users','users','Пользователи и роли'],['reports','reports','Отчёты'],['settings','settings','Настройки'],...(API.enabled?[['api','api','Проверка API']]:[])];
  let live=false,state,me,view='orders',orderFilter='all',menuFilter='all',menuTab='cats',query='',userFilter='all',reportPeriod='day',reportScope='branch',reportDate=Store.today(),loadSequence=0,cache={},confirmation,editorImage='',uploadFile=null,editingId=null,toastTimer;
  let orderTab='active',payState=null;
  let settingsTab='main',cashTab='shift';   // вкладки «Настройки: Главное | Чековые аппараты» и «Касса: Смена | К оплате | Официанты | История»
  // Переключатель вкладок — тот же вид, что «Активные | К оплате» в «Заказах»
  function tabs(items,current,attr){return `<div class="order-tabs" role="tablist">${items.map(([id,label,count])=>`<button type="button" role="tab" data-${attr}="${id}" aria-selected="${id===current}">${label}${count!=null?` <i>${count}</i>`:''}</button>`).join('')}</div>`;}   // «Активные | К оплате»; открытое окно оплаты
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
    $('#environment-label').innerHTML=live?`<span class="env-app">Панель кафе «Муслим»</span>${branchName()?`<span class="env-sep"> · </span><b class="env-branch">${esc(branchName())}</b>`:''}`:'Демо · изменения только в этом браузере · Telegram не подключён';   // на телефоне филиал — крупно, «Панель…» — мелко под ним
    const guestLink=$('.environment-actions a');if(guestLink)guestLink.href=live&&currentBranch()?`./?branch=${currentBranch().id}`:'./';   // «Меню гостей» — меню этого филиала
  }
  function canManageMenu(){return !live||['programmer','chef','admin','cashier'].includes(me?.role);}   // кассир — как админ
  function canAccess(id){
    if(id==='api')return live&&['programmer','owner'].includes(me?.role);
    if(id==='cash')return live&&['programmer','chef','admin','cashier'].includes(me?.role);                       // «Касса» — кассиру и администрации
    if(id==='quick')return live&&['programmer','chef','admin','cashier','waiter'].includes(me?.role);            // «Заказ за гостя» — официант, кассир, админ
    return !live||['programmer','chef','admin','cashier'].includes(me?.role)||['orders',...(me?.role==='cook'?['menu']:[]),...(me?.role==='waiter'?['tables']:[])].includes(id);   // официант видит столы, повар — блюда (стоп-лист)
  }
  function showLogin(message=''){
    stopWatch();   // вышли — уведомления больше не нужны
    ++loadSequence;live=false;me=null;cache={};
    document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
    $('#admin-shell').hidden=true;$('#login-screen').hidden=false;$('#content').innerHTML='';
    $('#login-form').elements.password.value='';$('#login-error').textContent=message;
    pinMode(codeOnly(),message);                                                     // на сайте вход только по коду
  }
  // ===== Вход по коду сотрудника (как в 1С): набрал свой код → «Войти». Логина и пароля на сайте нет =====
  // Форма логина и пароля остаётся только в Telegram (привязать Telegram) и в демо-версии (кнопки ролей)
  // Пока выключено: входим по логину и паролю. Включить потом — pinLogin:true в runtime-config.js (и PIN_LOGIN=1 на сервере)
  function pinOn(){return Boolean(window.MUSLIM_CONFIG?.pinLogin);}
  function codeOnly(){return pinOn()&&API.enabled&&!window.MuslimTG?.active&&!window.MUSLIM_CONFIG?.demo;}
  let pinValue='',pinBusy=false;
  function pinMode(on,message=''){
    $('#pin-login').hidden=!on;$('#password-login').hidden=on;                                     // цифры или логин+пароль
    $('#pin-switch').hidden=true;                                                                   // переключателя больше нет
    pinValue='';paintPin();$('#pin-error').textContent=on?message:'';
  }
  function paintPin(){$('#pin-dots').innerHTML=pinValue?'<i class="on"></i>'.repeat(pinValue.length):'<span>Наберите код и нажмите «Войти»</span>';}   // кружок на каждую цифру — сколько цифр в коде, не видно
  async function pinKey(key){
    if(pinBusy)return;
    if(key==='del'){pinValue=pinValue.slice(0,-1);paintPin();return;}
    if(/^\d$/.test(key)){if(pinValue.length<8){pinValue+=key;paintPin();}$('#pin-error').textContent='';return;}   // цифры только копим
    if(key!=='ok')return;
    if(!pinValue){$('#pin-error').textContent='Наберите свой код.';return;}                         // входим только по кнопке «Войти»
    pinBusy=true;
    try{const user=await API.pinLogin(pinValue);pinValue='';paintPin();await enter(true,user);}
    catch(error){pinValue='';paintPin();$('#pin-error').textContent=error.message;$('#pin-dots').classList.remove('shake');void $('#pin-dots').offsetWidth;$('#pin-dots').classList.add('shake');}
    finally{pinBusy=false;}
  }
  function nav(){
    $('#navigation').innerHTML=views.filter(([id])=>canAccess(id)).map(([id,icon,name])=>`<button class="nav-button" data-view="${id}" ${view===id?'aria-current="page"':''}><span class="nav-icon" aria-hidden="true">${window.MuslimIcons.render(icon)}</span><span class="nav-label">${name}</span><span class="nav-label-short">${id==='users'?'Роли':id==='tables'?'Столы':id==='menu'?'Блюда':id==='quick'?'Заказать':name}</span>${id==='orders'&&cache.newCount?`<b class="nav-badge">${cache.newCount}</b>`:''}</button>`).join('');
  }
  async function enter(useAPI,user){
    live=useAPI;me=user;state=useAPI?null:Store.load();
    if(!live){try{sessionStorage.setItem('muslim-demo-open','1');}catch{/* Вход работает без сохранения сессии. */}}
    $('#login-screen').hidden=true;$('#admin-shell').hidden=false;
    $('#staff-name').textContent=live?(me.first_name||me.username):'Администратор';
    $('#staff-role').textContent=live?`Роль: ${me.role_display}`:'Демонстрационный режим';
    $('#my-pin').hidden=$('#session-pin').hidden=!(live&&pinOn());                    // «Мой код» — только когда включён вход по коду
    if(live)API.setBranch(multiBranch()?currentBranch()?.id:null);   // шеф — последний выбранный филиал, остальные — свой (сервер)
    paintBranch();
    const requested=location.hash.slice(1);view=views.some(v=>v[0]===requested)&&canAccess(requested)?requested:homeView();
    await render();
    paintTelegram();   // кнопка «Привязать Telegram»
    startWatch();   // следим за новыми заказами и вызовами
  }
  async function render(quiet=false){   // quiet=true — тихое обновление, без надписи «Загружаем…»
    if(!canAccess(view))view=homeView();
    const sequence=++loadSequence;nav();location.hash=view;
    if(!quiet)$('#content').innerHTML='<div class="loading">Загружаем…</div>';
    try{
      let html='';
      if(view==='cash')html=await cashView();
      if(view==='orders')html=await ordersView();
      if(view==='quick')html=await quickView();
      if(view==='menu')html=await menuView();
      if(view==='tables')html=await tablesView();
      if(view==='users')html=await usersView();
      if(view==='reports')html=await reportsView();
      if(view==='settings')html=await settingsView();
      if(view==='api')html=apiView();
      if(sequence===loadSequence){const paint=()=>{$('#content').innerHTML=html;if(view==='settings'&&live&&$('#agent-status'))agentAlive();};   // проверка программы печати — когда раздел уже на экране
      const smooth=view==='orders'&&quiet&&document.startViewTransition&&!matchMedia('(prefers-reduced-motion: reduce)').matches;if(smooth)await document.startViewTransition(paint).updateCallbackDone;else paint();nav();paintControls($('#content'));filterRows();const tabs=$('.floor-tabs'),open=tabs?.querySelector('[aria-selected=true]');if(tabs&&open)tabs.scrollLeft=Math.max(0,open.offsetLeft-(tabs.clientWidth-open.offsetWidth)/2);}   // открытая вкладка этажа всегда видна (на телефоне ряд прокручивается)
    }catch(error){if(sequence!==loadSequence)return;$('#content').innerHTML=heading(views.find(v=>v[0]===view)?.[2]||'Панель')+`<div class="panel"><h2>Не удалось загрузить раздел</h2><p class="error">${esc(error.message)}</p><p class="fine">${error.status===500?'Сервер вернул 500. Ошибку нужно исправить в API.':error.status===401?'Войдите повторно.':error.status===403?'У вашей роли нет доступа к этому разделу.':'Проверьте подключение и повторите.'}</p><br><button class="secondary" data-reload>Повторить</button></div>`;}
  }
  // ===== «Заказ за гостя» (как в 1С): стол → меню без фото → «Отправить на кухню». Заказ сразу «Принят» =====
  const qo={data:null,table:null,cat:null,search:'',lines:[],comment:'',floor:null};   // table: id стола или 'takeaway'
  const qoAll=()=>(qo.data?.menu||[]).flatMap(c=>c.dishes.map(d=>({...d,cat:c.id})));
  // Кнопки меню: у блюда с размерами — отдельная кнопка на каждый размер («Пепперони 30 см»)
  function qoTiles(){
    const q=qo.search.trim().toLowerCase();
    const dishes=qoAll().filter(d=>q?d.name.toLowerCase().includes(q):d.cat===qo.cat);
    return dishes.flatMap(d=>d.sizes.length?d.sizes.map(s=>({d,s,name:`${d.name} ${s.name}`,price:s.price})):[{d,s:null,name:d.name,price:d.price}]);
  }
  const qoKey=(dish,size,extras)=>[dish,size||0,[...extras].sort((a,b)=>a-b).join('.')].join('|');
  function qoPrice(line){const d=qoAll().find(x=>x.id===line.dish_id);return line.price+line.extras.reduce((s,id)=>s+(d?.extras.find(e=>e.id===id)?.price||0),0);}
  const qoTotal=()=>qo.lines.reduce((s,l)=>s+qoPrice(l)*l.qty,0);
  function qoTableName(){if(qo.table==='takeaway')return 'С собой';const t=qo.data?.tables.find(t=>t.id===qo.table);return t?t.name:'';}
  async function quickView(){
    qo.data=await API.request('/staff/quick-order/');
    if(qo.cat==null||!qo.data.menu.some(c=>c.id===qo.cat))qo.cat=qo.data.menu[0]?.id??null;
    return qo.table==null?qoTablesHtml():qoMenuHtml();
  }
  function qoTablesHtml(){
    const tables=qo.data.tables,floors=[...new Set(tables.map(t=>t.floor))];
    if(!floors.includes(qo.floor))qo.floor=floors[0]??1;
    const mins=t=>t.since?Math.max(1,Math.round((Date.now()-new Date(t.since))/60000)):0;
    const ago=m=>m>=60?`${Math.floor(m/60)} ч ${m%60} мин`:`${m} мин`;
    const takeaway=me?.role!=='waiter'?'<button type="button" class="primary" data-qo="table" data-id="takeaway">С собой</button>':'';   // «С собой» — только кассир и админ
    return heading('Заказ за гостя','Выберите стол — откроется меню',takeaway)
      +(floors.length>1?`<div class="toolbar"><div class="pills">${floors.map(f=>`<button type="button" class="pill ${f===qo.floor?'active':''}" data-qo="floor" data-id="${f}" aria-pressed="${f===qo.floor}">${f} этаж</button>`).join('')}</div></div>`:'')
      +`<div class="table-tiles qo-tiles">${tables.filter(t=>t.floor===qo.floor).map(t=>`<button type="button" class="table-tile qo-table ${t.bill_requested?'busy bill':t.busy?'busy':''}" data-qo="table" data-id="${t.id}"><strong>${esc(t.name)}</strong>`
        +`<span class="tag">${t.bill_requested?'Просят счёт':t.busy?esc(money(t.total)):'Свободен'}</span>`
        +(t.busy||t.bill_requested?`<small>${esc(t.waiter||'')}${t.since?` · ${ago(mins(t))}`:''}</small>`:'')
        +`</button>`).join('')||'<div class="empty">Столов нет — добавьте их в «Столы и QR»</div>'}</div>`;
  }
  function qoMenuHtml(){
    const t=qo.table==='takeaway'?null:qo.data.tables.find(x=>x.id===qo.table);
    const counts={};qo.lines.forEach(l=>{const k=`${l.dish_id}|${l.size_id||0}`;counts[k]=(counts[k]||0)+l.qty;});
    const tiles=qoTiles().map(({d,s,name,price})=>{const n=counts[`${d.id}|${s?.id||0}`];return `<button type="button" class="qo-dish ${d.available?'':'stop'}" data-qo="add" data-dish="${d.id}" data-size="${s?.id||''}" ${d.available?'':'disabled'}><strong>${esc(name)}</strong><span>${d.available?esc(money(price)):'Нет в наличии'}</span>${n?`<b class="nav-badge qo-count">${n}</b>`:''}</button>`;}).join('');
    const rows=qo.lines.map((l,i)=>{const d=qoAll().find(x=>x.id===l.dish_id),ex=l.extras.map(id=>d?.extras.find(e=>e.id===id)?.name).filter(Boolean);
      const inner=`<span>${esc(l.name)}</span><small>${ex.length?'+ '+esc(ex.join(', '))+' · ':''}${money(qoPrice(l))}${d?.extras.length&&!ex.length?' · <u>добавки</u>':''}</small>`;
      return `<div class="qo-line">${d?.extras.length?`<button type="button" class="qo-line-name" data-qo="extras" data-id="${i}">${inner}</button>`:`<div class="qo-line-name">${inner}</div>`}`
        +`<div class="qo-qty"><button type="button" class="secondary" data-qo="minus" data-id="${i}" aria-label="Меньше">−</button><b>${l.qty}</b><button type="button" class="secondary" data-qo="plus" data-id="${i}" aria-label="Больше">+</button></div></div>`;}).join('');
    const subtitle=t?.busy?`Дозаказ · уже ${money(t.total)}${t.waiter?` · официант ${t.waiter}`:''}`:t?.waiter?`Официант ${t.waiter}`:'Новый заказ';
    return heading(esc(qoTableName()),esc(subtitle),'<button type="button" class="secondary" data-qo="back">← Столы</button>')
      +`<div class="toolbar"><div class="pills qo-cats">${qo.data.menu.map(c=>`<button type="button" class="pill ${!qo.search&&c.id===qo.cat?'active':''}" data-qo="cat" data-id="${c.id}" aria-pressed="${!qo.search&&c.id===qo.cat}">${esc(c.name)}</button>`).join('')}</div>`
      +`<input id="qo-search" type="search" aria-label="Поиск блюда" placeholder="Поиск блюда" value="${esc(qo.search)}" autocomplete="off"></div>`
      +`<div class="qo-layout"><div class="qo-dishes">${tiles||'<div class="empty">Ничего не найдено</div>'}</div>`
      +`<aside class="panel qo-check"><h2>${qo.lines.length?`Новые позиции · ${qo.lines.reduce((s,l)=>s+l.qty,0)}`:'Нажмите на блюдо'}</h2><div class="qo-lines">${rows}</div>`
      +`<div class="qo-foot"><label>Комментарий для кухни<textarea id="qo-comment" rows="2" maxlength="500" placeholder="Например: без лука">${esc(qo.comment)}</textarea></label><div class="qo-total"><span>Итого</span><strong>${money(qoTotal())}</strong></div>`
      +`<button type="button" class="primary qo-send" data-qo="send" ${qo.lines.length?'':'disabled'}>Отправить на кухню</button></div></aside></div>`;
  }
  function qoPaint(){if(view!=='quick')return;const focus=document.activeElement?.id;$('#content').innerHTML=qo.table==null?qoTablesHtml():qoMenuHtml();paintControls($('#content'));if(focus==='qo-search'){const s=$('#qo-search');s.focus();s.setSelectionRange(s.value.length,s.value.length);}}
  function qoReset(){qo.table=null;qo.lines=[];qo.comment='';qo.search='';}
  async function qoAct(button){
    const what=button.dataset.qo,id=button.dataset.id;
    if(what==='table'){qo.table=id==='takeaway'?'takeaway':Number(id);qo.lines=[];qo.comment='';qo.search='';qoPaint();return;}
    if(what==='floor'){qo.floor=Number(id);qoPaint();return;}
    if(what==='cat'){qo.cat=Number(id);qo.search='';qoPaint();return;}
    if(what==='back'){if(!qo.lines.length){qoReset();await render(true);return;}confirm('Вернуться к столам?','Новые позиции не отправлены и пропадут.',async()=>{qoReset();await render(true);});return;}
    if(what==='add'){const dish=Number(button.dataset.dish),size=button.dataset.size?Number(button.dataset.size):null;const d=qoAll().find(x=>x.id===dish);if(!d)return;
      const line=qo.lines.find(l=>l.dish_id===dish&&l.size_id===size&&!l.extras.length);
      if(line)line.qty=Math.min(99,line.qty+1);else{const s=size?d.sizes.find(x=>x.id===size):null;qo.lines.push({dish_id:dish,size_id:size,name:s?`${d.name} ${s.name}`:d.name,price:s?s.price:d.price,extras:[],qty:1});}
      qoPaint();return;}
    if(what==='plus'){const l=qo.lines[id];if(l)l.qty=Math.min(99,l.qty+1);qoPaint();return;}
    if(what==='minus'){const l=qo.lines[id];if(l){l.qty--;if(l.qty<1)qo.lines.splice(Number(id),1);}qoPaint();return;}
    if(what==='extras'){qoExtras(Number(id));return;}
    if(what==='extras-save'){const l=qo.lines[editingId];if(l){l.extras=[...document.querySelectorAll('#qo-extras-form input:checked')].map(i=>Number(i.value));
      const same=qo.lines.findIndex((x,i)=>i!==editingId&&qoKey(x.dish_id,x.size_id,x.extras)===qoKey(l.dish_id,l.size_id,l.extras));   // такая же строка уже есть — складываем
      if(same>=0){qo.lines[same].qty=Math.min(99,qo.lines[same].qty+l.qty);qo.lines.splice(editingId,1);}}
      editor.close();qoPaint();return;}
    if(what==='send'){qo.comment=$('#qo-comment')?.value||'';
      const order=await API.request('/staff/quick-order/',{method:'POST',body:{table:qo.table==='takeaway'?null:qo.table,comment:qo.comment,
        items:qo.lines.map(l=>({dish_id:l.dish_id,size_id:l.size_id,extra_ids:l.extras,quantity:l.qty}))}});
      toast(`Заказ №${order.number??order.id} · ${qoTableName()} — отправлен на кухню`);qoReset();await render(true);return;}
  }
  // Добавки к строке чека: нажали на строку → отметили галочками
  function qoExtras(index){
    const l=qo.lines[index],d=qoAll().find(x=>x.id===l?.dish_id);if(!d)return;editingId=index;
    $('#editor-title').textContent=l.name;
    $('#editor-content').innerHTML=`<form id="qo-extras-form" class="qo-extras">${d.extras.map(e=>`<label class="qo-extra"><input type="checkbox" value="${e.id}" ${l.extras.includes(e.id)?'checked':''}><span>${esc(e.name)}</span><b>+${esc(e.price)}</b></label>`).join('')}
      <footer class="form-footer"><button class="primary" type="button" data-qo="extras-save">Готово</button></footer></form>`;
    editor.showModal();
  }
  document.addEventListener('input',event=>{if(event.target.id==='qo-search'){qo.search=event.target.value;qoPaint();}else if(event.target.id==='qo-comment')qo.comment=event.target.value;});
  async function ordersView(){
    if(live&&orderTab==='pay'&&canPay()){cache.fresh=null;return billsView();}   // вкладка «К оплате»
    let orders,calls=[];
    if(live&&cache.fresh){({orders,calls}=cache.fresh);cache.fresh=null;}   // данные только что получены — без лишнего запроса
    else if(live){const data=await Promise.all([API.request('/staff/orders/?active=true'),seesCalls()?API.request('/staff/table-calls/'):Promise.resolve([])]);orders=list(data[0]);calls=list(data[1]);}
    else orders=state.orders;
    cache.orders=orders;cache.calls=calls;cache.activeCount=orders.length;refreshBillCount();cache.newCount=waitingCount(orders);if(live)remember(orders,calls);   // то, что уже на экране, не «новое»
    const filtered=orders.filter(o=>orderFilter==='all'||kindOf(o)===orderFilter);   // фильтр по типу: в кафе / с собой / доставка / самовывоз
    const groups=live&&me.role==='courier'
      ?[['cooking','Готовятся',['accepted','cooking']],['ready','Готовы к выдаче',['ready']],['way','В пути',['on_the_way']]]   // курьер: свои колонки
      :[['new','Новые',['new']],['cooking','Готовятся',['accepted','cooking']],['ready','Готовы и в пути',['ready','on_the_way']]];
    const callHtml=calls.length?`<div class="notice">${calls.map(c=>`<div class="actions"><strong>${esc(c.table_name)}: ${esc(c.kind_display)}${c.people?` · ${c.people} чел.`:''}</strong>${c.kind==='bill'?'<button class="primary" data-order-tab="pay">К оплате</button>':''}<button class="secondary" data-call-done="${c.id}">Выполнено</button></div>`).join('')}</div>`:'';
    return heading('Заказы',live?`${orders.length} активных заказов`:'Примеры заказов из макета',`<div class="pills order-pills">${orderFilters().map(([id,label])=>pill(label,id,orderFilter===id,'order-filter')).join('')}</div><button class="secondary" data-reload>↻ Обновить</button>`)+orderTabs(orders.length)+callHtml+`<div class="board">${groups.map(([id,label,statuses])=>{const items=filtered.filter(o=>statuses.includes(o.status));return `<section class="column"><h2 class="column-heading"><i class="dot ${id}"></i>${label}<span>${items.length}</span></h2>${items.map(orderCard).join('')||'<div class="empty">Здесь пока нет заказов</div>'}</section>`;}).join('')}</div>`;
  }
  // ===== Вкладки «Активные | К оплате» (официант и администрация) =====
  function orderTabs(active){
    if(!live||!canPay())return '';
    return `<div class="order-tabs" role="tablist"><button type="button" role="tab" data-order-tab="active" aria-selected="${orderTab==='active'}">Активные <i>${active}</i></button><button type="button" role="tab" data-order-tab="pay" aria-selected="${orderTab==='pay'}">К оплате <i id="pay-count">${cache.billCount??'…'}</i></button></div>`;
  }
  function refreshBillCount(){                                          // цифра на вкладке «К оплате» — без задержки списка
    if(!live||!canPay())return;
    API.request('/staff/bills/').then(b=>{cache.billCount=list(b).length;const el=$('#pay-count');if(el)el.textContent=cache.billCount;}).catch(()=>{});
  }
  const ordersWord=n=>n%10===1&&n%100!==11?'заказ':[2,3,4].includes(n%10)&&![12,13,14].includes(n%100)?'заказа':'заказов';   // 1 заказ, 2 заказа, 5 заказов
  const billTime=iso=>new Date(iso).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
  function billMeta(b){
    return [b.orders.length>1?`${b.orders.length} ${ordersWord(b.orders.length)}`:`№${b.orders[0]}`,`открыт ${billTime(b.opened_at)}`,
      b.staff?`${esc(b.staff_role)}: ${esc(b.staff)}`:b.waiter&&`${b.kind==='delivery'?'Курьер':'Официант'}: ${esc(b.waiter)}`,b.customer&&esc(b.customer),b.phone&&esc(b.phone)].filter(Boolean).join(' · ');
  }
  // «К оплате»: счета столов (все заказы стола — один счёт), доставки и самовывозы
  async function billsView(){
    const bills=list(await API.request('/staff/bills/'));cache.bills=bills;cache.billCount=bills.length;
    return heading('Заказы',`${bills.length} к оплате`,`<button class="secondary" data-reload>↻ Обновить</button>`)+orderTabs(cache.activeCount??'…')+billGrid(bills);
  }
  function billGrid(bills){
    const cards=bills.map((b,i)=>`<article class="bill-card kind-${esc(b.kind)}"><div class="bill-head"><h3>${esc(b.title)}</h3>${b.bill_requested?`<span class="bill-ask">просит счёт${b.people?` · ${b.people} чел.`:''}</span>`:''}</div><p class="fine">${billMeta(b)}</p>${b.in_progress?`<p class="fine bill-wip">Ещё не подано: ${b.in_progress}</p>`:''}<strong class="bill-sum">${money(b.total)}</strong><div class="bill-actions"><button type="button" class="secondary" data-bill-print="${i}">🖨 Счёт</button><button type="button" class="primary" data-bill-pay="${i}">Оплатить</button></div></article>`).join('');
    return bills.length?`<div class="bill-grid">${cards}</div>`:'<section class="panel"><p class="empty">Все счета оплачены</p></section>';
  }

  // ===== «Касса»: смена кассира — открыть, внесение / изъятие, закрыть с подсчётом наличных =====
  async function cashView(){
    const [data,bills]=await Promise.all([API.request('/staff/cash/'),API.request('/staff/bills/')]);
    const shift=data.shift;cache.shift=shift;cache.bills=list(bills);cache.billCount=cache.bills.length;cache.history=data.history||[];cache.pastShifts=data.past_shifts||[];
    const signed=n=>n===0?'0 сом':`${n>0?'+ ':'− '}${money(Math.abs(n))}`,day=iso=>new Date(iso).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'});
    const pastBlock=`<h2 class="cash-h">Прошлые смены</h2>`+(cache.pastShifts.length?`<section class="panel past-shifts"><table class="shifts-table"><thead><tr><th>Дата</th><th>Время</th><th>Открыл(а)</th><th>Закрыл(а)</th><th class="num">На начало</th><th class="num">Наличные</th><th class="num">Карта</th><th class="num">Должно быть</th><th class="num">По факту</th><th class="num">Разница</th></tr></thead><tbody>${cache.pastShifts.map((x,i)=>`<tr data-shift-open="${i}" tabindex="0" title="Показать отчёт смены"><td data-label="Дата"><b>${day(x.opened_at)}</b></td><td data-label="Время">${billTime(x.opened_at)}–${billTime(x.closed_at)}</td><td data-label="Открыл(а)">${esc(x.opened_by)}</td><td data-label="Закрыл(а)">${esc(x.closed_by)}</td><td class="num" data-label="На начало">${money(x.opening_cash)}</td><td class="num" data-label="Наличные">${money(x.cash)}</td><td class="num" data-label="Карта">${money(x.card)}</td><td class="num" data-label="Должно быть">${money(x.expected)}</td><td class="num" data-label="По факту">${money(x.counted)}</td><td class="num ${x.difference<0?'minus':x.difference>0?'plus':''}" data-label="Разница"><b>${signed(x.difference)}</b></td></tr>`).join('')}</tbody></table></section>`:'<section class="panel"><p class="empty">Закрытых смен пока нет</p></section>');
    const historyBlock=`<h2 class="cash-h">История оплат${shift?' за смену':' за сегодня'}</h2>`+(cache.history.length?`<section class="panel cash-history">${cache.history.map((h,i)=>`<div class="history-row"><button type="button" class="history-open" data-history-open="${i}" title="Показать чек"><span class="history-time">${billTime(h.paid_at)}</span><span class="history-main"><strong>${esc(h.title)}</strong><small class="fine">${esc(h.method)}${h.by?` · ${esc(h.by)}`:''}${h.orders.length>1?` · ${h.orders.length} ${ordersWord(h.orders.length)}`:''}</small></span><strong class="history-sum">${money(h.total)}</strong></button><button type="button" class="secondary" data-receipt-copy="${i}" title="Напечатать копию чека">🖨 Чек</button></div>`).join('')}</section>`:'<section class="panel"><p class="empty">Оплат пока нет</p></section>');
    const tabBar=tabs([['shift','Смена'],['pay','К оплате',cache.bills.length],['waiters','Официанты'],['history','История']],cashTab,'cash-tab');
    if(cashTab==='pay')return heading('Касса',esc(branchName()))+tabBar+billGrid(cache.bills);                 // «К оплате»
    if(cashTab==='history')return heading('Касса',esc(branchName()))+tabBar+historyBlock+pastBlock;           // «История»
    if(cashTab==='waiters')return heading('Касса',shift?`${esc(branchName())} · смена с ${billTime(shift.opened_at)}`:esc(branchName()))+tabBar
      +(shift?await waitersBlock():`<section class="panel"><p class="fine">Откройте смену на вкладке «Смена» — здесь появятся официанты и их выплаты за смену.</p></section>`);
    if(!shift)return heading('Касса',esc(branchName()))+tabBar+`<section class="panel cash-open"><h2>Открыть смену</h2><p class="fine">Посчитайте наличные в кассе перед началом работы. Без открытой смены кассир не принимает оплату.</p><label class="field">В кассе наличных, сом<input id="cash-start" type="number" min="0" inputmode="numeric" value="0"></label><p class="error" id="cash-error"></p><button type="button" class="primary" data-cash-open>Открыть смену</button></section>`;
    const tile=(name,value)=>`<article class="stat"><span>${name}</span><strong>${value}</strong></article>`;
    const moves=shift.moves.length?`<section class="panel cash-moves"><h2>Внесения и изъятия</h2><table class="moves-table"><thead><tr><th>Время</th><th>Операция</th><th>Причина</th><th>Кто</th><th class="num">Сумма</th></tr></thead><tbody>${shift.moves.map(m=>`<tr class="move-${m.kind}"><td>${billTime(m.at)}</td><td><b>${esc(m.label)}</b></td><td>${m.comment?esc(m.comment):'<span class="fine">—</span>'}</td><td>${esc(m.by)}</td><td class="num"><b>${m.kind==='out'?'−':'+'} ${money(m.amount)}</b></td></tr>`).join('')}</tbody></table></section>`:'';
    return heading('Касса',`${esc(branchName())} · сегодня`)+tabBar
      +`<section class="cash-shift"><div><b><i class="cash-dot"></i>Смена открыта с ${billTime(shift.opened_at)}</b><small>Кассир ${esc(shift.opened_by)} · в кассе на начало ${money(shift.opening_cash)}</small></div><div class="cash-buttons"><button type="button" class="secondary" data-cash-move="in">＋ Внесение</button><button type="button" class="secondary" data-cash-move="out">− Изъятие</button><button type="button" class="primary" data-cash-close>Закрыть смену</button></div></section>`
      +`<div class="stats cash-stats">${tile('Наличные',money(shift.cash))}${tile('Карта',money(shift.card))}${tile('Счетов оплачено',shift.orders)}${tile('В кассе сейчас',money(shift.expected))}</div>`
      +moves;
  }
  // ===== «Касса» → «Официанты»: выплата за смену процентом от суммы столов или суммой вручную =====
  async function waitersBlock(){
    const w=await API.request('/staff/cash/waiters/');cache.wp=w;
    if(!w)return '';
    const manual=w.mode==='manual';
    const rows=w.rows.map(r=>`<tr><td><b>${esc(r.name)}</b></td><td class="num">${r.orders}</td><td class="num">${money(r.total)}</td><td class="num"><input class="wp-amount" data-wp-id="${r.id}" data-wp-total="${r.total}" type="number" min="0" inputmode="numeric" value="${r.amount}" ${w.paid_out?'disabled':''}></td></tr>`).join('');
    return `<section class="panel waiters-pay"><h2>Официанты за смену</h2>`
      +(w.rows.length?`<div class="wp-controls"><b>Выплата:</b><div class="pills"><button type="button" class="pill ${manual?'':'active'}" data-wp="mode" data-wp-mode="percent">Процент от суммы</button><button type="button" class="pill ${manual?'active':''}" data-wp="mode" data-wp-mode="manual">Сумма вручную</button></div>`
        +(manual?'':`<label class="wp-percent"><input id="wp-percent" type="number" min="0" max="100" step="0.5" inputmode="decimal" value="${w.percent||''}" placeholder="5" ${w.paid_out?'disabled':''}> %</label><button type="button" class="secondary" data-wp="calc" ${w.paid_out?'disabled':''}>Посчитать всем</button>`)+`</div>`
        +`<div class="data-wrap"><table class="data-table wp-table"><thead><tr><th>Официант</th><th class="num">Столов оплачено</th><th class="num">Сумма столов</th><th class="num">Выплата, сом</th></tr></thead><tbody>${rows}</tbody>`
        +`<tfoot><tr><td><b>Итого</b></td><td class="num"><b>${w.orders}</b></td><td class="num"><b>${money(w.total)}</b></td><td class="num"><b id="wp-sum">${money(w.amount)}</b></td></tr></tfoot></table></div>`
        +`<p class="fine">Считаются оплаченные за эту смену столы, которые вёл официант. Сумму у любого можно исправить вручную.${w.paid_out?' <b>Выдано из кассы.</b>':''}</p>`
        +`<div class="actions">${w.paid_out?'':'<button type="button" class="primary" data-wp="save">Сохранить</button><button type="button" class="secondary" data-wp="payout">Выдать из кассы</button>'}<button type="button" class="secondary" data-wp="print">🖨 Напечатать</button></div>`
        :'<p class="fine">За эту смену ещё нет оплаченных столов официантов.</p>')+`</section>`;
  }
  function waitersPayload(){
    const amounts={};document.querySelectorAll('.wp-amount').forEach(i=>{if(i.value!=='')amounts[i.dataset.wpId]=Number(i.value);});
    return {mode:cache.wp?.mode||'percent',percent:Number($('#wp-percent')?.value||cache.wp?.percent||0),amounts};
  }
  function waitersSum(){let s=0;document.querySelectorAll('.wp-amount').forEach(i=>{s+=Number(i.value||0);});const el=$('#wp-sum');if(el)el.textContent=money(s);}
  async function waitersAct(button){
    const what=button.dataset.wp;
    if(what==='mode'){const body={...waitersPayload(),mode:button.dataset.wpMode,amounts:{}};await API.request('/staff/cash/waiters/',{method:'POST',body});await render(true);return;}   // сменили способ — суммы считаются заново
    if(what==='calc'){const p=Number($('#wp-percent')?.value||0);if(!(p>0))throw new Error('Впишите процент, например 5.');document.querySelectorAll('.wp-amount').forEach(i=>{i.value=Math.round(Number(i.dataset.wpTotal)*p/100);});waitersSum();toast(`Посчитано по ${p}% — проверьте и нажмите «Сохранить»`);return;}
    if(what==='save'){await API.request('/staff/cash/waiters/',{method:'POST',body:waitersPayload()});toast('Выплаты официантам сохранены');await render(true);return;}
    if(what==='payout'){await API.request('/staff/cash/waiters/',{method:'POST',body:waitersPayload()});const sum=[...document.querySelectorAll('.wp-amount')].reduce((s,i)=>s+Number(i.value||0),0);
      confirm('Выдать официантам из кассы?',`${money(sum)} — запишется изъятием «Официантам», «Должно быть в кассе» уменьшится.`,async()=>{await API.request('/staff/cash/waiters/?action=payout',{method:'POST',body:{}});toast('Выдано из кассы');await render(true);});return;}
    if(what==='print'){if(!cache.wp?.paid_out)await API.request('/staff/cash/waiters/',{method:'POST',body:waitersPayload()});await API.request('/staff/cash/waiters/?action=print',{method:'POST',body:{}});toast('Отправлено на чековый аппарат');return;}
  }
  document.addEventListener('input',event=>{if(event.target.classList?.contains('wp-amount'))waitersSum();});
  function cashMoveDialog(kind){
    $('#editor-title').textContent=kind==='in'?'Внесение наличных':'Изъятие наличных';
    $('#editor-content').innerHTML=`<div class="pay-form"><p class="fine">${kind==='in'?'Положили деньги в кассу (например, на размен).':'Забрали деньги из кассы (например, инкассация).'}</p><label class="field">Сумма, сом<input id="cash-amount" type="number" min="1" inputmode="numeric" required></label><label class="field">Комментарий<input id="cash-comment" maxlength="150" placeholder="${kind==='in'?'Размен':'Инкассация'}"></label><p class="error" id="cash-error"></p><button type="button" class="primary pay-submit" data-cash-move-save="${kind}">${kind==='in'?'Внести':'Изъять'}</button></div>`;
    editor.showModal();$('#cash-amount').focus();
  }
  function cashCloseDialog(){
    const s=cache.shift;if(!s)return;
    const line=(name,value)=>`<div class="split-line"><span>${name}</span><span>${value}</span></div>`;
    $('#editor-title').textContent='Закрыть смену';
    $('#editor-content').innerHTML=`<div class="pay-form"><p class="fine">Смена ${esc(s.opened_by)} · с ${billTime(s.opened_at)}</p>${line('В кассе на начало',money(s.opening_cash))}${line('Наличными за смену','+ '+money(s.cash))}${s.cash_in?line('Внесение','+ '+money(s.cash_in)):''}${s.cash_out?line('Изъятие','− '+money(s.cash_out)):''}
      <div class="split-line pay-total"><strong>Должно быть в кассе</strong><strong>${money(s.expected)}</strong></div>
      <span class="pay-label">Посчитали наличные</span><div class="pay-calc"><label>В кассе по факту<input id="cash-counted" type="number" min="0" inputmode="numeric"></label><div>Разница<strong id="cash-diff">—</strong></div></div>
      <p class="fine">Картой за смену: ${money(s.card)} · счетов: ${s.orders}</p><p class="error" id="cash-error"></p><button type="button" class="primary pay-submit" data-cash-close-save>Закрыть смену · печать отчёта</button></div>`;
    editor.showModal();
    const input=$('#cash-counted');input.focus();
    input.oninput=()=>{const d=input.value===''?null:Number(input.value)-s.expected;const out=$('#cash-diff');out.textContent=d==null?'—':d===0?'0 сом ✓':`${d>0?'+ ':'− '}${money(Math.abs(d))}`;out.className=d&&d<0?'minus':'';};
  }
  // Окно с чеком: как он выйдет на чековом аппарате + кнопка печати
  function showReceipt(title,note,job,printAttr){
    $('#editor-title').textContent=title;
    $('#editor-content').innerHTML=`<div class="receipt-view"><p class="fine">${note}</p><iframe class="receipt-frame" title="Чек" scrolling="no"></iframe><button type="button" class="primary" ${printAttr}>🖨 Напечатать${job.kind==='receipt'?' копию':job.kind==='bill'?' счёт':''}</button></div>`;
    const frame=$('.receipt-frame');frame.srcdoc=MuslimReceipt.html(job);
    frame.onload=()=>{const body=frame.contentDocument.body;frame.style.height=body.scrollHeight+12+'px';};
    editor.showModal();
  }
  async function cashAction(path,body){                                   // запрос «Кассы» с ошибкой прямо в окне
    try{return await API.request(path,{method:'POST',body});}
    catch(error){const out=$('#cash-error');if(out)out.textContent=error.message;else toast(error.message);return null;}
  }
  // Окно «Оплата»: способ, сколько дал гость, сдача → «Оплачено · печать чека»
  function openPay(bill){
    payState={bill,method:bill.payment_method==='card'?'card':'cash',cash:'',received:''};
    $('#editor-title').textContent=`Оплата · ${bill.title}`;drawPay();editor.showModal();
  }
  function drawPay(){
    const {bill,method}=payState,total=bill.total;
    const quick=[...new Set([100,500,1000,5000].map(step=>Math.ceil(total/step)*step).filter(v=>v>total))].slice(0,3);   // быстрые суммы: 2 000, 5 000
    $('#editor-content').innerHTML=`<form id="pay-form" class="pay-form"><p class="fine">${billMeta(bill)}</p>
      <div class="pay-items">${bill.items.map(it=>`<div class="split-line"><span>${esc(it.name)}${it.extras?.length?` <small>+ ${esc(it.extras.join(', '))}</small>`:''} × ${it.qty}</span><span>${money(it.sum)}</span></div>`).join('')}</div>
      <div class="split-line pay-total"><strong>Итого</strong><strong>${money(total)}</strong></div>
      <span class="pay-label">Способ оплаты</span><div class="pay-methods">${[['cash','Наличные'],['card','Карта'],['mixed','Наличные + карта']].map(([v,l])=>`<button type="button" data-pay-method="${v}" aria-pressed="${method===v}">${l}</button>`).join('')}</div>
      ${method==='mixed'?`<label class="field pay-field">Наличными, сом<input name="cash" type="number" min="1" max="${total-1}" inputmode="numeric" value="${esc(payState.cash)}" required></label><p class="fine" id="pay-card-part"></p>`:''}
      ${method!=='card'?`<span class="pay-label">Расчёт</span><div class="pay-calc"><label>Получено<input name="received" type="number" min="0" inputmode="numeric" value="${esc(payState.received)}" placeholder="без сдачи"></label><div>Сдача<strong id="pay-change">—</strong></div></div><div class="pay-quick"><button type="button" data-pay-quick="exact" aria-pressed="false">Без сдачи</button>${quick.map(v=>`<button type="button" data-pay-quick="${v}" aria-pressed="false">${money(v)}</button>`).join('')}</div>`:''}
      <p class="error" id="pay-error"></p><button class="primary pay-submit" type="submit">Оплачено · печать чека</button></form>`;
    const form=$('#pay-form');
    const update=()=>{
      payState.cash=form.elements.cash?.value||'';payState.received=form.elements.received?.value||'';
      const cashPart=method==='mixed'?Number(payState.cash||0):method==='cash'?total:0;
      if($('#pay-card-part'))$('#pay-card-part').textContent=payState.cash?`Картой: ${money(Math.max(0,total-cashPart))}`:'Остальное — картой';
      if($('#pay-change')){const got=Number(payState.received);$('#pay-change').textContent=payState.received===''?'—':got<cashPart?'мало':money(got-cashPart);}
    };
    form.addEventListener('input',update);update();
    form.onsubmit=async event=>{
      event.preventDefault();const button=form.querySelector('.pay-submit');button.disabled=true;$('#pay-error').textContent='';
      try{
        const result=await API.request('/staff/bills/pay/',{method:'POST',body:{orders:bill.orders,method,cash:method==='mixed'?Number(payState.cash):undefined,received:method!=='card'&&payState.received!==''?Number(payState.received):undefined}});
        editor.close();payState=null;toast(`Оплачено ${money(result.total)}${result.change?` · сдача ${money(result.change)}`:''}${result.table_freed?' · стол свободен':''}`);await render(true);
      }catch(error){$('#pay-error').textContent=error.message;button.disabled=false;}
    };
  }

  // ===== Чековый аппарат: компьютер, к которому он подключён, сам забирает и печатает чеки филиала =====
  const Printer={
    key:'muslim-printer',
    get(){try{return JSON.parse(localStorage.getItem(this.key)||'null');}catch{return null;}},
    set(value){try{if(value)localStorage.setItem(this.key,JSON.stringify(value));else localStorage.removeItem(this.key);}catch{/* без хранилища печать не включить */}},
    on(){return Boolean(this.get()?.on);},
  };
  const printTab=Math.random().toString(36).slice(2);let printBusy=false;
  function printLock(){                                                  // печатает только одна вкладка браузера
    try{const lock=JSON.parse(localStorage.getItem('muslim-printer-lock')||'null');if(lock&&lock.id!==printTab&&Date.now()-lock.t<10000)return false;
      localStorage.setItem('muslim-printer-lock',JSON.stringify({id:printTab,t:Date.now()}));}catch{/* одна вкладка — и так одна */}
    return true;
  }
  // ===== Программа печати: одно окно панели → три аппарата по IP (порт 9100). Программа — muslim-print.bat на этом компьютере =====
  const AGENT='http://127.0.0.1:18080';
  const DEFAULT_IPS={hall:'192.168.10.21',kitchen1:'192.168.10.22',kitchen2:'192.168.10.20'};   // Бар, Кухня-9, Фаст фуд
  const PRINTERS=[['hall','Зал (Бар): счёт, оплата, смена'],['kitchen1','Кухонный аппарат 1 (горячее)'],['kitchen2','Кухонный аппарат 2 (фастфуд)']];
  const agentQueue=[];let agentOk=null;                                    // чеки, которые ещё не дошли до аппарата; работает ли программа
  function printerIp(kind,config){const ips={...DEFAULT_IPS,...(config.ips||{})};return kind==='kitchen1'?ips.kitchen1:kind==='kitchen2'?ips.kitchen2:ips.hall;}
  async function agentAlive(){
    const stop=new AbortController(),timer=setTimeout(()=>stop.abort(),2000);
    try{const r=await fetch(AGENT+'/ping',{signal:stop.signal,cache:'no-store'});agentOk=r.ok;}catch{agentOk=false;}finally{clearTimeout(timer);}
    paintAgent();return agentOk;
  }
  function paintAgent(note=''){
    const el=$('#agent-status');if(!el)return;
    el.className='agent-status '+(agentOk?'on':agentOk===false?'off':'');
    el.textContent=agentOk?`Программа печати работает${agentQueue.length?` · ждут печати: ${agentQueue.length}`:''}${note?' · '+note:''}`:agentOk===false?'Программа печати не найдена — запустите muslim-print.bat на этом компьютере':'Проверяем программу печати…';
  }
  async function agentSend(job,config){
    const ip=printerIp(job.kind,config);if(!ip)return;
    const body=MuslimEscpos.toBase64(MuslimEscpos.build(job,Number(config.page||17)));
    const r=await fetch(`${AGENT}/print?ip=${encodeURIComponent(ip)}`,{method:'POST',headers:{'Content-Type':'text/plain'},body});
    if(!r.ok)throw new Error((await r.text())||`аппарат ${ip} не ответил`);
  }
  async function printTick(){
    const config=Printer.get();
    if(!live||!config?.on||printBusy||!API.hasSession()||!printLock())return;
    const kinds=printKinds(config);if(!kinds.length)return;
    printBusy=true;
    try{
      if(config.mode==='agent'){                                            // через программу печати
        if(!window.MuslimEscpos||!await agentAlive())return;              // программа не запущена — чеки ждут на сервере
        if(agentQueue.length<50)for(const job of list(await API.request('/staff/print-jobs/claim/',{method:'POST',body:{kinds},branch:config.branch||undefined})))agentQueue.push(job);
        while(agentQueue.length){await agentSend(agentQueue[0],config);agentQueue.shift();}
        paintAgent();
      }else if(window.MuslimReceipt){                                        // через Chrome (один принтер на окно)
        for(const job of list(await API.request('/staff/print-jobs/claim/',{method:'POST',body:{kinds},branch:config.branch||undefined})))await MuslimReceipt.print(job);
      }
    }catch(error){if(config.mode==='agent')paintAgent(error.message);}      // аппарат не ответил — повторим через 3 секунды
    finally{printBusy=false;}
  }
  setInterval(printTick,3000);
  // Что печатает этот компьютер
  const PRINT_GROUPS=[['cash','Зал: счёт, чек об оплате, отчёт смены',['bill','receipt','shift']],['kitchen1','Кухонный аппарат 1 (горячее)',['kitchen1']],['kitchen2','Кухонный аппарат 2 (фастфуд)',['kitchen2']],['order','Полный чек заказа после подтверждения (если нужен)',['order']]];
  const CAT_PRINTERS=[['kitchen1','Кухонный аппарат 1'],['kitchen2','Кухонный аппарат 2'],['none','Не печатать (только в чеке оплаты)']];   // куда идут блюда категории
  function printKinds(config){const groups=config?.groups||['cash'];return PRINT_GROUPS.filter(([id])=>groups.includes(id)).flatMap(([, ,k])=>k);}
  function printSample(target){                                             // пробный чек для аппарата
    const now=new Date(),date=now.toLocaleDateString('ru-RU'),time=now.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
    if(target==='kitchen1')return {kind:target,payload:{number:0,place:'ПРОБНЫЙ ЧЕК',staff_role:'Кухня 1 (горячее)',waiter:'',date,time,items:[{name:'Мясо по-казахски',extras:[],qty:2},{name:'Шорпо',extras:[],qty:1}],comment:'Пробный чек горячей кухни'}};
    if(target==='kitchen2')return {kind:target,payload:{number:0,place:'ПРОБНЫЙ ЧЕК',staff_role:'Кухня 2 (фастфуд)',waiter:'',date,time,items:[{name:'Бургер',extras:['Сыр'],qty:2},{name:'Пицца 30 см',extras:[],qty:1}],comment:'Пробный чек фастфуда'}};   // у каждой кухни свой пробный чек — их не перепутать
    return MuslimReceipt.sample(branchName());
  }
  function printerPanel(){
    if(!live)return '';
    const config=Printer.get()||{},on=Boolean(config.on),mode=config.mode||(on?'browser':'agent'),groups=config.groups||['cash','kitchen1','kitchen2'],ips={...DEFAULT_IPS,...(config.ips||{})};
    const agentBlock=`<div class="print-mode-box" ${mode==='agent'?'':'hidden'}><p id="agent-status" class="agent-status">Проверяем программу печати…</p>
      <div class="printer-ips">${PRINTERS.map(([id,label])=>`<label class="field">${label}<input data-printer-ip="${id}" value="${esc(ips[id])}" inputmode="decimal" placeholder="192.168.10.21"></label><button type="button" class="secondary" data-agent-test="${id}">Пробный чек</button>`).join('')}</div>
      <label class="field print-page">Кодировка кириллицы<select id="print-page"><option value="17" ${String(config.page||17)==='17'?'selected':''}>CP866 (обычно у Xprinter)</option><option value="46" ${String(config.page)==='46'?'selected':''}>Windows-1251</option></select></label>
      <p class="fine">Программа печати — файл <b>muslim-print.bat</b>: скачайте, положите на этот компьютер и запустите (для автозапуска — в папку Win+R → <b>shell:startup</b>). Если в пробном чеке вместо букв «кракозябры», смените кодировку.</p>
      <div class="actions"><button type="button" class="primary" data-agent-download>Скачать программу печати</button></div></div>`;
    const browserBlock=`<div class="print-mode-box" ${mode==='browser'?'':'hidden'}><p class="fine">Каждое окно Chrome печатает на свой принтер: зал — <b>kassa-chrome.bat</b>, кухня 1 — <b>kitchen1-chrome.bat</b>, кухня 2 — <b>kitchen2-chrome.bat</b>.</p><div class="actions"><button type="button" class="secondary" data-print-test>Пробный чек</button><button type="button" class="secondary" data-print-test-kitchen>Пробный кухонный чек</button></div></div>`;
    return `<section class="panel printer-panel"><h2>🖨 Чековые аппараты</h2><p class="fine">Включите на одном компьютере в кафе. Какие блюда на какую кухню — в «Блюдах и категориях» → карандаш у категории.</p>
      <label class="check-line"><input type="checkbox" id="printer-on" ${on?'checked':''}> Этот компьютер печатает чеки филиала «${esc(branchName())}»</label>
      <div class="print-groups" ${on?'':'hidden'}>
        <p class="fine">Как печатать:</p>
        <label class="check-line"><input type="radio" name="print-mode" value="agent" ${mode==='agent'?'checked':''}> Программа печати — одно окно, все три аппарата по IP (рекомендуется)</label>
        <label class="check-line"><input type="radio" name="print-mode" value="browser" ${mode==='browser'?'checked':''}> Через Chrome — один принтер на окно</label>
        ${agentBlock}${browserBlock}
        <p class="fine">Что печатать с этого компьютера:</p>${PRINT_GROUPS.map(([id,label])=>`<label class="check-line"><input type="checkbox" data-print-group="${id}" ${groups.includes(id)?'checked':''}> ${label}</label>`).join('')}
      </div></section>`;
  }



  // Четыре типа заказа: в кафе (зелёный), с собой (жёлтый), доставка (красный), самовывоз (оранжевый)
  const KIND_ICON={hall:'tables',takeaway:'bag',delivery:'truck',pickup:'store'};
  const KIND_NAME={hall:'В кафе',takeaway:'С собой',delivery:'Доставка',pickup:'Самовывоз'};
  function kindOf(o){return live?o.kind:o.type==='cafe'?'hall':o.type;}
  // Вызовы со столов видят официант и администрация (повару и курьеру они не нужны)
  function seesCalls(){return ['programmer','chef','admin','cashier','waiter'].includes(me?.role);}
  function canPay(){return ['programmer','chef','admin','waiter','cashier','courier'].includes(me?.role);}            // «К оплате» и «Оплатить»
  function homeView(){return me?.role==='cashier'?'cash':'orders';}                                         // кассир начинает с «Кассы»
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
      if(o.courier_comment)row('note',`Комментарий курьеру: ${esc(o.courier_comment)}`);
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
    return `<article class="order-card kind-${kind}" style="view-transition-name:order-${esc(String(o.id))}"><div class="order-top"><strong>№${o.number||o.id}</strong><span class="tag kind-tag">${icon(KIND_ICON[kind]||'tables')}${esc(title)}</span><small>${live?`${esc(clock(o.created_at))} · ${esc(o.status_label)}`:o.minutes+' мин'}</small></div>${kind==='takeaway'?'<p class="takeaway-mark">С СОБОЙ — упаковать</p>':''}${orderInfo(o)}<div class="order-items">${items.map(i=>`${esc(i.name)} × ${i.qty}`).join('<br>')}</div>${o.comment||o.note?`<p class="order-note">${esc(o.comment||o.note)}</p>`:''}<div class="order-bottom"><strong>${money(live?o.total:Store.orderTotal(o))}</strong><div class="actions${live&&o.status==='new'?' new-grid':''}">${actions.map(a=>`<button class="${a.needs_reason||a.action==='reject'?'danger':'primary'}" data-order="${o.id}" data-number="${o.number||o.id}" data-kind="${esc(kind)}" data-action="${esc(a.action)}" data-reason="${Boolean(a.needs_reason)}">${esc(a.label)}</button>`).join('')}${live&&o.status==='new'?`<button class="secondary ticket-btn" data-order-print="${o.id}" data-number="${o.number||o.id}" title="Напечатать чек заказа на чековом аппарате">🖨 Распечатать чек</button>`:''}</div></div></article>`;
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
    const catRow=c=>{const n=c.dishes_count||0,count=n?`${n} ${plural(n,'блюдо','блюда','блюд')}`:'Пусто';return `<li class="cat-row ${String(c.id)===menuFilter?'selected':''} ${c.is_active?'':'hidden-cat'}" data-cat-id="${c.id}"><button type="button" class="drag-handle" data-drag-cat aria-label="Перетащить «${esc(c.name)}»" title="Потяните, чтобы поменять порядок">${icon('grip')}</button><button type="button" class="cat-select" data-menu-filter="${c.id}"><strong>${esc(c.name)}</strong><small>${count}${c.is_active?'':' · скрыта от гостей'} · 🖨 ${({kitchen1:'кухня 1',kitchen2:'кухня 2',none:'не печатать'})[c.printer||'kitchen1']}</small></button>${toggle(`Видна гостям: ${c.name}`,c.is_active,`data-cat-visible="${c.id}"`)}<button type="button" class="icon-button" data-edit-category="${c.id}" aria-label="Переименовать «${esc(c.name)}»"></button><button type="button" class="danger icon-button" data-delete-category="${c.id}" aria-label="Удалить «${esc(c.name)}»" ${n?'disabled title="Сначала перенесите или удалите блюда"':''}></button></li>`;};
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
    $('#editor-content').innerHTML=`<form id="category-form">${field('Название','name',c.name,'text','maxlength="100" required')}<label class="check-line"><input type="checkbox" name="is_active" ${c.is_active?'checked':''}>Видна гостям</label><label class="field">Куда печатать после подтверждения<select name="printer">${CAT_PRINTERS.map(([v,l])=>`<option value="${v}" ${(c.printer||'kitchen1')===v?'selected':''}>${l}</option>`).join('')}</select></label><p class="fine">${c.dishes_count?`В категории ${c.dishes_count} ${plural(c.dishes_count,'блюдо','блюда','блюд')}. Удалить её можно, когда она станет пустой.`:'Категория пустая — её можно удалить.'}</p><p id="editor-error" class="error"></p><footer class="form-footer"><button class="primary" type="submit">Сохранить</button>${c.dishes_count?'':`<button type="button" class="danger" data-delete-category="${c.id}">Удалить</button>`}</footer></form>`;
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
    $('#editor-content').innerHTML=`<form id="dish-form"><div class="image-editor"><div id="image-preview">${image(d?.photo||d?.image)}</div><div class="photo-upload"><label class="upload-button">${icon('upload')}<span id="photo-button-label">${d?.photo||d?.image?'Заменить фото':'Добавить фото'}</span><input id="dish-photo" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Загрузить фото блюда" aria-describedby="photo-help photo-status"></label><small class="fine photo-file-name" id="photo-help">PNG, JPG, WebP · до 3,5 МБ</small><span id="photo-status" class="photo-status" role="status" aria-live="polite"></span></div></div>${field('Название','name',d?.name||'','text','required maxlength="100"')}<label>Описание<textarea name="description" maxlength="500">${esc(d?.description||'')}</textarea></label><label>Категория<select name="category">${cache.categories.map(c=>`<option value="${c.id}" ${(d?d.category===c.id:String(c.id)===menuFilter)?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label>${field('Основная цена, сом','price',live?(d?.price||0):(d?.prices[0]||0),'number','min="0" max="1000000" required step="1"')}<fieldset><legend>Размеры и цены</legend><div id="size-rows">${sizes.map(sizeRow).join('')}</div><button class="secondary" type="button" id="add-size">+ Добавить размер</button></fieldset>${live?`<fieldset><legend>Добавки</legend>${cache.extras.map(e=>`<label class="setting-line">${esc(e.name)} · ${money(e.price)}<input style="width:18px" name="extra" type="checkbox" value="${e.id}" ${d?.extras?.includes(e.id)?'checked':''}></label>`).join('')}</fieldset>`:''}<div class="setting-line">В наличии${toggle('В наличии',d?(live?d.is_available:d.available):true,'name="available"')}</div><p class="fine">${live?'Изменения сохраняются на сервере.':'Изменения сохраняются только в этом браузере.'}</p><p id="editor-error" class="error" role="alert"></p><footer class="form-footer"><button class="primary" type="submit">Сохранить</button>${d?`<button class="danger" type="button" data-delete-dish="${d.id}">Удалить</button>`:''}</footer></form>`;paintControls(editor);editor.showModal();
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
    const onFloor=f=>halls.filter(t=>(t.floor||1)===f).sort((a,b)=>(a.number||0)-(b.number||0));   // по номерам: «Стол 2» всегда между 1 и 3                                    // столы одного этажа
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
    return heading('Пользователи и роли',live?'Права проверяются сервером':'Демо-роли не предоставляют настоящий доступ',addButton)+`<div class="toolbar"><div class="pills">${filters.map(r=>pill(r==='all'?`Все · ${cache.users.length}`:roles[r],r,userFilter===r,'user-filter')).join('')}</div><input id="user-search" type="search" aria-label="Поиск пользователей" placeholder="Имя или логин" value="${esc(query)}"></div><div class="users-layout"><div class="data-wrap"><table class="data-table"><thead><tr><th>Пользователь</th><th>Роль</th><th class="category-col">Статус</th><th aria-label="Действия"></th></tr></thead><tbody>${users.map(u=>{const name=u.name||u.first_name||u.username,roleOptions=cache.roles.some(r=>r.value===u.role)?cache.roles:[{value:u.role,label:roles[u.role]},...cache.roles];return `<tr data-search="${esc(`${name} ${u.username||u.handle||''} ${u.email||''}`.toLowerCase())}"><td><div class="user-cell"><span class="avatar">${esc(name[0])}</span><div><strong>${esc(name)}</strong><small>@${esc(u.handle||u.username)}${u.email?' · '+esc(u.email):''}${live&&pinOn()&&!u.has_pin?' · <b class="no-pin">без кода</b>':''}</small></div></div></td><td><select class="role-select" data-role-user="${u.id}" aria-label="Роль: ${esc(name)}" ${(live?!u.can_edit||u.id===me.id:u.role==='owner')?'disabled':''}>${roleOptions.map(r=>`<option value="${r.value}" ${r.value===u.role?'selected':''}>${esc(r.label)}</option>`).join('')}</select></td><td class="category-col">${live?u.is_active?'Активен':'Отключён':u.role==='blocked'?'Отключён':'Активен'}</td><td>${live&&u.can_edit&&u.id!==me.id?`<div class="row-actions"><button class="icon-button" data-edit-staff="${u.id}" aria-label="Изменить: ${esc(name)}" title="Изменить сотрудника"></button><button class="icon-button danger" data-delete-staff="${u.id}" aria-label="Удалить: ${esc(name)}" title="Удалить сотрудника"></button></div>`:''}</td></tr>`;}).join('')||'<tr><td colspan="4" class="empty">Пользователи не найдены</td></tr>'}</tbody></table></div><aside class="panel"><h2>История смены ролей</h2>${cache.audit.slice().reverse().slice(0,20).map(a=>`<div class="audit-row"><strong>${esc(a.user_name||a.name)}</strong><br>${esc(a.old_role_display||roles[a.from])} → ${esc(a.new_role_display||roles[a.to])}<small>${esc(a.created_at||a.at)}</small></div>`).join('')||'<p class="fine">Пока нет изменений ролей</p>'}</aside></div>`;
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
      ${!pinOn()?'':field(u.has_pin?'Новый код входа':'Код входа — не задан!','pin','','text','inputmode="numeric" pattern="\\d{2,8}" maxlength="8" autocomplete="off" placeholder="'+(u.has_pin?'Не менять':'Только цифры')+'"')}
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
      phone:text('phone'),telegram_id:tg?Number(tg):null,is_active:v.has('is_active'),...(text('pin')?{pin:text('pin')}:{}),
    }});
    if(text('role')&&text('role')!==u?.role)await API.request(`/admin/staff/${editingId}/set-role/`,{method:'POST',body:{role:text('role')}});
    if(password)await API.request(`/admin/staff/${editingId}/set-password/`,{method:'POST',body:{password}});
    editor.close();toast(`Сотрудник «${text('first_name')||text('username')}» сохранён`);await render();
  }
  // Окно «Мой код входа»: каждый сам ставит себе 2 цифры (шефу код больше никто не поставит)
  function myPin(){
    $('#editor-title').textContent='Мой код входа';
    $('#editor-content').innerHTML=`<form id="pin-form">
      ${field('Новый код','pin','','password','inputmode="numeric" pattern="\\d{2,8}" maxlength="8" required autocomplete="new-password" placeholder="Только цифры"')}
      <p class="fine">Старый код перестанет работать. Код знаете только вы: его не видит никто, даже админ.</p>
      <p id="editor-error" class="error"></p>
      <footer class="form-footer"><button class="primary" type="submit">Сохранить</button></footer>
    </form>`;
    paintControls(editor);editor.showModal();
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
      ${!pinOn()?'':field('Код входа','pin','','text','inputmode="numeric" pattern="\\d{2,8}" maxlength="8" required autocomplete="off" placeholder="Только цифры"')}
      <div class="two-fields">${field('Пароль','password','','password','minlength="10" required autocomplete="new-password"')}${field('Повторите пароль','password2','','password','minlength="10" required autocomplete="new-password"')}</div>
      <p class="fine">${multiBranch()?`Сотрудник будет работать в филиале «${esc(branchName())}» (шеф — во всех). `:''}${pinOn()?'Код входа передайте сотруднику лично — потом его не увидит никто, даже вы. Логин и пароль нужны для Telegram-бота.':'Логин или email и пароль передайте сотруднику лично. Он сможет войти сразу.'}</p>
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
      telegram_id:tg?Number(tg):null,password:String(v.get('password')),pin:text('pin')
    }});
    editor.close();toast(`Сотрудник ${text('first_name')} добавлен`);await render();
  }
  // ===== Уведомления: раз в 10 секунд спрашиваем сервер, не появилось ли что-то новое =====
  // Официант (и админ): новый заказ, «Позвать официанта», «Попросить счёт», заказ готов.
  // Повар: заказ подтверждён официантом — пора готовить.
  let watchTimer=null,seen=null;
  const WATCH_EVERY=5000;                                       // 5 секунд: изменения из Telegram сразу видны и на сайте
  let lastVersion=null,lastFull=0,versionBusy=false;
  async function tick(){                                         // раз в 1,5 секунды: «что-то изменилось?» — крошечный запрос
    if(!live||versionBusy||document.hidden)return;versionBusy=true;
    try{const {v}=await API.request('/version/',{auth:false});
      if(v!==lastVersion||Date.now()-lastFull>WATCH_EVERY*4){lastVersion=v;lastFull=Date.now();await watch();}   // изменилось — обновляем сразу
    }catch{/* нет связи — попробуем через секунду */}finally{versionBusy=false;}
  }
  function startWatch(){stopWatch();if(!live)return;lastVersion=null;tick();watchTimer=setInterval(tick,1500);paintBell();}
  function stopWatch(){clearInterval(watchTimer);watchTimer=null;seen=null;MuslimNotify.title(0);}
  // Запоминаем, что сотрудник уже видел (чтобы не звенеть повторно)
  function remember(orders,calls){seen={orders:new Map(orders.map(o=>[o.id,o.status])),calls:new Set(calls.map(c=>c.id)),key:orders.map(o=>o.id+':'+o.status+':'+(o.claimed_by_name||'')+':'+(o.available_actions||[]).map(a=>a.action).join('.')).join(',')+'|'+calls.map(c=>c.id).join(',')};}   // «Беру стол» и кнопки — тоже изменение
  // Человек сейчас что-то вводит — не перерисовываем страницу у него под руками
  function typing(){const el=document.activeElement;return Boolean(el&&$('#content').contains(el)&&/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName));}
  async function watch(){
    if(!live)return;
    const role=me.role,isCook=role==='cook',isCourier=role==='courier',isBoss=['programmer','chef','admin','cashier'].includes(role);
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
    if(before&&(before.key!==seen.key||(view==='orders'&&orderTab==='pay')||view==='cash')&&['orders','tables','cash'].includes(view)&&!(view==='cash'&&cashTab==='waiters')&&!document.querySelector('dialog[open]')&&!typing()){if(view==='orders')cache.fresh={orders,calls};await render(true);}   // список сам обновился
  }
  // ===== Кнопка «Telegram» в верхней полосе: привязан ли Telegram (привязка — входом в боте), «Отвязать» =====
  function paintTelegram(){
    let b=$('#telegram-toggle');
    if(!b){b=document.createElement('button');b.type='button';b.id='telegram-toggle';$('#notify-toggle').before(b);}   // кнопка рядом со «Звук»
    b.hidden=!live;if($('#tg-chip'))$('#tg-chip').hidden=true;if(!live)return;   // метку «TG» покажем ниже, когда знаем, привязан ли
    const on=Boolean(me?.telegram_id);                                                  // уже привязан?
    b.innerHTML=icon('telegram')+`<span class="tg-long">${on?'Telegram ✓':'Telegram не привязан'}</span><span class="tg-short">${on?'TG ✓':'Telegram'}</span><span class="m-lbl">Telegram</span><em class="m-state">${on?'подключён':'не привязан'}</em>`;   // m-… — подписи для меню «⋯» на телефоне
    const chip=$('#tg-chip');if(chip){chip.hidden=false;chip.classList.toggle('linked',on);chip.innerHTML=icon('telegram')+`<span>${on?'TG':'TG ✕'}</span>`;chip.setAttribute('aria-label',b.getAttribute('aria-label')||'Telegram');}   // метка «TG» рядом с «⋯»
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
  async function paintPush(){const b=$('#push-toggle');if(!b||!window.MuslimPush)return;b.hidden=!live;if(!live)return;const on=await MuslimPush.active().catch(()=>false);b.innerHTML=`<span class="m-only">${icon('mobile')}</span><span class="d-lbl">${on?'📲 Push вкл':'📲 Push'}</span><span class="m-lbl">Push-уведомления</span><em class="m-state">${on?'вкл':''}</em>`;b.setAttribute('aria-pressed',String(on));}   // push на телефон
  function paintBell(){paintPush();const b=$('#notify-toggle');if(!b)return;b.hidden=!live;const on=MuslimNotify.enabled();b.setAttribute('aria-pressed',String(on));b.innerHTML=icon('bell')+`<span class="d-lbl">${on?'Звук вкл':'Звук выкл'}</span><span class="m-lbl">Звук заказов</span><em class="m-state">${on?'вкл':'выкл'}</em>`;b.classList.toggle('muted',!on);}
  function reportBranch(){return multiBranch()&&reportScope==='all'?'all':undefined;}   // «Оба филиала» — только у шефа
  async function reportsView(){
    const actions=`<button class="secondary" data-export-report>${live?'Скачать PDF':'Печать / PDF'}</button><button class="secondary" data-export-csv>${live?'JSON':'CSV'}</button>`;
    const top=heading('Отчёты',live?'':'Демонстрационные данные',actions)+`<div class="toolbar"><div class="pills">${pill('За день','day',reportPeriod==='day','report-period')}${!live||['chef','programmer','admin','cashier'].includes(me?.role)?pill('За 45 дней','period',reportPeriod==='period','report-period'):''}</div>${multiBranch()?`<div class="pills">${pill('Оба филиала',reportScope==='all'?'branch':'all',reportScope==='all','report-scope')}</div>`:''}${reportPeriod==='day'?`<input class="report-date" type="date" id="report-date" value="${reportDate}" max="${Store.today()}" aria-label="Дата отчёта">`:'<span class="fine">%RANGE%</span>'}</div>`;
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

    // 7. Официанты: на компьютере — таблица, на планшете и телефоне — карточки
    const W=r.waiters||[],minutes=m=>m==null?'—':`${String(m).replace('.',',')} мин`;
    const bestTag=(w,i)=>i===0&&W.length>1&&w.revenue?'<span class="best-tag">лучший</span>':'';
    const waitersBlock=`<section class="panel full waiters-panel"><h2>Официанты</h2>${W.length?`<table class="data-table waiters-table"><thead><tr><th>Официант</th><th>Заказы</th><th>Выручка</th><th>Ср. чек</th><th>Вызовы</th><th>Ответ на вызов</th><th>Доля</th></tr></thead><tbody>${W.map((w,i)=>`<tr><td><strong>${esc(w.name)}</strong>${bestTag(w,i)}</td><td>${w.orders}</td><td>${money(w.revenue)}</td><td>${money(w.avg_check)}</td><td>${w.calls}</td><td>${minutes(w.response_min)}</td><td><div class="progress"><span style="width:${w.share}%"></span></div></td></tr>`).join('')}</tbody></table>
      <div class="waiter-cards">${W.map((w,i)=>`<article class="waiter-card"><div class="split-line"><strong>${esc(w.name)}${bestTag(w,i)}</strong><strong>${money(w.revenue)}</strong></div><div class="progress"><span style="width:${w.share}%"></span></div><div class="split-line"><small>${w.orders} ${ordersWord(w.orders)} · ср. чек ${money(w.avg_check)}</small><small>${w.calls} вызов. · ${minutes(w.response_min)}</small></div></article>`).join('')}</div>`
      :`<p class="empty">Нет заказов в зале за ${isDay?'этот день':'этот период'}</p>`}</section>`;
    const S=r.shifts||[],signed=n=>n===0?'0 сом':`${n>0?'+':'−'} ${money(Math.abs(n))}`;
    const shiftsBlock=S.length?`<section class="panel full shifts-panel"><h2>Смены кассы</h2>${S.map(x=>`<article class="shift-row"><div><strong>${esc(x.cashier)}</strong><small class="fine"> · ${new Date(x.opened_at).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})} ${billTime(x.opened_at)}–${billTime(x.closed_at)}</small></div><span>Наличные ${money(x.cash)}</span><span>Карта ${money(x.card)}</span><span>Счетов ${x.orders}</span><strong class="${x.difference<0?'minus':''}">Разница ${signed(x.difference)}</strong></article>`).join('')}</section>`:'';
    const unpaid=r.unpaid?.count?`<p class="fine unpaid-note">Ещё не оплачено: ${r.unpaid.count} ${ordersWord(r.unpaid.count)} · ${money(r.unpaid.sum)}</p>`:'';

    // Раскладка рядами, без пустот: плитки → график во всю ширину → карточки одинаковой высоты → топ блюд → официанты → архив
    const cards=[split('Откуда выручка',r.by_kind),split('Оплата',r.by_payment).replace(/<\/section>$/,unpaid+'</section>'),reasons].filter(Boolean);
    return `<div class="report">${banner}${stats}${chart}<div class="report-cards cards-${cards.length}">${cards.join('')}</div>${topBlock}${waitersBlock}${shiftsBlock}${archiveBlock}</div>`;
  }
  async function settingsView(){
    const s=live?await API.request('/admin/cafe/'):state.settings;cache.settings=s;
    const get=(remote,local)=>live?s[remote]:s[local];
    const tabBar=live?tabs([['main','Главное'],['printers','🖨 Чековые аппараты']],settingsTab,'settings-tab'):'';
    if(live&&settingsTab==='printers')return heading('Настройки')+tabBar+printerPanel();                     // вкладка «Чековые аппараты»
    return heading('Настройки','',`<button class="primary" type="submit" form="settings-form">Сохранить</button>`)+tabBar+`<form id="settings-form"><div class="settings-grid"><section class="panel"><h2>Приём заказов</h2><div class="setting-line">Принимать заказы с сайта${toggle('Принимать заказы',get('is_accepting_orders','acceptOrders'),'name="acceptOrders"')}</div><div class="setting-line">Принимать доставку${toggle('Принимать доставку',get('is_delivery_enabled','acceptDelivery'),'name="acceptDelivery"')}</div><div class="two-fields">${field('Открываемся','opens',get('opens_at','opens')?.slice(0,5),'time','required')}${field('Закрываемся','closes',get('closes_at','closes')?.slice(0,5),'time','required')}</div></section><section class="panel"><h2>Доставка</h2><div class="three-fields">${field('Мин. сумма, сом','deliveryMin',get('delivery_min_sum','deliveryMin'),'number','min="0" max="1000000" required')}${field('Стоимость, сом','deliveryFee',get('delivery_fee','deliveryFee'),'number','min="0" max="1000000" required')}${field('Время, мин','deliveryTime',get('delivery_time','deliveryTime'),'text','maxlength="50" required')}</div>${field('Бесплатная доставка от, сом (0 — нет)','freeFrom',get('free_delivery_from','freeFrom'),'number','min="0" max="1000000" required')}</section><section class="panel"><h2>${multiBranch()?'Филиал и контакты':'Контакты кафе'}</h2>${multiBranch()?field('Название филиала','branchName',s.branch_name,'text','maxlength="60" required'):''}${field('Адрес','address',s.address,'text','maxlength="200"')}${field('Телефон','phone',s.phone,'tel','maxlength="30"')}</section><section class="panel"><h2>Telegram</h2><p class="fine">Telegram пока не подключён. Уведомления и отправка отчётов в группу будут доступны после подключения бота.</p><div class="setting-line">Отчёт в группу${toggle('Отчёт в Telegram',false,'disabled')}</div><p class="fine">Время работы и параметры доставки сохраняются ${live?'на сервере':'только в этом браузере'}.</p></section>${live?'':`<section class="panel"><h2>Ссылка меню для QR</h2>${field('Адрес гостевого меню','menuUrl',s.menuUrl,'url','required maxlength="400"')}<p class="fine">Для печати QR укажите опубликованный адрес сайта, доступный гостям.</p></section>`}</div><p id="settings-error" class="error" role="alert"></p></form>`;
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
    if(button.dataset.view){view=button.dataset.view;query='';if(view==='quick')qoReset();await render();return;}
    if(button.dataset.qo){await qoAct(button);return;}                       // «Заказ за гостя»
    if(button.id==='telegram-toggle'){await telegramDialog();return;}   // привязать / отвязать Telegram
    if(button.id==='telegram-check'){await telegramCheck();return;}     // проверить привязку
    if(button.id==='push-toggle'){button.disabled=true;try{const result=await MuslimPush.enable();toast(result==='ok'?'Push включены: уведомления будут приходить на этот телефон':result);}catch(error){toast(error.message);}finally{button.disabled=false;paintPush();}return;}
    if(button.id==='notify-toggle'){const on=!MuslimNotify.enabled();MuslimNotify.setEnabled(on);if(on){MuslimNotify.unlock();await MuslimNotify.askPermission();MuslimNotify.beep();}paintBell();toast(on?'Уведомления включены':'Уведомления выключены');return;}
    if(button.dataset.branch){if(String(button.dataset.branch)===String(currentBranch()?.id))return;API.setBranch(button.dataset.branch);cache={};menuFilter='all';tablesFloor='delivery';paintBranch();toast(`Филиал: ${branchName()}`);await render();startWatch();return;}   // другой филиал: всё панели — по нему
    if(button.hasAttribute('data-reload')){await render();return;}
    if(button.dataset.floorTab){tablesFloor=button.dataset.floorTab==='delivery'?'delivery':Number(button.dataset.floorTab);await render(true);return;}   // вкладка: доставка или этаж
    if(button.hasAttribute('data-add-category')){const form=$('#new-category');if(!form)return;form.hidden=false;form.querySelector('.error').textContent='';$('#new-cat-name').focus();return;}   // «+ Категория»: поле названия сверху списка
    if(button.hasAttribute('data-cancel-category')){const form=$('#new-category');form.reset();form.hidden=true;return;}
    if(button.dataset.bar){const out=$('#chart-readout');if(out)out.textContent=button.dataset.bar;document.querySelectorAll('.bar-group.picked').forEach(b=>b.classList.remove('picked'));button.classList.add('picked');return;}   // столбик графика
    if(button.hasAttribute('data-close')){button.closest('dialog').close();return;}
    if(button.dataset.orderFilter){orderFilter=button.dataset.orderFilter;await render();return;}
    if(button.dataset.orderTab){orderTab=button.dataset.orderTab;await render();return;}
    if(button.dataset.settingsTab){settingsTab=button.dataset.settingsTab;await render(true);return;}          // «Главное | Чековые аппараты»
    if(button.dataset.cashTab){cashTab=button.dataset.cashTab;await render(true);return;}                      // «Смена | К оплате | Официанты | История»
    if(button.dataset.wp!==undefined){await waitersAct(button);return;}                                        // «Официанты»: выплаты                       // «Активные | К оплате»
    if(button.hasAttribute('data-cash-open')){const v=$('#cash-start')?.value;if(await cashAction('/staff/cash/open/',{cash:Number(v||0)})){toast('Смена открыта');await render(true);}return;}
    if(button.dataset.cashMove){cashMoveDialog(button.dataset.cashMove);return;}
    if(button.dataset.cashMoveSave){const amount=Number($('#cash-amount').value||0);if(await cashAction('/staff/cash/move/',{kind:button.dataset.cashMoveSave,amount,comment:$('#cash-comment').value})){editor.close();toast(button.dataset.cashMoveSave==='in'?'Внесение записано':'Изъятие записано');await render(true);}return;}
    if(button.hasAttribute('data-cash-close')){cashCloseDialog();return;}
    if(button.dataset.shiftCopy){await API.request('/staff/cash/shift-copy/',{method:'POST',body:{id:Number(button.dataset.shiftCopy)}});button.closest('dialog')?.close();toast('Копия отчёта смены отправлена на чековый аппарат');return;}
    if(button.dataset.orderTicket){                                                     // чек «ЗАКАЗ» из карточки заказа
      const id=button.dataset.orderTicket,job=await API.request(`/staff/orders/${id}/ticket/`);
      showReceipt(`Чек заказа №${job.payload.number}`,`${esc(job.payload.type||'')} · ${esc(job.payload.place||'')}`,job,`data-order-print="${id}"`);return;}
    if(button.dataset.orderPrint){await API.request(`/staff/orders/${button.dataset.orderPrint}/print/`,{method:'POST'});toast(`Чек заказа${button.dataset.number?' №'+button.dataset.number:''} отправлен на чековый аппарат`);if(button.closest('dialog'))button.closest('dialog').close();return;}
    if(button.dataset.historyOpen){const h=cache.history?.[Number(button.dataset.historyOpen)];if(!h)return;                 // чек из «Истории оплат»
      if(!h.receipt){toast('Чек не загрузился: перезапустите сайт на сервере (sudo systemctl restart muslim).');return;}
      showReceipt(`Чек · ${h.title}`,`${billTime(h.paid_at)} · ${esc(h.method)}${h.by?` · принял(а) ${esc(h.by)}`:''}`,{kind:'receipt',payload:h.receipt},`data-receipt-copy="${button.dataset.historyOpen}"`);return;}
    if(button.dataset.receiptCopy){const h=cache.history?.[Number(button.dataset.receiptCopy)];if(!h)return;await API.request('/staff/cash/receipt-copy/',{method:'POST',body:{orders:h.orders}});toast('Копия чека отправлена на чековый аппарат');return;}
    if(button.hasAttribute('data-cash-close-save')){const v=$('#cash-counted').value;if(v===''){$('#cash-error').textContent='Посчитайте наличные и введите сумму.';return;}const r=await cashAction('/staff/cash/close/',{counted:Number(v)});if(r){editor.close();toast(`Смена закрыта · разница ${r.difference>=0?'+':'−'}${money(Math.abs(r.difference))}`);await render(true);}return;}
    if(button.dataset.billPrint){const bill=cache.bills?.[Number(button.dataset.billPrint)];if(!bill)return;      // «Счёт»: сначала показать, потом напечатать
      const job=await API.request('/staff/bills/preview/',{method:'POST',body:{orders:bill.orders}});
      showReceipt(`Счёт · ${bill.title}`,`${money(bill.total)} · ещё не оплачен`,job,`data-bill-print-send="${button.dataset.billPrint}"`);return;}
    if(button.dataset.billPrintSend){const bill=cache.bills?.[Number(button.dataset.billPrintSend)];if(!bill)return;
      await API.request('/staff/bills/print/',{method:'POST',body:{orders:bill.orders}});button.closest('dialog')?.close();toast('Счёт отправлен на чековый аппарат');return;}
    if(button.dataset.billPay){const bill=cache.bills?.[Number(button.dataset.billPay)];if(bill)openPay(bill);return;}
    if(button.dataset.payMethod&&payState){payState.method=button.dataset.payMethod;drawPay();return;}            // наличные / карта / наличные + карта
    if(button.hasAttribute('data-pay-quick')&&payState){                                                            // быстрые суммы: «Без сдачи», 600, 1 000, 5 000
      const input=$('#pay-form')?.elements.received;if(!input)return;
      const cashPart=payState.method==='mixed'?Number(payState.cash||0):payState.bill.total;              // сколько нужно наличными
      input.value=button.dataset.payQuick==='exact'?cashPart:button.dataset.payQuick;input.dispatchEvent(new Event('input',{bubbles:true}));
      document.querySelectorAll('[data-pay-quick]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));return;}
    if(button.dataset.agentTest){const config=Printer.get()||{};try{await agentSend(printSample(button.dataset.agentTest),{...config,mode:'agent'});toast('Пробный чек отправлен');}catch(error){toast(error.message==='Failed to fetch'?'Программа печати не запущена на этом компьютере':error.message);}agentAlive();return;}
    if(button.hasAttribute('data-agent-download')){const text=await (await fetch('muslim-print.bat',{cache:'no-store'})).text();download('muslim-print.bat',text.replace(/\r?\n/g,'\r\n'),'application/octet-stream');return;}   // CRLF — как любит Windows
    if(button.hasAttribute('data-print-test-kitchen')){await MuslimReceipt.print({kind:'kitchen1',payload:{number:0,place:'ПРОБНЫЙ ЧЕК',staff_role:'Кухня',waiter:'',date:new Date().toLocaleDateString('ru-RU'),time:new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),items:[{name:'Плов',extras:[],qty:2},{name:'Чай чёрный',extras:[],qty:1}],comment:''}});return;}
    if(button.hasAttribute('data-print-test')){await MuslimReceipt.print(MuslimReceipt.sample(branchName()));return;}   // пробный чек
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
    if(button.id==='add-size'){if($('#size-rows').children.length>=4){toast('Максимум четыре варианта размера');return;}$('#size-rows').insertAdjacentHTML('beforeend',sizeRow());syncBasePrice();return;}
    if(button.hasAttribute('data-remove-size')){button.closest('.sizes-row').remove();syncBasePrice();return;}
    if(button.dataset.deleteDish){const id=button.dataset.deleteDish,d=cache.dishes.find(d=>String(d.id)===id);confirm('Удалить блюдо?',`«${d.name}» будет удалено ${live?'с сервера':'из локального меню'}.`,async()=>{if(live){await API.request(`/admin/dishes/${id}/`,{method:'DELETE'});toast(`«${d.name}» удалено`);}else await localChange(s=>{s.menu.dishes=s.menu.dishes.filter(d=>d.id!==id);},'Блюдо удалено');editor.close();await render();});return;}
    if(button.dataset.order){const id=Number(button.dataset.order),action=button.dataset.action,label=button.textContent.trim(),number=button.dataset.number||id;
      const perform=async reason=>{if(live){const card=button.closest('.order-card');card?.classList.add('is-busy');card?.querySelectorAll('button').forEach(b=>b.disabled=true);let updated;try{updated=await API.orderAction(id,action,reason);}catch(error){card?.classList.remove('is-busy');card?.querySelectorAll('button').forEach(b=>b.disabled=false);throw error;}if(cache.orders&&updated){const rest=cache.orders.filter(o=>o.id!==updated.id);cache.fresh={orders:['completed','cancelled'].includes(updated.status)?rest:cache.orders.map(o=>o.id===updated.id?updated:o),calls:cache.calls||[]};}toast(`Заказ №${number}: ${({claim:'вы взяли его',accept:'подтверждён · чек заказа ушёл на чековый аппарат',reject:'отклонён',cancel:'отменён',cook:'готовится',ready:'готов',send:'в пути'})[action]||label.toLowerCase()}`,button.dataset.kind);}else await localChange(s=>Store.transition(s,id,action),'Статус обновлён');await render(true);};
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
  document.addEventListener('click',event=>{const row=event.target.closest('[data-shift-open]');if(!row)return;   // прошлая смена → её отчёт
    const x=cache.pastShifts?.[Number(row.dataset.shiftOpen)];if(!x)return;
    showReceipt(`Смена · ${new Date(x.opened_at).toLocaleDateString('ru-RU')}`,`${billTime(x.opened_at)}–${billTime(x.closed_at)} · открыл(а) ${esc(x.opened_by)} · закрыл(а) ${esc(x.closed_by)}`,{kind:'shift',payload:x.report},`data-shift-copy="${x.id}"`);});
  document.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.matches?.('[data-shift-open]'))event.target.click();});
  document.addEventListener('change',async event=>{const input=event.target;
    try{
      if(input.id==='report-date'){reportDate=input.value||Store.today();await render();}
      if(input.dataset.printerIp){const c=Printer.get()||{on:true,branch:API.branch()};c.ips={...(c.ips||{}),[input.dataset.printerIp]:input.value.trim()};Printer.set(c);toast('IP сохранён');}
      if(input.id==='print-page'){const c=Printer.get()||{on:true,branch:API.branch()};c.page=Number(input.value);Printer.set(c);toast('Кодировка сохранена');}
      if(input.name==='print-mode'){const c=Printer.get()||{on:true,branch:API.branch()};c.mode=input.value;Printer.set(c);await render(true);return;}
      if(input.dataset.printGroup){const c=Printer.get()||{on:true,branch:API.branch()};const g=new Set(c.groups||['cash','kitchen1','kitchen2']);input.checked?g.add(input.dataset.printGroup):g.delete(input.dataset.printGroup);c.groups=[...g];Printer.set(c);toast('Сохранено для этого окна');}
      if(input.id==='printer-on'){$('.print-groups')?.toggleAttribute('hidden',!input.checked);Printer.set(input.checked?{mode:'agent',ips:{...DEFAULT_IPS},page:17,...(Printer.get()||{}),on:true,branch:API.branch(),groups:Printer.get()?.groups||['cash','kitchen1','kitchen2']}:null);if(input.checked)agentAlive();toast(input.checked?'Чеки будут печататься на этом компьютере':'Печать чеков на этом компьютере выключена');}
      if(input.dataset.catVisible){input.disabled=true;await API.request(`/admin/categories/${input.dataset.catVisible}/`,{method:'PATCH',body:{is_active:input.checked}});toast(input.checked?'Категория снова видна гостям':'Категория скрыта от гостей');await render(true);return;}
      if(input.dataset.availability){const id=input.dataset.availability;input.disabled=true;if(live)await API.request(me.role==='cook'?`/admin/dishes/${id}/toggle-available/`:`/admin/dishes/${id}/`,{method:me.role==='cook'?'POST':'PATCH',body:me.role==='cook'?{}:{is_available:input.checked}});if(live){const d=cache.dishes.find(d=>String(d.id)===String(id));toast(`«${d?.name||'Блюдо'}» ${input.checked?'снова в наличии':'— нет в наличии'}`);}else await localChange(s=>{s.menu.dishes.find(d=>d.id===id).available=input.checked;},'Наличие обновлено');await render();}
      if(input.dataset.roleUser){const id=input.dataset.roleUser,role=input.value,u=cache.users.find(u=>String(u.id)===id);confirm('Изменить роль?',`${u.name||u.first_name||u.username}: ${roles[u.role]} → ${roles[role]}. ${live?'Права изменятся на сервере.':'Это локальный пример.'}`,async()=>{if(live)await API.request(`/admin/staff/${id}/set-role/`,{method:'POST',body:{role}});else await localChange(s=>{const u=s.users.find(u=>u.id===id);s.audit.push({name:u.name,from:u.role,to:role,at:new Date().toLocaleString('ru-RU')});u.role=role;},'Роль изменена');await render();});input.value=u.role;}
      if(input.id==='dish-photo'){const file=input.files[0];if(!file)return;$('#photo-status').textContent='';$('#photo-status').classList.remove('error');if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>3.5*1024*1024)throw new Error('Нужно фото PNG, JPG или WebP до 3,5 МБ.');uploadFile=file;input.disabled=true;input.closest('.upload-button').setAttribute('aria-busy','true');const url=URL.createObjectURL(file);try{const photo=new Image();photo.src=url;await photo.decode();const canvas=document.createElement('canvas'),scale=Math.min(1,700/Math.max(photo.width,photo.height));canvas.width=Math.round(photo.width*scale);canvas.height=Math.round(photo.height*scale);canvas.getContext('2d').drawImage(photo,0,0,canvas.width,canvas.height);editorImage=canvas.toDataURL('image/jpeg',.8);$('#image-preview').innerHTML=image(editorImage);$('#photo-button-label').textContent='Заменить фото';$('#photo-help').textContent=file.name;$('#photo-help').title=file.name;$('#photo-status').textContent='Фото готово. Нажмите «Сохранить», чтобы применить.';}finally{URL.revokeObjectURL(url);}}
    }catch(error){toast(error.message);if(input.dataset.availability)await render();if(input.id==='dish-photo'){input.value='';uploadFile=null;if($('#photo-status')){$('#photo-status').textContent=error.message;$('#photo-status').classList.add('error');}}}finally{input.disabled=false;if(input.id==='dish-photo')input.closest('.upload-button')?.removeAttribute('aria-busy');}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['dish-form','table-form','settings-form','reason-form','staff-form','staff-edit-form','pin-form'].includes(form.id)&&!['new-category','category-form'].includes(form.id))return;event.preventDefault();const submit=form.querySelector('[type=submit]')||form.querySelector('.primary');if(submit)submit.disabled=true;
    try{
      if(form.id==='dish-form')await saveDish(form);
      if(form.id==='staff-form')await saveStaff(form);   // новый сотрудник
      if(form.id==='staff-edit-form')await saveStaffEdit(form);   // «Изменить сотрудника»
      if(form.id==='pin-form'){const pin=String(new FormData(form).get('pin')||'').trim();await API.request('/auth/me/pin/',{method:'POST',body:{pin}});me.has_pin=true;editor.close();toast('Новый код сохранён');}
      if(form.id==='new-category'){const name=String(new FormData(form).get('name')).trim();await API.request('/admin/categories/',{method:'POST',body:{name}});toast(`Категория «${name}» добавлена`);await render(true);}   // новая категория — в конец списка
      if(form.id==='category-form'){const v=new FormData(form);await API.request(`/admin/categories/${editingId}/`,{method:'PATCH',body:{name:String(v.get('name')).trim(),is_active:v.has('is_active'),printer:v.get('printer')||'kitchen1'}});editor.close();toast('Категория сохранена');await render(true);}
      if(form.id==='table-form'&&!live){const values=new FormData(form),payload={name:String(values.get('name')).trim(),number:Number(values.get('number'))};if(!payload.name)throw new Error('Укажите название стола.');await localChange(s=>{if(s.tables.some(t=>t.number===payload.number&&t.number!==editingId))throw new Error('Стол с таким номером уже существует.');s.orders.forEach(o=>{if(o.table===editingId)o.table=payload.number;});s.tables=s.tables.filter(t=>t.number!==editingId);s.tables.push(payload);s.tables.sort((a,b)=>a.number-b.number);},'Стол сохранён');editor.close();await render();}
      if(form.id==='settings-form'){const values=new FormData(form),s={acceptOrders:values.has('acceptOrders'),acceptDelivery:values.has('acceptDelivery'),opens:String(values.get('opens')),closes:String(values.get('closes')),deliveryMin:Number(values.get('deliveryMin')),deliveryFee:Number(values.get('deliveryFee')),deliveryTime:String(values.get('deliveryTime')).trim(),freeFrom:Number(values.get('freeFrom')),address:String(values.get('address')).trim(),phone:String(values.get('phone')).trim()};if(live)await API.request('/admin/cafe/',{method:'PATCH',body:{is_accepting_orders:s.acceptOrders,is_delivery_enabled:s.acceptDelivery,opens_at:s.opens,closes_at:s.closes,delivery_min_sum:s.deliveryMin,delivery_fee:s.deliveryFee,delivery_time:s.deliveryTime,free_delivery_from:s.freeFrom,address:s.address,phone:s.phone,...(values.has('branchName')?{branch_name:String(values.get('branchName')).trim()}:{})}});if(live&&values.has('branchName')){me=await API.request('/auth/me/');paintBranch();}if(!live)await localChange(next=>Object.assign(next.settings,s,{menuUrl:String(values.get('menuUrl'))}),'Настройки сохранены');toast('Настройки сохранены');}
      if(form.id==='reason-form'){const reason=new FormData(form).get('reason').trim();if(!reason)throw new Error('Укажите причину отмены.');await cache.reasonHandler(reason);editor.close();}
    }catch(error){const target=form.querySelector('.error')||form.closest('dialog')?.querySelector('.error');if(target)target.textContent=error.message;else toast(error.message);}finally{if(submit)submit.disabled=false;}
  });
  $('#login-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;$('#login-error').textContent='';try{if(!API.enabled)throw new Error('Запустите локальную версию сайта для подключения к API.');const data=new FormData(form),tg=window.MuslimTG?.active,user=tg?await API.telegramLogin(MuslimTG.initData,String(data.get('username')).trim(),String(data.get('password'))):await API.login(String(data.get('username')).trim(),String(data.get('password')),data.has('remember'));/* в мини-приложении вход ещё и привязывает Telegram */form.reset();await enter(true,user);}catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}});
  function logout(){API.logout();try{sessionStorage.removeItem('muslim-demo-open');}catch{/* Нет сохранённой демо-сессии. */}location.hash='';showLogin();}
  $('#logout').addEventListener('click',logout);
  $('#my-pin').addEventListener('click',()=>{if(live)myPin();});
  $('#session-pin').addEventListener('click',()=>{if(live)myPin();});
  $('#pin-login').addEventListener('click',event=>{const key=event.target.closest('[data-pin]')?.dataset.pin;if(key)pinKey(key);});
  document.querySelectorAll('[data-pin-mode]').forEach(button=>button.addEventListener('click',()=>pinMode(button.dataset.pinMode==='pin')));
  document.addEventListener('keydown',event=>{                                                   // цифры с клавиатуры кассы тоже работают
    if($('#pin-login').hidden||$('#login-screen').hidden)return;
    if(/^\d$/.test(event.key))pinKey(event.key);else if(event.key==='Backspace')pinKey('del');else if(event.key==='Enter')pinKey('ok');
  });
  $('#session-logout').addEventListener('click',logout);
  // ===== Телефон: меню «⋯» в верхней полосе (Telegram, звук, Push, меню гостей, выход) =====
  const envBar=$('.environment'),envMore=$('#env-more');
  function envMenu(open){envBar.classList.toggle('open',open);envMore.setAttribute('aria-expanded',String(open));}   // открыть / закрыть список
  envMore.addEventListener('click',event=>{event.stopPropagation();envMenu(!envBar.classList.contains('open'));});
  document.addEventListener('click',event=>{if(envBar.classList.contains('open')&&!event.target.closest('#env-more'))setTimeout(()=>envMenu(false));},true);   // нажали пункт или мимо — закрываем (пункт при этом срабатывает)
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&envBar.classList.contains('open')){envMenu(false);envMore.focus();}});
  $('#tg-chip').addEventListener('click',()=>$('#telegram-toggle')?.click());   // метка «TG» — то же, что пункт «Telegram»
  window.addEventListener('muslim-session-expired',()=>{if(live)showLogin('Сессия истекла. Войдите повторно.');});
  window.addEventListener('muslim-api-result',()=>{if(view==='api'&&$('#api-results'))$('#api-results').innerHTML=resultRows();});
  $('#login-description').textContent=API.enabled?'Войдите по email или логину, который выдал администратор.':'Панель без базы данных. Вы можете проверить все разделы на демонстрационных данных.';
  if(!API.enabled){
    $('#login-form').hidden=true;
    $('#login-description').textContent='Сервер не подключён. Откройте панель с запущенным сервером, чтобы войти.';
    const localUrl=window.MUSLIM_CONFIG?.localAppUrl;
    if(localUrl){const link=document.createElement('a');link.className='primary local-api-link';link.href=new URL('/admin',localUrl).href;link.textContent='Открыть с API';$('#login-description').after(link);}
  }
  // ===== Демо-версия (только на своём компьютере: её включает frontend/server.cjs, на сервере nginx её не знает) =====
  const DEMO_STAFF=[['demo_chef','Шеф','Имрон · оба филиала, отчёты, настройки'],['demo_admin','Админ','Азамат · заказы, меню, столы, сотрудники'],
    ['demo_cook','Повар','Айбек · кухня и стоп-лист'],['demo_waiter','Официант','Бекзат · зал, столы, вызовы'],['demo_cashier','Кассир','Айжан · касса, смена, оплата'],['demo_courier','Курьер','Нурлан · доставки']];
  if(API.enabled&&window.MUSLIM_CONFIG?.demo){                       // демо-сайт: войти одной кнопкой за любую роль
    $('#login-form').hidden=true;
    $('#login-description').textContent='Демо-версия: настоящая панель с примером кафе — меню, столы, заказы и отчёты за месяц. Войдите за любую роль:';
    const box=document.createElement('div');box.className='demo-roles';
    box.innerHTML=DEMO_STAFF.map(([login,role,what])=>`<button type="button" class="demo-role" data-demo-login="${login}"><b>${role}</b><small>${what}</small></button>`).join('');
    $('#login-description').after(box);
    box.addEventListener('click',async event=>{const button=event.target.closest('[data-demo-login]');if(!button)return;box.querySelectorAll('button').forEach(b=>b.disabled=true);
      try{await enter(true,await API.login(button.dataset.demoLogin,'demo-muslim-2026',true));}catch(error){$('#login-error').textContent=error.message;}finally{box.querySelectorAll('button').forEach(b=>b.disabled=false);}});
    const bar=document.createElement('div');bar.className='demo-bar';bar.textContent='Демо-версия · пример кафе, настоящая база не затрагивается';document.body.prepend(bar);
  }
  else if(window.MUSLIM_CONFIG?.demoUrl&&!window.MuslimTG?.active){  // свой компьютер: кнопка «Открыть демо-версию» (демо запускается demo.bat)
    const demo=document.createElement('a');demo.className='secondary demo-open';demo.href=new URL('/admin',window.MUSLIM_CONFIG.demoUrl).href;demo.textContent='Открыть демо-версию';
    $('#login-form').after(demo);
  }
  if(codeOnly()&&!API.hasSession())pinMode(true);                   // сразу цифры: на сайте вход только по коду
  paintControls(document);
  // Вход сохранён — не показываем форму входа, пока сервер проверяет сессию (иначе она мелькает)
  // Мини-приложение Telegram: вход сам, по Telegram (пароль — только в первый раз, чтобы привязать Telegram к сотруднику)
  if(API.enabled&&window.MuslimTG?.active&&!API.hasSession()){
    $('#login-screen').hidden=true;
    API.telegramLogin(MuslimTG.initData).then(user=>enter(true,user)).catch(error=>{
      showLogin(error.data?.detail==='not_linked'?'Войдите один раз логином и паролем — дальше панель будет открываться сама, через Telegram.':error.message);
      const remember=$('#login-form').elements.remember;if(remember)remember.closest('label').hidden=true;   // в Telegram вход и так запоминается
    });
  }
  else if(API.enabled&&API.hasSession()){$('#login-screen').hidden=true;API.request('/auth/me/').then(user=>enter(true,user)).catch(error=>showLogin(error.message));}
})();
