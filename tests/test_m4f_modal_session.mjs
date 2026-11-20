#!/usr/bin/env node
// Offline smoke test for M4F cookie-based modal lookup. Does not call any API.
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const file = process.argv[2] || 'app/static/js/consultation-modal.js';
const {initConsultation} = await import(pathToFileURL(path.resolve(file)).href);

function createDom() {
  const elements = new Map();
  function el(id) {
    if (elements.has(id)) return elements.get(id);
    const item = {
      id, hidden: false, value: '', textContent: '', required: false, disabled: false,
      dataset: {}, files: [], open: false, style: {},
      after() {}, append() {}, appendChild() {}, setAttribute() {}, closest() {return null;},
      addEventListener() {},
      getBoundingClientRect() {return {left:0,right:100,top:0,bottom:100};},
      showModal() {this.open = true;},
      close() {this.open = false;},
      checkValidity() {return true;},
      focus() {},
      querySelectorAll() {return [];},
      querySelector(sel) {
        if (sel === 'input[name="consultation-mode"]:checked') return {value:'qrng'};
        if (sel === 'input[name="consultation-style"]:checked') return {value:'direct'};
        if (sel.includes('consultation-qrng-provider') && sel.includes('nist')) return el('nist-radio');
        return null;
      },
    };
    elements.set(id,item);
    return item;
  }
  globalThis.document = {getElementById:el,createElement:tag=>el(`node-${tag}`),createTextNode:t=>({textContent:t})};
  globalThis.MutationObserver = class {observe() {}};
  globalThis.fetch = async url => {
    assert.equal(url, '/api/v1/services/catalog');
    return {ok:true,json:async()=>({services:[]})};
  };
  globalThis.window = {dispatchEvent() {}};
  return el;
}

async function scenario(result, expectSignedIn) {
  const el = createDom();
  let requests = [];
  const dialog = initConsultation({
    async lookupAccount(payload) {requests.push(payload); return result;},
    async onSubmit() {return false;},
  });
  dialog.open();
  // Yield to the resolved Promise in verifyAccount().
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 1, 'expected exactly one cookie-session lookup');
  assert.equal(requests[0].accountCode, null);
  assert.equal(requests[0].keyFile, null);
  assert.equal(el('consultation-auth').hidden, expectSignedIn,
    'keyfile controls should be hidden only when authenticated');
  assert.equal(el('consultation-balance').textContent.startsWith('Signed in'), expectSignedIn);
  if (expectSignedIn) assert.match(el('consultation-balance').textContent, /40 credits available/);
}

await scenario({verified:true,credits:40}, true);
await scenario({verified:false,message:'Login required'}, false);
console.log('M4F modal cookie-session smoke tests: 2 passed');
