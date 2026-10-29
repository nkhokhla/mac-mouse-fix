import test from 'node:test';
import assert from 'node:assert/strict';
import worker,{REPOSITORY,EVENT} from '../worker/index.js';
test('rotating signing secrets verifies new callback and retains old key for overlap',async()=>{
  const items=new Map(),sent=[];
  const env={BUCKET:{get:async k=>items.has(k)?{json:async()=>JSON.parse(items.get(k))}:null,put:async(k,v)=>{items.set(k,v);return {};},list:async()=>({objects:[]})},OUTBOUND_FETCH:async(u,o)=>{sent.push(o);return Response.json({challenge:JSON.parse(o.body).challenge});}};
  async function subscribe(secret){return (await worker.fetch(new Request('https://bridge/mcp',{method:'POST',headers:{'oai-authenticated-user-id':'owner'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'events/subscribe',params:{name:EVENT,arguments:{repository:REPOSITORY},delivery:{mode:'webhook',url:'https://connectors.api.openai.com/callback',secret}}})}),env)).json();}
  const old='whsec_'+Buffer.alloc(32,1).toString('base64'),next='whsec_'+Buffer.alloc(32,2).toString('base64');
  const a=await subscribe(old),b=await subscribe(next);assert.equal(a.result.id,b.result.id);assert.equal(sent.length,2);
  const stored=JSON.parse(items.get('subscriptions/'+a.result.id));assert.equal(stored.previous_secret,old);assert.equal(stored.secret,next);assert.ok(stored.rotation_until>Date.now());
});
