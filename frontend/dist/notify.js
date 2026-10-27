// Уведомления админ-панели: звук, вибрация, всплывающее окно системы и счётчик во вкладке браузера.
// Что именно считать «новым» (заказ, вызов, заказ на кухню), решает admin.js — здесь только «как сообщить».
(() => {
  'use strict';
  const KEY = 'muslim-notify-sound';          // где запоминаем «звук вкл/выкл» (в этом браузере)
  const baseTitle = document.title;           // исходное название вкладки
  let audio = null;                           // звуковой движок браузера (создаём после первого нажатия)

  // Включены ли уведомления. По умолчанию — да
  function enabled() { try { return localStorage.getItem(KEY) !== 'off'; } catch { return true; } }
  function setEnabled(on) { try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* Настройка живёт до перезагрузки. */ } }

  // Браузер разрешает звук только после того, как человек хоть раз нажал на страницу
  function unlock() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === 'suspended') audio.resume();
    } catch { /* Звук в этом браузере недоступен. */ }
  }

  // Короткий сигнал «дзинь-дзинь» из двух нот (без звуковых файлов)
  function beep() {
    if (!enabled() || !audio) return;
    const start = audio.currentTime;
    [[880, 0], [1175, 0.18]].forEach(([frequency, delay]) => {
      const tone = audio.createOscillator(), volume = audio.createGain();
      tone.type = 'sine';
      tone.frequency.value = frequency;                                         // высота ноты
      volume.gain.setValueAtTime(0.0001, start + delay);                        // плавно включаем
      volume.gain.exponentialRampToValueAtTime(0.35, start + delay + 0.02);
      volume.gain.exponentialRampToValueAtTime(0.0001, start + delay + 0.16);   // и плавно гасим
      tone.connect(volume).connect(audio.destination);
      tone.start(start + delay);
      tone.stop(start + delay + 0.18);
    });
  }

  // Системные уведомления работают только на https или localhost
  function canSystem() { return 'Notification' in window && window.isSecureContext; }
  async function askPermission() {
    if (canSystem() && Notification.permission === 'default') {
      try { await Notification.requestPermission(); } catch { /* Пользователь закрыл запрос. */ }
    }
  }
  // Окно системы показываем, только когда вкладка свёрнута: на открытой странице хватает звука и подсказки
  function system(text) {
    if (!enabled() || !canSystem() || Notification.permission !== 'granted' || !document.hidden) return;
    try {
      const note = new Notification('Муслим', { body: text, icon: 'assets/logo-mark.png' });
      note.onclick = () => { window.focus(); note.close(); };                   // нажали — открываем панель
    } catch { /* На некоторых телефонах так нельзя — остаётся звук. */ }
  }

  // Счётчик в названии вкладки: «(3) Муслим — Админ-панель»
  function title(count) { document.title = count ? `(${count}) ${baseTitle}` : baseTitle; }

  // Сообщить о событиях: звук + вибрация (телефон) + окно системы
  function alert(messages) {
    beep();
    if (enabled() && navigator.vibrate) { try { navigator.vibrate([200, 100, 200]); } catch { /* Нет вибрации. */ } }
    system(messages.join('\n'));
  }

  document.addEventListener('pointerdown', unlock, { passive: true });          // первое нажатие разрешает звук
  document.addEventListener('keydown', unlock);

  window.MuslimNotify = { enabled, setEnabled, askPermission, alert, beep, title, canSystem, unlock };
})();