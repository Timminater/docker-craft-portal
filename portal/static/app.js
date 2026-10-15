'use strict';
const root = document.getElementById('app');
const state = {setup:false,user:null,csrf:null,multiUser:false,appOriginConfigured:false,apps:[],admin:null,page:'apps',search:'',favs:[],poll:null,adminError:'',polling:false};
const e = x => String(x ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors = [['#9b65e8','#5a65ed'],['#2899e2','#2869bb'],['#f4a33d','#d45358'],['#32b89c','#217c8d'],['#e478a0','#a84d98'],['#7161d6','#bd69af'],['#17a08d','#2b72aa']];
const icons = {apps:'▦',admin:'⚙',users:'♙',events:'◷'};
function fmtTime(t){return t ? new Date(t*1000).toLocaleString('nl-NL',{dateStyle:'short',timeStyle:'short'}) : 'Nog nooit';}
function fmtBytes(n){return (n / 1024 / 1024).toFixed(1) + ' MB';}
function toast(message, bad=false){document.querySelector('.toast')?.remove();const el=document.createElement('div');el.className='toast'+(bad?' err':'');el.setAttribute('role',bad?'alert':'status');el.textContent=message;document.body.append(el);setTimeout(()=>el.remove(),5000);}
async function api(path, {method='GET', data=null,auth=true}={}) {
  const headers={'X-Craft-Client':'portal-v1'};
  if(data!==null)headers['Content-Type']='application/json';
  if(auth && state.csrf && method!=='GET')headers['X-Craft-CSRF']=state.csrf;
  const r=await fetch(path,{method,headers,body:data===null?undefined:JSON.stringify(data),credentials:'same-origin',cache:'no-store'});
  if(!r.ok){let err={};try{err=await r.json();}catch{};
    if(r.status===401 && auth){state.user=null;state.csrf=null;render();}
    throw new Error(typeof err.detail==='string'?err.detail:`HTTP ${r.status}`);
  }
  return r.json();
}
function userFavorites(){try{return JSON.parse(localStorage.getItem(`craft:favs:${state.user.public_id}`)||'[]');}catch{return [];}}
function saveFaves(){localStorage.setItem(`craft:favs:${state.user.public_id}`,JSON.stringify(state.favs));}
async function init(){try{let b=await api('/api/bootstrap',{auth:false});state.setup=b.setup_required;state.user=b.user;state.csrf=b.csrf;state.multiUser=b.multi_user;state.appOriginConfigured=b.app_origin_configured;if(state.user){state.favs=userFavorites();await loadApps();}render();}catch(ex){root.innerHTML='<div class="boot">Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina.</div>';}}
async function loadApps(){const a=await api('/api/apps');state.apps=a.apps;}
async function loadAdmin(){state.admin=await api('/api/admin/status');}
function brand(){return `<div class="brand"><div class="brand-mark">✦</div><strong>Craft Portal</strong></div>`;}
function shell(content){return `<div class="app-shell"><aside class="sidebar">${brand()}<nav class="nav" aria-label="Hoofdnavigatie">
 ${[['apps','Applicaties'],['admin','Beheer'],['users','Gebruikers'],['events','Activiteiten']].filter(x=>x[0]==='apps'||state.user.role==='admin').map(([id,label])=>`<button class="${state.page===id?'active':''}" data-page="${id}" aria-label="${label}" aria-current="${state.page===id?'page':'false'}"><span>${icons[id]}</span><span class="nav-label">${label}</span></button>`).join('')}</nav>
 <div class="sidebar-bottom"><div class="small muted">Zelf gehost • Privé</div><button class="ghost" style="margin-top:10px" id="logout">↪ Uitloggen</button></div></aside>
 <main class="main"><div class="top"><div><span class="upper">ARTCRAFT APPLICATIES</span><h1>${e(({apps:'Mijn applicaties',admin:'Systeembeheer',users:'Gebruikersbeheer',events:'Activiteitenlog'})[state.page])}</h1></div><div class="top-right"><span class="small muted">${e(state.user.username)}</span><div class="avatar">${e(state.user.username[0].toUpperCase())}</div></div></div>${content}</main></div>`;}
function authScreen(){const setup=state.setup;return `<div class="auth-wrap"><div class="auth-card">${brand()}
  <h1>${setup?'Welkom bij Craft Portal':'Log in op Craft Portal'}</h1>
  <p class="muted">${setup?'Maak je beveiligde beheerdersaccount aan.':'Al je creatieve applicaties, op één plek.'}</p>
  <form id="auth-form" class="stack">
  ${setup?`<div class="field"><label for="code">Eenmalige installatiecode</label><input id="code" name="code" autocomplete="off" required placeholder="Bekijk de Docker-logs"></div>`:''}
  <div class="field"><label for="username">Gebruikersnaam</label><input id="username" name="username" autocomplete="username" required minlength="3" maxlength="48" autofocus></div>
  <div class="field"><label for="password">Wachtwoord</label><input id="password" type="password" name="password" autocomplete="${setup?'new-password':'current-password'}" required minlength="${setup?12:1}"></div>
  <button class="primary" type="submit">${setup?'Beheerdersaccount aanmaken':'Inloggen'} →</button></form>
  ${setup?'<div class="notice"><strong>Eerste installatie</strong><ol><li>Bekijk de containerlogs voor de eenmalige installatiecode.</li><li>Kies een beheerdersnaam en een wachtwoord van minimaal 12 tekens.</li><li>Na het aanmaken controleert de portal automatisch de officiële applicaties. Bekijk de voortgang onder Beheer.</li></ol>Na de eerste installatie vervalt de code. Bewaar deze niet in gedeelde documenten.</div>':'<div class="notice">Je bewerkingen vinden lokaal in je browser plaats. Sla documenten op of maak back-ups voordat je het tabblad sluit.</div>'}
  </div></div>`;}
function card(app){const i=state.apps.findIndex(x=>x.slug===app.slug);const [a,b]=colors[i%colors.length];const ready=!!app.active_version&&!app.disabled;return `<article class="app-card"><div class="card-head"><div class="app-logo" style="--logo-a:${a};--logo-b:${b}">${e(app.name.substring(0,2))}</div>
 <button class="fav ${state.favs.includes(app.slug)?'isfav':''}" data-fav="${e(app.slug)}" title="Favoriet" aria-label="${e(app.name)} als favoriet" aria-pressed="${state.favs.includes(app.slug)}">${state.favs.includes(app.slug)?'★':'☆'}</button></div>
 <h3>${e(app.name)}</h3><p>${e(app.description)}</p><div style="margin:12px 0">${ready?`<span class="pill ok">● v${e(app.active_version.replace(/^v/,''))}</span>`:`<span class="pill warn">${app.disabled?'Uitgeschakeld':'Installatie wordt voorbereid'}</span>`}</div>
 <div class="card-footer"><span class="tiny muted">${app.latest_version?`Release ${e(app.latest_version)}`:'Nog niet geïnstalleerd'}</span><div class="card-actions"><button class="mini" data-download="${e(app.slug)}" aria-label="Desktopversie downloaden" title="Desktopversie">↓</button><button class="primary" data-open="${e(app.slug)}" ${ready&&state.appOriginConfigured?'':'disabled'}>Openen ↗</button></div></div></article>`;}
function appsPage(){let list=state.apps.filter(x=>!x.disabled).filter(x=>(x.name+' '+x.description).toLowerCase().includes(state.search.toLowerCase())).sort((a,b)=>Number(state.favs.includes(b.slug))-Number(state.favs.includes(a.slug))||a.name.localeCompare(b.name));const ready=state.apps.filter(x=>x.active_version&&!x.disabled).length;return `<section class="hero"><div class="tag">✦ JOUW CREATIEVE WERKOMGEVING</div><h2>Alles wat je nodig hebt.<br>Gewoon in je browser.</h2><p>Open een app zonder installatie, of download de volledige desktopversie. Je eigen Craft Portal houdt de webapps up-to-date.</p><div class="row"><span class="pill ok">● ${ready} apps beschikbaar</span><span class="pill">Open source</span></div></section>
 <div class="section-head"><div><h2>Ontdek applicaties</h2><p class="small muted">Foto's, documenten, video, audio, design en meer</p></div><label class="searchbar">⌕ <input id="search" type="search" value="${e(state.search)}" placeholder="Zoek applicaties" aria-label="Zoek applicaties"></label></div>
 ${!state.appOriginConfigured?'<div class="alert">Configureer een apart app-domein (CRAFT_SINGLE_APP_URL of CRAFT_APPS_DOMAIN) om WebAssembly-apps veilig gescheiden van het beheerdersportaal te openen.</div>':''}
 <div id="app-results">${list.length?`<div class="app-grid">${list.map(card).join('')}</div>`:`<div class="empty">${state.apps.length?'Geen applicaties gevonden.':'De eerste controle wordt uitgevoerd. Gecontroleerde apps verschijnen hier vanzelf.'}</div>`}</div>`;}
function adminPage(){if(!state.admin)return '<div class="boot">Beheerinformatie laden…</div>';const a=state.admin;const s=a.settings;return `<div class="stats"><div class="stat"><span class="upper">Geïnstalleerde apps</span><strong>${a.apps.filter(x=>x.active_version).length}</strong></div><div class="stat"><span class="upper">Actieve download</span><strong>${a.running?'Ja':'Nee'}</strong></div><div class="stat"><span class="upper">Schijfruimte</span><strong>${fmtBytes(a.bytes)}</strong></div><div class="stat"><span class="upper">Accounts</span><strong>${a.users}</strong></div></div>
 <div id="admin-refresh-status" role="status">${state.adminError?`<div class="alert error">Status vernieuwen mislukt. ${e(state.adminError)} <button class="secondary" id="retry-admin">Opnieuw proberen</button></div>`:''}</div>
 <section class="panel"><div id="update-summary"><div class="row between"><div><h2>Update Manager</h2><p class="small muted">Laatste controle: ${fmtTime(a.last_check)} · ${e(a.last_result)}</p></div><button class="primary" id="run-update" ${a.running?'disabled':''}>${a.running?'⟳ Controle bezig':'⟳ Nu controleren'}</button></div>${a.running?'<p class="small muted" role="status" style="margin-top:12px">Officiële releases worden gecontroleerd en waar nodig geïnstalleerd. Dit kan enkele minuten duren.</p><progress aria-label="Updatecontrole bezig" style="width:100%;margin-top:8px"></progress>':''}</div>
 <form id="settings-form" class="stack" style="margin-top:26px"><div class="form-grid"><div class="field"><label for="interval">Controle-interval</label><select name="interval" id="interval">${[1,3,6,12,24].map(x=>`<option value="${x}" ${s.update_interval_hours==x?'selected':''}>Iedere ${x} uur</option>`).join('')}</select></div>
 <div class="field"><label for="keep">Eerdere versies bewaren</label><select name="keep" id="keep">${[0,1,2,3,5].map(x=>`<option value="${x}" ${s.keep_previous_versions==x?'selected':''}>${x} vorige versie${x===1?'':'s'}</option>`).join('')}</select></div></div>
 <label class="row"><input type="checkbox" name="auto" ${s.auto_install_versions==='true'?'checked':''}> Nieuwe versies automatisch installeren</label>
 <label class="row"><input type="checkbox" name="discover" ${s.auto_discover_apps==='true'?'checked':''}> Nieuwe officiële apps automatisch toevoegen</label>
 <div><button class="secondary" type="submit">Instellingen opslaan</button></div></form></section>
 <section class="panel" id="app-management"><div class="section-head"><div><h2>Applicatiebeheer</h2><p class="small muted">Versies, foutmeldingen en terugrollen</p></div></div><div class="table-wrap"><table><thead><tr><th>Applicatie</th><th>Actieve versie</th><th>Laatste release</th><th>Status</th><th>Beheer</th></tr></thead><tbody>${a.apps.map(x=>`<tr><td><strong>${e(x.slug)}</strong>${x.last_error?`<p class="tiny" style="color:var(--error)">${e(x.last_error)}</p>`:''}</td><td>${e(x.active_version||'—')}</td><td>${e(x.latest_version||'—')}</td><td><span class="status"><span class="dot ${x.last_error?'warn':!x.active_version?'bad':''}"></span>${x.disabled?'Uit':x.active_version?'Gereed':'Wachten'}</span></td><td><div class="row"><button class="mini" data-versions="${e(x.slug)}" title="Versies" aria-label="Versies van ${e(x.slug)}">◷</button><button class="mini" data-pause="${e(x.slug)}" data-paused="${x.auto_update}" title="Automatische updates pauzeren/hervatten" aria-label="Automatische updates voor ${e(x.slug)} ${x.auto_update?'pauzeren':'hervatten'}">${x.auto_update?'Ⅱ':'▶'}</button></div></td></tr>`).join('')}</tbody></table></div></section>
 <div class="notice">Updates van WebAssembly-apps wijzigen geen persoonlijke bestanden op de server. Sommige Craft-apps bewaren documenten alleen in de browser. Maak waar nodig apart back-ups.</div>`;}
function usersPage(){if(!state.multiUser)return `<div class="panel"><h2>Een veilige single-userinstallatie</h2><p class="muted" style="margin-top:8px">Extra accounts zijn nog niet toegestaan. De ArtCraft-apps bewaren browserdata per website, niet per ingelogde gebruiker. Configureer CRAFT_APPS_DOMAIN met wildcard-DNS en HTTPS om gebruikersaccounts veilig te scheiden.</p></div>`;
 return `<div class="panel"><h2>Nieuw account</h2><form id="new-user" class="stack" style="margin-top:20px"><div class="form-grid"><div class="field"><label for="new-username">Gebruikersnaam</label><input id="new-username" autocomplete="username" name="username" required minlength="3" maxlength="48"></div><div class="field"><label for="new-role">Rol</label><select id="new-role" name="role"><option value="user">Gebruiker</option><option value="admin">Administrator</option></select></div></div><div class="field"><label for="new-password">Initieel wachtwoord (min. 12 tekens)</label><input id="new-password" type="password" name="password" minlength="12" required autocomplete="new-password"></div><div><button class="primary">Gebruiker toevoegen</button></div></form></div><div id="users-list" class="panel">Accounts laden…</div>`;}
function eventsPage(){return `<div class="panel"><div class="section-head"><div><h2>Systeemactiviteit</h2><p class="small muted">De laatste 120 gebeurtenissen</p></div><button id="refresh-events" class="secondary">Vernieuwen</button></div><div id="events-list">Laden…</div></div>`;}
function render(){if(!state.user){closeModal();root.innerHTML=authScreen();return;}root.innerHTML=shell(({apps:appsPage,admin:adminPage,users:usersPage,events:eventsPage})[state.page]()); if(state.page==='users'&&state.multiUser)refreshUsers();if(state.page==='events')refreshEvents();}
async function refreshUsers(){try{const r=await api('/api/admin/users');const el=document.getElementById('users-list');if(!el)return;el.innerHTML=`<h2>Accounts</h2><div class="table-wrap"><table><thead><tr><th>Gebruikersnaam</th><th>Rol</th><th>Status</th><th>Actie</th></tr></thead><tbody>${r.users.map(u=>`<tr><td>${e(u.username)}</td><td>${e(u.role)}</td><td>${u.enabled?'Actief':'Uitgeschakeld'}</td><td>${u.enabled&&u.id!==state.user.id?`<button class="danger" data-disable-user="${u.id}">Uitschakelen</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`;}catch(ex){toast(ex.message,true);}}
async function refreshEvents(){try{const r=await api('/api/admin/events');const el=document.getElementById('events-list');if(!el)return;el.innerHTML=`<div class="table-wrap"><table><thead><tr><th>Tijd</th><th>Niveau</th><th>Gebeurtenis</th><th>Details</th></tr></thead><tbody>${r.events.map(x=>`<tr><td>${fmtTime(x.at)}</td><td>${e(x.level)}</td><td>${e(x.action)} ${x.slug?`· ${e(x.slug)}`:''}</td><td>${e(x.detail)}</td></tr>`).join('')}</tbody></table></div>`;}catch(ex){toast(ex.message,true);}}
async function openApp(slug){const {url}=await api(`/api/apps/${encodeURIComponent(slug)}/launch`,{method:'POST'});window.open(url,'_blank','noopener,noreferrer');}
function preferredInstaller(assets){
 const ua=navigator.userAgent.toLowerCase();
 let pattern = ua.includes('windows') ? /windows-x64\.msi$/ : ua.includes('mac') ? /macos-universal\.dmg$/ : /linux-x86_64\.AppImage$/;
 return assets.find(a=>pattern.test(a.name)) || assets[0] || null;
}
let modalOpener=null;
function closeModal(){
 document.querySelector('.modal-back')?.remove();
 root.inert=false;
 document.body.classList.remove('modal-open');
 if(modalOpener?.isConnected)modalOpener.focus();
 else if(modalOpener){const heading=root.querySelector('h1');if(heading){heading.tabIndex=-1;heading.focus();}}
 modalOpener=null;
}
function showModal(el){
 closeModal();
 modalOpener=document.activeElement;
 root.inert=true;
 document.body.classList.add('modal-open');
 document.body.append(el);
 el.querySelector('#close-modal').focus();
 el.addEventListener('click',event=>{if(event.target===el||event.target.closest('#close-modal'))closeModal();});
 el.addEventListener('keydown',event=>{
  if(event.key==='Escape'){event.preventDefault();closeModal();return;}
  if(event.key!=='Tab')return;
  const items=[...el.querySelectorAll('button:not(:disabled),select:not(:disabled),input:not(:disabled),a[href],summary,[tabindex="0"]')].filter(x=>x.getClientRects().length);
  const first=items[0],last=items[items.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
 });
}
async function downloads(slug){
 const r=await api(`/api/apps/${encodeURIComponent(slug)}/downloads`);
 const preferred=preferredInstaller(r.assets);const el=document.createElement('div');el.className='modal-back';
 el.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-label="Native download"><div class="row between"><h2>Download ${e(slug)}</h2><button class="mini" id="close-modal" aria-label="Sluiten">×</button></div>
 <p class="muted small" style="margin-bottom:16px">Download de officiële native applicatie voor je computer, zonder de browseromgeving.</p>
 ${preferred?`<div class="panel" style="background:#1b3044"><div class="small muted">Aanbevolen voor dit apparaat</div><strong style="display:block;margin:6px 0 14px">${e(preferred.name)}</strong><a class="primary" href="${e(preferred.url)}" target="_blank" rel="noopener noreferrer">↓ Download installatiebestand</a></div>`:''}
 <div class="field"><label for="installer-platform">Platform</label><select id="installer-platform"><option value="all">Alle platforms</option><option value="windows">Windows</option><option value="macos">macOS</option><option value="linux">Linux</option></select></div>
 <div id="installer-results" class="stack" aria-live="polite"></div>
 <a class="secondary" style="margin-top:18px" href="${e(r.github)}" target="_blank" rel="noopener noreferrer">Officiële releases op GitHub ↗</a></div>`;
 const platform=el.querySelector('#installer-platform');
 const updateInstallers=()=>{
  const assets=r.assets.filter(a=>platform.value==='all'||installerPlatform(a.name)===platform.value);
  el.querySelector('#installer-results').innerHTML=assets.length?assets.map(a=>`<a class="version-chip" href="${e(a.url)}" target="_blank" rel="noopener noreferrer"><span>${e(a.name)}</span><span>↗</span></a>`).join(''):'Geen installers voor dit platform beschikbaar.';
 };
 platform.addEventListener('change',updateInstallers);updateInstallers();
 showModal(el);
}
function installerPlatform(name){
 if(/windows|\.(?:msi|exe)$/i.test(name))return 'windows';
 if(/macos|darwin|\.(?:dmg|pkg)$/i.test(name))return 'macos';
 if(/linux|\.(?:appimage|deb|rpm)$/i.test(name))return 'linux';
 return 'other';
}
async function versions(slug){const r=await api(`/api/admin/apps/${encodeURIComponent(slug)}/versions`);const active=state.admin.apps.find(x=>x.slug===slug)?.active_version;const el=document.createElement('div');el.className='modal-back';el.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-label="Versiebeheer"><div class="row between"><h2>Versies van ${e(slug)}</h2><button class="mini" id="close-modal" aria-label="Sluiten">×</button></div><p class="muted small">Rollback wijzigt niet automatisch de documenten en browseropslag. Automatische updates voor deze app worden na rollback gepauzeerd.</p><div class="stack">${r.versions.map(v=>`<div class="version-chip"><span>${e(v.version)} ${v.version===active?'(actief)':''}</span>${v.version===active?'<span class="pill ok">Actief</span>':`<button class="secondary" data-rollback="${e(slug)}" data-version="${e(v.version)}">Activeren</button>`}</div>`).join('')||'Geen eerdere versies beschikbaar.'}</div></div>`;showModal(el);}
root.addEventListener('submit', async event=>{
  const form=event.target;
  if(!['auth-form','settings-form','new-user'].includes(form.id))return;
  event.preventDefault();const data=new FormData(form);const button=form.querySelector('button[type=submit],button.primary,button.secondary');if(button)button.disabled=true;
  try{
    if(form.id==='auth-form'){
      const payload={username:data.get('username'),password:data.get('password')};
      if(state.setup)payload.code=data.get('code');
      await api(state.setup?'/api/setup':'/api/login',{method:'POST',data:payload,auth:false});await init();toast('Welkom bij Craft Portal');
    } else if(form.id==='settings-form'){
      await api('/api/admin/settings',{method:'PUT',data:{update_interval_hours:Number(data.get('interval')),keep_previous_versions:Number(data.get('keep')),auto_install_versions:data.get('auto')==='on',auto_discover_apps:data.get('discover')==='on'}});
      await loadAdmin();render();toast('Instellingen opgeslagen');
    } else if(form.id==='new-user'){
      await api('/api/admin/users',{method:'POST',data:{username:data.get('username'),password:data.get('password'),role:data.get('role')}});
      form.reset();refreshUsers();toast('Gebruiker toegevoegd');
    }
  }catch(ex){toast(ex.message,true);}finally{if(button)button.disabled=false;}
});
root.addEventListener('input', event=>{if(event.target.id==='search'){
 state.search=event.target.value;
 const results=document.getElementById('app-results');
 const apps=state.apps.filter(x=>!x.disabled&&(x.name+' '+x.description).toLowerCase().includes(state.search.toLowerCase())).sort((a,b)=>Number(state.favs.includes(b.slug))-Number(state.favs.includes(a.slug))||a.name.localeCompare(b.name));
 if(results)results.innerHTML=apps.length?`<div class="app-grid">${apps.map(card).join('')}</div>`:'<div class="empty" role="status">Geen applicaties gevonden.</div>';
}});
document.addEventListener('click',async event=>{
 const target=event.target.closest('button');if(!target||(!root.contains(target)&&!target.closest('.modal-back')))return;
 try{
  if(target.dataset.page){state.page=target.dataset.page;if(state.page==='admin')await loadAdmin();render();const heading=root.querySelector('h1');heading.tabIndex=-1;heading.focus();}
  else if(target.id==='logout'){await api('/api/logout',{method:'POST'});state.user=null;state.csrf=null;state.admin=null;state.page='apps';render();}
  else if(target.dataset.fav){const slug=target.dataset.fav;state.favs=state.favs.includes(slug)?state.favs.filter(x=>x!==slug):[...state.favs,slug];saveFaves();render();root.querySelectorAll('[data-fav]').forEach(button=>{if(button.dataset.fav===slug)button.focus();});}
  else if(target.dataset.open){await openApp(target.dataset.open);}
  else if(target.dataset.download){await downloads(target.dataset.download);}
  else if(target.id==='run-update'){target.disabled=true;try{await api('/api/admin/check',{method:'POST'});toast('Updatecontrole gestart');await refreshAdmin();}finally{if(target.isConnected)target.disabled=!!state.admin?.running;}}
  else if(target.id==='retry-admin'){await refreshAdmin();}
  else if(target.dataset.versions){await versions(target.dataset.versions);}
  else if(target.dataset.rollback){if(confirm(`Versie ${target.dataset.version} activeren?`)){await api(`/api/admin/apps/${target.dataset.rollback}/rollback`,{method:'POST',data:{version:target.dataset.version}});closeModal();await loadAdmin();await loadApps();render();toast('Versie teruggezet');}}
  else if(target.dataset.pause){const slug=target.dataset.pause;await api(`/api/admin/apps/${slug}`,{method:'PUT',data:{auto_update:target.dataset.paused==='0'}});await loadAdmin();render();toast('App-instellingen aangepast');}
  else if(target.dataset.disableUser){if(confirm('Dit account en alle sessies uitschakelen?')){await api(`/api/admin/users/${target.dataset.disableUser}/disable`,{method:'PUT'});await refreshUsers();toast('Account uitgeschakeld');}}
  else if(target.id==='refresh-events'){refreshEvents();}
 }catch(ex){toast(ex.message,true);}
});
function updateAdminView(){
 if(!state.user||state.page!=='admin')return;
 const view=document.createElement('div');view.innerHTML=adminPage();
 // Keep unsaved settings and keyboard focus in the live form intact.
 for(const selector of ['.stats','#update-summary','#app-management','#admin-refresh-status']){
  const current=root.querySelector(selector),fresh=view.querySelector(selector);
  if(current&&fresh&&current.innerHTML!==fresh.innerHTML){
   if(current.contains(document.activeElement)&&!['run-update','retry-admin'].includes(document.activeElement.id))continue;
   const focusId=current.contains(document.activeElement)?document.activeElement.id:null;
   current.innerHTML=fresh.innerHTML;
   if(focusId)document.getElementById(focusId)?.focus();
  }
 }
}
async function refreshAdmin(){
 if(state.polling)return;
 state.polling=true;
 try{
  await loadAdmin();
  await loadApps();
  state.adminError='';
 }catch(ex){if(state.user)state.adminError=ex.message;}
 finally{state.polling=false;updateAdminView();}
}
setInterval(async()=>{
 if(!state.user)return;
 if(state.page==='admin'){await refreshAdmin();return;}
 if(state.page==='apps'){
  try{
   const before=JSON.stringify(state.apps);await loadApps();
   if(before!==JSON.stringify(state.apps)&&state.page==='apps'){
    const results=document.getElementById('app-results');
    if(results&&!results.contains(document.activeElement)){
     const view=document.createElement('div');view.innerHTML=appsPage();
     results.innerHTML=view.querySelector('#app-results').innerHTML;
     const hero=root.querySelector('.hero');if(hero)hero.innerHTML=view.querySelector('.hero').innerHTML;
    }
   }
  }catch{}
 }
},12000);
init();
