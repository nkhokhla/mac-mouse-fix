// MCP Events webhook profile, protocol 2026-07-28. Sites MUST remain owner-private.
// Sites dispatch authenticates MCP users and the service ingress bearer token.
export const REPOSITORY = 'nkhokhla/mac-mouse-fix';
export const BRANCH = 'automation/upstream-sync';
export const EVENT = 'upstream_sync.attention';
const enc = new TextEncoder();
const json = (body,status=200) => Response.json(body,{status,headers:{'cache-control':'no-store'}});
const fail = (message,code=-32602) => {throw Object.assign(new Error(message),{code});};
const object = v => !!v && typeof v==='object' && !Array.isArray(v);
const only = (v,keys) => {if(!object(v)||Object.keys(v).some(k=>!keys.includes(k)))fail('Unexpected object fields');};
const positive = v => Number.isSafeInteger(v)&&v>0;
const isSha = v => typeof v==='string'&&/^[a-f0-9]{40}$/.test(v);
export const canonical = v => JSON.stringify(v,(_,x)=>object(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
const hash = async v => [...new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(v)))].map(x=>x.toString(16).padStart(2,'0')).join('');
const equal = (a,b) => {if(typeof a!=='string'||typeof b!=='string')return false;let d=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)d|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return d===0;};
const read = async (b,k) => {const o=await b.get(k);return o?o.json():null;};
const put = (b,k,v,options={}) => b.put(k,JSON.stringify(v),{httpMetadata:{contentType:'application/json'},...options});
async function list(b,prefix){const out=[];let cursor;do{const p=await b.list({prefix,cursor,limit:1000});out.push(...p.objects);cursor=p.truncated?p.cursor:undefined;}while(cursor);return out;}

