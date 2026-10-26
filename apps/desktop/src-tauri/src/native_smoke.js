// Runs only in a smoke-tests build, in the bundled main window of --demo.
(async () => {
  const invoke = (command, args = {}) => window.__TAURI_INTERNALS__.invoke(command, args);
  const assert = (value, message) => { if (!value) throw Error(message); };
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async test => {
    for (let i = 0; i < 100; i++) { if (test()) return; await delay(100); }
    throw Error('TEST_ONLY render timeout');
  };
  const enabled = selector => {
    const control = document.querySelector(selector);
    return control && !control.disabled && document.querySelector('#app')?.getAttribute('aria-busy') === 'false';
  };
  const click = async selector => { await until(() => enabled(selector)); document.querySelector(selector).click(); };
  const refuses = async (command, args, code) => {
    try { await invoke(command, args); } catch (error) { assert(error.code === code, command + ': ' + JSON.stringify(error)); return true; }
    throw Error(command + ' unexpectedly succeeded');
  };
  const progress = phase => invoke('report_linux_smoke', {phase, evidence:{
    renderedVault:false, renderedQuotaUi:false, renderedHarnessUi:false, renderedSkillsUi:false,
    unknownVisible:false, demoQueryRendered:false, resized:false, confirmedWrite:false,
    confirmationRefused:false, cancellationRefused:false, duplicateRefused:false,
    rollbackApplied:false, capabilityDenied:false, demoMutationRefused:false
  }});
  try {
    await until(() => document.querySelector('#keys-list')?.textContent.includes('演示') && enabled('[data-panel="usage"]'));
    await progress('ready');
    // Wait for actual native ACL receipt, bounded independently of UI timing.
    let capabilityDenied = false;
    for (let attempt=0; attempt<50; attempt++) {
      capabilityDenied = await progress('awaitingPermission') === true;
      if (capabilityDenied) break;
      await delay(100);
    }
    assert(capabilityDenied, 'native permission acknowledgement timeout');
    await progress('preview');

    const snapshot = await invoke('snapshot');
    const selected = snapshot.targets.map(target => target.Id);
    assert(snapshot.demo && selected.length === 2, 'isolated demo fixture');
    let plan = await invoke('preview', {selected});
    assert(plan.files.length === 1 && plan.files[0].changed && !plan.files[0].error, 'native masked preview');
    assert(!JSON.stringify(plan).includes('FAKE_DEMO_'), 'preview must mask fixture values');
    const confirmationRefused = await refuses('apply_preview', {id:plan.id, confirmed:false}, 'CONFIRM_REQUIRED');
    await invoke('cancel_preview');
    const cancellationRefused = await refuses('apply_preview', {id:plan.id, confirmed:true}, 'PREVIEW_EXPIRED');
    assert((await invoke('list_backups')).length === 0, 'refused writes must not back up');

    plan = await invoke('preview', {selected});
    const applied = await invoke('apply_preview', {id:plan.id, confirmed:true});
    assert(applied.length === 1 && applied[0].outcome === 'applied', 'native write');
    await progress('applied');
    const duplicateRefused = await refuses('apply_preview', {id:plan.id, confirmed:true}, 'PREVIEW_EXPIRED');
    // The supervising process independently observes applied bytes on disk.
    await delay(1500);
    const backups = await invoke('list_backups');
    assert(backups.length === 1 && !backups[0].error, 'encrypted native backup');
    const rollback = await invoke('preview_rollback', {backupPath:backups[0].backupPath});
    await refuses('apply_preview', {id:rollback.id, confirmed:false}, 'CONFIRM_REQUIRED');
    const restored = await invoke('apply_preview', {id:rollback.id, confirmed:true});
    assert(restored.length === 1 && restored[0].outcome === 'applied', 'native whole-file rollback');
    await progress('rolledBack');
    await refuses('apply_preview', {id:rollback.id, confirmed:true}, 'PREVIEW_EXPIRED');
    assert((await invoke('list_backups')).length === 2, 'rollback must preserve current bytes in another encrypted backup');
    await delay(1500);
    const demoMutationRefused = await refuses('skills_install', {
      sourcePath:'TEST_ONLY', rootId:'zcode', name:'TEST_ONLY', confirmed:true
    }, 'DEMO_READONLY');

    await progress('quota');
    const unknown = document.querySelector('#glm-usage-result').textContent.includes('未知');
    await click('[data-panel="usage"]');
    const select = document.querySelector('#glm-key');
    await until(() => enabled('#glm-key') && select.options.length > 1);
    select.value=select.options[1].value; select.dispatchEvent(new Event('change'));
    const confirm=document.querySelector('#confirm-glm-query');
    confirm.checked=true; confirm.dispatchEvent(new Event('change'));
    await click('#query-glm');
    await until(() => document.querySelector('#glm-usage-result').textContent.includes('60.0%'));
    await progress('harness');
    await click('[data-panel="harness"]');
    await click('#query-harness');
    await until(() => document.querySelector('#harness-status-result').textContent.includes('记录就绪'));
    await progress('skills');
    await click('[data-panel="skills"]');
    await click('#inventory-skills');
    await until(() => document.querySelector('#skills-roots').textContent.includes('内置分发管理'));
    await until(() => enabled('#inventory-skills'));
    await progress('finished');
    await invoke('report_linux_smoke', {phase:null, evidence:{
      renderedVault:document.querySelector('#keys-list').textContent.includes('••••••••'),
      renderedQuotaUi:!!document.querySelector('#codex-cli') && !!document.querySelector('#query-glm'),
      renderedHarnessUi:document.querySelector('#harness-status-result').textContent.includes('codex'),
      renderedSkillsUi:document.querySelector('#skills-roots').textContent.includes('demo-skill'),
      unknownVisible:unknown, demoQueryRendered:document.querySelector('#glm-usage-result').textContent.includes('TEST_ONLY 演示数据'),
      resized:window.innerWidth<=650, confirmedWrite:true, confirmationRefused,
      cancellationRefused, duplicateRefused, rollbackApplied:true, capabilityDenied, demoMutationRefused
    }});
  } catch { await progress('failed'); }
})();
