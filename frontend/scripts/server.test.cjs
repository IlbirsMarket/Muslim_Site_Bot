const {test}=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const {createServer}=require('../server.cjs');
async function listen(server){await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));return 'http://127.0.0.1:'+server.address().port;}
async function close(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
test('local proxy forwards JSON, JWT and multipart bodies to fixed API paths',async t=>{
  const upstream=http.createServer(async(req,res)=>{const chunks=[];for await(const chunk of req)chunks.push(chunk);res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({path:req.url,authorization:req.headers.authorization,body:Buffer.concat(chunks).toString(),type:req.headers['content-type']}));});
  const origin=await listen(upstream),server=createServer({apiOrigin:origin}),local=await listen(server);t.after(async()=>{await close(server);await close(upstream);});
  const config=await(await fetch(local+'/runtime-config.js')).text();assert.match(config,/"apiBase":"\/backend\/api"/);
  const data=await(await fetch(local+'/backend/api/admin/dishes/?search=test',{method:'POST',headers:{Authorization:'Bearer test-token','Content-Type':'application/json'},body:JSON.stringify({name:'Тест'})})).json();assert.equal(data.path,'/api/admin/dishes/?search=test');assert.equal(data.authorization,'Bearer test-token');assert.equal(JSON.parse(data.body).name,'Тест');
  const form=new FormData();form.append('photo',new Blob(['photo'],{type:'image/png'}),'photo.png');const upload=await(await fetch(local+'/backend/api/admin/dishes/1/',{method:'PATCH',body:form})).json();assert.match(upload.type,/multipart\/form-data; boundary=/);assert.match(upload.body,/photo.png/);
  assert.equal((await fetch(local+'/backend/private/')).status,404);
});
test('offline API returns explicit 502; demo mode performs no forwarding',async t=>{const server=createServer({apiOrigin:'http://127.0.0.1:1'}),local=await listen(server);t.after(()=>close(server));const r=await fetch(local+'/backend/api/menu/');assert.equal(r.status,502);assert.match((await r.json()).detail,/недоступен/);const demo=createServer({apiEnabled:false}),url=await listen(demo);t.after(()=>close(demo));assert.equal((await fetch(url+'/backend/api/menu/')).status,503);assert.match(await(await fetch(url+'/runtime-config.js')).text(),/"apiBase":null/);});
