"""Exercise the browser translation module directly without a browser dependency."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node is required for JavaScript unit checks')
def test_language_negotiation_pluralization_and_fallback():
    source = Path(__file__).parents[1] / 'portal/static/i18n.js'
    script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
function load(languages){
 const context={navigator:{languages},document:{documentElement:{},querySelectorAll:()=>[]},window:{},Intl};
 vm.runInNewContext(source.replace(' const languages =', ' window.testDictionaries=dictionaries; const languages ='),context);
 context.window.testDictionaries.en.testEnglishFallback='English fallback';
 assert.equal(context.window.CraftI18n.t('testEnglishFallback'),'English fallback');
 assert.equal(context.document.documentElement.lang,context.window.CraftI18n.locale);
 return context.window.CraftI18n;
}
for(const [languages,expected] of [
 [['nl-NL','en-US'],'nl'],[['en-GB','nl-NL'],'en'],[['fr-FR','nl-BE'],'nl'],
 [['de-DE'],'en'],[[],'en']])assert.equal(load(languages).locale,expected);
const en=load(['en-US']),nl=load(['nl-NL']);
assert.equal(en.t('appsReady',{count:1}),'1 app ready');
assert.equal(en.t('appsReady',{count:2}),'2 apps ready');
assert.equal(nl.t('appsReady',{count:1}),'1 app beschikbaar');
assert.equal(nl.t('appsReady',{count:0}),'0 apps beschikbaar');
assert.equal(nl.t('previousVersions',{count:1}),'1 vorige versie');
assert.equal(nl.t('previousVersions',{count:2}),'2 vorige versies');
assert.equal(en.t('completely-unknown-key'),'completely-unknown-key');
assert.equal(nl.t('completely-unknown-key'),'completely-unknown-key');
assert.equal(en.errorMessage('Incorrect username or password'),'Incorrect username or password');
assert.equal(nl.errorMessage('Incorrect username or password'),'Onjuiste gebruikersnaam of wachtwoord');
assert.equal(nl.errorMessage('Upstream technical diagnostic'),'Upstream technical diagnostic');
assert.equal(nl.updaterResult('2 updates; 1 errors'),'2 updates; 1 fouten');
console.log(JSON.stringify({status:'ok'}));
'''
    result = subprocess.run(['node', '-e', script, str(source)], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {'status': 'ok'}
