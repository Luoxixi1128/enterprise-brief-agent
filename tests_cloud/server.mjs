// Local QA only: executes the production SQL in PostgreSQL/WASM. Object storage
// and the REST gateway are stand-ins, not a claim of live Supabase validation.
import { PGlite } from '@electric-sql/pglite';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import assert from 'node:assert/strict';

const db = new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role;
create schema storage; create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint);`);
const schema = readFileSync(new URL('../supabase/schema.sql', import.meta.url),'utf8');
await db.exec(schema);
await db.exec(schema); // repeat initialization must be safe
const rpc = async (op, visitor='', owner_id='', body={}) =>
  (await db.query('select public.brief_cloud($1,$2,$3,$4::jsonb) as result', [op, visitor, owner_id, JSON.stringify(body)])).rows[0].result;
assert.deepEqual(await rpc('ping'), {schema:1});
for (const role of ['anon','authenticated']) {
  const r = (await db.query("select has_function_privilege($1,'public.brief_cloud(text,text,text,jsonb)','execute') as allowed",[role])).rows[0];
  assert.equal(r.allowed,false);
  for (const name of ['brief_tasks','brief_versions','brief_visitors','brief_files','brief_counters','brief_runtime']) {
    const p = (await db.query('select has_table_privilege($1,$2,\'select,insert,update,delete\') as allowed',[role,'public.'+name])).rows[0];
    assert.equal(p.allowed,false);
  }
}
assert.equal((await db.query("select has_function_privilege('service_role','public.brief_cloud(text,text,text,jsonb)','execute') as allowed")).rows[0].allowed,true);
const objects = new Map();
let fail = null;
const server = http.createServer(async (req,res) => {
  if(req.headers.apikey !== process.env.QA_KEY){res.writeHead(403);res.end();return;}
  const chunks=[];for await (const c of req) chunks.push(c);
  const data=Buffer.concat(chunks);
  const send = (status,value) => {res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
  try {
    if(req.url === '/__qa') {
      const b=JSON.parse(data);
      if(b.op==='reset') {await db.exec('truncate public.brief_visitors,public.brief_tasks,public.brief_versions,public.brief_files,public.brief_counters,public.brief_runtime cascade');objects.clear();fail=null;}
      else if(b.op==='expire') await db.exec("update public.brief_runtime set expires_at=now()-interval '1 second'");
      else if(b.op==='fail') fail=b.target;
      else if(b.op==='corrupt') objects.set(b.key,Buffer.from('bad data'));
      else if(b.op==='sql') {send(200,(await db.query(b.sql,b.params||[])).rows);return;}
      send(200,{});return;
    }
    if(req.url === '/rest/v1/rpc/brief_cloud') {
      const b=JSON.parse(data);
      if(fail==='all' || fail===b.op){send(503,{private_detail:'never forward raw provider errors'});return;}
      send(200,await rpc(b.op,b.visitor,b.owner_id,b.body));return;
    }
    const prefix='/storage/v1/object/brief-private/';
    if(req.url.startsWith(prefix)) {
      if(fail==='upload' && req.method==='POST'){send(503,{private_detail:'storage unavailable'});return;}
      const key=decodeURIComponent(req.url.slice(prefix.length));
      if(req.method==='POST'){objects.set(key,data);send(200,{Key:key});return;}
      if(!objects.has(key)){send(404,{});return;}
      res.writeHead(200,{'Content-Type':'application/octet-stream'});res.end(objects.get(key));return;
    }
    send(404,{});
  } catch(e) {console.error(e);send(500,{error:String(e)});}
});
server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({port:server.address().port,sqlPermissions:'passed'})));
process.on('SIGTERM',()=>server.close(()=>db.close().then(()=>process.exit())));
