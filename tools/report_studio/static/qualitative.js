/* Qualitative evidence has categories, never invented numerical axes. */
window.ReportQualitative=(()=>{
  const states={recorded:'材料记载',proposed:'建议',unresolved:'待验证'};
  const relationText={included:'明确涉及',excluded:'明确排除',unknown:'未明确'};
  function render(c,{el,show}){
    const root=el('div','qualitative-plot');
    const statement=(item,index)=>{
      const b=el('button',`qual-statement is-${item.nature}`);b.type='button';b.dataset.itemIndex=String(index);
      b.append(el('span','qual-state',states[item.nature]),el('strong','',item.label),el('span','qual-detail',item.detail));
      b.onclick=()=>show(item.label,states[item.nature]+' · '+item.detail,item.quote,item.source_ids);return b;
    };
    if(c.kind==='contrast'){
      root.append(el('p','qual-reading','定性对照 · 两侧按相同维度阅读，点击要点查看原文依据。'));
      const head=el('div','contrast-head');head.append(el('span','','比较维度'),el('strong','',c.left_label),el('strong','',c.right_label));root.append(head);
      c.rows.forEach((row,i)=>{const pair=el('div','qual-row contrast-pair');pair.dataset.itemIndex=String(i);const a=statement(row.left,i),b=statement(row.right,i);a.dataset.side=c.left_label;b.dataset.side=c.right_label;pair.append(el('h4','contrast-dimension',row.label),a,b);root.append(pair);});
    }else if(c.kind==='membership'){
      root.append(el('p','qual-reading','● 明确涉及　× 明确排除　· 未明确。点的位置只表示类别归属，不表示覆盖率或优先级。'));
      const scroll=el('div','membership-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','类别归属点阵，窄屏可横向阅读');
      const table=el('table','membership-table'),head=el('thead'),tr=el('tr');tr.append(el('th','','对象 / 职责'));
      c.sets.forEach(set=>tr.append(el('th','',set)));head.append(tr);table.append(head);const body=el('tbody');
      c.items.forEach((item,i)=>{const row=el('tr','qual-row');row.dataset.itemIndex=String(i);const label=el('th');label.scope='row';label.append(el('strong','',item.label),el('small','',item.detail));row.append(label);
        c.sets.forEach((set,j)=>{const relation=item.relations.find(r=>r.set_index===j),state=relation?.relation||'unknown',cell=el('td');
          const dot=el('button',`membership-cell is-${state}`,state==='included'?'●':state==='excluded'?'×':'·');dot.type='button';dot.dataset.itemIndex=String(i);dot.setAttribute('aria-label',`${item.label} · ${set}：${relationText[state]}`);
          if(relation)dot.onclick=()=>show(item.label+' · '+set,relationText[state]+' · '+item.detail,relation.quote,relation.source_ids);
          else{dot.disabled=true;dot.title='材料未提供此项归属依据，不代表排除。';}
          cell.append(dot);row.append(cell);});body.append(row);});
      table.append(body);scroll.append(table);root.append(scroll);
    }else if(c.kind==='evidence_strip'){
      root.append(el('p','qual-reading','按证据性质分栏 · 同栏项目并列，点击要点查看原文依据。'));
      const grid=el('div','evidence-columns');for(const [nature,name] of Object.entries(states)){const items=c.items.map((item,i)=>({item,i})).filter(x=>x.item.nature===nature);if(!items.length)continue;
        const column=el('section',`evidence-column is-${nature}`);column.append(el('h4','',name));items.forEach(({item,i})=>{const b=statement(item,i);b.classList.add('evidence-entry');column.append(b);});grid.append(column);}root.append(grid);
    }
    return root;
  }
  return {render,states,relationText};
})();
