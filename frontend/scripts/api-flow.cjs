const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const origin=process.env.MUSLIM_API_ORIGIN||'http://172.20.10.4:8000';
let input='';
process.stdout.write('Ready for test credentials on stdin (hidden).\n');
if(process.stdin.isTTY)process.stdin.setRawMode(true);
process.stdin.setEncoding('utf8');
process.stdin.on('data',async chunk=>{if(chunk.includes('\u0003'))process.exit(130);input+=chunk;if(!/[\r\n]/.test(input))return;process.stdin.pause();if(process.stdin.isTTY)process.stdin.setRawMode(false);try{await run(JSON.parse(input.trim()));process.exit(0);}catch(error){console.error(error.message);process.exit(1);}});
async function run({password}){
  const sessions={},results=[],owned={},stamp=Date.now(),marker=`SITE-TEST-${stamp}`;
  const log=(entry)=>{results.push(entry);console.log(JSON.stringify(entry));};
  async function call(role,url,{method='GET',body,expect=[200,201,204],binary=false}={}){
    const headers={Accept:binary?'*/*':'application/json'};if(role)headers.Authorization='Bearer '+sessions[role];if(body!==undefined)headers['Content-Type']='application/json';
    const r=await fetch(origin+'/api'+url,{method,headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
    const safePath=url.replace(/\/tables\/[^/]+\//,'/tables/{id-or-token}/').replace(/\/orders\/[0-9a-f-]{36}\//,'/orders/{public_id}/');
    log({role:role||'guest',method,path:safePath,status:r.status,expected:expect.includes(r.status)});
    let data=null;if(r.status!==204){if(binary&&r.ok)data=Buffer.from(await r.arrayBuffer());else if(r.headers.get('content-type')?.includes('json'))data=await r.json();else data={detail:'Ответ не в формате JSON'};}
    if(!expect.includes(r.status))throw new Error(`${method} ${safePath}: HTTP ${r.status} ${JSON.stringify(data).slice(0,700)}`);
    return data;
  }
  try{
    for(const role of ['chef','admin','cook','waiter']){
      const r=await fetch(origin+'/api/auth/login/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:role+'1',password}),signal:AbortSignal.timeout(15000)});
      if(!r.ok)throw new Error(`Вход ${role}: ${r.status}`);sessions[role]=(await r.json()).access;
    }
    owned.category=await call('chef','/admin/categories/',{method:'POST',body:{name:marker,position:9999,is_active:true}});
    owned.extra=await call('chef','/admin/extras/',{method:'POST',body:{name:marker+' extra',price:17,is_available:true}});
    owned.dish=await call('chef','/admin/dishes/',{method:'POST',body:{category:owned.category.id,name:'ТЕСТ САЙТА '+stamp,description:marker,price:200,extras:[owned.extra.id],is_available:true,is_active:true,position:9999}});
    owned.size=await call('chef','/admin/sizes/',{method:'POST',body:{dish:owned.dish.id,name:'Тестовый размер',price:250,position:0}});
    await call('admin',`/admin/dishes/${owned.dish.id}/`,{method:'PATCH',body:{description:marker+' edited'}});
    const stopped=await call('cook',`/admin/dishes/${owned.dish.id}/toggle-available/`,{method:'POST',body:{}});assert.equal(stopped.is_available,false);
    const available=await call('cook',`/admin/dishes/${owned.dish.id}/toggle-available/`,{method:'POST',body:{}});assert.equal(available.is_available,true);
    await call('cook',`/admin/dishes/${owned.dish.id}/`,{method:'PATCH',body:{price:1},expect:[403]});
    assert.equal((await call('chef',`/admin/dishes/${owned.dish.id}/`)).price,200);
    const tables=await call('chef','/admin/tables/');const used=new Set(tables.map(t=>t.number));let number=900;while(used.has(number))number++;
    owned.table=await call('chef','/admin/tables/',{method:'POST',body:{kind:'hall',number,name:marker,is_active:true}});
    assert.equal((await call(null,`/tables/${owned.table.token}/`)).name,marker);
    try{const qr=await call('chef',`/admin/tables/${owned.table.id}/qr/`,{binary:true});assert.equal(qr.subarray(1,4).toString(),'PNG');}catch(error){log({check:'qr_png',error:error.message});}
    await call(null,'/orders/',{method:'POST',body:{table_token:owned.table.token,items:[{dish_id:owned.dish.id,quantity:0}]},expect:[400]});
    owned.order=await call(null,'/orders/',{method:'POST',body:{table_token:owned.table.token,device_key:marker,comment:'ТЕСТ ИНТЕГРАЦИИ САЙТА '+marker,payment_method:'cash',items:[{dish_id:owned.dish.id,size_id:owned.size.id,extra_ids:[owned.extra.id],quantity:2}]}});
    assert.equal(owned.order.total,534);
    assert.equal((await call(null,`/orders/${owned.order.public_id}/`)).total,534);
    const all=await call('admin','/staff/orders/?active=true');owned.staffOrder=(Array.isArray(all)?all:all.results).find(o=>o.number===owned.order.number);assert.ok(owned.staffOrder);
    const id=owned.staffOrder.id;
    const fresh=await call('waiter',`/staff/orders/${id}/`);log({check:'waiter_new_actions',actions:fresh.available_actions});
    const claimed=await call('waiter',`/staff/orders/${id}/claim/`,{method:'POST',body:{}});
    log({check:'claimed_status',status:claimed.status});
    if(claimed.status==='new')await call('admin',`/staff/orders/${id}/status/`,{method:'POST',body:{action:'accept',reason:''}});
    await call('cook',`/staff/orders/${id}/status/`,{method:'POST',body:{action:'cook',reason:''}});
    await call('cook',`/staff/orders/${id}/status/`,{method:'POST',body:{action:'ready',reason:''}});
    const ready=await call('waiter',`/staff/orders/${id}/`);log({check:'waiter_actions',actions:ready.available_actions});
    await call('waiter',`/staff/orders/${id}/status/`,{method:'POST',body:{action:'complete',reason:''}});
    owned.completed=true;assert.equal((await call(null,`/orders/${owned.order.public_id}/`)).status,'completed');
    const tableCall=await call(null,'/table-calls/',{method:'POST',body:{table_token:owned.table.token,kind:'waiter'}});
    await call('waiter',`/staff/table-calls/${tableCall.id}/done/`,{method:'POST',body:{}});
    await call('waiter',`/staff/tables/${owned.table.id}/close-visit/`,{method:'POST',body:{}});
    log({check:'order_flow',success:true,testOrderNumber:owned.order.number,total:534});
  }finally{
    if(owned.staffOrder&&!owned.completed){try{await call('admin',`/staff/orders/${owned.staffOrder.id}/status/`,{method:'POST',body:{action:'cancel',reason:marker+' cleanup'}});}catch(error){log({cleanup:'order',error:error.message});}}
    for(const [key,route] of [['table','tables'],['size','sizes'],['dish','dishes'],['extra','extras'],['category','categories']]){
      if(!owned[key])continue;
      try{await call('chef',`/admin/${route}/${owned[key].id}/`,{method:'DELETE'});}catch(error){
        if(['table','dish','category'].includes(key)){try{await call('chef',`/admin/${route}/${owned[key].id}/`,{method:'PATCH',body:{is_active:false}});}catch{log({cleanup:key,id:owned[key].id,requiresReview:true});}}
        else log({cleanup:key,id:owned[key].id,requiresReview:true});
      }
    }
    fs.mkdirSync(path.join(__dirname,'../tmp'),{recursive:true});fs.writeFileSync(path.join(__dirname,'../tmp/api-flow-results.json'),JSON.stringify({marker,results},null,2));
  }
}
