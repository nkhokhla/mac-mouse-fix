import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import worker,{REPOSITORY,BRANCH,EVENT,signedHeaders,callbackURL,canonical,validateEvent} from '../worker/index.js';

class Bucket {
  constructor(){this.items=new Map();this.seq=0;}
  async get(key){const x=this.items.get(key);return x?{etag:x.etag,json:async()=>JSON.parse(x.body)}:null;}
  async put(key,body,options={}){
    const old=this.items.get(key),c=options.onlyIf;
    if(c?.etagMatches&&old?.etag!==c.etagMatches)return null;
    if(c?.etagDoesNotMatch==='*'&&old)return null;
    const x={body,etag:String(++this.seq)};this.items.set(key,x);return x;
  }
  async delete(key){this.items.delete(key);}
  async list({prefix,cursor,limit=1000}){const keys=[...this.items.keys()].filter(x=>x.startsWith(prefix)).sort();const n=Number(cursor||0);return {objects:keys.slice(n,n+limit).map(key=>({key})),truncated:n+limit<keys.length,cursor:String(n+limit)};}
}
const SECRET='whsec_'+Buffer.alloc(32,7).toString('base64');
const URL='https://connectors.api.openai.com/test/callback';
const request=(path,body,owner='owner')=>new Request('https://bridge.example'+path,{method:'POST',headers:{'content-type':'application/json',...(owner?{'oai-authenticated-user-id':owner}:{})},body:JSON.stringify(body)});
async function rpc(env,method,params={},owner='owner'){return (await worker.fetch(request('/mcp',{jsonrpc:'2.0',id:1,method,params},owner),env)).json();}
const params=(args={repository:REPOSITORY},url=URL,secret=SECRET)=>({name:EVENT,arguments:args,delivery:{mode:'webhook',url,secret}});
const event=(number=3,id='evt_example_123')=>({eventId:id,name:EVENT,timestamp:'2026-10-29T10:00:00Z',cursor:null,data:{repository:REPOSITORY,pull_request_number:number,url:`https://github.com/${REPOSITORY}/pull/${number}`,title:'Review upstream updates',head_sha:'a'.repeat(40),base_sha:'b'.repeat(40),head_branch:BRANCH,base_branch:'master',reason:'sync_completed',source_event:'workflow_run',source_id:'123',source_url:`https://github.com/${REPOSITORY}/actions/runs/123`}});
function setup(){
  const sent=[];
  const env={BUCKET:new Bucket(),OUTBOUND_FETCH:async(url,options)=>{
    assert.equal(options.redirect,'error');assert.equal(url,URL);
    const body=JSON.parse(options.body);sent.push({body,headers:options.headers});
    const sig='v1,'+createHmac('sha256',Buffer.alloc(32,7)).update(`${options.headers['webhook-id']}.${options.headers['webhook-timestamp']}.${options.body}`).digest('base64');
    assert.ok(options.headers['webhook-signature'].split(' ').includes(sig));
    return body.type==='verification'?Response.json({challenge:body.challenge}):new Response(null,{status:200});
  }};
  return {env,sent};
}
async function ingest(env,e){return worker.fetch(request('/api/ingest',e,null),env);}
test('discovery exposes actual events and tool methods',async()=>{
  const {env}=setup();const d=await rpc(env,'server/discover');assert.deepEqual(d.result.supportedVersions,['2026-07-28']);assert.ok(d.result.capabilities.events);
  const e=await rpc(env,'events/list');assert.equal(e.result.events[0].name,EVENT);assert.deepEqual(e.result.events[0].delivery,['webhook']);
});
test('Standard Webhooks signature matches independent HMAC',async()=>{
  const h=await signedHeaders(SECRET,'evt_123','{"a":1}','sub_123',10);
  assert.equal(h['webhook-signature'],'v1,'+createHmac('sha256',Buffer.alloc(32,7)).update('evt_123.10.{"a":1}').digest('base64'));
});
test('subscribe verifies, persists across worker calls and is idempotent',async()=>{
  const {env,sent}=setup();const a=await rpc(env,'events/subscribe',params());const b=await rpc(env,'events/subscribe',params());
  assert.equal(a.result.id,b.result.id);assert.equal(sent.length,1);assert.equal((await env.BUCKET.list({prefix:'subscriptions/'})).objects.length,1);
  assert.equal(a.result.cursor,null);
});
test('canonical key order cannot create duplicate subscriptions',async()=>{
  const {env}=setup();const a=await rpc(env,'events/subscribe',params({repository:REPOSITORY,pull_request_number:3}));const b=await rpc(env,'events/subscribe',params({pull_request_number:3,repository:REPOSITORY}));assert.equal(a.result.id,b.result.id);
});
test('no user identity cannot subscribe',async()=>{const {env}=setup();assert.equal((await rpc(env,'events/subscribe',params(),null)).error.code,-32024);});
test('callback URL policy denies SSRF, redirects and credentials',()=>{
  for(const u of ['http://connectors.api.openai.com/a','https://127.0.0.1/a','https://localhost/a','https://connectors.api.openai.com.evil.test/a','https://user@connectors.api.openai.com/a','https://connectors.api.openai.com:8443/a','https://connectors.api.openai.com/a#x'])assert.throws(()=>callbackURL(u,{}));
  assert.equal(callbackURL(URL,{}),URL);
});
test('invalid secret and callback challenge cannot activate subscriptions',async()=>{
  const {env}=setup();assert.ok((await rpc(env,'events/subscribe',params(undefined,URL,'whsec_YQ=='))).error);
  env.OUTBOUND_FETCH=async()=>Response.json({challenge:'wrong'});
  assert.equal((await rpc(env,'events/subscribe',params())).error.code,-32015);
  assert.equal((await env.BUCKET.list({prefix:'subscriptions/'})).objects.length,0);
});
test('matching event delivers once and uses signed exact envelope',async()=>{
  const {env,sent}=setup();await rpc(env,'events/subscribe',params());
  assert.equal((await ingest(env,event())).status,200);assert.equal((await ingest(env,event())).status,200);
  assert.equal(sent.filter(x=>x.body.name===EVENT).length,1);
  assert.equal(sent.at(-1).headers['webhook-id'],event().eventId);
});
test('PR filter excludes other PRs and repository/branch boundaries are strict',async()=>{
  const {env,sent}=setup();await rpc(env,'events/subscribe',params({repository:REPOSITORY,pull_request_number:3}));
  assert.equal((await ingest(env,event(4))).status,503);assert.equal(sent.length,1);
  const e=event();e.data.head_branch='feature/other';assert.throws(()=>validateEvent(e));
});
test('no active subscriber is a visible failure and event remains stored',async()=>{
  const {env}=setup();assert.equal((await ingest(env,event())).status,503);assert.ok(await env.BUCKET.get('events/'+event().eventId));
});
test('transient failure persists outbox and retry delivers',async()=>{
  const {env}=setup();await rpc(env,'events/subscribe',params());const good=env.OUTBOUND_FETCH;
  env.OUTBOUND_FETCH=async()=>new Response(null,{status:503});assert.equal((await ingest(env,event())).status,503);
  assert.equal((await env.BUCKET.list({prefix:'pending/'})).objects.length,1);
  env.OUTBOUND_FETCH=good;const retried=await rpc(env,'tools/call',{name:'retry_sync_deliveries',arguments:{}});assert.equal(JSON.parse(retried.result.content[0].text).delivered,1);
});
test('410 terminates and 413 is permanent rather than retried',async()=>{
  for(const code of [410,413]){
    const {env}=setup();await rpc(env,'events/subscribe',params());env.OUTBOUND_FETCH=async()=>new Response(null,{status:code});await ingest(env,event());
    assert.equal((await env.BUCKET.list({prefix:'pending/'})).objects.length,0);
    if(code===410)assert.equal((await env.BUCKET.list({prefix:'subscriptions/'})).objects.length,0);
  }
});
test('another principal cannot unsubscribe owner subscription; unsubscribe is idempotent',async()=>{
  const {env}=setup();await rpc(env,'events/subscribe',params());
  const stop={name:EVENT,arguments:{repository:REPOSITORY},delivery:{url:URL}};
  await rpc(env,'events/unsubscribe',stop,'other');assert.equal((await env.BUCKET.list({prefix:'subscriptions/'})).objects.length,1);
  await rpc(env,'events/unsubscribe',stop);await rpc(env,'events/unsubscribe',stop);assert.equal((await env.BUCKET.list({prefix:'subscriptions/'})).objects.length,0);
});
test('expiration stops delivery and TTL grants are finite and bounded',async()=>{
  const {env}=setup();const r=await rpc(env,'events/subscribe',{...params(),ttlMs:null});const key='subscriptions/'+r.result.id;const sub=await readSub(env,key);assert.ok(sub.expires_at<=Date.now()+604800000);
  sub.expires_at=0;await env.BUCKET.put(key,JSON.stringify(sub));assert.equal((await ingest(env,event())).status,503);
});
async function readSub(env,key){return (await env.BUCKET.get(key)).json();}
test('duplicate event ID with changed payload is rejected',async()=>{const {env}=setup();await ingest(env,event());const e=event();e.data.title='changed';assert.equal((await ingest(env,e)).status,400);});
test('work leases are exclusive, completion is owner-scoped, completed events stay deduped',async()=>{
  const {env}=setup();await ingest(env,event());
  const args={pull_request_number:3,event_id:event().eventId,head_sha:event().data.head_sha};
  const tool=async(name,arguments_,owner='owner')=>(await rpc(env,'tools/call',{name,arguments:arguments_},owner)).result;
  const first=JSON.parse((await tool('claim_sync_pr',args)).content[0].text);assert.equal(first.claimed,true);
  assert.equal(JSON.parse((await tool('claim_sync_pr',args)).content[0].text).claimed,false);
  const done={pull_request_number:3,claim_token:first.claim_token,outcome:'completed',summary:'Validated patch'};
  assert.equal((await tool('finish_sync_pr',done,'other')).isError,true);
  await tool('finish_sync_pr',done);assert.equal(JSON.parse((await tool('claim_sync_pr',args)).content[0].text).reason,'already_handled');
  const s=JSON.stringify(await tool('sync_bridge_status',{}));assert.ok(!s.includes(first.claim_token));assert.ok(!s.includes(SECRET));assert.ok(!s.includes(URL));
});
test('malformed JSON and notification behavior follow JSON-RPC',async()=>{
  const {env}=setup();const bad=await worker.fetch(new Request('https://bridge.example/mcp',{method:'POST',body:'bad'}),env);assert.equal((await bad.json()).error.code,-32700);
  assert.equal((await worker.fetch(request('/mcp',{jsonrpc:'2.0',method:'notifications/initialized'}),env)).status,202);
});
