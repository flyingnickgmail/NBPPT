/* Fixed local shaders, never supplied by a model. Depth-tested solids retain
   SVG labels, source interactions and the existing vector fallback. */
window.ReportSpaceGPU=(()=>{
  const key=p=>p.map(v=>v.toFixed(6)).join(',');
  function smoothNormals(faces){
    const vertices=new Map();
    faces.forEach(f=>f.points.forEach(p=>{const k=f.partIndex+':'+key(p);if(!vertices.has(k))vertices.set(k,[]);vertices.get(k).push(f);}));
    return faces.map(f=>f.points.map(p=>{
      if(['box','prism'].includes(f.part.shape)||f.points.length>4)return f.normal;
      const neighbours=vertices.get(f.partIndex+':'+key(p)).filter(face=>face.points.length<=4).map(face=>face.normal).filter(n=>n.reduce((s,v,i)=>s+v*f.normal[i],0)>.65);
      const sum=neighbours.reduce((s,n)=>s.map((v,i)=>v+n[i]),[0,0,0]),length=Math.hypot(...sum)||1;
      return sum.map(v=>v/length);
    }));
  }
  function create(canvas,onLoss){
    const gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:false,preserveDrawingBuffer:true});
    if(!gl)return null;
    const vertex=`attribute vec3 position;attribute vec3 normal;attribute vec3 base;attribute vec3 finish;
      varying vec3 vNormal;varying vec3 vBase;varying vec3 vFinish;
      void main(){gl_Position=vec4(position,1.0);vNormal=normal;vBase=base;vFinish=finish;}`;
    const fragment=`precision mediump float;varying vec3 vNormal;varying vec3 vBase;varying vec3 vFinish;
      void main(){
        vec3 n=normalize(vNormal),light=normalize(vec3(-.45,-.65,.85)),view=normalize(vec3(0.,-.88,.46));
        float diffuse=max(0.,dot(n,light)),rim=pow(1.-max(0.,dot(n,view)),3.);
        float spec=pow(max(0.,dot(n,normalize(light+view))),mix(12.,80.,vFinish.x));
        float glass=step(.85,vFinish.x);
        float studioBand=exp(-pow((dot(n,normalize(vec3(.2,-.65,.74)))-.72)*10.,2.));
        vec3 c=vBase*(.64+.38*diffuse)*(1.-glass*.3)+vec3(.93,.92,.89)*(spec*vFinish.y+rim*vFinish.y*.17);
        c+=glass*vec3(.92,.93,.94)*(.035+studioBand*.13);
        gl_FragColor=vec4(clamp(c,0.,1.),vFinish.z);
      }`;
    const shaders=[];
    const compile=(type,text)=>{const shader=gl.createShader(type);shaders.push(shader);gl.shaderSource(shader,text);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw new Error('Spatial shader compile failed');return shader;};
    let program,buffer;
    try{
      program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);
      if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('Spatial shader link failed');
      buffer=gl.createBuffer();
    }catch(_){shaders.forEach(s=>gl.deleteShader(s));if(program)gl.deleteProgram(program);return null;}
    shaders.forEach(s=>gl.deleteShader(s));
    const attributes=['position','normal','base','finish'].map(name=>gl.getAttribLocation(program,name));
    let lost=false;
    canvas.addEventListener('webglcontextlost',()=>{lost=true;onLoss();});
    const finishes={metal:[.65,.23],glass:[.9,.32],ceramic:[.35,.08],paper:[.05,.015],fiber:[.08,.015],rubber:[.1,.025]};
    function draw(items,normals,rotate,yaw,tones,opacity,night=false){
      if(lost||gl.isContextLost())return false;
      const data=[];
      for(const item of items){
        if(!item.front)continue;
        const part=item.f.part,tone=part.tone==='blue'?'accent':part.tone;
        let rgb=tones[tone]||tones.silver;
        // Night fill light must not turn dark glass or tyres into white solids.
        if(night&&tone==='ink'&&['glass','rubber'].includes(part.material))rgb=rgb.map((v,i)=>v*.35+window.ReportBrand.tones.ink[i]*.65);
        const base=rgb.map(v=>v/255),finish=finishes[part.material]||finishes.paper;
        const alpha=opacity(part.group);if(alpha<.001)continue;
        const add=i=>{const p=item.screen[i],n=rotate(normals[item.index][i],[0,0,yaw*180/Math.PI]);data.push(p[0]/340-1,1-p[1]/305,item.depths[i]/100,...n,...base,...finish,alpha);};
        for(let i=1;i<item.screen.length-1;i++){add(0);add(i);add(i+1);}
      }
      gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clearDepth(1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
      gl.useProgram(program);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.DYNAMIC_DRAW);
      attributes.forEach((location,i)=>{gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,48,i*12);});
      gl.drawArrays(gl.TRIANGLES,0,data.length/12);
      return true;
    }
    return {draw};
  }
  return {create,smoothNormals};
})();
