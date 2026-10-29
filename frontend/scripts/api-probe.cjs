const fs=require('node:fs');
const path=require('node:path');
const origin=process.env.MUSLIM_API_ORIGIN||'http://172.20.10.4:8000';
let input='';
process.stdout.write('Ready for test credentials on stdin (hidden).\n');
if(process.stdin.isTTY)process.stdin.setRawMode(true);
process.stdin.setEncoding('utf8');
process.stdin.on('data',async chunk=>{
  if(chunk.includes('\u0003'))process.exit(130);
  input+=chunk;
  if(!/[\r\n]/.test(input))return;
  process.stdin.pause();if(process.stdin.isTTY)process.stdin.setRawMode(false);
  try{const data=JSON.parse(input.trim());if(data.usernames){for(const username of data.usernames)await probe({username,password:data.password});}else await probe(data);process.exit(0);}catch(error){console.error(error.message);process.exit(1);}
});
async function probe(credentials){
  const response=await fetch(origin+'/api/auth/login/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:credentials.username,password:credentials.password})});
  if(!response.ok)throw new Error('Login failed: HTTP '+response.status);
  const tokens=await response.json();
  const headers={Authorization:'Bearer '+tokens.access,Accept:'application/json'};
  if(credentials.cleanupDishName){
    const name=credentials.cleanupDishName;
    if(!name.startsWith('ТЕСТ САЙТА — фото '))throw new Error('Only a named photo-test fixture may be removed.');
    const data=await(await fetch(origin+'/api/admin/dishes/?search='+encodeURIComponent(name),{headers})).json();
    const dishes=(Array.isArray(data)?data:data.results||[]).filter(d=>d.name===name&&d.description==='Проверка загрузки изображения из сайта в API. Временное тестовое блюдо.');
    if(dishes.length!==1)throw new Error('Expected exactly one matching test fixture.');
    const dish=dishes[0];if(!dish.photo)throw new Error('Test photo did not persist.');
    const url=new URL(dish.photo);if(url.origin!==origin||!url.pathname.startsWith('/media/'))throw new Error('Unexpected photo origin.');
    const photo=await fetch(url);if(!photo.ok||!photo.headers.get('content-type')?.startsWith('image/'))throw new Error('Saved photo is not readable.');
    const removed=await fetch(origin+'/api/admin/dishes/'+dish.id+'/',{method:'DELETE',headers});if(removed.status!==204)throw new Error('Test cleanup failed: '+removed.status);
    console.log(JSON.stringify({photoSaved:true,photoReadStatus:photo.status,testDishRemoved:true}));return;
  }
  const endpoints=['/api/auth/me/','/api/admin/cafe/','/api/admin/categories/','/api/admin/dishes/','/api/admin/extras/','/api/admin/sizes/','/api/admin/tables/','/api/admin/staff/','/api/admin/staff/roles/','/api/admin/staff/role-log/','/api/staff/orders/?active=true','/api/staff/table-calls/','/api/admin/reports/day/','/api/admin/reports/period/','/api/admin/reports/periods/'];
  const results=[];
  for(const endpoint of endpoints){
    const started=Date.now();const r=await fetch(origin+endpoint,{headers});let data;try{data=await r.json();}catch{data={};}
    results.push({method:'GET',path:endpoint,status:r.status,ms:Date.now()-started,shape:Array.isArray(data)?'array('+data.length+')':Object.keys(data)});
    const summary=endpoint.endsWith('/me/')?{role:data.role,role_display:data.role_display}:endpoint.endsWith('/roles/')?data:endpoint.includes('/reports/')?data:endpoint.includes('orders/')?{count:data.count,items:(Array.isArray(data)?data:data.results||[]).map(o=>({id:o.id,status:o.status,actions:o.available_actions}))}:undefined;
    console.log(JSON.stringify({path:endpoint,status:r.status,shape:results.at(-1).shape,summary}));
  }
  fs.mkdirSync(path.join(__dirname,'../tmp'),{recursive:true});
  fs.writeFileSync(path.join(__dirname,'../tmp/api-auth-results-'+credentials.username+'.json'),JSON.stringify(results,null,2));
  // Tokens and credentials are never written to disk or printed.
}