export function filters(args={}){
  only(args,['repository','pull_request_number']);
  if(args.repository!==REPOSITORY||(args.pull_request_number!==undefined&&!positive(args.pull_request_number)))fail('Invalid upstream-sync filters');
  return args;
}
export function callbackURL(value,env){
  let u;try{u=new URL(value);}catch{fail('Invalid callback URL');}
  // Exact trusted public hosts avoid arbitrary DNS destinations and SSRF.
  const hosts=(env.CALLBACK_HOST_ALLOWLIST||'connectors.api.openai.com').split(',').map(x=>x.trim());
  if(u.protocol!=='https:'||u.username||u.password||u.hash||(u.port&&u.port!=='443')||!hosts.includes(u.hostname)||!u.hostname.includes('.')||u.hostname.endsWith('.local')||/^\d+(\.\d+){3}$/.test(u.hostname))fail('Callback must use HTTPS on an explicitly trusted host');
  return u.href;
}
function keyBytes(secret){
  if(typeof secret!=='string'||!/^whsec_[A-Za-z0-9+/]+={0,2}$/.test(secret))fail('Invalid Standard Webhooks secret');
  let bytes;try{bytes=Uint8Array.from(atob(secret.slice(6)),c=>c.charCodeAt(0));}catch{fail('Invalid signing key');}
  if(bytes.length<24||bytes.length>64)fail('Signing key must be 24–64 bytes');return bytes;
}
export async function signedHeaders(secret,id,body,sub,timestamp=Math.floor(Date.now()/1000)){
  const key=await crypto.subtle.importKey('raw',keyBytes(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const sig=new Uint8Array(await crypto.subtle.sign('HMAC',key,enc.encode(`${id}.${timestamp}.${body}`)));
  return {'content-type':'application/json','webhook-id':id,'webhook-timestamp':String(timestamp),'webhook-signature':'v1,'+btoa(String.fromCharCode(...sig)),'X-MCP-Subscription-Id':sub};
}
async function send(sub,event,env){
  const body=JSON.stringify(event),id=event.eventId||'msg_verification_'+crypto.randomUUID();
  const headers=await signedHeaders(sub.secret,id,body,sub.id);
  if(sub.previous_secret&&sub.rotation_until>Date.now())headers['webhook-signature']+=' '+(await signedHeaders(sub.previous_secret,id,body,sub.id,Number(headers['webhook-timestamp'])))['webhook-signature'];
  return (env.OUTBOUND_FETCH||fetch)(callbackURL(sub.url,env),{method:'POST',headers,body,redirect:'error',signal:AbortSignal.timeout(10000)});
}
const dataFields=['repository','pull_request_number','url','title','head_sha','base_sha','head_branch','base_branch','reason','source_event','source_id','source_url'];
export function validateEvent(e){
  only(e,['eventId','name','timestamp','data','cursor']);
  if(e.name!==EVENT||typeof e.eventId!=='string'||!/^[A-Za-z0-9_-]{8,160}$/.test(e.eventId)||typeof e.timestamp!=='string'||!Number.isFinite(Date.parse(e.timestamp))||!/(Z|[+-]\d\d:\d\d)$/.test(e.timestamp)||e.cursor!==null)fail('Invalid event envelope');
  const d=e.data;only(d,dataFields);
  if(d.repository!==REPOSITORY||d.head_branch!==BRANCH||d.base_branch!=='master'||!positive(d.pull_request_number)||!isSha(d.head_sha)||!isSha(d.base_sha)||d.url!==`https://github.com/${REPOSITORY}/pull/${d.pull_request_number}`)fail('Event is outside upstream-sync scope');
  if(!['sync_completed','pr_opened','pr_reopened','pr_updated','feedback','bootstrap'].includes(d.reason)||!['workflow_run','pull_request_target','pull_request_review','pull_request_review_comment','issue_comment','workflow_dispatch'].includes(d.source_event))fail('Unsupported event kind');
  for(const k of ['title','source_id','source_url'])if(typeof d[k]!=='string'||d[k].length>1000)fail('Invalid '+k);
  if(enc.encode(JSON.stringify(e)).length>16384)fail('Event too large');return e;
}
const inputSchema={type:'object',properties:{repository:{type:'string',enum:[REPOSITORY]},pull_request_number:{type:'integer',minimum:1,description:'Omit to include PR #3 and future upstream-sync PRs.'}},required:['repository'],additionalProperties:false};
const payloadSchema={type:'object',properties:Object.fromEntries(dataFields.map(k=>[k,{type:k==='pull_request_number'?'integer':'string'}])),required:dataFields,additionalProperties:false};
const empty={type:'object',properties:{},additionalProperties:false};
const tools=[
  {name:'sync_bridge_status',description:'Read subscriptions and delivery counts. Callback URLs and signing secrets are redacted.',inputSchema:empty,annotations:{readOnlyHint:true}},
  {name:'retry_sync_deliveries',description:'Retry pending event deliveries for this caller. Does not poll GitHub.',inputSchema:empty},
  {name:'claim_sync_pr',description:'Acquire a 30-minute exclusive work lease before modifying an upstream-sync PR. Repeated event IDs cannot be claimed again.',inputSchema:{type:'object',properties:{pull_request_number:{type:'integer',minimum:1},event_id:{type:'string'},head_sha:{type:'string'}},required:['pull_request_number','event_id','head_sha'],additionalProperties:false}},
  {name:'finish_sync_pr',description:'Record completed or blocked work and release its lease.',inputSchema:{type:'object',properties:{pull_request_number:{type:'integer',minimum:1},claim_token:{type:'string'},outcome:{type:'string',enum:['completed','blocked']},summary:{type:'string'}},required:['pull_request_number','claim_token','outcome','summary'],additionalProperties:false}}
];
async function drain(env,owner=null,eventId=null){
  let delivered=0,pending=0;
  const candidates=(await list(env.BUCKET,'pending/')).filter(x=>!eventId||x.key.endsWith('/'+eventId));
  for(const item of candidates.slice(0,20)){
    const work=await read(env.BUCKET,item.key);if(!work||(owner&&work.owner!==owner))continue;
    const sub=await read(env.BUCKET,'subscriptions/'+work.subscription);
    if(!sub||sub.expires_at<=Date.now()){await env.BUCKET.delete(item.key);continue;}
    const done='delivered/'+sub.id+'/'+work.eventId;
    if(await env.BUCKET.get(done)){await env.BUCKET.delete(item.key);continue;}
    try{
      const response=await send(sub,await read(env.BUCKET,'events/'+work.eventId),env);
      if(response.ok||response.status===413){await put(env.BUCKET,done,{at:Date.now(),status:response.status});await env.BUCKET.delete(item.key);delivered++;}
      else if(response.status===410){await env.BUCKET.delete('subscriptions/'+sub.id);await env.BUCKET.delete(item.key);}
      else pending++;
    }catch{pending++;}
  }
  return {delivered,pending};
}
async function subscribe(p,owner,env){
  only(p,['name','arguments','delivery','cursor','ttlMs','maxAgeMs']);
  if(p.name!==EVENT)fail('Unknown event');
  if(p.cursor!==undefined&&p.cursor!==null)fail('Emit-only events do not support replay cursors');
  const args=filters(p.arguments);only(p.delivery,['mode','url','secret']);
  if(p.delivery.mode!=='webhook')fail('Only webhook delivery is supported');
  const url=callbackURL(p.delivery.url,env);keyBytes(p.delivery.secret);
  if(p.ttlMs!==undefined&&p.ttlMs!==null&&(!positive(p.ttlMs)))fail('Invalid TTL');
  const ttl=Math.max(60000,Math.min(p.ttlMs===null?604800000:(p.ttlMs??86400000),604800000));
  const id='sub_'+await hash(canonical([owner,url,EVENT,args])),old=await read(env.BUCKET,'subscriptions/'+id);
  const sub={id,owner,url,name:EVENT,arguments:args,secret:p.delivery.secret,expires_at:Date.now()+ttl,verified_at:old?.verified_at||0};
  if(!old||!equal(old.secret,sub.secret)||old.expires_at<=Date.now()||sub.verified_at<Date.now()-86400000){
    const challenge=crypto.randomUUID();let r,body;
    try{r=await send(sub,{type:'verification',challenge},env);body=await r.json();}catch{fail('Callback verification failed',-32015);}
    if(!r.ok||!equal(body.challenge,challenge))fail('Callback challenge failed',-32015);sub.verified_at=Date.now();
  }
  if(old&&!equal(old.secret,sub.secret)){sub.previous_secret=old.secret;sub.rotation_until=Date.now()+3600000;}
  else if(old?.rotation_until>Date.now()){sub.previous_secret=old.previous_secret;sub.rotation_until=old.rotation_until;}
  await put(env.BUCKET,'subscriptions/'+id,sub);
  return {id,refreshBefore:new Date(sub.expires_at).toISOString(),cursor:null,truncated:false};
}
async function status(env,owner=null){
  const subs=(await Promise.all((await list(env.BUCKET,'subscriptions/')).map(x=>read(env.BUCKET,x.key)))).filter(x=>x&&(!owner||x.owner===owner)).map(x=>({id:x.id,event:x.name,arguments:x.arguments,active:x.expires_at>Date.now(),expires_at:new Date(x.expires_at).toISOString()}));
  const leases=(await Promise.all((await list(env.BUCKET,'leases/')).map(x=>read(env.BUCKET,x.key)))).filter(x=>x&&(!owner||x.owner===owner)).map(({owner,claim_token,...x})=>x);
  return {repository:REPOSITORY,branch:BRANCH,event:EVENT,subscriptions:subs,leases,pending_deliveries:(await list(env.BUCKET,'pending/')).length,received_events:(await list(env.BUCKET,'events/')).length,delivered_events:(await list(env.BUCKET,'delivered/')).length};
}
async function callTool(name,args,owner,env){
  if(name==='sync_bridge_status'){only(args,[]);return status(env,owner);}
  if(name==='retry_sync_deliveries'){only(args,[]);return drain(env,owner);}
  if(name==='claim_sync_pr'){
    only(args,['pull_request_number','event_id','head_sha']);
    if(!positive(args.pull_request_number)||!isSha(args.head_sha)||typeof args.event_id!=='string'||!/^[A-Za-z0-9_-]{8,160}$/.test(args.event_id))fail('Invalid claim');
    const event=await read(env.BUCKET,'events/'+args.event_id);
    if(!event||event.data.pull_request_number!==args.pull_request_number||event.data.head_sha!==args.head_sha)fail('Claim must match a recorded upstream-sync event');
    if(await env.BUCKET.get('handled/'+args.event_id))return {claimed:false,reason:'already_handled'};
    const key='leases/'+args.pull_request_number,item=await env.BUCKET.get(key),old=item?await item.json():null;
    if(old?.expires_at>Date.now())return {claimed:false,reason:'already_running'};
    const lease={...args,owner,claim_token:crypto.randomUUID(),expires_at:Date.now()+1800000,outcome:'running'};
    const result=await put(env.BUCKET,key,lease,{onlyIf:item?{etagMatches:item.etag}:{etagDoesNotMatch:'*'}});
    return result?{claimed:true,claim_token:lease.claim_token,expires_at:new Date(lease.expires_at).toISOString()}:{claimed:false,reason:'concurrent_claim'};
  }
  if(name==='finish_sync_pr'){
    only(args,['pull_request_number','claim_token','outcome','summary']);
    if(!positive(args.pull_request_number)||!['completed','blocked'].includes(args.outcome)||typeof args.summary!=='string'||args.summary.length>2000)fail('Invalid completion');
    const key='leases/'+args.pull_request_number,item=await env.BUCKET.get(key),old=item?await item.json():null;
    if(!old||old.owner!==owner||!equal(old.claim_token,args.claim_token))fail('Lease does not belong to this caller',-32024);
    const result=await put(env.BUCKET,key,{...old,outcome:args.outcome,summary:args.summary,expires_at:0,finished_at:Date.now()},{onlyIf:{etagMatches:item.etag}});
    if(!result)fail('Lease changed; read status before retrying');
    await put(env.BUCKET,'handled/'+old.event_id,{outcome:args.outcome,at:Date.now()});return {recorded:true};
  }
  fail('Unknown tool',-32601);
}
async function rpc(m,request,env){
  if(!object(m)||m.jsonrpc!=='2.0'||typeof m.method!=='string')fail('Invalid JSON-RPC request',-32600);
  const {method,params:p={}}=m,owner=request.headers.get('oai-authenticated-user-id');
  if(method==='server/discover')return {resultType:'complete',supportedVersions:['2026-07-28'],capabilities:{tools:{},events:{listChanged:false}}};
  if(method==='initialize')return {protocolVersion:'2026-07-28',capabilities:{tools:{},events:{}},serverInfo:{name:'mac-mouse-fix-mcp-events',version:'1.0.0'}};
  if(method==='ping')return {};
  if(method==='tools/list')return {tools};
  if(method==='events/list')return {events:[{name:EVENT,description:'An open upstream-sync PR needs attention. Includes PR #3 and future automation/upstream-sync PRs after sync workflow completion, branch updates and human feedback. Fetch current PR details with GitHub tools.',delivery:['webhook'],inputSchema,payloadSchema}]};
  if(method.startsWith('notifications/'))return null;
  if(!owner)fail('An authenticated Site user is required',-32024);
  if(!env.BUCKET)fail('Persistent storage unavailable',-32603);
  if(method==='events/subscribe')return subscribe(p,owner,env);
  if(method==='events/unsubscribe'){
    only(p,['name','arguments','delivery']);if(p.name!==EVENT)fail('Unknown event');only(p.delivery,['url']);
    const id='sub_'+await hash(canonical([owner,callbackURL(p.delivery.url,env),EVENT,filters(p.arguments)]));
    await env.BUCKET.delete('subscriptions/'+id);return {};
  }
  if(method==='tools/call'){
    try{return {content:[{type:'text',text:JSON.stringify(await callTool(p.name,p.arguments||{},owner,env))}]};}
    catch(e){return {isError:true,content:[{type:'text',text:e.message}]};}
  }
  fail('Method not found',-32601);
}
async function ingest(event,env){
  validateEvent(event);const key='events/'+event.eventId,existing=await read(env.BUCKET,key);
  if(existing&&canonical(existing)!==canonical(event))fail('Event ID reused with different data');
  if(!existing){const saved=await put(env.BUCKET,key,event,{onlyIf:{etagDoesNotMatch:'*'}});if(!saved&&canonical(await read(env.BUCKET,key))!==canonical(event))fail('Concurrent event ID conflict');}
  let subscribers=0;
  for(const entry of await list(env.BUCKET,'subscriptions/')){
    const sub=await read(env.BUCKET,entry.key);
    if(!sub||sub.expires_at<=Date.now()||(sub.arguments.pull_request_number&&sub.arguments.pull_request_number!==event.data.pull_request_number))continue;
    subscribers++;
    if(!await env.BUCKET.get('delivered/'+sub.id+'/'+event.eventId))await put(env.BUCKET,'pending/'+sub.id+'/'+event.eventId,{owner:sub.owner,subscription:sub.id,eventId:event.eventId},{onlyIf:{etagDoesNotMatch:'*'}});
  }
  if(!subscribers)return json({stored:true,error:'No active subscriber. Subscribe and replay from GitHub Actions.'},503);
  const result=await drain(env,null,event.eventId);
  const pending=(await list(env.BUCKET,'pending/')).some(x=>x.key.endsWith('/'+event.eventId));
  return json({stored:true,...result},pending?503:200);
}
const page=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mac Mouse Fix · MCP Events</title><style>body{margin:0;background:#f4f5f7;color:#172334;font:16px system-ui}main{max-width:860px;margin:56px auto;padding:24px}h1{font-size:38px;letter-spacing:-1.4px}p{line-height:1.65;color:#4b5b70}.tag{font:12px ui-monospace;color:#206653}section{background:white;padding:24px;border:1px solid #e1e5eb;border-radius:16px;margin:24px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 ui-monospace}a{color:#235fb5}button{border:0;border-radius:8px;background:#172334;color:white;padding:12px 20px;cursor:pointer}</style><main><span class="tag">PRIVATE · MCP EVENTS / WEBHOOK</span><h1>Upstream updates, handled when they happen.</h1><p>Event bridge for <a href="https://github.com/nkhokhla/mac-mouse-fix/pull/3">PR #3</a> and future upstream-sync pull requests.</p><section><h2>Connection status</h2><pre id="status">Loading…</pre><button onclick="load()">Refresh status</button></section><section><h2>Event path</h2><p>GitHub Actions → MCP server → signed callback → subscribed agent.</p><p>The bridge transports events. It does not run a model or modify the repository. Repair starts after the relay is configured and an agent subscribes to <code>upstream_sync.attention</code>. There is no GitHub polling timer.</p></section><section><h2>Subscribe</h2><p>Connect this Site’s private plugin. Subscribe to <code>upstream_sync.attention</code> with repository <code>nkhokhla/mac-mouse-fix</code>. Leave the PR number filter unset to include future upstream-sync PRs.</p><p>The agent should resolve conflicts while preserving fork behavior, validate changes, and report blockers.</p></section></main><script>async function load(){try{const r=await fetch('/api/status');if(!r.ok)throw Error('Status unavailable');document.querySelector('#status').textContent=JSON.stringify(await r.json(),null,2)}catch(e){document.querySelector('#status').textContent=e.message}}load()</script></html>`;
export default {async fetch(request,env){
  const path=new URL(request.url).pathname;
  try{
    if(path==='/'&&request.method==='GET')return new Response(page,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
    if(path==='/api/status'&&request.method==='GET')return json(await status(env));
    if(path==='/api/ingest'&&request.method==='POST'){
      if(!env.BUCKET)return json({error:'Persistent storage unavailable'},503);
      const raw=await request.text();if(enc.encode(raw).length>16384)return json({error:'Payload too large'},413);
      return await ingest(JSON.parse(raw),env);
    }
    if(path==='/mcp'&&request.method==='POST'){
      const raw=await request.text();if(enc.encode(raw).length>32768)return json({error:'Request too large'},413);
      let m;try{m=JSON.parse(raw);}catch{return json({jsonrpc:'2.0',id:null,error:{code:-32700,message:'Parse error'}});}
      try{const result=await rpc(m,request,env);return result===null?new Response(null,{status:202}):json({jsonrpc:'2.0',id:m.id??null,result});}
      catch(e){return json({jsonrpc:'2.0',id:m?.id??null,error:{code:e.code||-32603,message:e.code?e.message:'Internal error'}});}
    }
    return json({error:'Not found'},404);
  }catch(e){return json({error:e.code?e.message:'Request failed'},e.code===-32602?400:500);}
}};
