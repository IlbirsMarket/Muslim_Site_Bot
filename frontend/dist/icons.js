(() => {
  'use strict';
  const paths = {
    orders:'<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M9 9h6M9 13h6M9 17h4"/>',
    menu:'<path d="M4 3v6a2 2 0 0 0 4 0V3M6 3v18M20 21V3c-4 2-5 6-5 10h5"/>',
    tables:'<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><path d="M15 15h3v3h3v3h-6v-3M21 12v3M12 3v3M3 12h3M12 12h3M12 18v3"/>',
    users:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M21 21v-3a6 6 0 0 0-3-5"/>',
    reports:'<path d="M4 3v18h17M9 17v-5M14 17V7M19 17v-8"/>',
    settings:'<path d="m9 3-1 3-3 .5-2 3 2 2v2l-2 2 2 3 3 .5 1 3h6l1-3 3-.5 2-3-2-2v-2l2-2-2-3-3-.5-1-3Z"/><circle cx="12" cy="12" r="3"/>',
    api:'<path d="m8 5-7 7 7 7M16 5l7 7-7 7M14 3l-4 18"/>',
    edit:'<path d="m14 5 5 5M4 20l5-1L21 7a2.1 2.1 0 0 0-4-4L5 15l-1 5Z"/>',
    trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    close:'<path d="m6 6 12 12M18 6 6 18"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    refresh:'<path d="M20 11a8 8 0 0 0-14-5L3 9M3 3v6h6M4 13a8 8 0 0 0 14 5l3-3M21 21v-6h-6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    checked:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    save:'<path d="M4 3h13l4 4v14H3V3h1ZM7 3v6h9V3M7 21v-8h10v8"/>',
    download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    print:'<path d="M7 7V3h10v4M7 17H4V8h16v9h-3M7 14h10v7H7ZM17 11h.01"/>',
    upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L6 21"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    logout:'<path d="M9 4H4v16h5M14 8l4 4-4 4M8 12h13"/>',
    external:'<path d="M14 3h7v7M21 3 10 14M10 3H3v18h18v-7"/>',
    bag:'<path d="M6 8h12l-1 12H7L6 8z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
    grip:'<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
    store:'<path d="M4 10h16v10H4zM3 10l2-6h14l2 6M10 20v-5h4v5"/>',
    bell:'<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    back:'<path d="m12 5-7 7 7 7M5 12h15"/>',
    file:'<path d="M14 3H5v18h14V8l-5-5ZM14 3v5h5M8 13h8M8 17h6"/>',
    chef:'<path d="M7 15a4 4 0 0 1-3-7 4 4 0 0 1 6-4 4 4 0 0 1 6 0 4 4 0 0 1 4 7 4 4 0 0 1-3 4M7 14v7h10v-7M7 17h10"/>',
    truck:'<path d="M3 5h12v12H3ZM15 9h4l3 4v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>'
  };
  function render(name) {
    return `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[name] || paths.image}</svg>`;
  }
  window.MuslimIcons = { render };
})();