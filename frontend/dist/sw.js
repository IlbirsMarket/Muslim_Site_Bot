// Сервис-воркер «Муслим»: показывает push-уведомления на телефоне (сайт на экране «Домой»).
// Уведомление приходит пустым — текст забираем с сервера (/backend/api/push/inbox/).
self.addEventListener('install',()=>self.skipWaiting());                       // новая версия — сразу
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('push',event=>{
  event.waitUntil((async()=>{
    let items=[];
    try{
      const sub=await self.registration.pushManager.getSubscription();         // наш адрес подписки — пропуск к «ящику»
      const response=await fetch('/backend/api/push/inbox/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:sub?sub.endpoint:''})});
      items=(await response.json()).items||[];
    }catch(error){/* нет сети — покажем общее уведомление */}
    if(!items.length)items=[{title:'Муслим',body:'Есть новости по заказам',url:'/'}];
    for(const item of items){
      await self.registration.showNotification(item.title||'Муслим',{body:item.body||'',icon:'/assets/icon-192.png',badge:'/assets/icon-192.png',data:{url:item.url||'/'},tag:(item.title||'')+(item.body||''),renotify:true});
    }
  })());
});
self.addEventListener('notificationclick',event=>{                                // нажали — открываем сайт или панель
  event.notification.close();
  const url=new URL(event.notification.data?.url||'/',self.location.origin).href;
  event.waitUntil((async()=>{
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    for(const client of windows){if(client.url.startsWith(url)&&'focus' in client)return client.focus();}
    return self.clients.openWindow(url);
  })());
});
