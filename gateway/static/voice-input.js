/* Recording is local until explicitly stopped/uploaded; transcription does not submit a job. */
(()=>{
  const $=id=>document.getElementById(id);
  let recorder=null,stream=null,limit=null,available=false,transcribing=false,epoch=0;
  function status(text){$('voice-input-status').textContent=text;}
  window.configureVoiceInput=(cap,authenticated)=>{
    epoch++;
    available=Boolean(cap?.available&&authenticated);
    $('record-voice').disabled=!available||transcribing;
    $('voice-file').disabled=!available||transcribing;
    if(!available){clearTimeout(limit);if(recorder)recorder.onstop=null;stream?.getTracks().forEach(t=>t.stop());$('record-voice').textContent='录一段语音';}
    if(!available) status(authenticated?'服务器尚未配置语音转写，可先粘贴转写文字。':'请使用有生成权限的密钥登录后录音或上传音频。');
  };
  async function upload(blob){
    if(!available||transcribing)return;
    if(!blob.size||blob.size>10*1024*1024){status('录音为空或超过10MB，请重新录制。');return;}
    const currentEpoch=epoch;
    transcribing=true;$('record-voice').disabled=true;$('voice-file').disabled=true;
    status('正在服务器离线转写，请稍候；尚未创建视频任务。');
    try{
      const r=await fetch('/api/voice/transcribe',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/octet-stream'},body:blob});
      const data=await r.json();
      if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'转写失败');
      if(epoch!==currentEpoch||!available)return;
      const input=$('source');input.value=(input.value.trim()?input.value.trim()+'\n\n':'')+data.text;
      input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
      status('文字已填入，请核对专有名词、数字和要求，再点击开始生成。录音文件已从服务器清除。');
    }catch(error){if(epoch===currentEpoch)status(error.message+'；不会创建任务或扣视频算力。');}
    finally{transcribing=false;$('record-voice').disabled=!available;$('voice-file').disabled=!available;}
  }
  $('record-voice').onclick=async()=>{
    if(recorder?.state==='recording'){recorder.stop();return;}
    if(!available)return;
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){status('当前浏览器不支持录音，请上传音频文件。');return;}
    try{
      stream=await navigator.mediaDevices.getUserMedia({audio:true});
      recorder=new MediaRecorder(stream);const chunks=[];
      recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      recorder.onstop=()=>{clearTimeout(limit);stream.getTracks().forEach(t=>t.stop());$('record-voice').textContent='录一段语音';upload(new Blob(chunks,{type:recorder.mimeType}));};
      recorder.start(1000);$('record-voice').textContent='结束录音并转写';status('正在录音，最长3分钟；点击结束后上传转写。');
      limit=setTimeout(()=>{if(recorder?.state==='recording')recorder.stop();},179000);
    }catch(error){stream?.getTracks().forEach(t=>t.stop());status('无法使用麦克风，请检查浏览器权限或上传录音。');}
  };
  $('voice-file').onchange=()=>{const file=$('voice-file').files[0];if(file)upload(file);$('voice-file').value='';};
  window.addEventListener('pagehide',()=>{clearTimeout(limit);if(recorder)recorder.onstop=null;stream?.getTracks().forEach(t=>t.stop());});
})();
