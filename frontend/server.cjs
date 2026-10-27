const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, 'dist');
const mime = { '.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.svg':'image/svg+xml', '.woff2':'font/woff2', '.txt':'text/plain; charset=utf-8', '.png':'image/png', '.jpg':'image/jpeg', '.webp':'image/webp', '.ico':'image/x-icon' };
function createServer({apiOrigin=new URL(process.env.MUSLIM_API_ORIGIN || 'http://172.20.10.4:8000'),apiEnabled=process.env.MUSLIM_ENABLE_API!=='0'}={}) {
apiOrigin=new URL(apiOrigin);
if(!['http:','https:'].includes(apiOrigin.protocol)||apiOrigin.username||apiOrigin.password)throw new Error('MUSLIM_API_ORIGIN должен быть HTTP(S)-адресом без пароля.');
return http.createServer(async (req, res) => {
  let pathname;
  try { pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname); } catch { res.writeHead(400).end(); return; }
  if (pathname === '/runtime-config.js') {
    res.writeHead(200, {'Content-Type':'text/javascript; charset=utf-8','Cache-Control':'no-store'}).end('window.MUSLIM_CONFIG='+JSON.stringify({apiBase:apiEnabled?'/backend/api':null,apiOrigin:apiEnabled?apiOrigin.origin:null,apiDocs:apiOrigin.origin+'/api/docs/'})+';'); return;
  }
  if (pathname.startsWith('/backend/api/') || pathname.startsWith('/backend/media/')) {
    if(!apiEnabled){res.writeHead(503,{'Content-Type':'application/json'}).end(JSON.stringify({detail:'API отключён. Панель работает без базы данных.'}));return;}
    // Только два фиксированных пути к настроенному серверу. Не является открытым прокси.
    const requested = new URL(req.url,'http://localhost');
    const upstreamPath=requested.pathname.slice('/backend'.length);
    if (!upstreamPath.startsWith('/api/')&&!upstreamPath.startsWith('/media/')) { res.writeHead(400).end();return; }
    const target=new URL(upstreamPath+requested.search,apiOrigin);
    const headers={Accept:req.headers.accept||'application/json'};
    if (req.headers.authorization) headers.Authorization=req.headers.authorization;
    if (req.headers['content-type']) headers['Content-Type']=req.headers['content-type'];
    try {
      const chunks=[];let length=0;
      for await (const chunk of req) { length+=chunk.length; if(length>5*1024*1024){res.writeHead(413).end();return;} chunks.push(chunk); }
      const response=await fetch(target,{method:req.method,headers,body:['GET','HEAD'].includes(req.method)?undefined:Buffer.concat(chunks),redirect:'manual',signal:AbortSignal.timeout(20000)});
      if (response.status>=300&&response.status<400) { res.writeHead(502,{'Content-Type':'application/json'}).end(JSON.stringify({detail:'API вернул перенаправление. Проверьте путь запроса.'}));return; }
      res.writeHead(response.status,{'Content-Type':response.headers.get('content-type')||'application/octet-stream','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
      res.end(Buffer.from(await response.arrayBuffer()));
    } catch { res.writeHead(502,{'Content-Type':'application/json'}).end(JSON.stringify({detail:'Локальный API недоступен. Проверьте MUSLIM_API_ORIGIN и подключение к сети.'})); }
    return;
  }
  if (pathname==='/admin'||pathname==='/admin/') pathname='/admin.html';
  if (/^\/t\/[^/]+\/?$/.test(pathname)) { res.writeHead(302,{Location:'/?token='+encodeURIComponent(pathname.split('/')[2])}).end();return; }
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (error, data) => {
    if (error) { res.writeHead(404).end('Not found'); return; }
    res.writeHead(200, { 'Content-Type':mime[path.extname(file)] || 'application/octet-stream', 'X-Content-Type-Options':'nosniff', 'Cache-Control':'no-cache' }); res.end(data);   // no-cache: после замены файлов браузер берёт свежие
  });
});
}
module.exports={createServer};
if(require.main===module){
  const port=process.env.PORT===undefined?4174:Number(process.env.PORT);
  if(!Number.isInteger(port)||port<0||port>65535)throw new Error('PORT должен быть числом от 0 до 65535.');
  const server=createServer();
  server.listen(port,'127.0.0.1',()=>console.log(`Local: http://localhost:${server.address().port}\nAdmin: http://localhost:${server.address().port}/admin\nAPI: ${process.env.MUSLIM_ENABLE_API==='0'?'off':process.env.MUSLIM_API_ORIGIN||'http://172.20.10.4:8000'}`));
}