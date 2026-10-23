/* One generated overview, shared by cover, reading rail, and offline download. */
window.ReportOverview = (() => {
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
  function create(asset,{target,title}) {
    if(!asset || !/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(asset.data_url))return null;
    const modal=el('dialog','overview-dialog');modal.setAttribute('aria-label','报告全景图');
    const bar=el('div','overview-dialog-bar'),heading=el('h2','','报告全景图');
    const controls=el('div','overview-tools');
    const bytes=Uint8Array.from(atob(asset.data_url.split(',')[1]),c=>c.charCodeAt(0));
    const downloadURL=/^(?:\/api\/reports)?\/preview\/[a-f0-9]+\/?$/.test(location.pathname)?location.pathname.replace(/\/$/,'')+'/overview.png':URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
    const makeDownload=()=>{const a=el('a','overview-download','下载分享图片 ↓');a.href=downloadURL;a.download=(title||'报告').replace(/[\\/:*?"<>|]/g,'-').slice(0,70)+'-全景图.png';return a;};
    const close=el('button','','关闭全景图 ×');close.type='button';close.onclick=()=>modal.close();
    const zoom=el('button','','放大阅读');zoom.type='button';zoom.setAttribute('aria-pressed','false');
    zoom.onclick=()=>{const enlarged=modal.classList.toggle('is-enlarged');zoom.textContent=enlarged?'适应窗口':'放大阅读';zoom.setAttribute('aria-pressed',String(enlarged));};
    controls.append(zoom,makeDownload(),close);bar.append(heading,controls);
    const scroll=el('div','overview-scroll'),full=el('img','overview-full');full.src=asset.data_url;full.alt=asset.alt;scroll.append(full);
    modal.append(bar,scroll,el('p','overview-caption',asset.caption+' · 图片为摘要，完整证据见正文。'));
    let opener=null;
    modal.addEventListener('close',()=>{opener?.focus();});
    modal.addEventListener('click',e=>{if(e.target===modal)modal.close();});
    target.append(modal);
    const open=()=>{opener=document.activeElement;modal.classList.remove('is-enlarged');zoom.textContent='放大阅读';zoom.setAttribute('aria-pressed','false');modal.showModal();scroll.scrollTop=0;};
    const trigger=()=>{const b=el('button','','报告全景图');b.type='button';b.onclick=open;return b;};
    const figure=(compact=false)=>{
      const f=el('figure','overview-card'+(compact?' overview-compact':''));
      f.append(el('p','eyebrow',compact?'全局视角 / 一图读懂':'一图读懂 · 可下载分享'));
      const b=el('button','overview-preview');b.type='button';b.setAttribute('aria-label','放大查看报告全景图');b.onclick=open;
      const img=el('img');img.src=asset.data_url;img.alt=asset.alt;img.decoding='async';b.append(img,el('span','overview-open','点击放大 ↗'));f.append(b);
      if(!compact){const caption=el('figcaption','overview-card-footer');caption.append(el('span','',asset.caption),makeDownload());f.append(caption);}
      return f;
    };
    return {open,trigger,figure};
  }
  return {create};
})();
