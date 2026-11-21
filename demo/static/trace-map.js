"use strict";
/* Human-readable view of ACTUAL replay hook events, not an LLM rationale.
   Categories are inferred from source folders and explicitly labelled as such. */
(function () {
  const root=document.getElementById("traceMap");
  if (!root) return;
  const escapeHtml = value => String(value == null?"":value).replace(/[&<>"']/g,
    c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const PHASES=[
    ["observe","01","観察・記憶","会話の文脈を記録するフック"],
    ["respond","02","回答候補を生成","各モジュールが返信を提案"],
    ["choose","03","候補を選択","arbiterが採択を判断"],
    ["after","04","後処理","返信後の処理と会話履歴"]
  ];
  function area(path, fn) {
    if(path.includes("/understanding/"))return ["理解","入力の解釈に関するファイル"];
    if(path.includes("/knowledge/"))return ["知識","辞書・事実を参照する領域"];
    if(path.includes("/memory/"))return ["記憶","会話情報を扱う領域"];
    if(path.includes("/compose/"))return ["組み立て","回答の構成に関する領域"];
    if(path.endsWith("/arbiter.py"))return ["回答選択","採択条件を調べる領域"];
    if(path.includes("/modules/"))return ["候補生成","応答モジュールの領域"];
    return ["呼び出し","その他の処理"];
  }

  function preview(turn) {
    if(!turn){
      root.innerHTML='<div class="map-empty"><div class="map-empty-icon">◎</div>'+
        '<strong>会話を始めて、処理の道順を見てみましょう</strong>'+
        '<p>実行行や関数の呼び出しは、選んだ質問の再実行で観測します。</p></div>';
      return;
    }
    root.innerHTML='<div class="map-preview"><span class="map-flag">PYBOT 純正 / 元の質問の観測</span>'+
      '<h4>候補 '+Number(turn.candidate_count||0)+' 件 → 採択 '+escapeHtml(turn.module||"fallback")+'</h4>'+
      '<p>「▶ 経路を観測」を押すと、観察 → 候補生成 → 選択 → 後処理を、元のPyBotを再実行して可視化します。処理後には各関数をクリックしてソースへ移動できます。</p></div>';
  }

  function render(trace, turn) {
    if(!trace){preview(turn);return;}
    const match=!!trace.replay_equal;
    const counts=trace.phase_counts||{};
    const hooks=(trace.phase_events||[]);
    const phases=PHASES.map(([key,number,title,desc])=>{
      const actual=hooks.filter(e=>e.phase===key);
      const modules=[...new Set(actual.map(e=>e.module))].slice(0,3);
      return '<div class="map-step"><div class="map-step-num">'+number+'</div>'+
       '<div class="map-step-body"><strong>'+title+'</strong><p>'+desc+'</p>'+
       '<small>'+ (modules.length?"通過例: "+modules.map(escapeHtml).join("、"):"記録なし") +'</small></div>'+
       '<div class="map-step-count"><strong>'+Number(counts[key]||0)+'</strong><span>hook calls</span></div></div>';
    }).join('<div class="map-connector">↓</div>');
    const candidates=turn && Array.isArray(turn.candidates)?turn.candidates:[];
    const answer=candidates.length?candidates.map((candidate,i)=>
      '<div class="map-candidate '+(turn.chosen_index===i?"selected":"")+'">'+
      '<div><b>'+escapeHtml(candidate.module)+'</b><small>PRIORITY '+escapeHtml(candidate.priority)+'</small></div>'+
      (turn.chosen_index===i?'<span>採択</span>':'<span>見送り</span>')+'</div>'
    ).join(""):'<p class="map-muted">候補なし（PyBotのフォールバック）</p>';

    // A chronological sample of observed calls. We select one occurrence per
    // function and cap the list for readability. This is a SAMPLE, not all calls.
    const chain=Array.isArray(trace.call_chain)?trace.call_chain:[];
    const unique=[],seen=new Set();
    for(const c of chain){
      const key=c.path+":"+c.fn+":"+c.line;
      if(seen.has(key))continue;
      seen.add(key);
      unique.push(c);
      if(unique.length>=24)break;
    }
    const cards=unique.map((call,index)=>{
      const [cat]=area(call.path||"",call.fn||"");
      return '<button class="map-function" type="button" data-flow-index="'+index+'">'+
        '<span class="map-order">'+String(index+1).padStart(2,"0")+'</span>'+
        '<span class="map-function-main"><small>'+escapeHtml(cat)+' / '+escapeHtml(call.path)+'</small>'+
        '<b>'+escapeHtml(call.fn)+'()</b></span>'+
        '<span class="map-time">'+Number(call.at_ms||0).toFixed(1)+'ms ↗</span></button>';
    }).join("");
    const scope=turn && trace.selected_module!==turn.module ?
      '<p class="map-caution">現在は非採択候補 <b>'+escapeHtml(trace.selected_module)+'</b> の呼び出しも含めて観察しています。実際の採択は <b>'+escapeHtml(turn.module)+'</b> です。</p>':"";
    const notice=match?
      '<div class="map-evidence good">✓ 再実行は元の回答と採択モジュールが一致。通過行は再実行時の観測です。</div>':
      '<div class="map-evidence warning">! 再実行結果が元と異なりました。これは元のターンの確定した処理経路ではありません。</div>';
    root.innerHTML=
      '<div class="map-identity"><span class="map-flag">PYBOT 純正 / 回答候補の実測</span>'+
      '<span class="map-flag lab">LIVE LAB / 再実行の解析</span></div>'+
      notice+scope+
      '<div class="map-section-heading"><h4>1. 処理の流れ</h4><span>実際に呼ばれたhookの回数</span></div>'+
      '<div class="map-pipeline">'+phases+'</div>'+
      '<div class="map-section-heading"><h4>2. 候補から選択へ</h4><span>元のターンの採択結果</span></div>'+
      '<div class="map-candidates">'+answer+'</div>'+
      '<div class="map-section-heading"><h4>3. 関数の呼び出しを辿る</h4><span>一部抜粋 · クリックでソースへ</span></div>'+
      '<div class="map-function-list">'+(cards||'<div class="map-muted">呼び出しを観測できませんでした。</div>')+'</div>'+
      '<p class="map-footnote">実際の関数呼び出し順から重複を整理して最大24個を表示します。実行の全容ではありません。'+
      (trace.call_chain_truncated?'呼び出しログは最大210件で記録を打ち切っています。':'')+
      '「理解・知識・記憶・組み立て」等の分類は<strong>ファイルの所属フォルダから推定した説明</strong>であり、各関数の動作や回答理由を検証した結論ではありません。詳しい条件はソースで確認してください。</p>';
    root.querySelectorAll("[data-flow-index]").forEach(btn=>btn.onclick=()=>{
      const call=unique[Number(btn.dataset.flowIndex)];
      if (call && /^bot\/[a-zA-Z0-9_/]+\.py$/.test(call.path) &&
          typeof window.PyBotLabTraceMap.onOpen==="function") {
        window.PyBotLabTraceMap.onOpen(call.path,call.line);
      }
    });
  }
  window.PyBotLabTraceMap={render,onOpen:null};
  preview(null);
})();
