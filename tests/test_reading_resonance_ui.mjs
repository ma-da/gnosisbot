// Minimal DOM and fetch fixture; no network or browser required.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
class Element {
  constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.listeners={};this.disabled=false;this.textContent='';}
  setAttribute(k,v){this.attrs[k]=String(v);}
  append(...nodes){this.children.push(...nodes);}
  addEventListener(k,fn){this.listeners[k]=fn;}
  click(){if(!this.disabled)this.listeners.click?.();}
}
globalThis.document={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)};
const src=readFileSync(process.argv[2]||'app/static/js/reading-resonance.js','utf8');
const {faceButton}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
const item={consultation_id:'a'.repeat(32),status:'completed',resonance:{resonated:false}};
assert.equal(faceButton({...item,status:'pending'}),null);assert.equal(faceButton({...item,resonance:undefined}),null);
const wrap=faceButton(item),btn=wrap.children[0],mouth=btn.children[0].children[2],note=wrap.children[1];
assert.equal(btn.attrs['aria-pressed'],'false');const frown=mouth.attrs.d;
let calls=0, resolve;
globalThis.fetch=(url,options)=>{calls++;assert.equal(url,`/api/v1/accounts/readings/${item.consultation_id}/resonance`);assert.equal(options.method,'PUT');assert.equal(options.credentials,'same-origin');assert.equal(JSON.parse(options.body).resonated,true);return new Promise(r=>resolve=r);};
btn.click();assert.equal(btn.disabled,true);btn.click();assert.equal(calls,1);
const rerender=faceButton(item).children[0];assert.equal(rerender.disabled,true);
resolve({ok:true,json:async()=>({resonated:true})});await new Promise(r=>setImmediate(r));
assert.equal(btn.attrs['aria-pressed'],'true');assert.equal(rerender.attrs['aria-pressed'],'true');assert.notEqual(mouth.attrs.d,frown);assert.equal(btn.disabled,false);
globalThis.fetch=async(url,options)=>{assert.equal(JSON.parse(options.body).resonated,false);return {ok:true,json:async()=>({resonated:false})};};
btn.click();await new Promise(r=>setImmediate(r));assert.equal(btn.attrs['aria-pressed'],'false');assert.equal(mouth.attrs.d,frown);
globalThis.fetch=async()=>({ok:false});btn.click();await new Promise(r=>setImmediate(r));assert.equal(btn.attrs['aria-pressed'],'false');assert.match(note.textContent,/Could not save/);assert.equal(btn.disabled,false);
assert.equal(faceButton({...item,resonance:{resonated:true}}).children[0].attrs['aria-pressed'],'true');
console.log('PASS: default, toggle, persistence rendering, in-flight deduplication, rerender, failed save, pending exclusion');
