(async () => {
  const {t} = CraftI18n;
  const message = document.getElementById('message');
  message.textContent=t('Beveiligde applicatiesessie openen…');
  const parts = new URLSearchParams(location.hash.substring(1));
  const ticket = parts.get('ticket');
  const slug = parts.get('slug');
  const embedded=parts.get('embedded')==='1';
  const storage=parts.get('storage')==='1';
  const portalOrigin=document.querySelector('meta[name="craft-portal-origin"]')?.content;
  function report(type){
    if(!embedded||window.parent===window||!portalOrigin)return;
    try{const origin=new URL(portalOrigin).origin;if(origin!==portalOrigin)return;window.parent.postMessage({type,slug},origin);}catch{}
  }
  history.replaceState(null, '', location.pathname);
  if (!ticket || !slug) { message.textContent = t("Open deze applicatie via het Craft Portal."); return; }
  try {
    const resp = await fetch('/_redeem', {
      method: 'POST', headers: {'Content-Type':'application/json', 'X-Craft-Client':'app-bridge-v1'},
      credentials: 'same-origin', body: JSON.stringify({ticket,slug}), cache:'no-store'
    });
    if (!resp.ok) throw new Error(t("Toegang geweigerd of verlopen."));
    await resp.arrayBuffer(); // Finish the redemption response before navigating the frame.
    // Storage belongs to the actual app origin. Authenticate that origin without
    // starting an editor or touching the user's documents.
    if(storage){location.replace('/_storage?slug='+encodeURIComponent(slug));return;}
    // Resolve the active app version after redeeming the one-time ticket.
    const info = await fetch('/_app_info?slug=' + encodeURIComponent(slug), {credentials:'same-origin',cache:'no-store'});
    if (!info.ok) throw new Error(t("Applicatieversie niet beschikbaar."));
    const data = await info.json();
    const path=data.path;
    if(typeof path!=='string'||!path.startsWith('/')||path.startsWith('//')||new URL(path,location.origin).origin!==location.origin)throw new Error(t('Applicatieversie niet beschikbaar.'));
    // This only confirms successful authentication/navigation, not app compatibility.
    report('craft-bridge-navigating');
    location.replace(path);
  } catch (err) { report('craft-bridge-error');message.textContent = err instanceof TypeError ? t('Kan geen verbinding maken met Craft Portal. Controleer je server of vernieuw de pagina.') : err.message; }
})();
