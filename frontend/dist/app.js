(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const money = value => `${new Intl.NumberFormat('ru-RU').format(value)} сом`;
  const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[char]);
  const API=window.MuslimAPI,live=API.enabled;
  let cafe=null,tableInfo=null;
  const tableToken=new URLSearchParams(location.search).get('token');
  let viewOnly=live&&(!tableToken||new URLSearchParams(location.search).get('view')==='menu');   // без QR или после «Освободить стол» — только меню
  let freedAt0=null;                                                              // когда стол освобождали до того, как гость открыл QR
  const cartKey=live?'muslim-api-cart-v1':'muslim-cart-v1';
  const maxQty=live?50:99;
  const storage = {
    read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
    write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } }
  };
  // ===== Филиал: по QR — филиал этого QR (выбора нет). Без QR — последний филиал гостя, сверху переключатель (только посмотреть меню) =====
  const branchKey='muslim-guest-branch';
  let guestBranch=storage.read(branchKey,null),branches=[];
  { const asked=Number(new URLSearchParams(location.search).get('branch'));   // ссылка «Меню гостей» из панели: ./?branch=2
    if(!tableToken&&Number.isInteger(asked)&&asked>0){guestBranch=asked;storage.write(branchKey,asked);} }
  function branchQuery(){                                                        // какое меню и какие настройки просить у сервера
    if(tableToken&&!viewOnly)return `?token=${encodeURIComponent(tableToken)}`;
    return guestBranch?`?branch=${encodeURIComponent(guestBranch)}`:'';
  }
  function rememberBranch(id){if(id){guestBranch=id;storage.write(branchKey,id);}}   // запомнили, откуда гость пришёл
  async function loadBranches(){                                                 // список филиалов для переключателя
    try{branches=await API.request('/branches/',{auth:false});}catch{branches=[];}
    if(!Array.isArray(branches))branches=[];
    if(guestBranch&&!branches.some(b=>b.id===guestBranch))guestBranch=null;      // филиал выключили — показываем первый
  }
  function paintBranches(){                                                      // «Филиал 1 / Филиал 2» над меню
    let box=$('#branch-switch');
    if(!live||!viewOnly||branches.length<2){box?.remove();return;}
    if(!box){box=document.createElement('div');box.id='branch-switch';box.className='branch-pill';box.setAttribute('role','group');box.setAttribute('aria-label','Филиал');$('.header-actions').before(box);}   // в зелёной шапке — один выбор на весь сайт
    const current=guestBranch||branches[0].id;
    box.innerHTML=branches.map(b=>`<button type="button" data-guest-branch="${b.id}" aria-pressed="${b.id===current}" ${b.address?`title="${escape(b.address)}"`:''}>${escape(b.name)}</button>`).join('');
  }
  const MenuRepository = { async load() { return live?API.normalizeMenu(await API.request('/menu/'+branchQuery(),{auth:false})):window.MuslimStore.load().menu; } };
  let menu, category = 'pizza', mode = 'cafe', cart = [], selection, lastOrder = '';
  let toastTimer;
  const table = new URLSearchParams(location.search).get('table');
  const tableNumber = table && /^\d{1,3}$/.test(table) && Number(table) > 0 ? Number(table) : null;
  if (tableNumber) $('#table-label').textContent = `Стол №${tableNumber}`;
  if (live && viewOnly) $('#table-label').textContent = 'Меню';                     // без QR — просто меню

  function art(type) {
    const path = type === 'drinks' ? '<path d="M7 8h10l-1 13H8L7 8ZM13 8l2-6h4M6 8h12"/>' : '<path d="M12 3 3 20h18L12 3Z"/><path d="M5 17h14"/><circle cx="12" cy="9" r="1"/><circle cx="9" cy="14" r="1"/><circle cx="15" cy="14" r="1"/>';
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
  }
  function toast(message) {
    $('#toast').textContent = message;
    $('#toast').classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 2800);
  }
  function unitPrice(item) {
    const dish = menu.dishes.find(d => d.id === item.id);
    return dish.prices[item.size] + item.extras.reduce((sum, id) => sum + menu.extras.find(e => e.id === id).price, 0);
  }
  const total = () => cart.reduce((sum, item) => sum + unitPrice(item) * item.qty, 0);
  function itemNote(item) {
    const dish = menu.dishes.find(d => d.id === item.id);
    const parts = dish.sizes ? [dish.sizes[item.size]] : dish.category === 'pizza' ? [`${[25,30,35][item.size]} см`] : [];
    item.extras.forEach(id => parts.push(`+ ${menu.extras.find(e => e.id === id).name}`));
    if (item.comment) parts.push(item.comment);
    return parts.join(' · ');
  }
  function saveCart() {
    if (!storage.write(cartKey, { cart, mode, comment: $('#order-comment').value })) toast('Браузер не сохранил корзину. Не закрывайте страницу.');
  }
  function renderCategories() {
    $('#categories').innerHTML = menu.categories.map(c => `<button class="category" data-category="${c.id}" aria-pressed="${category === c.id}"><span>${escape(c.name)}</span><span>${menu.dishes.filter(d => d.category === c.id).length}</span></button>`).join('');
  }
  function renderMenu() {
    const query = $('#search').value.trim().toLocaleLowerCase('ru');
    const current = menu.categories.find(c => c.id === category);
    const dishes = menu.dishes.filter(d => query ? `${d.name} ${d.description}`.toLocaleLowerCase('ru').includes(query) : d.category === category);
    $('#category-title').textContent = query ? 'Результаты поиска' : current?.name||'Меню';
    $('#category-description').textContent = `${dishes.length} ${dishes.length === 1 ? 'блюдо' : dishes.length > 1 && dishes.length < 5 ? 'блюда' : 'блюд'}${!query && current?.note ? ` · ${current.note}` : ''}`;
    $('#products').innerHTML = dishes.map(d => `<article class="product${d.available ? '' : ' unavailable'}"><button class="product-art" data-dish="${d.id}" aria-label="Подробнее: ${escape(d.name)}">${dishArt(d)}${d.badge ? `<span class="badge">${escape(d.badge)}</span>` : ''}</button><div class="product-body"><h3>${escape(d.name)}</h3><p>${escape(d.description)}</p><div class="product-footer"><span class="price">${d.prices.length>1 ? 'от ' : ''}${money(d.prices[0])}</span>${d.available ? `<button class="choose" data-dish="${d.id}">Выбрать</button>` : '<span class="stopped">Нет в наличии</span>'}</div></div></article>`).join('');
    $('#empty').hidden = dishes.length > 0;
    $('#empty').innerHTML = query ? '<strong>Ничего не нашлось</strong>Попробуйте другое название или ингредиент.' : '<strong>Скоро здесь будет вкусно</strong>Блюда этой категории пока не добавлены.<br>Посмотрите пиццы и напитки.';
    renderCategories();
  }
  function renderCart() {
    $('#cart-items').innerHTML = cart.length ? cart.map((item, i) => {
      const dish = menu.dishes.find(d => d.id === item.id);
      return `<article class="cart-row"><h3>${escape(dish.name)}</h3><p>${escape(itemNote(item))}</p><div class="cart-row-bottom"><div class="stepper"><button data-cart-index="${i}" data-delta="-1" aria-label="Уменьшить: ${escape(dish.name)}">−</button><span>${item.qty}</span><button data-cart-index="${i}" data-delta="1" aria-label="Увеличить: ${escape(dish.name)}" ${item.qty >= maxQty ? 'disabled' : ''}>+</button></div><strong>${money(unitPrice(item) * item.qty)}</strong></div></article>`;
    }).join('') : `<div class="cart-empty">${art('drinks')}<strong>Здесь будет ваш заказ</strong><p>Выберите что-нибудь вкусное<br>из нашего меню</p></div>`;
    $('#total').textContent = $('#mobile-total').textContent = money(total());
    $('#cart-count').textContent = cart.reduce((n, i) => n + i.qty, 0);
    $('#checkout').disabled = !cart.length;
    $('#order-comment').parentElement.hidden = !cart.length;
    document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', button.dataset.mode === mode));
  }
  function showDish(id) {
    const dish = menu.dishes.find(d => d.id === id);
    selection = { id, size: 0, extras: [], qty: 1, comment: '' };
    const variants=dish.sizes||(dish.category==='pizza'?dish.prices.map((_,i)=>`${[25,30,35][i]} см`):[]);
    const extras=menu.extras.filter(e=>dish.extraIds?dish.extraIds.includes(e.id):dish.category==='pizza');
    $('#dish-content').innerHTML = `<div class="dish-layout"><div class="dish-art">${dishArt(dish)}</div><div class="dish-details"><h2 id="dish-title">${escape(dish.name)}</h2><p>${escape(dish.description)}</p>${variants.length?`<fieldset><legend>Размер</legend><div class="sizes">${dish.prices.map((p,i)=>`<label class="option"><input type="radio" name="size" value="${i}" ${i===0?'checked':''}><strong>${escape(variants[i])}</strong><span>${money(p)}</span></label>`).join('')}</div></fieldset>`:''}${extras.length?`<fieldset><legend>Добавки</legend>${extras.map(e=>`<label class="extra"><input type="checkbox" name="extra" value="${e.id}">${escape(e.name)}<span>+${money(e.price)}</span></label>`).join('')}</fieldset>`:''}<label class="field">Комментарий<input id="dish-comment" maxlength="200" placeholder="Например: без лука"></label><div class="dish-actions"><div class="stepper"><button data-dish-delta="-1" aria-label="Уменьшить количество">−</button><span id="dish-qty">1</span><button data-dish-delta="1" aria-label="Увеличить количество">+</button></div><button class="primary" id="add-dish" ${dish.available ? '' : 'disabled'}>${dish.available ? `Добавить · ${money(unitPrice(selection))}` : 'Нет в наличии'}</button></div></div></div>`;
    $('#dish-dialog').showModal();
  }
  function updateSelection() {
    selection.size = Number($('input[name="size"]:checked')?.value || 0);
    selection.extras = [...document.querySelectorAll('input[name="extra"]:checked')].map(input => input.value);
    $('#dish-qty').textContent = selection.qty;
    if (menu.dishes.find(d => d.id === selection.id).available) $('#add-dish').textContent = `Добавить · ${money(unitPrice(selection) * selection.qty)}`;
  }
  function openCheckout() {
    if (!cart.length) return;
    if(viewOnly){toast('Стол освобождён. Чтобы заказать, отсканируйте QR-код на столе.');return;}
    if(live&&!tableInfo){toast('Откройте меню по QR стола или доставки из админ-панели.');return;}
    if(live&&cafe&&!cafe.is_open){toast('Сейчас кафе не принимает заказы.');return;}
    if(live&&mode==='delivery'&&cafe&&!cafe.is_delivery_enabled){toast('Доставка сейчас отключена.');return;}
    if(live&&mode==='delivery'&&cafe&&total()<cafe.delivery_min_sum){toast(`Минимальная сумма доставки: ${money(cafe.delivery_min_sum)}`);return;}
    $('#checkout-title').textContent = ({ cafe:'Ваш заказ в кафе', takeaway:'С собой', delivery:'Доставка', pickup:'Самовывоз' })[mode];
    const noContacts = live ? !['delivery','pickup'].includes(mode) : mode === 'cafe';   // за столом (в кафе и с собой) имя и телефон не нужны
    $('#customer-fields').hidden = noContacts;
    $('#address-fields').hidden = mode !== 'delivery';
    const form = $('#checkout-form');
    if(live){$('#checkout-dialog .info').textContent='Проверьте заказ. Кафе подтвердит его и сверит наличие блюд.';form.querySelector('[type=submit]').textContent='Отправить заказ';}
    form.elements.customer.required = !noContacts;
    form.elements.phone.required = !noContacts;
    form.elements.address.required = mode === 'delivery';
    // Скрытые поля не участвуют в проверке и не включаются в список.
    [...form.elements].forEach(input => { if (input.name) input.disabled = input.name!=='payment' && (noContacts || (['address','apartment','entrance','floor','courierNote'].includes(input.name) && mode !== 'delivery')); });
    $('#checkout-summary').innerHTML = cart.map(item => `<div class="summary-line"><span>${escape(menu.dishes.find(d => d.id === item.id).name)} × ${item.qty}<br><small>${escape(itemNote(item))}</small></span><strong>${money(unitPrice(item) * item.qty)}</strong></div>`).join('') + (mode === 'delivery' ? `<div class="summary-line"><span>Стоимость доставки</span><span>${live?money(deliveryFee()):'Уточняется в кафе'}</span></div>` : '') + `<div class="summary-line summary-total"><strong>${live?'Итого':'Блюда на сумму'}</strong><strong>${money(total()+(live?deliveryFee():0))}</strong></div>`;
    $('#checkout-dialog').showModal();
  }
  document.addEventListener('click', async event => {
    const branchButton=event.target.closest('[data-guest-branch]');
    if(branchButton){                                                   // гость смотрит меню другого филиала
      const id=Number(branchButton.dataset.guestBranch);if(id===(guestBranch||branches[0]?.id))return;
      rememberBranch(id);paintBranches();
      try{[menu,cafe]=await Promise.all([MenuRepository.load(),API.request('/cafe/'+branchQuery(),{auth:false})]);}catch(error){toast(error.message);return;}
      category=menu.categories[0]?.id||'';renderMenu();renderCart();window.scrollTo({top:0,behavior:'smooth'});
      return;
    }
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (button.hasAttribute('data-close')) { button.closest('dialog').close(); return; }
    if (button.dataset.category) { category = button.dataset.category; $('#search').value = ''; renderMenu(); return; }
    if (button.dataset.dish) { showDish(button.dataset.dish); return; }
    if (button.dataset.cartIndex !== undefined) {
      const i = Number(button.dataset.cartIndex); cart[i].qty += Number(button.dataset.delta);
      if (cart[i].qty <= 0) cart.splice(i, 1);
      renderCart(); saveCart(); return;
    }
    if (button.dataset.dishDelta) { selection.qty = Math.max(1, Math.min(maxQty, selection.qty + Number(button.dataset.dishDelta))); updateSelection(); return; }
    if (button.dataset.mode) { if(!allowedModes().includes(button.dataset.mode)){toast(tableInfo?.kind==='hall'?'Доставка и самовывоз — на главной странице сайта.':'«В кафе» и «С собой» — по QR-коду на столе.');return;}mode = button.dataset.mode; renderCart(); saveCart(); return; }
    if (button.dataset.service) {
      if(live){if(!tableToken||tableInfo?.kind!=='hall'){toast('Для вызова официанта нужен QR стола.');return;}button.disabled=true;try{await API.request('/table-calls/',{method:'POST',auth:false,body:{table_token:tableToken,kind:button.dataset.service==='waiter'?'waiter':'bill'}});toast('Запрос передан сотруднику кафе');}catch(error){toast(error.message);}finally{button.disabled=false;}return;}
      $('#service-title').textContent = button.dataset.service === 'waiter' ? 'Позвать официанта' : 'Попросить счёт';
      $('#service-dialog').showModal(); return;
    }
    if (button.id === 'add-dish') {
      selection.comment = $('#dish-comment').value.trim();
      const existing = cart.find(i => i.id === selection.id && i.size === selection.size && i.comment === selection.comment && JSON.stringify(i.extras) === JSON.stringify(selection.extras));
      if (existing && existing.qty + selection.qty > maxQty) { toast(`Максимум ${maxQty} одинаковых блюд`); return; }
      if (existing) existing.qty += selection.qty; else cart.push({ ...selection });
      renderCart(); saveCart(); $('#dish-dialog').close(); toast('Добавлено в ваш заказ');
    }
  });
  $('#search').addEventListener('input', renderMenu);
  $('#dish-dialog').addEventListener('change', updateSelection);
  $('#order-comment').addEventListener('input', saveCart);
  $('#checkout').addEventListener('click', openCheckout);
  $('#open-cart').addEventListener('click', () => { $('#cart').classList.add('is-open'); $('#close-cart').focus(); });
  $('#close-cart').addEventListener('click', () => { $('#cart').classList.remove('is-open'); $('#open-cart').focus(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#cart').classList.remove('is-open'); });
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
    if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); }
  }));
  $('#checkout-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!cart.length) return;
    const values = new FormData(event.currentTarget);
    const phone = String(values.get('phone') || '');
    const needPhone = live ? ['delivery','pickup'].includes(mode) : mode !== 'cafe';   // телефон нужен для доставки и самовывоза (за столом — нет)
    if (needPhone && (phone.replace(/\D/g, '').length < 9 || phone.replace(/\D/g, '').length > 15)) {
      event.currentTarget.elements.phone.setCustomValidity('Укажите телефон: от 9 до 15 цифр.'); event.currentTarget.elements.phone.reportValidity(); return;
    }
    if(live){
      const button=event.currentTarget.querySelector('[type=submit]');if(button.disabled)return;button.disabled=true;
      $('#checkout-api-error')?.remove();
      try{
        const payload=API.orderPayload({menu,cart,tableToken,deviceKey:deviceKey(),mode,fields:Object.fromEntries(values),comment:$('#order-comment').value.trim()});
        const order=await API.request('/orders/',{method:'POST',auth:false,body:payload});
        // Корзина очищается только после подтверждённого ответа сервера.
        cart=[];$('#order-comment').value='';saveCart();renderCart();$('#checkout-dialog').close();showOrder(order);   // корзина и комментарий очищены
        rememberOrder(order);renderMyOrders();                                                                         // заказ сразу появляется в «Мои заказы»
      }catch(error){const message=document.createElement('p');message.id='checkout-api-error';message.className='info';message.setAttribute('role','alert');message.textContent=error.message;button.before(message);}finally{button.disabled=false;}
      return;
    }
    const lines = ['МУСЛИМ · СПИСОК ЗАКАЗА', 'Не отправлен в кафе', '', ({cafe:'В кафе',takeaway:'С собой',delivery:'Доставка',pickup:'Самовывоз'})[mode] + (mode === 'cafe' && tableNumber ? ` · Стол №${tableNumber}` : ''), ''];
    cart.forEach(item => { lines.push(`${menu.dishes.find(d => d.id === item.id).name} × ${item.qty} — ${money(unitPrice(item)*item.qty)}`); if (itemNote(item)) lines.push(`  ${itemNote(item)}`); });
    lines.push('', `Блюда на сумму: ${money(total())}`);
    if (mode === 'delivery') lines.push('Стоимость доставки уточняется в кафе.');
    if ($('#order-comment').value.trim()) lines.push(`Комментарий: ${$('#order-comment').value.trim()}`);
    const labels = {customer:'Имя',phone:'Телефон',address:'Адрес',apartment:'Квартира',entrance:'Подъезд',floor:'Этаж',courierNote:'Комментарий курьеру',payment:'Оплата'};
    for (const [key, value] of values) if (String(value).trim()) lines.push(`${labels[key]}: ${key === 'payment' ? (value === 'card' ? 'Картой при получении' : 'Наличными') : String(value).trim()}`);
    lastOrder = lines.join('\n');
    $('#saved-summary').textContent = lastOrder;
    $('#checkout-dialog').close(); $('#saved-dialog').showModal();
  });
  $('#checkout-form').elements.phone.addEventListener('input', event => event.target.setCustomValidity(''));
  $('#copy-order').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(lastOrder); $('#copy-order').textContent = 'Скопировано ✓'; setTimeout(() => $('#copy-order').textContent = 'Скопировать список', 2000); }
    catch { $('#copy-order').textContent = 'Скачайте список кнопкой ниже'; }
  });
  $('#download-order').addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([lastOrder], {type:'text/plain;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'Муслим — список заказа.txt'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  async function start() {
    if(live&&viewOnly)await loadBranches();                               // без QR — нужен список филиалов
    menu = await MenuRepository.load();
    if(!menu.categories.some(c=>c.id===category))category=menu.categories[0]?.id||'';
    if(live){
      cafe=await API.request('/cafe/'+branchQuery(),{auth:false});
      $('#menu-note').textContent='Цены актуальные. Итог заказа кафе подтвердит после отправки.';
      $('.draft-note').textContent='Заказ сразу увидят в кафе.';
      // Есть токен — это QR стола. Нет токена — главная страница = QR доставки
      if(viewOnly){enterViewOnly(false,new URLSearchParams(location.search).get('view')==='menu'?'freed':'plain');}   // только меню
      else if(tableToken){try{tableInfo=await API.request(`/tables/${encodeURIComponent(tableToken)}/`,{auth:false});freedAt0=tableInfo.freed_at||null;rememberBranch(tableInfo.branch);$('#table-label').textContent=tableInfo.kind==='hall'?(tableInfo.name||`Стол №${tableInfo.number}`):'Доставка';}catch(error){$('#table-label').textContent='QR устарел';toast('Этот QR больше не работает. Попросите у официанта новый.');}}
      applyModes();
      if(tableInfo?.kind==='hall'&&!$('#guest-services')){
        const services=document.createElement('div');services.id='guest-services';services.className='guest-services';services.innerHTML='<button type="button" class="secondary" data-service="waiter">Позвать официанта</button><button type="button" class="secondary" data-service="bill">Попросить счёт</button>';$('.welcome').after(services);
        if(tableInfo.telegram_url){const tg=document.createElement('a');tg.className='tg-order';tg.href=tableInfo.telegram_url;tg.target='_blank';tg.rel='noopener';tg.textContent='Заказать в Telegram';services.after(tg);}   // бот откроется сразу с этим столом
      }
      renderMyOrders();                                                   // «Мои заказы» с этого телефона
    }
    const saved = storage.read(cartKey, {});
    if (Array.isArray(saved.cart)) cart = saved.cart.filter(validItem);
    if (['cafe','takeaway','delivery','pickup'].includes(saved.mode)) mode = saved.mode;
    if (!allowedModes().includes(mode)) mode = allowedModes()[0];        // со стола — «в кафе», с главной — «доставка»
    applyModes();
    if (typeof saved.comment === 'string') $('#order-comment').value = saved.comment.slice(0,500);
    renderMenu(); renderCart();
  }
  // Позиция корзины ещё можно заказать: блюдо есть и в наличии, размер и добавки существуют
  function validItem(item) {
    if (!item || typeof item !== 'object') return false;
    const dish = menu.dishes.find(d => d.id === item.id && d.available);
    return Boolean(dish) && Number.isInteger(item.size) && item.size >= 0 && item.size < dish.prices.length && Number.isInteger(item.qty) && item.qty > 0 && item.qty <= maxQty && typeof item.comment === 'string' && item.comment.length <= 200 && Array.isArray(item.extras) && new Set(item.extras).size === item.extras.length && item.extras.every(id => menu.extras.some(e => e.id === id)&&(dish.extraIds?dish.extraIds.includes(id):dish.category==='pizza'));
  }
  // ===== Меню само обновляется: раз в 30 секунд и когда гость возвращается во вкладку =====
  // Страница НЕ перезагружается: открытые окна (блюдо, оформление) остаются, меняется только список блюд под ними.
  async function refreshMenu() {
    if (!live || !menu || document.hidden) return;                     // вкладка свёрнута — не тратим интернет гостя
    let next;
    try { [next, cafe] = await Promise.all([MenuRepository.load(), API.request('/cafe/'+branchQuery(), { auth:false })]); } catch { return; }   // нет связи — попробуем позже
    if (JSON.stringify(next) === JSON.stringify(menu)) return;          // ничего не поменялось
    menu = next;
    if (!menu.categories.some(c => c.id === category)) category = menu.categories[0]?.id || '';
    // Блюда, которые закончились (стоп-лист) или пропали из меню, убираем из корзины и говорим об этом гостю
    const removed = cart.filter(item => !validItem(item));
    if (removed.length) {
      const names = [...new Set(removed.map(item => (next.dishes.find(d => d.id === item.id) || {}).name).filter(Boolean))];
      cart = cart.filter(validItem); saveCart(); renderCart();
      toast(names.length ? `Закончилось: ${names.join(', ')}. Убрали из вашего заказа.` : 'Меню обновилось, часть заказа убрана.');
      if ($('#checkout-dialog').open) { $('#checkout-dialog').close(); if (cart.length) openCheckout(); }   // показываем заказ уже без этих блюд
    } else renderCart();                                                 // цены могли измениться — пересчитываем итог
    // Открыто окно блюда, которое закончилось, — закрываем его
    if ($('#dish-dialog').open && selection && !menu.dishes.some(d => d.id === selection.id && d.available)) { $('#dish-dialog').close(); toast('Это блюдо только что закончилось.'); }
    renderMenu();
  }
  setInterval(()=>{refreshMenu();checkTable();if(!document.hidden)renderMyOrders();}, 30000);   // меню, стол и статусы — раз в 30 секунд
  document.addEventListener('visibilitychange', () => { if (!document.hidden){refreshMenu();checkTable();renderMyOrders();} });
  // Какие способы можно выбрать: со стола — «В кафе» и «С собой», с главной страницы — «Доставка» и «Самовывоз»
  function allowedModes(){return !live?['cafe','delivery','pickup']:tableInfo?.kind==='hall'?['cafe','takeaway']:['delivery','pickup'];}
  function applyModes(){
    if(live&&!tableInfo)return;                                          // QR не найден — ничего не меняем
    const allowed=allowedModes();
    document.querySelectorAll('#order-modes [data-mode]').forEach(button=>{button.hidden=!allowed.includes(button.dataset.mode);});
    if(live&&tableInfo.kind!=='hall')document.querySelectorAll('[data-service]').forEach(button=>{button.hidden=true;});   // «Позвать официанта» — только за столом
  }
  function deliveryFee(){return mode==='delivery'&&cafe?cafe.free_delivery_from>0&&total()>=cafe.free_delivery_from?0:cafe.delivery_fee:0;}
  // Случайный ключ телефона. crypto.randomUUID есть только на https, поэтому на http (сайт по IP) собираем ключ сами
  function randomKey(){if(crypto.randomUUID)return crypto.randomUUID();const bytes=crypto.getRandomValues(new Uint8Array(16));return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
  function deviceKey(){let value=storage.read('muslim-device-key',null);if(typeof value!=='string'){value=randomKey();storage.write('muslim-device-key',value);}return value;}
  function dishArt(dish){
    if(dish.image&&/^(https?:|data:image\/(png|jpeg|webp);base64,)/.test(dish.image)){let url=dish.image;try{const parsed=new URL(url);if(live&&parsed.pathname.startsWith('/media/'))url='/backend'+parsed.pathname;}catch{/* Локальное фото. */}return `<img src="${escape(url)}" alt="" loading="lazy">`;}
    return art(dish.category);
  }
  // Окно заказа у гостя: номер, статус, состав, история. Отменён — видна причина
  function showOrder(order){
    let dialog=$('#order-status-dialog');if(!dialog){dialog=document.createElement('dialog');dialog.id='order-status-dialog';document.body.append(dialog);}
    const place=order.kind==='hall'||order.kind==='takeaway'?`${order.table_name||''}${order.kind==='takeaway'?' · с собой':''}`:order.kind_display;
    const cancelled=order.status==='cancelled';
    const time=iso=>{try{return new Date(iso).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});}catch{return '';}};
    dialog.innerHTML=`<button class="icon-button dialog-close" data-close aria-label="Закрыть">×</button><div class="checkout-body"><span class="eyebrow">Ваш заказ · ${escape(place)}</span><h2>Заказ №${order.number}</h2><p class="info order-state${cancelled?' cancelled':''}">${escape(order.status_label)}${cancelled&&order.cancel_reason?`<br><small>Причина: ${escape(order.cancel_reason)}</small>`:''}</p>${order.items.map(i=>`<div class="summary-line"><span>${escape(i.dish_name)} ${escape(i.size_name)} × ${i.quantity}</span><strong>${money(i.line_total)}</strong></div>`).join('')}${order.delivery_fee?`<div class="summary-line"><span>Доставка</span><strong>${money(order.delivery_fee)}</strong></div>`:''}<div class="total"><span>Итого</span><strong>${money(order.total)}</strong></div><div class="order-timeline">${(order.timeline||[]).map(t=>`<p><span>${escape(t.label)}</span><span>${escape(t.at?time(t.at):'')}</span></p>`).join('')}</div><button class="primary" id="refresh-order-status">Обновить статус</button><p id="order-status-error" class="info" hidden></p></div>`;
    $('#refresh-order-status').onclick=async()=>{const button=$('#refresh-order-status');button.disabled=true;try{const next=await API.request(`/orders/${encodeURIComponent(order.public_id)}/`,{auth:false});dialog.close();showOrder(next);renderMyOrders();}catch(error){$('#order-status-error').hidden=false;$('#order-status-error').textContent=error.message;}finally{button.disabled=false;}};
    if(!dialog.open)dialog.showModal();
  }
  // ===== «Мои заказы»: последние заказы с этого телефона (до 5 штук за сутки) =====
  const ORDERS_KEY='muslim-my-orders';
  function myOrders(){
    let list=storage.read(ORDERS_KEY,null);
    if(!Array.isArray(list)){                                             // переносим старую «последнюю» запись
      const old=storage.read('muslim-last-order',null);
      list=typeof old==='string'?[{id:old,at:Date.now()}]:[];
    }
    const dayAgo=Date.now()-24*3600e3;
    return list.filter(o=>o&&typeof o.id==='string'&&/^[0-9a-f-]{36}$/i.test(o.id)&&o.at>dayAgo).slice(0,5);
  }
  function rememberOrder(order){storage.write(ORDERS_KEY,[{id:order.public_id,at:Date.now()},...myOrders().filter(o=>o.id!==order.public_id)].slice(0,5));}
  let myOrdersBusy=false;
  async function renderMyOrders(){
    if(!live||myOrdersBusy)return;
    const list=myOrders();let box=$('#my-orders');
    if(!list.length){box?.remove();if(viewOnly)$('#open-cart').hidden=true;return;}
    if(!box){box=document.createElement('div');box.id='my-orders';box.className='my-orders';$('.cart-bottom').append(box);}
    myOrdersBusy=true;
    try{
      const orders=(await Promise.all(list.map(o=>API.request(`/orders/${encodeURIComponent(o.id)}/`,{auth:false}).catch(()=>null)))).filter(Boolean);
      cache.myOrders=orders;
      box.innerHTML=`<h3>Мои заказы</h3>${orders.map((o,i)=>`<button type="button" class="my-order status-${escape(o.status)}" data-my-order="${i}"><span>№${o.number} · ${money(o.total)}</span><strong>${escape(o.status_label)}</strong></button>`).join('')}`;
      if(viewOnly)$('#open-cart').hidden=false;                         // на телефоне кнопка внизу открывает «Мои заказы»
    }finally{myOrdersBusy=false;}
  }
  const cache={myOrders:[]};
  document.addEventListener('click',event=>{const b=event.target.closest('[data-my-order]');if(b){const order=cache.myOrders[Number(b.dataset.myOrder)];if(order)showOrder(order);}});
  // ===== Стол освободили: гость остаётся в меню, но заказать как «Стол N» уже не может =====
  // Меню без заказа. reason='freed' — стол освободили (надпись «Стол освобождён»); 'plain' — сайт открыли без QR
  function enterViewOnly(announce=true,reason='freed'){
    viewOnly=true;tableInfo=null;cart=[];saveCart();
    if(reason==='freed'){try{history.replaceState(null,'','./?view=menu');}catch{/* Адрес не поменялся — не страшно. */}}   // перезагрузка не вернёт стол
    document.body.classList.add('view-only');
    $('#table-label').textContent='Меню';
    $('#cart h2').textContent='Мои заказы';
    let note=$('#view-only-note');
    if(!note){note=document.createElement('div');note.id='view-only-note';note.className='view-only-note';note.innerHTML=reason==='freed'?'<strong>Стол освобождён</strong>Меню можно смотреть. Чтобы заказать снова, отсканируйте QR-код на столе.':'<strong>Меню кафе «Муслим»</strong>Чтобы заказать, отсканируйте QR-код на столе или QR доставки.';$('.welcome').after(note);}
    document.querySelectorAll('dialog[open]').forEach(d=>{if(d.id!=='order-status-dialog')d.close();});
    if(branches.length)paintBranches();else if(live)loadBranches().then(paintBranches);   // переключатель филиалов (только посмотреть)
    if(menu)renderCart();
    $('#open-cart').hidden=!myOrders().length;                            // на телефоне кнопка внизу — «Мои заказы»
    if(announce)toast('Стол освобождён. Чтобы заказать снова, отсканируйте QR-код на столе.');
    renderMyOrders();
  }
  async function checkTable(){                                            // раз в 30 секунд: не освободили ли стол
    if(!live||viewOnly||!tableToken||tableInfo?.kind!=='hall')return;
    try{const info=await API.request(`/tables/${encodeURIComponent(tableToken)}/`,{auth:false});if((info.freed_at||null)!==freedAt0)enterViewOnly();}
    catch(error){if(error.status===404)enterViewOnly();}                   // QR удалили или перевыпустили
  }

  window.addEventListener('storage',event=>{if(!live&&event.key===window.MuslimStore.KEY){document.querySelectorAll('dialog[open]').forEach(d=>d.close());start().catch(error=>toast(error.message));}});
  document.addEventListener('error',event=>{if(event.target.tagName==='IMG'){event.target.hidden=true;}},true);
  function menuLoadError(error){$('#products').innerHTML='';$('#categories').innerHTML='';$('#empty').hidden=false;$('#empty').textContent=error.message;const retry=document.createElement('button');retry.className='secondary';retry.textContent='Повторить загрузку';retry.onclick=()=>{retry.disabled=true;start().then(()=>$('#empty').hidden=menu.dishes.length>0).catch(menuLoadError);};$('#empty').append(document.createElement('br'),retry);}
  start().catch(menuLoadError);
})();
