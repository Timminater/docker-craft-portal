(async () => {
  const message = document.getElementById('message');
  const parts = new URLSearchParams(location.hash.substring(1));
  const ticket = parts.get('ticket');
  const slug = parts.get('slug');
  history.replaceState(null, '', location.pathname);
  if (!ticket || !slug) { message.textContent = 'Open deze applicatie via het Craft Portal.'; return; }
  try {
    const resp = await fetch('/_redeem', {
      method: 'POST', headers: {'Content-Type':'application/json', 'X-Craft-Client':'app-bridge-v1'},
      credentials: 'same-origin', body: JSON.stringify({ticket,slug}), cache:'no-store'
    });
    if (!resp.ok) throw new Error('Toegang geweigerd of verlopen.');
    // Resolve the active app version after redeeming the one-time ticket.
    const info = await fetch('/_app_info?slug=' + encodeURIComponent(slug), {credentials:'same-origin',cache:'no-store'});
    if (!info.ok) throw new Error('Applicatieversie niet beschikbaar.');
    const data = await info.json();
    location.replace(location.hostname.startsWith(slug + '--')
      ? `/v/${encodeURIComponent(data.version)}/`
      : `/a/${encodeURIComponent(slug)}/v/${encodeURIComponent(data.version)}/`);
  } catch (err) { message.textContent = err.message; }
})();
