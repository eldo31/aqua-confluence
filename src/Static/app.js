/* Aqua Confluence Quintuple – app.js v0.6 */
(function(){
  const VERSION = "v0.6";
  console.log("Aqua Confluence", VERSION, "chargé");

  const $  = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const n  = v => (Number.isFinite(+v) ? +v : 0);

  const state = {
    mode: "tao",                 // "tao" | "liam" | "concat"
    amb: "none",
    ambGain: -24,
    // indexés M0..M5 (M0 inutilisé) pour simplicité d’alignement
    offsets_ms: [0,0,14000,28000,42000,56000], // TAO: absolus depuis 0
    rel_ms:     [0,0,14000,28000,42000,56000], // LIAM: avant la fin (ms)
    xf_ms:      [0,0,5000,5000,5000,5000],
    durations:  [0,0,0,0,0,0],
    files: {1:null,2:null,3:null,4:null,5:null}
  };

  /* ---------- util ---------- */
  function mmss(ms){
    const s = Math.max(0, Math.round(ms/1000));
    const m = Math.floor(s/60), r = s%60;
    return `${m}:${String(r).padStart(2,'0')}`;
  }
  function sum(arr){ return arr.reduce((a,b)=>a+n(b),0); }

  /* ---------- UI badges / aides ---------- */
  function refreshBadge(){
    const badge = $("#modeBadge");
    const tag = ` — ${VERSION}`;
    if(state.mode==="concat") badge.textContent = "Mode actif : CONCAT (collage sec)"+tag;
    else if(state.mode==="liam") badge.textContent = "Mode actif : LIAM (offsets relatifs à la fin)"+tag;
    else badge.textContent = "Mode actif : TAO (offsets absolus)"+tag;

    $("#lblOffsets").textContent =
      state.mode==="liam" ? "Offsets relatifs à la fin (ms) — LIAM" : "Offsets absolus (ms) — TAO";

    $("#helpMode").textContent =
`TAO (absolu) : offset = position depuis 0 (ex: 14 000ms → M2 à 00:14).
LIAM (relatif fin) : 14 000ms → M2 commence 14s AVANT la fin de M1.
CONCAT : collage des pistes sans fondu.`;
  }

  /* ---------- sliders + input number liés ---------- */
  function bindPair(rangeId, numId, idx, isOffset){
    const r = $("#"+rangeId), x = $("#"+numId);
    const sync = v=>{
      x.value = v; r.value = v;
      if(isOffset){
        if(state.mode==="liam") state.rel_ms[idx] = n(v);
        else                    state.offsets_ms[idx] = n(v);
      }else{
        state.xf_ms[idx] = n(v);
      }
    };
    r.oninput = ()=> sync(n(r.value));
    x.oninput = ()=> sync(n(x.value));
  }
  function wireSliders(){
    bindPair("off2","off2n",2,true);
    bindPair("off3","off3n",3,true);
    bindPair("off4","off4n",4,true);
    bindPair("off5","off5n",5,true);
    bindPair("xf2","xf2n",2,false);
    bindPair("xf3","xf3n",3,false);
    bindPair("xf4","xf4n",4,false);
    bindPair("xf5","xf5n",5,false);

    $("#amb").onchange   = ()=> state.amb     = $("#amb").value;
    $("#ambGain").oninput= ()=> state.ambGain = n($("#ambGain").value || -24);
  }

  /* ---------- affichages d’état ---------- */
  function msg(txt){ $("#msg").textContent = txt; }

  function computeAbsoluteStartsFromRel(){
    // Convertit rel_ms (M2..M5) en offsets absolus (ms), en utilisant durations connues
    const abs = [0,0,0,0,0,0];
    // trouve pour chaque i la piste précédente existante (en supposant M(i-1) comme référence)
    for(let i=2;i<=5;i++){
      const dPrev = state.durations[i-1] || 0;
      // rel>0 => démarre rel ms AVANT la fin du précédent
      // rel=0 => démarre exactement à la fin
      // rel<0 => démarre |rel| ms APRÈS la fin
      const rel = n(state.rel_ms[i]);
      const start_i = Math.max(0, abs[i-1] + dPrev - rel);
      abs[i] = start_i;
    }
    return abs;
  }

  function showDurations(){
    const d = state.durations.slice(1); // M1..M5
    const totalConcat = mmss(sum(d));

    let text = `Durées M1..M5: ${d.map(mmss).join(" | ")}\n`+
               `Somme théorique (concat): ${totalConcat}\n`;

    if(state.mode==="liam"){
      const abs = computeAbsoluteStartsFromRel().slice(1); // M1..M5
      text += `LIAM → départs absolus estimés: ${abs.map(mmss).join(" | ")}\n`;
      text += `Astuce: rel=0 → M(i) commence à la fin de M(i-1); 14000 → 14s avant la fin.`;
    }else if(state.mode==="tao"){
      const abs = [0, state.offsets_ms[1], state.offsets_ms[2], state.offsets_ms[3], state.offsets_ms[4], state.offsets_ms[5]].slice(1);
      text += `TAO → offsets (absolus): ${abs.map(mmss).join(" | ")}`;
    }else{
      text += `CONCAT → collage sec sans fondu.`;
    }

    $("#durations").textContent = text;
  }

  /* ---------- upload / status ---------- */
  async function doUpload(){
    const fd = new FormData();
    for(let i=1;i<=5;i++){
      const f = state.files[i];
      if(f) fd.append(`file${i}`, f, f.name);
    }
    const res = await fetch("/upload",{method:"POST",body:fd});
    const js  = await res.json().catch(()=>({success:false}));
    if(js.success){
      msg("✅ Fichiers chargés (les affluents non envoyés ont été purgés côté serveur).");
      await refreshDurations();
    }else{
      msg("⚠️ Aucun fichier envoyé.");
    }
  }

  async function refreshDurations(){
    const res = await fetch("/status/durations");
    const js  = await res.json().catch(()=>({durations_ms:[0,0,0,0,0]}));
    state.durations = [0].concat(js.durations_ms||[0,0,0,0,0]);
    showDurations();
  }

  /* ---------- payloads ---------- */
  function buildPayload(engineOverride=null, previewFull=true){
    const engine = engineOverride ? engineOverride : (state.mode==="concat" ? "concat" : "mix");
    const offset_mode = (state.mode==="liam") ? "relative_end" : "abs";
    const payload = {
      engine,
      mode: state.mode==="concat" ? "tao" : state.mode, // le backend ignore le mode si concat
      ambience: state.amb,
      amb_gain_db: state.ambGain,
      xf_ms: [0,0,state.xf_ms[2],state.xf_ms[3],state.xf_ms[4],state.xf_ms[5]],
      preview_full: !!previewFull
    };
    if(offset_mode === "relative_end"){
      payload.offset_mode = "relative_end";
      payload.rel_ms = [0,0,state.rel_ms[2],state.rel_ms[3],state.rel_ms[4],state.rel_ms[5]];
    }else{
      payload.offset_mode = "abs";
      payload.offsets_ms = [0,0,state.offsets_ms[2],state.offsets_ms[3],state.offsets_ms[4],state.offsets_ms[5]];
    }
    return payload;
  }

  /* ---------- actions ---------- */
  async function doPreview(engineOverride=null){
    const body = JSON.stringify(buildPayload(engineOverride, /*preview_full*/ true));
    const res  = await fetch("/preview",{method:"POST",headers:{"Content-Type":"application/json"},body});
    if(!res.ok){
      const t = await res.text().catch(()=>res.statusText);
      msg("❌ Preview: "+t);
      return;
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const player = $("#player");
    player.style.display = "block";
    player.src = url;
    msg("🎧 Aperçu généré (mix complet).");
  }

  async function doRender(engineOverride=null){
    const body = JSON.stringify(buildPayload(engineOverride, /*preview_full*/ false));
    const res  = await fetch("/render",{method:"POST",headers:{"Content-Type":"application/json"},body});
    const js   = await res.json().catch(()=>({success:false,error:"json"}));
    if(!js.success){
      msg("❌ Render: "+(js.error||"erreur"));
      return;
    }
    msg(`✅ Delta prêt · durée=${js.details.total_duration}s · ${js.details.file_size}`);
  }

  async function doExport(fmt){
    const body = JSON.stringify({format:fmt, bitrate:(fmt==="mp3"?"192k":undefined), mono:false});
    const res  = await fetch("/export",{method:"POST",headers:{"Content-Type":"application/json"},body});
    if(!res.ok){ msg("❌ Export: "+res.status); return; }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (fmt==="mp3"?"delta_puissant.mp3":"delta_puissant.wav");
    a.click();
    msg("💾 Export téléchargé.");
  }

  async function doConcat(){
    const res = await fetch("/concat",{method:"POST"});
    const js  = await res.json().catch(()=>({success:false}));
    if(!js.success){ msg("❌ Concat: "+(js.error||"erreur")); return; }
    msg(`✅ Concat prêt · durée=${js.details.total_duration}s · ${js.details.file_size}`);
  }

  /* ---------- wiring ---------- */
  function wire(){
    // fichiers
    for(let i=1;i<=5;i++){
      $("#file"+i).addEventListener("change", e=>{
        const f = e.target.files[0];
        state.files[i] = f || null;
        $("#info"+i).textContent = f ? `${f.name} (${Math.round(f.size/1024/1024*100)/100} MB)` : "";
      });
    }
    // boutons
    $("#btnUpload").onclick = doUpload;
    $("#btnDur").onclick    = refreshDurations;
    $("#btnReset").onclick  = ()=>{
      for(let i=1;i<=5;i++){
        state.files[i]=null; const el=$("#file"+i); if(el) el.value="";
        const info=$("#info"+i); if(info) info.textContent="";
      }
      msg("↺ Reset local (côté serveur non supprimé). Re-charger puis «📤 Charger» si besoin.");
    };
    $("#btnPreview").onclick   = ()=> state.mode==="concat" ? doPreview("concat") : doPreview(null);
    $("#btnRender").onclick    = ()=> state.mode==="concat" ? doRender("concat") : doRender(null);
    $("#btnExportWav").onclick = ()=> doExport("wav");
    $("#btnExportMp3").onclick = ()=> doExport("mp3");
    $("#btnConcat").onclick    = doConcat;

    // modes
    $$("#modes button").forEach(b=>{
      b.onclick = ()=>{
        $$("#modes button").forEach(x=>x.classList.remove("active"));
        b.classList.add("active");
        state.mode = b.dataset.mode;  // "tao" | "liam" | "concat"
        refreshBadge();
        showDurations(); // rafraîchir l’aide (affichage des starts estimés)
      };
    });

    wireSliders();
    refreshBadge();
  }

  document.addEventListener("DOMContentLoaded", wire);
})();
