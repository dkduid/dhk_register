(function(){
  var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
  var b=$('#burger'),s=$('#side');if(b&&s)b.onclick=function(){s.classList.toggle('open')};
  $$('form[data-confirm]').forEach(function(f){f.addEventListener('submit',function(e){if(!confirm(f.dataset.confirm))e.preventDefault()})});
  $$('.drop input[type=file]').forEach(function(i){i.addEventListener('change',function(){i.parentNode.classList.toggle('has',i.files.length>0)})});
  // Form register: kolom bergantung + panduan klasifikasi
  var form=$('form.form [name=watermark]');
  if(form){
    var upd=function(){$$('.dep').forEach(function(d){var k=d.dataset.dep,v=$('input[name='+k+']:checked');var off=!(v&&v.value==='Y');d.classList.toggle('off',off);$$('input,select',d).forEach(function(x){x.disabled=off})})};
    $$('input[type=radio]').forEach(function(r){r.addEventListener('change',upd)});upd();
    var km=$('#kmap'),sel=$('select[name=klasifikasi]'),hint=$('#klas-hint');
    if(km&&sel){var M=JSON.parse(km.textContent);var h=function(){var m=M[sel.value];if(!m){hint.className='hint';return}
      var need=[m.req_wm&&'watermark',m.req_pw&&'password',m.req_nda&&'NDA'].filter(Boolean);
      hint.textContent=need.length?'Klasifikasi '+sel.value+' mewajibkan: '+need.join(', ')+'.':'Klasifikasi '+sel.value+' tidak mewajibkan kontrol tambahan.';hint.className='hint on'};
      sel.addEventListener('change',h);h()}
  }
  // Grafik dashboard
  var cd=$('#chartdata');
  if(cd&&window.Chart){
    var D=JSON.parse(cd.textContent),P=['#0f5c73','#2b8fb0','#7fb8c9','#b7791f','#d9480f','#6b7c93','#2f855a','#8a5a99'];
    Chart.defaults.font.family='"Segoe UI",system-ui,sans-serif';Chart.defaults.maintainAspectRatio=false;
    var opt={plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{precision:0}}}};
    new Chart($('#c-bulan'),{type:'bar',data:{labels:D.bulan.labels,datasets:[{data:D.bulan.values,backgroundColor:'#0f5c73',borderRadius:3}]},options:opt});
    new Chart($('#c-klas'),{type:'doughnut',data:{labels:D.klas.labels,datasets:[{data:D.klas.values,backgroundColor:D.klas.colors}]},options:{plugins:{legend:{position:'right'}},cutout:'60%'}});
    new Chart($('#c-unit'),{type:'bar',data:{labels:D.unit.labels,datasets:[{data:D.unit.values,backgroundColor:'#2b8fb0',borderRadius:3}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}}}}});
    new Chart($('#c-kontrol'),{type:'bar',data:{labels:D.kontrol.labels,datasets:[{label:'Ya',data:D.kontrol.ya,backgroundColor:'#2f855a'},{label:'Tidak',data:D.kontrol.tidak,backgroundColor:'#c9d2db'}]},
      options:{plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true},y:{stacked:true,beginAtZero:true,ticks:{precision:0}}}}});
  }
})();
