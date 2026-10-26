(() => {
  'use strict';
  const KEY = 'muslim-workspace-v1';
  const clone = value => JSON.parse(JSON.stringify(value));
  const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone:'Asia/Bishkek' }).format(new Date());
  const dayOffset = (day, offset) => { const date = new Date(`${day}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + offset); return date.toISOString().slice(0,10); };
  function seed() {
    const day = today();
    const orders = [
      { id:127, type:'cafe', table:4, status:'new', minutes:1, items:[{name:'Мясная 35 см',qty:1,price:890},{name:'Лимонад',qty:2,price:130}], note:'' },
      { id:126, type:'delivery', status:'new', minutes:3, items:[{name:'Маргарита 30 см',qty:2,price:550},{name:'Кола 0,5 л',qty:2,price:80}], fee:150, note:'Демонстрационная доставка' },
      { id:124, type:'cafe', table:7, status:'cooking', minutes:9, items:[{name:'Пепперони 30 см + сыр',qty:1,price:730},{name:'Куриная BBQ 25 см',qty:1,price:590},{name:'Кола 0,5 л',qty:2,price:80}], note:'Без лука' },
      { id:123, type:'cafe', table:2, status:'cooking', minutes:12, items:[{name:'Овощная 25 см',qty:1,price:480},{name:'Чай',qty:1,price:80}], note:'' },
      { id:122, type:'pickup', status:'cooking', minutes:14, items:[{name:'Пепперони 25 см',qty:1,price:550}], note:'С собой' },
      { id:125, type:'delivery', status:'ready', minutes:18, items:[{name:'Пепперони 30 см + сыр',qty:1,price:730},{name:'Куриная BBQ 25 см',qty:1,price:590},{name:'Кола 0,5 л',qty:2,price:80}], fee:150, note:'Демонстрационный заказ в пути' }
    ].map(order => ({...order, date:day}));
    const history = [];
    for (let n = 44; n >= 0; n--) {
      const date = dayOffset(day, -n);
      for (let i = 0; i < 12 + n % 7; i++) {
        const dish = window.MUSLIM_MENU.dishes[(n + i) % window.MUSLIM_MENU.dishes.length];
        history.push({id:`sample-${n}-${i}`,date,hour:10+i%13,type:i%3?'cafe':'delivery',payment:i%4?'cash':'card',status:i===0&&n%3===0?'cancelled':'completed',items:[{name:dish.name,qty:1+i%3,price:dish.prices[0]}],fee:i%3?0:150});
      }
    }
    return { version:1, menu:clone(window.MUSLIM_MENU), orders, history,
      tables:Array.from({length:12},(_,i)=>({number:i+1,name:`Стол ${i+1}`})),
      users:[{id:'owner',name:'Ибрагим',handle:'demo_owner',role:'owner'},{id:'admin',name:'Азамат',handle:'demo_admin',role:'admin'},{id:'manager',name:'Нурлан',handle:'demo_manager',role:'admin'},{id:'cook',name:'Айбек',handle:'demo_chef',role:'cook'},{id:'cook2',name:'Мирлан',handle:'demo_cook',role:'cook'},{id:'guest',name:'Бекзат',handle:'demo_guest',role:'user'},{id:'guest2',name:'Айгерим',handle:'demo_guest2',role:'user'}],
      audit:[],settings:{acceptOrders:true,acceptDelivery:true,opens:'10:00',closes:'23:00',deliveryMin:800,deliveryFee:150,deliveryTime:'40–60',freeFrom:3000,address:'',phone:'',reminder:3,dailyReport:true,menuUrl:new URL('./', location.href).origin + '/'} };
  }
  function validMenu(menu) {
    if (!menu || !Array.isArray(menu.categories) || !menu.categories.length || !Array.isArray(menu.dishes) || !Array.isArray(menu.extras)) return false;
    const text = (s, limit) => typeof s === 'string' && s.length <= limit;
    const id = s => typeof s === 'string' && /^[a-z0-9_-]{1,80}$/.test(s);
    if (!menu.categories.every(c => c && id(c.id) && text(c.name,80)) || new Set(menu.categories.map(c=>c.id)).size !== menu.categories.length) return false;
    if (!menu.extras.every(e => e && id(e.id) && text(e.name,80) && Number.isFinite(e.price) && e.price >= 0 && e.price <= 1000000) || new Set(menu.extras.map(e=>e.id)).size !== menu.extras.length) return false;
    return new Set(menu.dishes.map(d=>d?.id)).size === menu.dishes.length && menu.dishes.length <= 500 && menu.dishes.every(d => d && id(d.id) && text(d.name,100) && d.name.trim() && text(d.description,500) && menu.categories.some(c=>c.id===d.category) && Array.isArray(d.prices) && d.prices.length >= 1 && d.prices.length <= 3 && d.prices.every(p=>Number.isFinite(p)&&p>0&&p<=1000000) && typeof d.available === 'boolean' && (!d.sizes || (Array.isArray(d.sizes) && d.sizes.length===d.prices.length && d.sizes.every(s=>text(s,30)&&s.trim()))) && (!d.image || (text(d.image,900000) && /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(d.image))));
  }
  function validate(state) {
    if (!state || state.version!==1 || !validMenu(state.menu)) throw new Error('Не удалось прочитать каталог. Проверьте данные.');
    if (!Array.isArray(state.orders) || !Array.isArray(state.history) || !Array.isArray(state.tables) || !Array.isArray(state.users) || !Array.isArray(state.audit) || !state.settings) throw new Error('Некорректные данные панели.');
    if (state.tables.length>100 || !state.tables.every(t=>Number.isInteger(t.number)&&t.number>0&&t.number<=999&&typeof t.name==='string'&&t.name.length<=80) || new Set(state.tables.map(t=>t.number)).size!==state.tables.length) throw new Error('Проверьте номера столов.');
    if (!state.users.every(u=>u && typeof u.id==='string' && typeof u.name==='string' && typeof u.handle==='string' && ['owner','admin','chef','cook','waiter','user','blocked'].includes(u.role)) || state.users.filter(u=>u.role==='owner').length!==1) throw new Error('Проверьте роли пользователей.');
    if (![...state.orders,...state.history].every(o=>o && ['new','cooking','ready','completed','cancelled'].includes(o.status) && ['cafe','delivery','pickup'].includes(o.type) && /^\d{4}-\d{2}-\d{2}$/.test(o.date) && Array.isArray(o.items) && o.items.length && o.items.every(i=>typeof i.name==='string'&&Number.isFinite(i.price)&&i.price>0&&Number.isInteger(i.qty)&&i.qty>0) && (o.fee===undefined||(Number.isFinite(o.fee)&&o.fee>=0)))) throw new Error('Проверьте данные заказов.');
    for (const key of ['deliveryMin','deliveryFee','freeFrom','reminder']) if (!Number.isFinite(state.settings[key]) || state.settings[key]<0 || state.settings[key]>1000000) throw new Error('Проверьте числовые настройки.');
    if (!['opens','closes'].every(key=>/^([01]\d|2[0-3]):[0-5]\d$/.test(state.settings[key]))) throw new Error('Укажите время работы.');
    if (!['address','phone','deliveryTime','menuUrl'].every(key=>typeof state.settings[key]==='string'&&state.settings[key].length<500)) throw new Error('Проверьте настройки кафе.');
    const url = new URL(state.settings.menuUrl);
    if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw new Error('Для QR нужна ссылка http или https.');
    return state;
  }
  function load() {
    const raw = localStorage.getItem(KEY);
    return raw ? validate(JSON.parse(raw)) : seed();
  }
  function save(state) {
    validate(state);
    try { localStorage.setItem(KEY,JSON.stringify(state)); }
    catch { throw new Error('Не удалось сохранить: хранилище браузера недоступно или заполнено. Уменьшите фото и повторите.'); }
    window.dispatchEvent(new Event('muslim-store-change'));
  }
  function orderTotal(order) { return order.items.reduce((s,i)=>s+i.qty*i.price,0)+(order.fee||0); }
  function transition(state,id,next) {
    const order = state.orders.find(o=>o.id===id);
    const allowed={new:['cooking','cancelled'],cooking:['ready','cancelled'],ready:['completed','cancelled']};
    if (!order || !allowed[order.status]?.includes(next)) throw new Error('Этот переход статуса недоступен.');
    order.status=next;
    if (next==='completed'||next==='cancelled') { state.history.push({...order,date:today(),hour:new Date().getHours(),payment:'cash'}); state.orders=state.orders.filter(o=>o.id!==id); }
    return state;
  }
  window.MuslimStore = { KEY,seed,load,save,validMenu,validate,clone,today,dayOffset,orderTotal,transition };
})();
