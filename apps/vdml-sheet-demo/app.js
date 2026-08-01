(function(){
  const params=new URLSearchParams(location.search);
  const appId=params.get('app')||'';
  const readonly=params.get('ro')==='1';
  if(readonly)document.body.classList.add('readonly');
  const tbody=document.querySelector('#grid tbody');
  const status=document.getElementById('status');
  let rows=[{part:'NMD-PHY-44G',qty:'120',unit:'18.40',lead:'6'},{part:'NMD-PLL-22',qty:'80',unit:'12.75',lead:'4'}];
  function render(){
    tbody.innerHTML=rows.map((r,i)=>'<tr>'+
      '<td><input data-r="'+i+'" data-k="part" value="'+(r.part||'')+'"/></td>'+
      '<td><input data-r="'+i+'" data-k="qty" value="'+(r.qty||'')+'"/></td>'+
      '<td><input data-r="'+i+'" data-k="unit" value="'+(r.unit||'')+'"/></td>'+
      '<td><input data-r="'+i+'" data-k="lead" value="'+(r.lead||'')+'"/></td>'+
      '</tr>').join('');
    tbody.querySelectorAll('input').forEach(inp=>{
      inp.addEventListener('change',()=>{
        const i=+inp.dataset.r;const k=inp.dataset.k;
        rows[i]=rows[i]||{};rows[i][k]=inp.value;save();
      });
    });
  }
  function load(){
    if(!appId){render();status.textContent='Local only';return}
    status.textContent='Loading…';
    try{parent.postMessage({type:'airgpt_app_state_read',appId:appId},'*')}catch(e){}
    render();
  }
  function save(){
    if(readonly||!appId)return;
    status.textContent='Saving…';
    try{parent.postMessage({type:'airgpt_app_state_write',appId:appId,state:{rows:rows}},'*')}catch(e){}
  }
  window.addEventListener('message',(ev)=>{
    const d=ev.data||{};
    if(d.type==='airgpt_app_state'&&d.appId===appId&&d.state&&Array.isArray(d.state.rows)){
      rows=d.state.rows;render();status.textContent=d.saved?'Synced':'Updated';
    }
  });
  load();
})();
