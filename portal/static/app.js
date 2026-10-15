'use strict';
const {t, locale, errorMessage, updaterResult} = CraftI18n;
const root = document.getElementById('app');
const state = {setup:false,user:null,csrf:null,multiUser:false,appOriginConfigured:false,appOriginMode:'',apps:[],admin:null,page:'apps',search:'',favs:[],appOrder:[],poll:null,adminError:'',polling:false};
const e = x => String(x ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors = [['#9b65e8','#5a65ed'],['#2899e2','#2869bb'],['#f4a33d','#d45358'],['#32b89c','#217c8d'],['#e478a0','#a84d98'],['#7161d6','#bd69af'],['#17a08d','#2b72aa']];
const icons = {apps:'▦',admin:'⚙',users:'♙',events:'◷'};
function fmtTime(timestamp){return timestamp ? new Date(timestamp*1000).toLocaleString(locale,{dateStyle:'short',timeStyle:'short'}) : t("Nog nooit");}
function fmtBytes(n){return new Intl.NumberFormat(locale,{minimumFractionDigits:1,maximumFractionDigits:1}).format(n / 1024 / 1024) + ' MB';}
function toast(message, bad=false){document.querySelector('.toast')?.remove();const el=document.createElement('div');el.className='toast'+(bad?' err':'');el.setAttribute('role',bad?'alert':'status');el.textContent=message;document.body.append(el);setTimeout(()=>el.remove(),5000);}
async function api(path, {method='GET', data=null,auth=true}={}) {
  const headers={'X-Craft-Client':'portal-v1'};
  if(data!==null)headers['Content-Type']='application/json';
  if(auth && state.csrf && method!=='GET')headers['X-Craft-CSRF']=state.csrf;
  const r=await fetch(path,{method,headers,body:data===null?undefined:JSON.stringify(data),credentials:'same-origin',cache:'no-store'});
  if(!r.ok){let err={};try{err=await r.json();}catch{};
    if(r.status===401 && auth){resetWorkspace();state.user=null;state.csrf=null;render();}
    throw new Error(errorMessage(typeof err.detail==='string'?err.detail:`HTTP ${r.status}`));
  }
  return r.json();
}
function userFavorites(){try{return JSON.parse(localStorage.getItem(`craft:favs:${state.user.public_id}`)||'[]');}catch{return [];}}
function saveFaves(){localStorage.setItem(`craft:favs:${state.user.public_id}`,JSON.stringify(state.favs));}
async function init(){try{let b=await api('/api/bootstrap',{auth:false});state.setup=b.setup_required;if(state.user?.public_id!==b.user?.public_id)resetWorkspace();state.user=b.user;state.csrf=b.csrf;state.multiUser=b.multi_user;state.appOriginConfigured=b.app_origin_configured;state.appOriginMode=b.app_origin_mode||'';state.appOrder=[];if(state.user){state.favs=userFavorites();state.appOrder=(await api('/api/preferences')).app_order;await loadApps();}render();}catch(ex){root.innerHTML=`<div class="boot">${e(t("Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina."))}</div>`;}}
async function loadApps(){const a=await api('/api/apps');state.apps=a.apps;reconcileWorkspace();}
async function loadAdmin(){state.admin=await api('/api/admin/status');}
function brand(){return `<div class="brand"><div class="brand-mark">✦</div><strong>Craft Portal</strong></div>`;}
function shell(content){return `<div class="app-shell"><aside class="sidebar">${brand()}<nav class="nav" aria-label="${e(t("Hoofdnavigatie"))}">
 ${[['apps',t("Applicaties")],['admin',t("Beheer")],['users',t("Gebruikers")],['events',t("Activiteiten")]].filter(x=>x[0]==='apps'||state.user.role==='admin').map(([id,label])=>`<button class="${state.page===id?'active':''}" data-page="${id}" aria-label="${label}" aria-current="${state.page===id?'page':'false'}"><span>${icons[id]}</span><span class="nav-label">${label}</span></button>`).join('')}</nav>
 <div class="sidebar-bottom"><div class="small muted">${e(t("Zelf gehost • Privé"))}</div><button class="ghost mt-10" id="logout">${e(t("↪ Uitloggen"))}</button></div></aside>
 <main class="main"><div class="top"><div><span class="upper">${e(t("ARTCRAFT APPLICATIES"))}</span><h1>${e(({apps:t("Mijn applicaties"),admin:t("Systeembeheer"),users:t("Gebruikersbeheer"),events:t("Activiteitenlog")})[state.page])}</h1></div><div class="top-right"><span class="small muted">${e(state.user.username)}</span><div class="avatar">${e(state.user.username[0].toUpperCase())}</div></div></div>${content}</main></div>`;}
function authScreen(){const setup=state.setup;return `<div class="auth-wrap"><div class="auth-card">${brand()}
  <h1>${setup?t("Welkom bij Craft Portal"):t("Log in op Craft Portal")}</h1>
  <p class="muted">${setup?t("Maak je beveiligde beheerdersaccount aan."):t("Al je creatieve applicaties, op één plek.")}</p>
  <form id="auth-form" class="stack">
  ${setup?`<div class="field"><label for="code">${e(t("Eenmalige installatiecode"))}</label><input id="code" name="code" autocomplete="off" required placeholder="${e(t("Bekijk de Docker-logs"))}"></div>`:''}
  <div class="field"><label for="username">${e(t("Gebruikersnaam"))}</label><input id="username" name="username" autocomplete="username" required minlength="3" maxlength="48" autofocus></div>
  <div class="field"><label for="password">${e(t("Wachtwoord"))}</label><input id="password" type="password" name="password" autocomplete="${setup?'new-password':'current-password'}" required minlength="${setup?12:1}"></div>
  <button class="primary" type="submit">${setup?t("Beheerdersaccount aanmaken"):t("Inloggen")} →</button></form>
  ${setup?`<div class="notice"><strong>${e(t("Eerste installatie"))}</strong><ol><li>${e(t("Bekijk de containerlogs voor de eenmalige installatiecode."))}</li><li>${e(t("Kies een beheerdersnaam en een wachtwoord van minimaal 12 tekens."))}</li><li>${e(t("Na het aanmaken controleert de portal automatisch de officiële applicaties. Bekijk de voortgang onder Beheer."))}</li></ol>${e(t("Na de eerste installatie vervalt de code. Bewaar deze niet in gedeelde documenten."))}</div>`:`<div class="notice">${e(t("Je bewerkingen vinden lokaal in je browser plaats. Sla documenten op of maak back-ups voordat je het tabblad sluit."))}</div>`}
  </div></div>`;}
const appDescriptions = {solidcraft:'Parametrisch 3D-ontwerp en modelleren',photocraft:'Fotobewerking',paintcraft:'Fotobewerking',vectorcraft:'Vectorillustraties',filmcraft:'Videobewerking',lightcraft:"RAW-foto's en fotobibliotheek",pdfcraft:'PDF-bewerking',effectcraft:'Visuele effecten en animatie',designcraft:'Paginaopmaak en publicatie',figcraft:'Interfaceontwerp',wordcraft:'Tekstverwerking',soundcraft:'Audio en muziek',deckcraft:'Presentaties',cadcraft:'Technische tekeningen',gridcraft:'Spreadsheets'};
// Workflow references verified against each official storytold app README.
const appInspirations = {solidcraft:'Autodesk Fusion',photocraft:'Adobe Photoshop',vectorcraft:'Adobe Illustrator',filmcraft:'Adobe Premiere Pro',lightcraft:'Adobe Lightroom',pdfcraft:'Adobe Acrobat',effectcraft:'Adobe After Effects',designcraft:'Adobe InDesign',figcraft:'Figma',wordcraft:'Microsoft Word',soundcraft:'Avid Pro Tools',deckcraft:'Microsoft PowerPoint',cadcraft:'Autodesk AutoCAD',gridcraft:'Microsoft Excel'};
function inspiration(app){return appInspirations[app.slug] || '';}
function orderedApps(order=state.appOrder){const ranks=new Map(order.map((slug,index)=>[slug,index]));return state.apps.filter(app=>!app.disabled).sort((a,b)=>order.length?((ranks.get(a.slug)??Infinity)-(ranks.get(b.slug)??Infinity)||a.name.localeCompare(b.name,locale)):(Number(state.favs.includes(b.slug))-Number(state.favs.includes(a.slug))||a.name.localeCompare(b.name,locale)));}
function filteredApps(){const query=state.search.trim().toLocaleLowerCase(locale);return orderedApps().filter(app=>[app.name,app.slug,description(app),summary(app),category(app),inspiration(app)].join(' ').toLocaleLowerCase(locale).includes(query));}
function description(app){return t(appDescriptions[app.slug] || app.description || 'Creatieve applicatie');}
function category(app){const categories={solidcraft:'CAD',photocraft:'Photography',paintcraft:'Illustration',lightcraft:'Photography',vectorcraft:'Illustration',filmcraft:'Video',effectcraft:'Video',designcraft:'Design',figcraft:'Design',pdfcraft:'Documents',wordcraft:'Documents',soundcraft:'Audio',deckcraft:'Presentations',cadcraft:'CAD',gridcraft:'Spreadsheets'};return t(categories[app.slug]||'creativeTools');}
function summary(app){const type=app.slug.replace(/craft$/,'');return t('summary.'+(['photo','vector','film','light','pdf','effect','design','fig','word','sound','deck','cad','grid','solid'].includes(type)?type:'generic'));}
function artwork(slug){
 const drawings={
 photo:'<rect x="70" y="25" width="180" height="105" rx="9"/><circle cx="205" cy="52" r="13"/><path d="m75 115 58-61 40 39 23-23 49 45"/>',
 vector:'<path d="M65 115C100 0 216 140 255 30"/><path d="m65 115 32-66m158-19-32 66"/><rect x="57" y="107" width="16" height="16"/><rect x="247" y="22" width="16" height="16"/><circle cx="97" cy="49" r="7"/><circle cx="223" cy="96" r="7"/>',
 film:'<rect x="65" y="25" width="190" height="108" rx="9"/><path d="M65 50h190M90 25v25m35-25v25m35-25v25m35-25v25m35-25v25"/><path d="m141 70 38 23-38 23Z"/>',
 document:'<rect x="103" y="14" width="114" height="128" rx="7"/><path d="M125 44h70m-70 23h70m-70 23h45m-45 23h60"/>',
 sound:'<path d="M57 65v25m20-44v64m20-77v90m20-66v42m20-78v114m20-95v76m20-58v40m20-70v100m20-82v65m20-43v23m20-37v50"/>',
 grid:'<rect x="68" y="25" width="184" height="105" rx="8"/><path d="M68 53h184M68 79h184M68 104h184M115 25v105m46-105v105m45-105v105"/>',
 design:'<rect x="72" y="25" width="176" height="106" rx="8"/><rect x="88" y="42" width="64" height="72" rx="4"/><path d="M170 46h59m-59 20h45m-45 20h59m-59 20h37"/>',
 effect:'<path d="m160 17 18 41 45-9-24 39 29 36-46-4-22 31-16-40-44-4 32-29-12-43Z"/><circle cx="246" cy="39" r="8"/><path d="M73 92h24m-12-12v24"/>',
 cad:'<path d="m160 16 90 48v53l-90 26-90-44V46Z"/><path d="m70 46 90 47 90-29m-90 29v50m0-127v44l-90 39m90-39 90 57"/>',
 deck:'<rect x="65" y="24" width="190" height="100" rx="6"/><path d="M160 124v22m-30 0h60M85 103l36-36 34 20 44-42 33 16"/>'};
 const type=slug.includes('sound')?'sound':slug.includes('grid')?'grid':slug.includes('vector')?'vector':slug.includes('film')?'film':slug.includes('effect')?'effect':(slug==='solidcraft'||slug.includes('cad'))?'cad':slug.includes('deck')?'deck':/photo|light|paint/.test(slug)?'photo':/word|pdf/.test(slug)?'document':'design';
 return `<svg viewBox="0 0 320 150" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${drawings[type]}</svg>`;
}
function officialArt(app,kind){return `<span class="official-art official-${kind}" aria-hidden="true"><img src="/static/artcraft/${encodeURIComponent(app.slug)}/${kind}.webp" alt="" loading="${kind==='hero'?'lazy':'eager'}" decoding="async"><span class="art-fallback">${artwork(app.slug)}</span></span>`;}
// Capture image failures without inline handlers; only these local decorations use this fallback.
document.addEventListener('error',event=>{const image=event.target;if(image instanceof HTMLImageElement&&image.parentElement?.classList.contains('official-art')){image.hidden=true;image.parentElement.classList.add('art-failed');}},true);
function card(app){const i=[...app.slug].reduce((hash,char)=>(hash*31+char.charCodeAt(0))>>>0,0);const ready=!!app.active_version&&!app.disabled;return `<article class="app-card tone-${i%colors.length}"><div class="card-art">${officialArt(app,'hero')}<button class="fav ${state.favs.includes(app.slug)?'isfav':''}" data-fav="${e(app.slug)}" title="${e(t('Favoriet'))}" aria-label="${e(t('favoriteApp',{name:app.name}))}" aria-pressed="${state.favs.includes(app.slug)}">${state.favs.includes(app.slug)?'★':'☆'}</button></div>
 <div class="card-content"><span class="card-category">${e(category(app))}</span><h3>${e(app.name)}</h3><p>${e(summary(app))}</p>${inspiration(app)?`<div class="app-inspiration">${e(t('inspiredBy',{name:inspiration(app)}))}</div>`:''}<div class="card-status">${ready?`<span class="pill ok">● v${e(app.active_version.replace(/^v/,''))}</span>`:`<span class="pill warn">${e(t(app.disabled?'Uitgeschakeld':'Installatie wordt voorbereid'))}</span>`}</div></div>
 <div class="card-footer"><span class="tiny muted">${app.latest_version?`Release ${e(app.latest_version)}`:e(t('Nog niet geïnstalleerd'))}</span><div class="card-actions"><button class="mini" data-download="${e(app.slug)}" aria-label="${e(t('Desktopversie downloaden'))}" title="${e(t('Desktopversie'))}">↓</button><button class="primary" data-open="${e(app.slug)}" ${ready&&state.appOriginConfigured?'':'disabled'}>${e(t('Openen'))}<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 12 12 4M5 4h7v7"/></svg></button></div></div></article>`;}
function appsPage(){let list=filteredApps();const ready=state.apps.filter(x=>x.active_version&&!x.disabled).length;return `<section class="library-toolbar"><div class="library-intro"><p class="muted">${e(t('libraryIntro'))}</p><div class="library-summary"><span class="pill ok">● ${e(t('appsReady',{count:ready}))}</span><span class="small muted">${e(t('libraryCount',{count:state.apps.filter(x=>!x.disabled).length}))}</span></div></div><div class="library-tools"><button class="secondary" id="arrange-apps">${e(t('order.title'))}</button><label class="searchbar">⌕ <input id="search" type="search" value="${e(state.search)}" placeholder="${e(t('Zoek applicaties'))}" aria-label="${e(t('Zoek applicaties'))}"></label></div></section>
 ${!state.appOriginConfigured?`<div class="alert">${e(t('Configureer een apart app-domein (CRAFT_SINGLE_APP_URL of CRAFT_APPS_DOMAIN) om WebAssembly-apps veilig gescheiden van het beheerdersportaal te openen.'))}</div>`:''}
  <div id="app-results">${list.length?`<div class="app-grid">${list.map(card).join('')}</div>`:`<div class="empty">${e(t(state.apps.length?'Geen applicaties gevonden.':'De eerste controle wordt uitgevoerd. Gecontroleerde apps verschijnen hier vanzelf.'))}</div>`}</div>`;}
function adminPage(){if(!state.admin)return `<div class="boot">${e(t("Beheerinformatie laden…"))}</div>`;const a=state.admin;const s=a.settings;return `<div class="stats"><div class="stat"><span class="upper">${e(t("Geïnstalleerde apps"))}</span><strong>${a.apps.filter(x=>x.active_version).length}</strong></div><div class="stat"><span class="upper">${e(t("Actieve download"))}</span><strong>${a.running?t("Ja"):t("Nee")}</strong></div><div class="stat"><span class="upper">${e(t("Schijfruimte"))}</span><strong>${fmtBytes(a.bytes)}</strong></div><div class="stat"><span class="upper">Accounts</span><strong>${a.users}</strong></div></div>
 <div id="admin-refresh-status" role="status">${state.adminError?`<div class="alert error">${e(t("Status vernieuwen mislukt."))} ${e(state.adminError)} <button class="secondary" id="retry-admin">${e(t("Opnieuw proberen"))}</button></div>`:''}</div>
 <section class="panel"><div id="update-summary"><div class="row between"><div><h2>Update Manager</h2><p class="small muted">${e(t("Laatste controle:"))} ${fmtTime(a.last_check)} · ${e(updaterResult(a.last_result))}</p></div><button class="primary" id="run-update" ${a.running?'disabled':''}>${a.running?t("⟳ Controle bezig"):t("⟳ Nu controleren")}</button></div>${a.running?`<p class="small muted mt-10" role="status">${e(t("Officiële releases worden gecontroleerd en waar nodig geïnstalleerd. Dit kan enkele minuten duren."))}</p><progress class="update-progress" aria-label="${e(t("Updatecontrole bezig"))}"></progress>`:''}</div>
 <form id="settings-form" class="stack mt-20"><div class="form-grid"><div class="field"><label for="interval">${e(t("Controle-interval"))}</label><select name="interval" id="interval">${[1,3,6,12,24].map(x=>`<option value="${x}" ${s.update_interval_hours==x?'selected':''}>${e(t("interval",{count:x}))}</option>`).join('')}</select></div>
 <div class="field"><label for="keep">${e(t("Eerdere versies bewaren"))}</label><select name="keep" id="keep">${[0,1,2,3,5].map(x=>`<option value="${x}" ${s.keep_previous_versions==x?'selected':''}>${e(t("previousVersions",{count:x}))}</option>`).join('')}</select></div></div>
 <label class="row"><input type="checkbox" name="auto" ${s.auto_install_versions==='true'?'checked':''}> ${e(t("Nieuwe versies automatisch installeren"))}</label>
 <label class="row"><input type="checkbox" name="discover" ${s.auto_discover_apps==='true'?'checked':''}> ${e(t("Nieuwe officiële apps automatisch toevoegen"))}</label>
 <div><button class="secondary" type="submit">${e(t("Instellingen opslaan"))}</button></div></form></section>
 <section class="panel" id="app-management"><div class="section-head"><div><h2>${e(t("Applicatiebeheer"))}</h2><p class="small muted">${e(t("Versies, foutmeldingen en terugrollen"))}</p></div></div><div class="table-wrap"><table><thead><tr><th>${e(t("Applicatie"))}</th><th>${e(t("Actieve versie"))}</th><th>${e(t("Laatste release"))}</th><th>Status</th><th>${e(t("Beheer"))}</th></tr></thead><tbody>${a.apps.map(x=>`<tr><td><strong>${e(x.slug)}</strong>${x.last_error?`<p class="tiny text-error">${e(errorMessage(x.last_error))}</p>`:''}</td><td>${e(x.active_version||'—')}</td><td>${e(x.latest_version||'—')}</td><td><span class="status"><span class="dot ${x.last_error?'warn':!x.active_version?'bad':''}"></span>${x.disabled?t("Uit"):x.active_version?t("Gereed"):t("Wachten")}</span></td><td><div class="row"><button class="mini" data-versions="${e(x.slug)}" title="${e(t("Versies"))}" aria-label="${e(t("versionsOf",{name:x.slug}))}">◷</button><button class="mini" data-pause="${e(x.slug)}" data-paused="${x.auto_update}" title="${e(t("Automatische updates pauzeren/hervatten"))}" aria-label="${e(t(x.auto_update?"pauseUpdates":"resumeUpdates",{name:x.slug}))}">${x.auto_update?'Ⅱ':'▶'}</button></div></td></tr>`).join('')}</tbody></table></div></section>
 <div class="notice">${e(t("Updates van WebAssembly-apps wijzigen geen persoonlijke bestanden op de server. Sommige Craft-apps bewaren documenten alleen in de browser. Maak waar nodig apart back-ups."))}</div>`;}
function usersPage(){if(!state.multiUser)return `<div class="panel"><h2>${e(t("Een veilige single-userinstallatie"))}</h2><p class="muted mt-10">${e(t("workspace.enableAccounts"))}</p></div>`;
 return `${state.appOriginMode==='shared'?`<div class="notice">${e(t('workspace.sharedStorage'))}</div>`:''}<div class="panel"><h2>${e(t("Nieuw account"))}</h2><form id="new-user" class="stack mt-20"><div class="form-grid"><div class="field"><label for="new-username">${e(t("Gebruikersnaam"))}</label><input id="new-username" autocomplete="username" name="username" required minlength="3" maxlength="48"></div><div class="field"><label for="new-role">${e(t("Rol"))}</label><select id="new-role" name="role"><option value="user">${e(t("Gebruiker"))}</option><option value="admin">Administrator</option></select></div></div><div class="field"><label for="new-password">${e(t("Initieel wachtwoord (min. 12 tekens)"))}</label><input id="new-password" type="password" name="password" minlength="12" required autocomplete="new-password"></div><div><button class="primary">${e(t("Gebruiker toevoegen"))}</button></div></form></div><div id="users-list" class="panel">${e(t("Accounts laden…"))}</div>`;}
function eventsPage(){return `<div class="panel"><div class="section-head"><div><h2>${e(t("Systeemactiviteit"))}</h2><p class="small muted">${e(t("De laatste 120 gebeurtenissen"))}</p></div><button id="refresh-events" class="secondary">${e(t("Vernieuwen"))}</button></div><div id="events-list">${e(t("Laden…"))}</div></div>`;}
function render(){if(!state.user){resetWorkspace();closeModal();root.innerHTML=authScreen();return;}root.innerHTML=shell(({apps:appsPage,admin:adminPage,users:usersPage,events:eventsPage})[state.page]()); if(state.page==='users'&&state.multiUser)refreshUsers();if(state.page==='events')refreshEvents();updateWorkspace();}
async function refreshUsers(){try{const r=await api('/api/admin/users');const el=document.getElementById('users-list');if(!el)return;el.innerHTML=`<h2>Accounts</h2><div class="table-wrap"><table><thead><tr><th>${e(t("Gebruikersnaam"))}</th><th>${e(t("Rol"))}</th><th>Status</th><th>${e(t("Actie"))}</th></tr></thead><tbody>${r.users.map(u=>`<tr><td>${e(u.username)}</td><td>${e(t(u.role==='admin'?'Administrator':'Gebruiker'))}</td><td>${u.enabled?t("Actief"):t("Uitgeschakeld")}</td><td>${u.enabled&&u.id!==state.user.id?`<button class="danger" data-disable-user="${u.id}">${e(t("Uitschakelen"))}</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`;}catch(ex){toast(ex instanceof TypeError?t("Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina."):ex.message,true);}}
async function refreshEvents(){try{const r=await api('/api/admin/events');const el=document.getElementById('events-list');if(!el)return;el.innerHTML=`<div class="table-wrap"><table><thead><tr><th>${e(t("Tijd"))}</th><th>${e(t("Niveau"))}</th><th>${e(t("Gebeurtenis"))}</th><th>Details</th></tr></thead><tbody>${r.events.map(x=>`<tr><td>${fmtTime(x.at)}</td><td>${e(t(x.level))}</td><td>${e(t(x.action))} ${x.slug?`· ${e(x.slug)}`:''}</td><td>${e(updaterResult(x.detail))}</td></tr>`).join('')}</tbody></table></div>`;}catch(ex){toast(ex instanceof TypeError?t("Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina."):ex.message,true);}}
const workspace=document.createElement('section');
workspace.id='workspace';workspace.hidden=true;document.body.append(workspace);
const sessions=new Map();let activeApp=null;let workspaceGeneration=0;
function resetWorkspace(){workspaceGeneration++;for(const session of sessions.values())session.frame.remove();sessions.clear();activeApp=null;workspace.replaceChildren();workspace.hidden=true;root.inert=false;document.body.classList.remove('workspace-visible','has-dock');}
function reconcileWorkspace(){for(const [slug,session] of sessions){if(!state.apps.some(app=>app.slug===slug&&!app.disabled&&app.active_version)){session.frame.remove();sessions.delete(slug);if(activeApp===slug)activeApp=null;}}if(state.user)updateWorkspace();}
function appMark(app){return `<span class="dock-icon" aria-hidden="true">${officialArt(app,'icon')}</span>`;}
function updateWorkspace(){
 if(!state.user)return;
 const focused=document.activeElement?.tagName==='BUTTON'&&workspace.contains(document.activeElement)?{action:document.activeElement.dataset.workspace,slug:document.activeElement.dataset.open}:null;
 workspace.hidden=false;document.body.classList.add('has-dock');
 if(!workspace.querySelector('.workspace-stage'))workspace.innerHTML=`<div class="workspace-stage" hidden><header class="workspace-toolbar"></header><div class="workspace-frames"></div></div><nav class="workspace-dock" aria-label="${e(t('workspace.dock'))}"></nav>`;
 const stage=workspace.querySelector('.workspace-stage');stage.hidden=!activeApp;
 document.body.classList.toggle('workspace-visible',!!activeApp);root.inert=!!activeApp;
 for(const [slug,session] of sessions)session.frame.hidden=slug!==activeApp;
 const app=state.apps.find(app=>app.slug===activeApp),session=sessions.get(activeApp);
 const bar=workspace.querySelector('.workspace-toolbar');
 bar.innerHTML=app?`<div class="workspace-heading"><strong title="${e(app.name)}">${e(app.name)}</strong><span class="small muted workspace-status ${session?.status==='workspace.compatibility'?'workspace-status-helper':''}" role="status">${e(t(session?.status||'workspace.starting'))}</span></div><div class="workspace-actions">${[['home','library','M2 2h12v12H2zM2 6h12M2 10h12M6 2v12M10 2v12'],['separate','separate','M6 3H3v10h10v-3M9 3h4v4M7 9l6-6'],['retry','retry','M13 7a5 5 0 1 1-2-3M13 2v4H9'],['close','close','M4 4l8 8M12 4l-8 8']].map(([action,key,path])=>`<button class="${action==='close'?'danger':'secondary'}" data-workspace="${action}" aria-label="${e(t('workspace.'+key))}" title="${e(t('workspace.'+key))}"><svg class="workspace-action-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg><span class="workspace-action-label">${e(t('workspace.'+key))}</span></button>`).join('')}</div>`:'';
 workspace.querySelector('.workspace-dock').innerHTML=`<div class="dock-items"><button class="dock-app dock-home ${!activeApp?'selected':''}" data-workspace="home" aria-label="${e(t('workspace.library'))}" title="${e(t('workspace.library'))}" aria-pressed="${!activeApp}"><span class="dock-icon" aria-hidden="true">▦</span><span>${e(t('workspace.library'))}</span></button>${orderedApps().map(app=>`<button class="dock-app ${activeApp===app.slug?'selected':''} ${sessions.has(app.slug)?'running':''}" data-open="${e(app.slug)}" ${app.active_version&&state.appOriginConfigured?'':'disabled'} aria-label="${e(app.name)}" aria-pressed="${activeApp===app.slug}" title="${e(app.name)}">${appMark(app)}<span>${e(app.name)}</span></button>`).join('')}</div>`;
 if(focused){const buttons=[...workspace.querySelectorAll('button')];(buttons.find(button=>focused.action?button.dataset.workspace===focused.action:button.dataset.open===focused.slug)||workspace.querySelector('.dock-app.selected'))?.focus();}
 else if(activeApp&&root.contains(document.activeElement))workspace.querySelector('.dock-app.selected')?.focus();
}
async function openSeparately(slug){const {url}=await api(`/api/apps/${encodeURIComponent(slug)}/launch`,{method:'POST'});window.open(url,'_blank','noopener,noreferrer');}
async function openApp(slug){
 const app=state.apps.find(app=>app.slug===slug&&!app.disabled&&app.active_version);if(!app||!state.user)return;
 if(sessions.has(slug)){activeApp=slug;updateWorkspace();return;}
 if(sessions.size>=4){toast(t('workspace.limit'),true);return;}
 const generation=workspaceGeneration;
 // Reserve a frame before the request so rapid repeated clicks cannot launch duplicates.
 const frame=document.createElement('iframe');frame.title=app.name;frame.hidden=true;
 frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-downloads allow-pointer-lock');
 frame.setAttribute('allow','cross-origin-isolated; fullscreen; clipboard-read; clipboard-write');frame.referrerPolicy='no-referrer';
 const session={frame,origin:null,status:'workspace.starting'};sessions.set(slug,session);activeApp=slug;updateWorkspace();workspace.querySelector('.workspace-frames').append(frame);
 try{
  const result=await api(`/api/apps/${encodeURIComponent(slug)}/launch?embedded=true`,{method:'POST'});
  if(generation!==workspaceGeneration||sessions.get(slug)!==session)return;
  const url=new URL(result.url);if(url.origin!==result.origin||result.slug!==slug||!result.embedded||!['http:','https:'].includes(url.protocol))throw new Error(t('workspace.failed'));
  session.origin=url.origin;frame.src=url.href;
  session.status='workspace.compatibility';updateWorkspace();
 }catch(error){if(generation===workspaceGeneration&&sessions.get(slug)===session){session.status='workspace.failed';updateWorkspace();}throw error;}
}
window.addEventListener('message',event=>{
 for(const [slug,session] of sessions){
  if(!session.origin||event.origin!==session.origin||event.source!==session.frame.contentWindow||event.data?.slug!==slug)continue;
  if(event.data.type==='craft-bridge-error'){session.status='workspace.failed';updateWorkspace();}
  else if(event.data.type==='craft-bridge-navigating'){session.status='workspace.compatibility';updateWorkspace();}
 }
});
window.addEventListener('beforeunload',event=>{if(sessions.size){event.preventDefault();event.returnValue='';}});

function preferredInstaller(assets){
 const ua=navigator.userAgent.toLowerCase();
 let pattern = ua.includes('windows') ? /windows-x64\.msi$/ : ua.includes('mac') ? /macos-universal\.dmg$/ : /linux-x86_64\.AppImage$/;
 return assets.find(a=>pattern.test(a.name)) || assets[0] || null;
}
let modalOpener=null;
function closeModal(){
 document.querySelector('.modal-back')?.remove();
 root.inert=!!activeApp;workspace.inert=false;
 document.body.classList.remove('modal-open');
 if(modalOpener?.isConnected)modalOpener.focus();
 else if(modalOpener){const heading=root.querySelector('h1');if(heading){heading.tabIndex=-1;heading.focus();}}
 modalOpener=null;
}
function showModal(el){
 closeModal();
 modalOpener=document.activeElement;
 root.inert=true;workspace.inert=true;
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
function arrangeApps(){
 const owner=state.user.public_id;
 let draft=orderedApps().map(app=>app.slug),useDefault=!state.appOrder.length,dragged=null,saving=false;
 const el=document.createElement('div');el.className='modal-back';
 el.innerHTML=`<div class="modal order-modal" role="dialog" aria-modal="true" aria-labelledby="order-title"><div class="row between"><h2 id="order-title">${e(t('order.title'))}</h2><button class="mini" id="close-modal" aria-label="${e(t('Sluiten'))}">×</button></div><p class="small muted mt-10">${e(t('order.help'))}</p><ol class="reorder-list"></ol><div class="order-footer"><button class="secondary" id="reset-order">${e(t('order.reset'))}</button><button class="primary" id="save-order">${e(t('order.save'))}</button></div><p class="small muted" role="status" id="order-feedback"></p></div>`;
 const list=el.querySelector('.reorder-list'),feedback=el.querySelector('#order-feedback');
 function draw(focusSlug,direction){
  list.innerHTML=draft.map((slug,index)=>{const app=state.apps.find(app=>app.slug===slug)||{slug,name:slug};return `<li draggable="true" data-order-slug="${e(slug)}"><span class="order-grip" aria-hidden="true">⠿</span><span class="order-icon">${officialArt(app,'icon')}</span><span class="order-name">${e(app.name)}</span><button class="secondary" data-order-up="${e(slug)}" aria-label="${e(t('order.up',{name:app.name}))}" ${index===0?'disabled':''}>↑</button><button class="secondary" data-order-down="${e(slug)}" aria-label="${e(t('order.down',{name:app.name}))}" ${index===draft.length-1?'disabled':''}>↓</button></li>`;}).join('');
  if(focusSlug){const row=[...list.children].find(row=>row.dataset.orderSlug===focusSlug);(row?.querySelector(`[data-order-${direction}]:not(:disabled)`)||row?.querySelector('button:not(:disabled)'))?.focus();}
 }
 function move(slug,index,direction='up'){
  if(saving)return;const from=draft.indexOf(slug);if(from<0||index<0||index>=draft.length||from===index)return;
  draft.splice(from,1);draft.splice(index,0,slug);useDefault=false;draw(slug,direction);
  feedback.textContent=t('order.position',{name:state.apps.find(app=>app.slug===slug)?.name||slug,position:index+1,count:draft.length});
 }
 el.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||saving)return;
  const slug=button.dataset.orderUp||button.dataset.orderDown;
  if(slug){const direction=button.dataset.orderUp?'up':'down';move(slug,draft.indexOf(slug)+(direction==='up'?-1:1),direction);}
  else if(button.id==='reset-order'){useDefault=true;draft=orderedApps([]).map(app=>app.slug);draw();feedback.textContent=t('order.resetDraft');}
  else if(button.id==='save-order'){
   saving=true;el.querySelectorAll('button').forEach(button=>button.disabled=true);
   try{const preferences=await api('/api/preferences',{method:'PUT',data:{app_order:useDefault?[]:draft}});if(state.user?.public_id!==owner)return;state.appOrder=preferences.app_order;closeModal();render();document.getElementById('arrange-apps')?.focus();toast(t('order.saved'));}
   catch(error){if(el.isConnected){saving=false;el.querySelectorAll('button').forEach(button=>button.disabled=false);draw();feedback.textContent=error instanceof TypeError?t('Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina.'):error.message;}}
  }
 });
 el.addEventListener('click',event=>{if(saving)event.stopImmediatePropagation();},true);
 el.addEventListener('keydown',event=>{if(saving&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();}},true);
 list.addEventListener('dragstart',event=>{if(saving){event.preventDefault();return;}dragged=event.target.closest('[data-order-slug]')?.dataset.orderSlug||null;if(dragged){event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',dragged);}});
 list.addEventListener('dragover',event=>{if(dragged&&!saving){event.preventDefault();event.dataTransfer.dropEffect='move';}});
 list.addEventListener('drop',event=>{event.preventDefault();const target=event.target.closest('[data-order-slug]')?.dataset.orderSlug;if(dragged&&target)move(dragged,draft.indexOf(target));dragged=null;});
 list.addEventListener('dragend',()=>dragged=null);
 draw();showModal(el);
}

async function downloads(slug){
 const r=await api(`/api/apps/${encodeURIComponent(slug)}/downloads`);
 const preferred=preferredInstaller(r.assets);const el=document.createElement('div');el.className='modal-back';
 el.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-label="Native download"><div class="row between"><h2>Download ${e(slug)}</h2><button class="mini" id="close-modal" aria-label="${e(t("Sluiten"))}">×</button></div>
 <p class="muted small mb-16">${e(t("Download de officiële native applicatie voor je computer, zonder de browseromgeving."))}</p>
 ${preferred?`<div class="panel download-recommended"><div class="small muted">${e(t("Aanbevolen voor dit apparaat"))}</div><strong class="download-filename">${e(preferred.name)}</strong><a class="primary" href="${e(preferred.url)}" target="_blank" rel="noopener noreferrer">${e(t("↓ Download installatiebestand"))}</a></div>`:''}
 <div class="field"><label for="installer-platform">Platform</label><select id="installer-platform"><option value="all">${e(t("Alle platforms"))}</option><option value="windows">Windows</option><option value="macos">macOS</option><option value="linux">Linux</option></select></div>
 <div id="installer-results" class="stack" aria-live="polite"></div>
 <a class="secondary mt-20" href="${e(r.github)}" target="_blank" rel="noopener noreferrer">${e(t("Officiële releases op GitHub ↗"))}</a></div>`;
 const platform=el.querySelector('#installer-platform');
 const updateInstallers=()=>{
  const assets=r.assets.filter(a=>platform.value==='all'||installerPlatform(a.name)===platform.value);
  el.querySelector('#installer-results').innerHTML=assets.length?assets.map(a=>`<a class="version-chip" href="${e(a.url)}" target="_blank" rel="noopener noreferrer"><span>${e(a.name)}</span><span>↗</span></a>`).join(''):t("Geen installers voor dit platform beschikbaar.");
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
async function versions(slug){const r=await api(`/api/admin/apps/${encodeURIComponent(slug)}/versions`);const active=state.admin.apps.find(x=>x.slug===slug)?.active_version;const el=document.createElement('div');el.className='modal-back';el.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-label="${e(t("Versiebeheer"))}"><div class="row between"><h2>${e(t("versionsOf",{name:slug}))}</h2><button class="mini" id="close-modal" aria-label="${e(t("Sluiten"))}">×</button></div><p class="muted small">${e(t("Rollback wijzigt niet automatisch de documenten en browseropslag. Automatische updates voor deze app worden na rollback gepauzeerd."))}</p><div class="stack">${r.versions.map(v=>`<div class="version-chip"><span>${e(v.version)} ${v.version===active?t("(actief)"):''}</span>${v.version===active?`<span class="pill ok">${e(t("Actief"))}</span>`:`<button class="secondary" data-rollback="${e(slug)}" data-version="${e(v.version)}">${e(t("Activeren"))}</button>`}</div>`).join('')||t("Geen eerdere versies beschikbaar.")}</div></div>`;showModal(el);}
root.addEventListener('submit', async event=>{
  const form=event.target;
  if(!['auth-form','settings-form','new-user'].includes(form.id))return;
  event.preventDefault();const data=new FormData(form);const button=form.querySelector('button[type=submit],button.primary,button.secondary');if(button)button.disabled=true;
  try{
    if(form.id==='auth-form'){
      const payload={username:data.get('username'),password:data.get('password')};
      if(state.setup)payload.code=data.get('code');
      await api(state.setup?'/api/setup':'/api/login',{method:'POST',data:payload,auth:false});await init();toast(t("Welkom bij Craft Portal"));
    } else if(form.id==='settings-form'){
      await api('/api/admin/settings',{method:'PUT',data:{update_interval_hours:Number(data.get('interval')),keep_previous_versions:Number(data.get('keep')),auto_install_versions:data.get('auto')==='on',auto_discover_apps:data.get('discover')==='on'}});
      await loadAdmin();render();toast(t("Instellingen opgeslagen"));
    } else if(form.id==='new-user'){
      await api('/api/admin/users',{method:'POST',data:{username:data.get('username'),password:data.get('password'),role:data.get('role')}});
      form.reset();refreshUsers();toast(t("Gebruiker toegevoegd"));
    }
  }catch(ex){toast(ex instanceof TypeError?t("Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina."):ex.message,true);}finally{if(button)button.disabled=false;}
});
root.addEventListener('input', event=>{if(event.target.id==='search'){
 state.search=event.target.value;
 const results=document.getElementById('app-results');
 const apps=filteredApps();
 if(results)results.innerHTML=apps.length?`<div class="app-grid">${apps.map(card).join('')}</div>`:`<div class="empty" role="status">${e(t("Geen applicaties gevonden."))}</div>`;
}});
document.addEventListener('click',async event=>{
 const target=event.target.closest('button');if(!target||(!root.contains(target)&&!workspace.contains(target)&&!target.closest('.modal-back')))return;
 try{
  if(target.dataset.workspace){const action=target.dataset.workspace;if(action==='home'){activeApp=null;updateWorkspace();}else if(action==='separate'){await openSeparately(activeApp);}else if(['close','retry'].includes(action)&&confirm(t('workspace.confirmClose'))){const slug=activeApp;sessions.get(slug)?.frame.remove();sessions.delete(slug);activeApp=null;updateWorkspace();if(action==='retry')await openApp(slug);}}
  else if(target.dataset.page){state.page=target.dataset.page;if(state.page==='admin')await loadAdmin();render();const heading=root.querySelector('h1');heading.tabIndex=-1;heading.focus();}
  else if(target.id==='arrange-apps'){arrangeApps();}
  else if(target.id==='logout'){if(sessions.size&&!confirm(t('workspace.confirmLogout')))return;await api('/api/logout',{method:'POST'});state.user=null;state.csrf=null;state.admin=null;state.page='apps';resetWorkspace();render();}
  else if(target.dataset.fav){const slug=target.dataset.fav;state.favs=state.favs.includes(slug)?state.favs.filter(x=>x!==slug):[...state.favs,slug];saveFaves();render();root.querySelectorAll('[data-fav]').forEach(button=>{if(button.dataset.fav===slug)button.focus();});}
  else if(target.dataset.open){await openApp(target.dataset.open);}
  else if(target.dataset.download){await downloads(target.dataset.download);}
  else if(target.id==='run-update'){target.disabled=true;try{await api('/api/admin/check',{method:'POST'});toast(t("Updatecontrole gestart"));await refreshAdmin();}finally{if(target.isConnected)target.disabled=!!state.admin?.running;}}
  else if(target.id==='retry-admin'){await refreshAdmin();}
  else if(target.dataset.versions){await versions(target.dataset.versions);}
  else if(target.dataset.rollback){if(confirm(`${t("activateVersion",{version:target.dataset.version})}`)){await api(`/api/admin/apps/${target.dataset.rollback}/rollback`,{method:'POST',data:{version:target.dataset.version}});closeModal();await loadAdmin();await loadApps();render();toast(t("Versie teruggezet"));}}
  else if(target.dataset.pause){const slug=target.dataset.pause;await api(`/api/admin/apps/${slug}`,{method:'PUT',data:{auto_update:target.dataset.paused==='0'}});await loadAdmin();render();toast(t("App-instellingen aangepast"));}
  else if(target.dataset.disableUser){if(confirm(t("Dit account en alle sessies uitschakelen?"))){await api(`/api/admin/users/${target.dataset.disableUser}/disable`,{method:'PUT'});await refreshUsers();toast(t("Account uitgeschakeld"));}}
  else if(target.id==='refresh-events'){refreshEvents();}
 }catch(ex){toast(ex instanceof TypeError?t("Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina."):ex.message,true);}
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
let checkingWorkspaceSession=false;
async function checkWorkspaceSession(){
 if(!state.user||!sessions.size||checkingWorkspaceSession)return;
 checkingWorkspaceSession=true;
 const generation=workspaceGeneration;
 try{
  const bootstrap=await api('/api/bootstrap',{auth:false});
  if(generation!==workspaceGeneration)return;
  if(!bootstrap.user||bootstrap.user.public_id!==state.user?.public_id){resetWorkspace();await init();return;}
  // Preserve live frames, focused controls and unsaved portal forms for the same account.
  state.csrf=bootstrap.csrf;
 }catch{ /* A transient network error does not establish a session change. */ }
 finally{checkingWorkspaceSession=false;}
}
setInterval(async()=>{
 if(!state.user)return;
 await checkWorkspaceSession();
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
     const summary=root.querySelector('.library-summary');if(summary)summary.innerHTML=view.querySelector('.library-summary').innerHTML;
    }
   }
  }catch{}
 }
},12000);
init();
