/* Durable intents, never an alternative sales/stock/finance ledger. */
(function(root){
  'use strict';
  const NAME='vertyx-pdv-intents-v1';
  function db(){return new Promise((resolve,reject)=>{const r=indexedDB.open(NAME,1);r.onupgradeneeded=()=>{r.result.createObjectStore('state');r.result.createObjectStore('sales',{keyPath:'request_id'});};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function run(store,mode,operation){const d=await db();return new Promise((resolve,reject)=>{const t=d.transaction(store,mode),r=operation(t.objectStore(store));let result;r.onsuccess=()=>{result=r.result;};t.oncomplete=()=>{d.close();resolve(result);};t.onerror=t.onabort=()=>{d.close();reject(t.error||r.error);};});}
  const owner=(a,b)=>Boolean(a&&b&&a.organization===b.organization&&a.user===b.user);
  const state={get:key=>run('state','readonly',s=>s.get(key)),put:(key,value)=>run('state','readwrite',s=>s.put(value,key))};
  async function putSale(value){const d=await db();return new Promise((resolve,reject)=>{const t=d.transaction('sales','readwrite'),s=t.objectStore('sales'),read=s.get(value.request_id);read.onsuccess=()=>{if(read.result?.status!=='CONFIRMADA')s.put(value);};t.oncomplete=()=>{d.close();resolve();};t.onerror=t.onabort=()=>{d.close();reject(t.error);};});}
  const sales={all:()=>run('sales','readonly',s=>s.getAll()),put:putSale};
  async function enqueue(payload){await run('sales','readwrite',s=>s.add({request_id:payload.request_id,payload,status:'PENDENTE',created:new Date().toISOString(),error:''}));}
  async function sync(fetcher=root.fetch.bind(root)){
    let response;try{response=await fetcher('/pdv/offline/contexto/',{credentials:'same-origin',cache:'no-store',redirect:'error'});}catch(_){return 'UNREACHABLE';}
    if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))return 'AUTH_REQUIRED';
    const identity=await response.json();
    for(const row of await sales.all()){
      if(!owner(row.payload,identity)||!['PENDENTE','ENVIANDO'].includes(row.status))continue;
      row.status='ENVIANDO';await sales.put(row);
      try{
        const result=await fetcher('/pdv/sincronizacao/',{method:'POST',credentials:'same-origin',redirect:'error',headers:{'Content-Type':'application/json','X-CSRFToken':identity.csrf},body:JSON.stringify(row.payload)});
        if(!result.headers.get('content-type')?.includes('application/json')){row.status='PENDENTE';row.error='Entre novamente com o operador original.';await sales.put(row);break;}
        const data=await result.json();
        if(result.ok){row.status='CONFIRMADA';row.receipt=data.receipt;row.error='';}
        else if([400,403,409].includes(result.status)){row.status='CONFLITO';row.error=data.error||'Revisão necessária.';}
        else{row.status='PENDENTE';row.error='Servidor indisponível. Nova tentativa automática.';}
      }catch(_){row.status='PENDENTE';row.error='Sem confirmação. Nova tentativa usará o mesmo identificador.';}
      await sales.put(row);
    }
    return 'CONNECTED';
  }
  root.PDVOutbox={state,sales,owner,enqueue,sync};
})(globalThis);
