/* Deterministic offline renderer. Invoked only by the trusted Python worker. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {spawn,execFileSync} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url), here=path.dirname(fileURLToPath(import.meta.url));
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const work=path.resolve(process.argv[2]), config=JSON.parse(fs.readFileSync(path.join(work,'config.json')));
if(!path.isAbsolute(process.argv[2]) || fs.lstatSync(work).isSymbolicLink())throw Error('Unsafe HTML work directory');
const moduleRoot=process.env.NBPPT_PLAYWRIGHT_MODULE || path.join(here,'node_modules/playwright');
if(!path.isAbsolute(moduleRoot) || require(path.join(moduleRoot,'package.json')).version!=='1.62.1')throw Error('Pinned Playwright 1.62.1 required');
const {chromium}=require(moduleRoot), executable=process.env.NBPPT_CHROMIUM_BIN||chromium.executablePath();
const expected=process.env.NBPPT_CHROMIUM_SHA256, version=process.env.NBPPT_CHROMIUM_VERSION;
if(!path.isAbsolute(executable)||!expected||!version||sha(fs.readFileSync(executable))!==expected)throw Error('Chromium binary pin missing or changed');
if(!execFileSync(executable,['--version'],{encoding:'utf8'}).includes(version))throw Error('Chromium version changed');
const vendor=fs.readFileSync(path.join(here,'vendor/lottie_light.min.js'),'utf8');
const pin=JSON.parse(fs.readFileSync(path.join(here,'vendor/lottie-provenance.json')));
if(sha(vendor)!==pin.sha256)throw Error('Vendored Lottie changed');
const scene=fs.readFileSync(path.join(here,'scene.js'),'utf8')+
 (config.story_profile==='parcel-story-v1'?'\n'+fs.readFileSync(path.join(here,'story_scene.js'),'utf8'):'');
const font=fs.readFileSync(config.font);
if(sha(font)!==config.font_sha256)throw Error('Trusted font changed');
let context,encoder; const blocked=[],errors=[],chunks=[];let chunkBytes=0;
async function cleanup(){if(encoder&&!encoder.killed)encoder.kill('SIGTERM');if(context)await context.close();}
process.on('SIGTERM',()=>cleanup().finally(()=>process.exit(143)));
process.on('SIGINT',()=>cleanup().finally(()=>process.exit(130)));
const profile=path.join(work,'profile'), temp=path.join(work,'tmp');fs.mkdirSync(temp,{recursive:true});
try {
 context=await chromium.launchPersistentContext(profile,{
  executablePath:executable,headless:true,chromiumSandbox:true,acceptDownloads:false,serviceWorkers:'block',
  ignoreDefaultArgs:['--disable-dev-shm-usage'],
  viewport:{width:config.width,height:config.height},deviceScaleFactor:1,locale:'zh-CN',timezoneId:'UTC',
  env:{PATH:process.env.PATH,HOME:path.join(work,'home'),TMPDIR:temp,TMP:temp,TEMP:temp,XDG_CACHE_HOME:path.join(work,'cache')},
  args:[`--disk-cache-dir=${path.join(work,'cache')}`,'--disk-cache-size=134217728',`--crash-dumps-dir=${path.join(work,'crashes')}`,
        '--disable-breakpad','--disable-crash-reporter','--disable-background-networking','--disable-component-update',
        '--enable-automation','--disable-gpu','--disable-skia-runtime-opts','--disable-partial-raster',
        '--no-first-run','--no-default-browser-check','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND'],
 });
 await context.setOffline(true);await context.route('**/*',route=>{blocked.push(route.request().url());return route.abort();});
 const page=context.pages()[0]||await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text());});
 const session=await context.browser().newBrowserCDPSession();
 const command=await session.send('Browser.getBrowserCommandLine');
 if(command.arguments.some(arg=>arg==='--no-sandbox'||arg==='--disable-setuid-sandbox'))throw Error('Sandbox disabling flags forbidden');
 const processes=await session.send('SystemInfo.getProcessInfo');
 fs.writeFileSync(path.join(work,'browser.json'),JSON.stringify({version,sha256:expected,playwright:'1.62.1',
   profile,arguments:command.arguments,pids:processes.processInfo.map(p=>({pid:p.id,type:p.type}))},null,2));
 const nonce=crypto.randomBytes(18).toString('base64');
 const html=`<!doctype html><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'">
 <style>@font-face{font-family:MotionCJK;src:url(data:font/collection;base64,${font.toString('base64')})}*{box-sizing:border-box}body{margin:0;background:#142D33;overflow:hidden}svg#stage{position:absolute;width:100vw;height:100vh}#beat{position:absolute;left:5%;right:5%;bottom:13%;height:24px}#track{position:absolute;bottom:0;height:3px;left:0;right:0;background:#24454b}#route{height:100%;background:#dc7247}</style>
 <svg id="stage" viewBox="0 0 1280 720" xmlns="http://www.w3.org/2000/svg"></svg><div id="beat"></div><div id="track"><div id="route"></div></div>
 <script nonce="${nonce}">${vendor}</script><script nonce="${nonce}">${scene}</script>`;
 fs.writeFileSync(path.join(work,'scene.html'),html);
 await page.setContent(html,{waitUntil:'load'});
 await page.evaluate(async()=>{await document.fonts.load('20px MotionCJK','仓库协作助手');await document.fonts.ready;if(!document.fonts.check('20px MotionCJK','仓库协作助手'))throw Error('Pinned CJK font failed to load');});
 await page.waitForFunction(()=>window.motionReady===true);
 if(config.height>config.width)await page.evaluate(()=>document.querySelector('#beat').style.bottom='20%');
 const determinism=[];let global=0;
 for(const shot of config.shots){
  if(shot.reuse){
   const start=global;
   determinism.push(shot.reuse.seek);
   for(const c of shot.reuse.chunks){
    const name=`chunk-${String(chunks.length).padStart(4,'0')}.mp4`;
    if(c.path!==name||c.start_frame!==global||c.end_frame!==global+c.frame_count||c.shot_num!==shot.shot_num)
     throw Error('Cached chunk timeline mismatch');
    for(const [file,hash] of [[c.path,c.sha256],...c.samples.map((s,i)=>[c.path+(i===0?'.first.png':'.last.png'),s.sha256])]){
     if(path.basename(file)!==file||fs.lstatSync(path.join(work,file)).isSymbolicLink()||sha(fs.readFileSync(path.join(work,file)))!==hash)
      throw Error('Cached chunk changed');
    }
    chunkBytes+=fs.statSync(path.join(work,name)).size;if(chunkBytes>1024*1024*1024)throw Error('Chunk cache exceeds 1 GiB');
    chunks.push({...c,reused:true});global=c.end_frame;
   }
   if(global!==start+shot.frames)throw Error('Cached shot incomplete');
   console.log(JSON.stringify({type:'progress',pct:global/config.total_frames*90,frame:global,total_frames:config.total_frames,reused_shot:shot.shot_num}));
   continue;
  }
  let still=null;if(shot.image_path){const bytes=fs.readFileSync(shot.image_path);still='data:image/'+(shot.image_path.endsWith('.jpg')?'jpeg':'png')+';base64,'+bytes.toString('base64');}
  await page.evaluate(data=>window.configure(data),shot);
  const at=async frame=>{let image=still;if(shot.media_dir)image='data:image/jpeg;base64,'+fs.readFileSync(path.join(shot.media_dir,`${String(frame+1).padStart(6,'0')}.jpg`)).toString('base64');await page.evaluate(({frame,image})=>window.renderFrame(frame,image),{frame,image});};
  await at(0);const beforePixels=await page.screenshot({type:'png',animations:'allow'}),before=sha(beforePixels);
  const beforeDOM=await page.evaluate(()=>document.querySelector('#stage').outerHTML+document.querySelector('#beat').innerHTML);
  await at(shot.frames-1);await at(0);const afterPixels=await page.screenshot({type:'png',animations:'allow'}),after=sha(afterPixels);
  if(before!==after){fs.writeFileSync(path.join(work,`determinism-${shot.shot_num}.before.png`),beforePixels);fs.writeFileSync(path.join(work,`determinism-${shot.shot_num}.after.png`),afterPixels);fs.writeFileSync(path.join(work,`determinism-${shot.shot_num}.json`),JSON.stringify({before:beforeDOM,after:await page.evaluate(()=>document.querySelector('#stage').outerHTML+document.querySelector('#beat').innerHTML)}));throw Error(`Seeking backwards changed deterministic frame in shot ${shot.shot_num}: ${before} != ${after}`);}
  determinism.push({shot_num:shot.shot_num,frame:0,first_sha256:before,reseek_sha256:after});
  for(let from=0;from<shot.frames;from+=config.chunk_frames){
   const count=Math.min(config.chunk_frames,shot.frames-from),name=`chunk-${String(chunks.length).padStart(4,'0')}.mp4`;
   const destination=path.join(work,name),log=fs.openSync(path.join(work,name+'.log'),'w');
   encoder=spawn(config.ffmpeg,['-v','error','-nostdin','-f','image2pipe','-vcodec','png','-r','24','-i','pipe:0',
    '-an','-frames:v',String(count),'-c:v','libx264','-preset','fast','-crf','20','-threads','2','-pix_fmt','yuv420p',destination],
    {stdio:['pipe','ignore',log]});
   let exit;const exited=new Promise(resolve=>encoder.once('exit',(code,signal)=>{exit={code,signal};resolve(exit);}));
   encoder.stdin.on('error',()=>{});
   const samples=[];
   for(let i=from;i<from+count;i++){
    let image=still;if(shot.media_dir){const bytes=fs.readFileSync(path.join(shot.media_dir,`${String(i+1).padStart(6,'0')}.jpg`));image='data:image/jpeg;base64,'+bytes.toString('base64');}
    await page.evaluate(({frame,image})=>window.renderFrame(frame,image),{frame:i,image});
    if(errors.length||blocked.length)throw Error('Browser content failed or attempted network: '+JSON.stringify({errors,blocked}));
    const bytes=await page.screenshot({type:'png',animations:'allow',timeout:15000});
    // A one-frame remainder is both the first and last boundary. Preserve both
    // records so the independent gate never mistakes it for missing evidence.
    for(const [label,edge] of [['first',from],['last',from+count-1]])if(i===edge){fs.writeFileSync(path.join(work,name+`.${label}.png`),bytes);samples.push({local_frame:i,global_frame:global+i,sha256:sha(bytes)});}
    if(exit)throw Error('Frame encoder exited early');
    if(!encoder.stdin.write(bytes))await once(encoder.stdin,'drain');
   }
   encoder.stdin.end();const result=await exited;fs.closeSync(log);encoder=null;
   if(result.code!==0)throw Error('Chunk encode failed');
   chunkBytes+=fs.statSync(destination).size;if(chunkBytes>1024*1024*1024)throw Error('Chunk cache exceeds 1 GiB');
   chunks.push({path:name,shot_num:shot.shot_num,start_frame:global+from,end_frame:global+from+count,
      frame_count:count,sha256:sha(fs.readFileSync(destination)),samples,
      ...(shot.product_asset_id?{product_asset_id:shot.product_asset_id,product_asset_sha256:shot.product_asset_sha256}:{} )});
   console.log(JSON.stringify({type:'progress',pct:chunks.at(-1).end_frame/config.total_frames*90,
    frame:chunks.at(-1).end_frame,total_frames:config.total_frames}));
  }
  global+=shot.frames;
 }
 if(global!==config.total_frames)throw Error('Missing frames');
 fs.writeFileSync(path.join(work,'chunks.json'),JSON.stringify({engine:'html-chromium-lottie-v1',time_base:'1/24',
   total_frames:global,chunk_frames:config.chunk_frames,network_requests:blocked,errors,
   chromium_version:version,chromium_sha256:expected,playwright:'1.62.1',lottie:'5.13.0',lottie_sha256:pin.sha256,
   template_sha256:sha(scene),html_sha256:sha(html),font_sha256:config.font_sha256,font_loaded:true,seek_determinism:determinism,chunks},null,2));
}finally{await cleanup();}
