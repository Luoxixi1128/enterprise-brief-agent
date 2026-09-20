/* Adapted from the supplied FDE X website's particle-network and fde-matrix.
   Kept behind the workspace: no pointer interception or external requests. */
(() => {
  const canvas = document.getElementById('workspace-background');
  const ctx = canvas?.getContext('2d');
  if (!ctx) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const logo = new Image();
  let width = 0, height = 0, nodes = [], matrix = [], crop = null;
  let pointer = null, frame = 0, previous = 0;
  const ink = [23, 22, 20], line = [229, 225, 214];
  const rgba = (color, alpha) => `rgba(${color.join(',')},${alpha})`;

  function readLogo() {
    const sample = document.createElement('canvas');
    sample.width = sample.height = 1024;
    const c = sample.getContext('2d', {willReadFrequently:true});
    c.drawImage(logo, 0, 0, 1024, 1024);
    const pixels = c.getImageData(0, 0, 1024, 1024).data;
    let left = 1024, top = 1024, right = 0, bottom = 0;
    const columns = Array(1024).fill(false);
    for (let y=0; y<1024; y+=2) for (let x=0; x<1024; x+=2) {
      const p=(y*1024+x)*4;
      if (pixels[p]>150 && pixels[p+1]>150 && pixels[p+2]>150) {
        left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);columns[x]=true;
      }
    }
    // Match the reference's crop: separate the left icon from its FDE X lettering.
    let gapStart=-1, longest=0, chosen=-1;
    for(let x=0;x<1024;x++) {
      if(!columns[x]) {if(gapStart<0)gapStart=x;}
      else if(gapStart>=0) {
        if(x-gapStart>longest){longest=x-gapStart;chosen=gapStart;}gapStart=-1;
      }
    }
    if(longest>40 && chosen+longest>left)left=chosen+longest;
    if(right>left && bottom>top)crop={left,top,width:right-left,height:bottom-top};
    buildMatrix();
  }
  function buildMatrix() {
    if(!crop || !width)return;
    const w=Math.max(1,Math.round(Math.min(width*.72,1200)));
    const h=Math.max(1,Math.round(w*crop.height/crop.width));
    const sample=document.createElement('canvas');sample.width=w;sample.height=h;
    const c=sample.getContext('2d',{willReadFrequently:true});
    c.drawImage(logo,crop.left,crop.top,crop.width,crop.height,0,0,w,h);
    const pixels=c.getImageData(0,0,w,h).data;
    let count=0;
    for(let y=0;y<h;y+=4)for(let x=0;x<w;x+=4)if(pixels[(y*w+x)*4]>150)count++;
    const step=Math.max(3,Math.round(Math.sqrt(count*16/1500)));
    const offsetX=width*.944-w,offsetY=height*.669-h;
    matrix=[];
    for(let y=0;y<h;y+=step)for(let x=0;x<w;x+=step)if(pixels[(y*w+x)*4]>150) {
      const ox=offsetX+x,oy=offsetY+y;
      matrix.push({x:ox,y:oy,ox,oy,vx:0,vy:0,size:1.2+Math.random()*1.3});
    }
  }
  function resize() {
    const w=innerWidth,h=innerHeight;
    if(w===width && h===height)return;
    width=w;height=h;
    const ratio=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
    ctx.setTransform(ratio,0,0,ratio,0,0);
    const count=Math.min(110,Math.max(36,Math.round(w*h/16000)));
    nodes=Array.from({length:count},(_,i)=>({x:Math.random()*w,y:Math.random()*h,vx:(Math.random()-.5)*.16,vy:(Math.random()-.5)*.16,size:i<Math.max(4,Math.round(count*.06))?3:1+Math.random()*1.5,phase:Math.random()*Math.PI*2}));
    buildMatrix();draw(0,0);
  }
  function draw(time,dt) {
    ctx.clearRect(0,0,width,height);
    for(const p of matrix) {
      if(dt) {
        let fx=(p.ox-p.x)*.05,fy=(p.oy-p.y)*.05;
        if(pointer) {
          const dx=p.x-pointer.x,dy=p.y-pointer.y,d=Math.hypot(dx,dy);
          if(d<70 && d>.5){const force=.9*(1-(d/70)**2)*2;fx+=dx/d*force;fy+=dy/d*force;}
        }
        p.vx=(p.vx+fx*dt)*Math.pow(.82,dt);p.vy=(p.vy+fy*dt)*Math.pow(.82,dt);
        p.x+=p.vx*dt;p.y+=p.vy*dt;
      }
      const glow=pointer?Math.max(0,1-Math.hypot(p.x-pointer.x,p.y-pointer.y)/200):0;
      ctx.fillStyle=rgba(line.map((c,i)=>Math.round(c+(ink[i]-c)*glow)),.9);
      ctx.fillRect(p.x-p.size/2,p.y-p.size/2,p.size,p.size);
    }
    ctx.lineWidth=1;
    for(let i=0;i<nodes.length;i++) {
      const p=nodes[i];
      if(dt) {
        p.x+=p.vx*dt;p.y+=(p.vy+Math.sin(time/1000*.6+p.phase)*.25)*dt;
        if(p.x<4||p.x>width-4)p.vx*=-1;if(p.y<4||p.y>height-4)p.vy*=-1;
        p.x=Math.max(2,Math.min(width-2,p.x));p.y=Math.max(2,Math.min(height-2,p.y));
      }
      for(let j=i+1;j<nodes.length;j++) {
        const q=nodes[j],distance=Math.hypot(p.x-q.x,p.y-q.y);
        if(distance<130){ctx.strokeStyle=rgba([138,133,120],(1-distance/130)*.22);ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();}
      }
      if(pointer) {
        const distance=Math.hypot(p.x-pointer.x,p.y-pointer.y);
        if(distance<150){ctx.strokeStyle=rgba(ink,(1-distance/150)*.5);ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(pointer.x,pointer.y);ctx.stroke();}
      }
      ctx.fillStyle=rgba(ink,.8);ctx.fillRect(p.x-p.size/2,p.y-p.size/2,p.size,p.size);
    }
  }
  function tick(time) {
    if(document.hidden || reduced.matches){frame=0;return;}
    if(!previous || time-previous>=1000/30) {
      draw(time,previous?Math.min((time-previous)/(1000/60),2.5):1);previous=time;
    }
    frame=requestAnimationFrame(tick);
  }
  function restart() {
    cancelAnimationFrame(frame);frame=0;previous=0;
    if(!document.hidden && !reduced.matches)frame=requestAnimationFrame(tick);
    else draw(0,0);
  }
  function leave(){pointer=null;if(reduced.matches)draw(0,0);}
  window.addEventListener('pointermove',event=>{pointer={x:event.clientX,y:event.clientY};if(reduced.matches)draw(0,0);},{passive:true});
  document.documentElement.addEventListener('pointerleave',leave);
  window.addEventListener('blur',leave);
  window.addEventListener('resize',resize,{passive:true});
  document.addEventListener('visibilitychange',restart);
  reduced.addEventListener('change',restart);
  logo.onload=()=>{readLogo();if(reduced.matches)draw(0,0);};
  logo.src='/matrix-logo.png';
  resize();restart();
})();
