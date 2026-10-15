(() => {
  'use strict';
  const portalOrigin=document.querySelector('meta[name="craft-portal-origin"]')?.content;
  const slug=document.querySelector('meta[name="craft-app-slug"]')?.content;
  if(window.parent===window||!slug||!/^[a-z0-9][a-z0-9-]*$/.test(slug))return;
  try{if(new URL(portalOrigin).origin!==portalOrigin)return;}catch{return;}
  const storage=navigator.storage;
  const supported={estimate:typeof storage?.estimate==='function',persisted:typeof storage?.persisted==='function',persist:typeof storage?.persist==='function'};
  const send=data=>window.parent.postMessage(data,portalOrigin);
  const number=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=Number.MAX_SAFE_INTEGER?Math.round(value):null;
  const errorName=error=>['NotAllowedError','SecurityError','InvalidStateError','NotSupportedError','AbortError'].includes(error?.name)?error.name:'Unavailable';
  let busy=false;
  window.addEventListener('message',async event=>{
    const request=event.data;
    if(event.origin!==portalOrigin||event.source!==window.parent||!request||request.type!=='craft-storage-request'||request.slug!==slug||
       typeof request.id!=='string'||!/^[A-Za-z0-9_-]{8,100}$/.test(request.id)||!['estimate','persist'].includes(request.action))return;
    const result={type:'craft-storage-result',slug,id:request.id,usage:null,quota:null,persisted:null,supported,error:null};
    if(busy){result.error='Busy';send(result);return;}
    busy=true;
    try{
      if(request.action==='persist'){
        if(supported.persist){try{result.persisted=await storage.persist();}catch(error){result.error=errorName(error);}}
        else result.error='NotSupportedError';
      }
      if(supported.estimate){
        try{const estimate=await storage.estimate();result.usage=number(estimate.usage);result.quota=number(estimate.quota);}
        catch(error){result.error=result.error||errorName(error);}
      }
      if(supported.persisted){try{result.persisted=await storage.persisted();}catch(error){result.error=result.error||errorName(error);}}
      // Only aggregate metadata leaves this origin. No keys, filenames, database
      // names or documents are enumerated, read, modified or deleted.
      send(result);
    }finally{busy=false;}
  });
  send({type:'craft-storage-ready',slug});
})();
