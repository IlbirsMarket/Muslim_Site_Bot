const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
for(const file of [...fs.readdirSync(path.join(__dirname,'../dist')).filter(f=>f.endsWith('.js')).map(f=>'dist/'+f),'server.cjs']){
  const result=spawnSync(process.execPath,['--check',file],{cwd:path.join(__dirname,'..'),stdio:'inherit'});
  if(result.status!==0)process.exit(result.status||1);
}
console.log('All application scripts passed syntax checks.');
