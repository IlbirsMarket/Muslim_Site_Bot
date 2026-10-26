process.env.MUSLIM_ENABLE_API='0';
const {createServer}=require('../server.cjs');
const port=process.env.PORT===undefined?4174:Number(process.env.PORT);
const server=createServer({apiEnabled:false});
server.listen(port,'127.0.0.1',()=>console.log(`Demo: http://localhost:${server.address().port}/admin`));
