// Push-уведомления: регистрация сервис-воркера и подписка телефона (общая часть сайта гостя и панели)
(function(){
  const supported=()=>'serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
  const isIOS=()=>/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  const standalone=()=>window.matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
  function keyBytes(base64){const pad='='.repeat((4-base64.length%4)%4);const raw=atob((base64+pad).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from([...raw].map(c=>c.charCodeAt(0)));}
  async function registration(){if(!supported())return null;try{return await navigator.serviceWorker.register('/sw.js',{scope:'/'});}catch{return null;}}
  // Включить уведомления. extra — {device_key} для гостя; сотрудник определяется по входу. Возвращает текст для показа.
  async function enable(extra={}){
    if(isIOS()&&!standalone())return 'На iPhone: «Поделиться» → «На экран Домой», откройте сайт с экрана «Домой» и нажмите ещё раз.';
    if(!supported())return 'Этот браузер не умеет push-уведомления.';
    const {key}=await window.MuslimAPI.request('/push/key/',{auth:false});
    if(!key)return 'Уведомления пока не настроены на сервере.';
    const permission=await Notification.requestPermission();
    if(permission!=='granted')return 'Уведомления запрещены в настройках телефона.';
    const reg=await registration();if(!reg)return 'Не удалось включить уведомления.';
    await navigator.serviceWorker.ready;
    const sub=(await reg.pushManager.getSubscription())||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(key)});
    await window.MuslimAPI.request('/push/subscribe/',{method:'POST',auth:!extra.device_key,body:{endpoint:sub.endpoint,...extra}});
    return 'ok';
  }
  async function active(){if(!supported()||Notification.permission!=='granted')return false;const reg=await navigator.serviceWorker.getRegistration('/');return !!(reg&&await reg.pushManager.getSubscription());}
  if(supported())registration();                                        // сервис-воркер нужен заранее (для уведомлений)
  window.MuslimPush={enable,active,supported,isIOS,standalone};
})();
