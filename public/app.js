'use strict';

const byId = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const state = {data: null, roomType: '', metric: 'area', source: 'outline', selected: null, zoom: 1, origin: null, frame: null};
const svg = byId('plan');
const allType = '*';
const labelNames = {
  balcone: ['balconies', 'balcony', 'balconi'], bagno: ['bathroom', 'bathrooms', 'bagni'],
  cucina: ['kitchen', 'kitchens', 'cucine'], corridoio: ['corridor', 'corridors', 'corridoi', 'hallway', 'hallways'],
  stanza: ['stanze'], schlafzimmer: ['bedroom', 'bedrooms'], balkon: ['balcony', 'balconies'],
  kuche: ['kitchen', 'kitchens'], bad: ['bathroom', 'bathrooms'], korridor: ['corridor', 'corridors']
};
const number = new Intl.NumberFormat('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const normalized = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const tokens = value => normalized(value).split(/[^a-z0-9]+/).filter(Boolean);
const points = ring => ring.map(([x,y]) => x + ',' + -y).join(' ');
const make = (tag, attrs = {}) => {
  const el = document.createElementNS(svgNS, tag);
  Object.entries(attrs).forEach(([name, value]) => el.setAttribute(name, value));
  return el;
};
function roomValue(room) {
  return state.source === 'printed' ? room.printedArea : room.area;
}
function unitValue(value) {
  return Number.isFinite(value) ? number.format(value) + ' m²' : 'Unavailable';
}
function roomLabel(room) { return room.label || 'Unlabelled room'; }
function matches() {
  return state.data.rooms.filter(r => state.roomType === allType ? r.numbered !== false && r.label : r.label === state.roomType);
}
function labelOptions() {
  return [...new Set(state.data.rooms.map(room => room.label).filter(Boolean))].sort((a,b) => a.localeCompare(b));
}
function setQueryForSelection() {
  const label = state.roomType === allType ? 'all numbered, labelled rooms' : 'rooms labelled “' + state.roomType + '”';
  byId('query').value = state.metric === 'count' ? 'How many ' + label + ' are on this floor?' : 'What is the total area of ' + label + '?';
}
function message(line) {
  byId('query-message').textContent = line;
  byId('query-message').hidden = !line;
}
function choose(type, metric) {
  state.roomType = type;
  state.metric = metric;
  byId('room-type').value = type;
  const rooms = matches();
  state.selected = rooms.length ? rooms[0].id : null;
  message('');
  render();
}
function parseQuery(text) {
  const words = tokens(text);
  const wordSet = new Set(words);
  const simple = words.join(' ');
  const metric = /\b(area|square|metri|superficie|flache|flachensumme|m2|nettoflaeche|nettoflache)\b/.test(simple) ? 'area'
    : /\b(count|many|number|combien|quanti|quante|viele|numero)\b/.test(simple) ? 'count' : null;
  if (!metric) return null;
  // These require an operation or area scope beyond a simple count/sum.
  if (/\b(except|exclud\w*|without|excluding|minus|largest|smallest|average|mean|maximum|minimum|between|only indoor|indoor|outdoor|apartment|apartments|unit|units)\b/.test(simple)) return null;
  const hits = labelOptions().filter(label => [normalized(label), ...(labelNames[normalized(label)] || [])].some(alias => wordSet.has(alias)));
  if (hits.length > 1) return null;
  if (hits.length === 1) return {type: hits[0], metric};
  if (/\ball (?:the )?(?:numbered )?(?:labelled |labeled )?rooms\b/.test(simple)) return {type: allType, metric};
  return null;
}
function fitView() {
  const [xmin,ymin,xmax,ymax] = state.data.bounds;
  const w = xmax - xmin, h = ymax - ymin;
  const margin = Math.max(w,h) * .065;
  state.frame = [xmin-margin, -ymax-margin, w+margin*2, h+margin*2];
  state.origin = [xmin+w/2, -(ymin+h/2)];
  state.zoom = 1;
  applyView();
}
function applyView() {
  if (!state.frame) return;
  const [x,y,w,h] = state.frame;
  const vw = w/state.zoom, vh=h/state.zoom;
  const cx = Math.min(x+w-vw/2, Math.max(x+vw/2,state.origin[0]));
  const cy = Math.min(y+h-vh/2, Math.max(y+vh/2,state.origin[1]));
  state.origin=[cx,cy];
  svg.setAttribute('viewBox',[cx-vw/2,cy-vh/2,vw,vh].join(' '));
  byId('zoom-level').textContent = Math.round(100*state.zoom)+'%';
  byId('zoom-in').disabled = state.zoom >= 4;
  byId('zoom-out').disabled = state.zoom <= 1;
  byId('stage').classList.toggle('zoomed',state.zoom>1);
}
function changeZoom(factor) {
  if (!state.data) return;
  if (state.zoom === 1 && factor > 1 && state.selected) {
    const rt=state.data.rooms.find(r=>r.id===state.selected);
    if (rt) state.origin=[rt.center[0],-rt.center[1]];
  }
  state.zoom=Math.min(4,Math.max(1,state.zoom*factor));
  applyView();
}
let drag=null, suppressClick=false;
svg.addEventListener('pointerdown', event => {
  if (event.button!==0 || state.zoom<=1) return;
  const scale=svg.getScreenCTM()?.a;
  if (scale) drag={id:event.pointerId,x:event.clientX,y:event.clientY,origin:[...state.origin],scale,moved:false};
});
svg.addEventListener('pointermove', event=>{
  if (!drag || drag.id!==event.pointerId) return;
  const dx=event.clientX-drag.x, dy=event.clientY-drag.y;
  if (!drag.moved && Math.hypot(dx,dy)>4) {drag.moved=true;svg.setPointerCapture(event.pointerId);}
  if (!drag.moved) return;
  state.origin=[drag.origin[0]-dx/drag.scale,drag.origin[1]-dy/drag.scale];applyView();
});
function endDrag(event) {
  if (!drag || drag.id!==event.pointerId) return;
  suppressClick=drag.moved;drag=null;
  if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
  if (suppressClick) setTimeout(()=>{suppressClick=false;}, 0);
}
svg.addEventListener('pointerup',endDrag);svg.addEventListener('pointercancel',endDrag);
function selectRoom(id) {
  state.selected=id;
  render();
}
function draw(rooms) {
  const markers=new Map(rooms.map((r,i)=>[r.id,i+1]));
  const layer=document.createDocumentFragment();
  const edges=make('g');
  const textLayer=make('g',{'aria-hidden':'true'});
  const regionLayer=make('g');
  const [, , fw,fh] = state.frame;
  const radius=Math.min(fw,fh)*.020;
  for (const room of state.data.rooms) {
    if (!room.polygon?.length) continue;
    const match=markers.has(room.id), selected=state.selected===room.id;
    const poly=make('polygon',{points:points(room.polygon),class:'room-shape'+(match?' match':'')+(selected?' chosen':''),'data-room-id':room.id});
    const title=make('title');title.textContent=room.id+' · '+roomLabel(room)+' · '+unitValue(roomValue(room));poly.append(title);
    regionLayer.append(poly);
    const [x,y]=room.center;
    if (match) {
      const marker=make('g',{class:'map-marker'+(selected?' chosen':''),'data-room-id':room.id,transform:'translate('+x+' '+(-y)+')'});
      marker.append(make('circle',{r:radius}));
      const txt=make('text',{'font-size':radius*1.12});txt.textContent=markers.get(room.id);marker.append(txt);textLayer.append(marker);
    } else if (room.numbered!==false) {
      const txt=make('text',{class:'map-room-name',x,y:-y,'font-size':radius*.72});
      txt.textContent=room.id;textLayer.append(txt);
    }
  }
  for (const wall of state.data.walls) {
    if(wall.length>1) edges.append(make('polygon',{points:points(wall),class:'plan-wall'}));
  }
  for (const line of state.data.detailLines||[]) {
    if(line.length>1) edges.append(make('polyline',{points:points(line),class:'plan-detail'}));
  }
  layer.append(regionLayer,edges,textLayer);svg.replaceChildren(layer);
}
svg.addEventListener('click',event=>{
  const id=event.target.closest('[data-room-id]')?.getAttribute('data-room-id');
  if (id && !suppressClick) selectRoom(id);
});
function setMode(source) {
  state.source=source;
  byId('outline-mode').setAttribute('aria-pressed',String(source==='outline'));
  byId('printed-mode').setAttribute('aria-pressed',String(source==='printed'));
  if (state.data) render();
}
function render() {
  const rooms=matches();
  draw(rooms);
  const known=rooms.map(roomValue).filter(Number.isFinite);
  const total=known.reduce((sum,value)=>sum+value,0);
  const complete=known.length===rooms.length && rooms.length>0;
  byId('answer-title').textContent=state.metric==='count'?'Room count':'Combined area';
  const result=byId('answer');result.replaceChildren();
  const answer=state.metric==='count'?String(rooms.length):complete?number.format(total):'—';
  result.append(document.createTextNode(answer));
  if (state.metric==='area' && complete) {const unit=document.createElement('small');unit.textContent=' m²';result.append(unit);}
  const noun=rooms.length===1?'room':'rooms';
  const groupName=state.roomType===allType?'numbered, labelled rooms':'labelled “'+state.roomType+'”';
  byId('answer-caption').textContent=state.metric==='area'&&!complete&&rooms.length?'Area missing for '+(rooms.length-known.length)+' of '+rooms.length+' '+noun+'.':rooms.length+' '+noun+' '+(state.roomType===allType?'included':groupName);
  byId('evidence-count').textContent=rooms.length+' '+(rooms.length===1?'match':'matches');
  const buttons=document.createDocumentFragment();
  rooms.forEach((room,index)=>{
    const btn=document.createElement('button');btn.type='button';btn.className='evidence-row';btn.dataset.roomId=room.id;
    btn.setAttribute('aria-pressed',String(state.selected===room.id));
    btn.setAttribute('aria-label','Inspect room '+room.id+', '+roomLabel(room)+', '+unitValue(roomValue(room)));
    for (const [className,value] of [['number',String(index+1)],['room-id','Room '+room.id],['area',unitValue(roomValue(room))]]) {
      const span=document.createElement('span');span.className=className;span.textContent=value;btn.append(span);
    }
    buttons.append(btn);
  });
  if(!rooms.length){const p=document.createElement('p');p.className='empty-evidence';p.textContent='No rooms match this selection.';buttons.append(p);}
  const list=byId('evidence');
  const hadFocus=list.contains(document.activeElement);
  list.replaceChildren(buttons);
  if(hadFocus) [...list.children].find(b=>b.dataset.roomId===state.selected)?.focus({preventScroll:true});
  const room=state.data.rooms.find(r=>r.id===state.selected);
  const detail=byId('room-detail');detail.hidden=!room;
  if(room)detail.textContent='Room '+room.id+' · '+roomLabel(room)+' — outline '+room.area.toFixed(5)+' m², printed '+unitValue(room.printedArea)+'.';
}
byId('evidence').addEventListener('click', event=>{
  const id=event.target.closest('[data-room-id]')?.dataset.roomId;
  if(id) selectRoom(id);
});
byId('query-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(!state.data) return;
  const result=parseQuery(byId('query').value);
  if (result) choose(result.type,result.metric);
  else message('This sheet supports room counts and combined areas by label. Choose a room type below, or ask “How many rooms are labelled '+(state.roomType===allType?labelOptions()[0]:state.roomType)+'?” The previous result is still displayed.');
});
byId('room-type').addEventListener('change',event=>{choose(event.target.value,state.metric);setQueryForSelection();});
byId('outline-mode').addEventListener('click',()=>setMode('outline'));
byId('printed-mode').addEventListener('click',()=>setMode('printed'));
byId('zoom-fit').addEventListener('click',()=>{if(state.data)fitView();});
byId('zoom-in').addEventListener('click',()=>changeZoom(1.5));
byId('zoom-out').addEventListener('click',()=>changeZoom(1/1.5));
function addLink(title,url) {
  if (!url) return;
  const link=document.createElement('a');link.textContent=title;link.href=url;link.target='_blank';link.rel='noopener';byId('sheet-links').append(link);
}
async function loadSheet() {
  try {
    const response=await fetch('/data/swiss-floor.json');
    if(!response.ok) throw new Error('Drawing data unavailable');
    state.data=await response.json();
    const {sheet,rooms}=state.data;
    byId('drawing-title').textContent=sheet.title||'Floor plan';
    byId('sheet-id').textContent=sheet.id;
    byId('sheet-credit').textContent=sheet.credit;
    addLink('Original PDF',sheet.pdfUrl);addLink('DXF',sheet.dxfUrl);addLink('Dataset',sheet.sourceUrl);addLink('Licence',sheet.licenseUrl);
    const select=byId('room-type');
    for(const label of labelOptions()){const option=new Option(label,label);select.add(option);}
    select.add(new Option('All numbered, labelled rooms',allType));select.disabled=false;
    const frequencies=new Map();
    for(const room of rooms){if(room.label)frequencies.set(room.label,(frequencies.get(room.label)||0)+1);}
    const first=[...frequencies].sort((a,b)=>b[1]-a[1])[0]?.[0]||allType;
    fitView();choose(first,'area');setQueryForSelection();
    byId('loading').hidden=true;
  } catch (error) {
    byId('loading').textContent='Could not load the drawing. Reload the page to try again.';
    byId('ask').disabled=true;
    console.error(error);
  }
}
loadSheet();
