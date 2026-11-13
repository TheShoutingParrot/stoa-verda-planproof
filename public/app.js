'use strict';

const byId = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const state = {data: null, roomType: null, roomId: null, scope: null, metric: 'area', source: 'outline', selected: null, zoom: 1, origin: null, frame: null};
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
const objectNames = {
  doors: 'Door', windows: 'Window', toilets: 'Toilet', washbasins: 'Washbasin', bathtubs: 'Bathtub', showers: 'Shower'
};
function featureName(item) {
  if (state.scope?.kind === 'object_count') return objectNames[state.scope.target] + ' ' + item.id.split('-').pop();
  if (state.scope?.kind === 'apartment_count') return 'Apartment ' + item.id.slice(5);
  return 'Room ' + item.id;
}
function countsFeatures() {
  return state.scope?.kind === 'object_count' || state.scope?.kind === 'apartment_count';
}
function matches() {
  const {scope, data} = state;
  if (scope?.kind === 'object_count') return data.objects[scope.target];
  if (scope?.kind === 'apartment_count') return data.apartments.map(unit => ({...unit, id:'unit:'+unit.id, center:unit.labelPoint}));
  if (scope?.kind === 'floor_area' || scope?.kind === 'apartment_area') {
    const ids = new Set(scope.kind === 'floor_area' ? data.indoorRoomIds : data.apartments.find(u => u.id === scope.target).roomIds);
    return data.rooms.filter(room => ids.has(room.id));
  }
  if (state.roomId !== null) return state.data.rooms.filter(room => room.numbered && room.id === state.roomId);
  return state.data.rooms.filter(r => state.roomType === allType ? r.numbered !== false && r.label : r.label === state.roomType);
}
function labelOptions() {
  return [...new Set(state.data.rooms.map(room => room.label).filter(Boolean))].sort((a,b) => a.localeCompare(b));
}
function setQueryForSelection() {
  if (state.scope) {
    const {kind, target} = state.scope;
    const question = {object_count:'How many '+target+' are drawn on this floor plan?', apartment_count:'How many apartments are on this floor?',
      floor_area:'What is the net area of all numbered indoor rooms?', apartment_area:'What is the net indoor area of apartment '+target+'?'};
    byId('query').value = question[kind];
    return;
  }
  if (state.roomId !== null) {
    byId('query').value = 'What is the area of room ' + state.roomId + '?';
    return;
  }
  const label = state.roomType === allType ? 'all numbered, labelled rooms' : 'rooms labelled “' + state.roomType + '”';
  byId('query').value = state.metric === 'count' ? 'How many ' + label + ' are on this floor?' : 'What is the total area of ' + label + '?';
}
function message(line) {
  byId('query-message').textContent = line;
  byId('query-message').hidden = !line;
}
function scopeKey(scope) { return '@' + scope.kind + (scope.target ? ':'+scope.target : ''); }
function choose(type, metric, roomId = null, scope = null) {
  state.scope = scope;
  state.roomType = type;
  state.roomId = roomId;
  state.metric = metric;
  byId('room-type').value = scope ? scopeKey(scope) : roomId === null ? (type ?? '') : 'room:' + roomId;
  const rooms = matches();
  state.selected = rooms.length ? rooms[0].id : null;
  message('');
  render();
}
// A numbered-room request must resolve to a single polygon before label aggregation.
function parseRoomQuery(text) {
  const input = normalized(text).replace(/[−–]/g, '-');
  const identifiers = input.match(/(?<![\w.])-?[a-z]*\d+\.\d+(?!\w|\.\d)/g) || [];
  if (!identifiers.length) return null;
  const unsupported = {error: 'Ask for the area of one numbered room at a time.'};
  if (identifiers.length !== 1) return unsupported;
  const id = identifiers[0];
  const labelHint = input.match(/\(\s*['"“«]([^()]+?)['"”»]\s*\)/);
  let remainder = (labelHint ? input.replace(labelHint[0], '') : input).replace(id, ' ');
  remainder = remainder.replace(/\bm(?:²|\^?2)\b|m²/g, ' ').replace(/[.,?!#]/g, ' ').trim();
  // Limit this operation to a room lookup. Extra objects, filters and dimensions change the question.
  const allowed = new Set(('what s is the net floor area of for in how big large size show me get find room number no '
    + 'wie gross groß ist die nettoflache flache von vom raum zimmer '
    + 'quelle est la surface nette de piece du local '
    + 'qual e superficie netta del locale stanza').split(/\s+/));
  const words = tokens(remainder);
  if (words.some(word => !allowed.has(word))) return unsupported;
  if (/[^a-z0-9\s'’ß]/.test(remainder)) return unsupported;
  const room = state.data.rooms.find(r => r.numbered && normalized(r.id) === id);
  if (!room) return {error: 'Room ' + id.toUpperCase() + ' could not be uniquely identified on this drawing.'};
  if (labelHint && normalized(room.label) !== labelHint[1].trim()) {
    return {error: 'Room ' + room.id + ' is labelled “' + roomLabel(room) + '” on this drawing.'};
  }
  return {type: null, metric: 'area', roomId: room.id};
}
function takeoffQuery(text) {
  const q = tokens(text.replace(/m²/gi, 'm2')).join(' ');
  const count = q.match(/^(?:how many|count(?: the)?|number of) (.+?)(?: (?:are |are there )?(?:drawn |shown )?(?:on|in) (?:this|the) (?:floor plan|drawing|floor|plan))?$/);
  if (count) {
    const noun = count[1].replace(/ (?:interior doors and entrance doors together|wc|residential units)$/, '');
    const objects = {door:'doors', doors:'doors', window:'windows', windows:'windows', toilet:'toilets', toilets:'toilets',
      washbasin:'washbasins', washbasins:'washbasins', bathtub:'bathtubs', bathtubs:'bathtubs', shower:'showers', showers:'showers'};
    if (Object.hasOwn(objects, noun) && state.data.objects) return {metric:'count', scope:{kind:'object_count', target:objects[noun]}};
    if (/^(?:apartments?|residential units?)$/.test(noun) && state.data.apartments) {
      if (state.data.apartmentCountComplete === false) return {error:'Some apartment boundaries could not be resolved on this drawing.'};
      return {metric:'count', scope:{kind:'apartment_count'}};
    }
  }
  const lead = '(?:(?:what is (?:the )?|show (?:the )?)?(?:total )?(?:net )?(?:indoor |floor )?area(?: in m2)? of )';
  const apartment = q.match(new RegExp('^'+lead+'(?:apartment|unit) ([a-z0-9]+)(?: in m2)?(?: summing all its rooms except balconies loggias terraces and other outdoor spaces)?$'));
  if (apartment && state.data.apartments) {
    const unit = state.data.apartments.find(u => normalized(u.id) === apartment[1]);
    if (!unit || !unit.complete) return {error:'The indoor rooms of apartment '+apartment[1].toUpperCase()+' could not be resolved on this drawing.'};
    return {metric:'area', scope:{kind:'apartment_area', target:unit.id}};
  }
  if (new RegExp('^'+lead+'(?:all )?(?:numbered )?indoor rooms(?: on this floor)?(?: excluding balconies loggias terraces and other outdoor spaces shafts and voids)?$').test(q) && state.data.indoorRoomIds) {
    if (state.data.floorComplete === false) return {error:'Some indoor room boundaries could not be resolved on this drawing.'};
    return {metric:'area', scope:{kind:'floor_area'}};
  }
  return null;
}
function parseQuery(text) {
  text = text.trim().replace(/^(?:(?:please|(?:can|could) you(?: please)?(?: tell me)?|i(?: would like to know| need to know))\s+)+/i, '');
  const direct = takeoffQuery(text) || parseRoomQuery(text);
  if (direct) return direct;
  const words = tokens(text);
  const wordSet = new Set(words);
  const simple = words.join(' ');
  const metric = /\b(area|square|metri|superficie|flache|flachensumme|m2|nettoflaeche|nettoflache)\b/.test(simple) ? 'area'
    : /\b(count|many|number|combien|quanti|quante|viele|numero)\b/.test(simple) ? 'count' : null;
  if (!metric) return null;
  // These require an operation or area scope beyond a simple count/sum.
  if (/\b(except|exclud\w*|without|excluding|minus|largest|smallest|average|mean|maximum|minimum|between|larger|smaller|greater|less|over|under|above|below|only indoor|indoor|outdoor|apartment|apartments|unit|units)\b/.test(simple)) return null;
  // English room questions must consume the whole request, so extra objects,
  // conditions or units cannot silently become a room subtotal.
  if (/^(?:how|what|count|number|total|area|show)\b/.test(simple)) {
    const input = text.trim().replace(/[?!.]+$/, '').trim();
    const count = input.match(/^(?:how many|(?:count|number of)(?: the)?)\s+(.+?)(?:\s+(?:are there|are|are shown|are drawn))?(?:\s+(?:on|in) (?:this|the) (?:floor plan|floor|drawing))?$/i);
    const area = input.match(/^(?:(?:what(?:'s| is)|show(?: me)?)\s+)?(?:the )?(?:total |combined )?(?:net )?(?:floor )?area(?: in (?:m²|m2|square metres|square meters))? of (.+?)(?: on this floor)?$/i);
    if (!count && !area) return null;
    const target = (count || area)[1].trim();
    const metric = count ? 'count' : 'area';
    const named = target.match(/^(?:all (?:the )?)?rooms? (?:labelled|labeled|named|called) (.+)$/i);
    if (named) {
      const name = named[1].replace(/^['"“«]\s*(.*?)\s*['"”»]$/, '$1');
      const label = labelOptions().find(option => normalized(option) === normalized(name));
      return label ? {type:label, metric} : {error:'No room has the label “'+name+'” on this drawing.'};
    }
    if (/^all (?:the )?numbered[, ]+(?:labelled |labeled )rooms$/i.test(target)) return {type:allType, metric};
    const name = normalized(target).replace(/^(?:all |the )+/, '').replace(/ rooms?$/, '').trim();
    const labels = labelOptions().filter(option => [normalized(option), ...(labelNames[normalized(option)] || [])].includes(name));
    return labels.length === 1 ? {type:labels[0], metric} : null;
  }
  if (!/^(?:wie|wieviel|combien|quelle?|quali?|quanti|quante|quale|numero)\b/.test(simple)) return null;
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
    const rt=matches().find(r=>r.id===state.selected) || state.data.rooms.find(r=>r.id===state.selected);
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
  if (state.roomId !== null && state.roomId !== id) {
    const room = state.data.rooms.find(r => r.id === id);
    if (room?.numbered) {
      choose(null, 'area', room.id);
      setQueryForSelection();
    }
    return;
  }
  if (countsFeatures() && !matches().some(item => item.id === id)) return;
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
    const shape = {class:'room-shape'+(match?' match':'')+(selected?' chosen':''),'data-room-id':room.id};
    const poly = room.holes?.length
      ? make('path', {...shape, d:[room.polygon, ...room.holes].map(ring => 'M'+points(ring)+'Z').join(' '), 'fill-rule':'evenodd'})
      : make('polygon', {...shape, points:points(room.polygon)});
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
  if (countsFeatures()) {
    for (const [index,item] of rooms.entries()) {
      const group = make('g', {'data-room-id':item.id, class:'takeoff-feature'+(item.id===state.selected?' chosen':'')});
      if (item.polygon?.length) {
        for (const part of [item, ...(item.additionalFootprints || [])]) {
          const d = [part.polygon, ...(part.holes || [])].map(ring => 'M'+points(ring)+'Z').join(' ');
          group.append(make('path', {d, 'fill-rule':'evenodd', class:'unit-geometry'}));
        }
      }
      for (const line of item.lines || []) group.append(make('polyline',{points:points(line),class:'feature-line'}));
      const [x,y] = item.center;
      const marker = make('g',{class:'map-marker',transform:'translate('+x+' '+(-y)+')'});
      marker.append(make('circle',{r:radius*.67}));
      const text = make('text',{'font-size':radius*.85}); text.textContent=index+1; marker.append(text);
      const title=make('title'); title.textContent=featureName(item); group.append(title,marker); textLayer.append(group);
    }
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
  const specific = state.roomId !== null;
  const empty = !specific && !state.scope && state.roomType === null;
  byId('answer-title').textContent=empty?'No result':specific?'Room area':state.metric==='count'?'Room count':'Combined area';
  if (state.scope) byId('answer-title').textContent = {object_count:objectNames[state.scope.target]+' count',apartment_count:'Apartment count',
    apartment_area:'Apartment '+state.scope.target+' · indoor area',floor_area:'Indoor floor area'}[state.scope.kind];
  byId('outline-mode').disabled = byId('printed-mode').disabled = state.metric === 'count';
  const result=byId('answer');result.replaceChildren();
  const answer=state.metric==='count'?String(rooms.length):complete?number.format(total):'—';
  result.append(document.createTextNode(answer));
  if (state.metric==='area' && complete) {const unit=document.createElement('small');unit.textContent=' m²';result.append(unit);}
  const noun=rooms.length===1?'room':'rooms';
  const groupName=state.roomType===allType?'numbered, labelled rooms':'labelled “'+state.roomType+'”';
  byId('answer-caption').textContent=state.metric==='area'&&!complete&&rooms.length?'Area missing for '+(rooms.length-known.length)+' of '+rooms.length+' '+noun+'.':rooms.length+' '+noun+' '+(state.roomType===allType?'included':groupName);
  if (specific && rooms.length) byId('answer-caption').textContent='Room '+rooms[0].id+' · '+roomLabel(rooms[0]);
  if (state.scope && (state.metric==='count' || complete)) byId('answer-caption').textContent = countsFeatures() ? 'Counted on this drawing' : rooms.length+' indoor '+noun+' included';
  if (empty) byId('answer-caption').textContent='';
  byId('evidence-count').textContent=rooms.length+' '+(rooms.length===1?'match':'matches');
  const buttons=document.createDocumentFragment();
  rooms.forEach((room,index)=>{
    const btn=document.createElement('button');btn.type='button';btn.className='evidence-row';btn.dataset.roomId=room.id;
    btn.setAttribute('aria-pressed',String(state.selected===room.id));
    const name = featureName(room);
    const columns = [['number',String(index+1)],['room-id',name]];
    if (!countsFeatures()) columns.push(['area',unitValue(roomValue(room))]);
    btn.setAttribute('aria-label','Inspect '+name+(countsFeatures()?'':', '+roomLabel(room)+', '+unitValue(roomValue(room))));
    for (const [className,value] of columns) {
      const span=document.createElement('span');span.className=className;span.textContent=value;btn.append(span);
    }
    buttons.append(btn);
  });
  if(!rooms.length){const p=document.createElement('p');p.className='empty-evidence';p.textContent='No matches on this drawing.';buttons.append(p);}
  const list=byId('evidence');
  const hadFocus=list.contains(document.activeElement);
  list.replaceChildren(buttons);
  if(hadFocus) [...list.children].find(b=>b.dataset.roomId===state.selected)?.focus({preventScroll:true});
  const room=rooms.find(r=>r.id===state.selected) || state.data.rooms.find(r=>r.id===state.selected);
  const detail=byId('room-detail');detail.hidden=!room;
  if (room && countsFeatures()) detail.textContent=featureName(room)+' · '+(state.scope.kind === 'apartment_count' ? (room.polygon?.length ? 'Apartment boundary' : 'Apartment label') : 'Drawing symbol');
  else if(room)detail.textContent='Room '+room.id+' · '+roomLabel(room)+' — outline '+room.area.toFixed(5)+' m², printed '+unitValue(room.printedArea)+'.';
}
byId('evidence').addEventListener('click', event=>{
  const id=event.target.closest('[data-room-id]')?.dataset.roomId;
  if(id) selectRoom(id);
});
function submitQuery(text) {
  if (!state.data) return;
  const result = parseQuery(text);
  if (result?.error) {
    choose(null, 'area');
    message(result.error);
  } else if (result) {
    choose(result.type ?? null, result.metric, result.roomId, result.scope);
  } else {
    message('Ask for one room by number, or a room count or combined area by label. The previous result is still displayed.');
  }
}
byId('query-form').addEventListener('submit',event=>{
  event.preventDefault();
  submitQuery(byId('query').value);
});
byId('room-type').addEventListener('change',event=>{
  const value = event.target.value;
  if (value.startsWith('@')) {
    const [kind,target] = value.slice(1).split(':');
    const scope = target ? {kind,target} : {kind};
    choose(null, kind.endsWith('_count')?'count':'area', null, scope);
  } else if (value.startsWith('room:')) choose(null, 'area', value.slice(5));
  else choose(value, state.metric);
  setQueryForSelection();
});
byId('outline-mode').addEventListener('click',()=>setMode('outline'));
byId('printed-mode').addEventListener('click',()=>setMode('printed'));
byId('zoom-fit').addEventListener('click',()=>{if(state.data)fitView();});
byId('zoom-in').addEventListener('click',()=>changeZoom(1.5));
byId('zoom-out').addEventListener('click',()=>changeZoom(1/1.5));
function addLink(title,url) {
  if (!url) return;
  const link=document.createElement('a');link.textContent=title;link.href=url;link.target='_blank';link.rel='noopener';byId('sheet-links').append(link);
}
const originalSheet='site1102_bldg2242_floor10281';
const sheetFiles=new Map([
  [originalSheet,'/data/swiss-floor.json'],
  ['site1006_bldg2088_floor9498','/data/swiss/site1006_bldg2088_floor9498.json']
]);
let generation=0;
function clearSheet() {
  state.data=null;
  state.selected=null;
  state.roomId=null;
  state.frame=null;
  state.origin=null;
  state.zoom=1;
  setMode('outline');
  for(const id of ['sheet-links','evidence','plan','answer-caption','sheet-credit','evidence-count','sheet-id','room-type']){
    byId(id).replaceChildren();
  }
  byId('room-detail').hidden=true;
  byId('query').value='';
  byId('ask').disabled=true;
  byId('room-type').disabled=true;
  byId('answer').textContent='—';
  byId('drawing-title').textContent='Floor plan';
  byId('loading').textContent='Loading drawing…';
  byId('loading').hidden=false;
  message('');
}
async function loadSheet(stem=originalSheet, roomId=null, libraryPath=null) {
  const ticket=++generation;
  const picker = byId('drawing-select');
  const externalOption = picker.options?.namedItem('library-option');
  externalOption?.remove();
  if (libraryPath) {
    const option = new Option(libraryPath.split('/').pop(), libraryPath);
    option.id = 'library-option';
    picker.add(option);
  } else if (!sheetFiles.has(stem)) stem=originalSheet;
  picker.value=libraryPath || stem;
  clearSheet();
  try {
    const address = libraryPath ? '/api/drawing?' + new URLSearchParams({path:libraryPath}) : sheetFiles.get(stem);
    const response=await fetch(address);
    if(!response.ok) throw new Error('Drawing data unavailable');
    const payload=await response.json();
    const data = libraryPath ? payload.geometry : payload;
    if (ticket!==generation) return;
    if (libraryPath ? payload.drawing?.path !== libraryPath || payload.drawing.kind !== 'swiss' || !data?.sheet
                    : data.sheet.id !== stem) throw new Error('Unexpected drawing data');
    if (libraryPath) byId('library-option').textContent = payload.drawing.title || payload.drawing.name;
    state.data=data;
    const {sheet,rooms}=state.data;
    byId('drawing-title').textContent=sheet.title||'Floor plan';
    byId('sheet-id').textContent=sheet.id;
    byId('sheet-credit').textContent=sheet.credit;
    addLink('Original PDF',sheet.pdfUrl);addLink('DXF',sheet.dxfUrl);addLink('Dataset',sheet.sourceUrl);addLink('Licence',sheet.licenseUrl);addLink('Attribution',sheet.creditUrl);
    const select=byId('room-type');
    for(const label of labelOptions())select.add(new Option(label,label));
    select.add(new Option('All numbered, labelled rooms',allType));
    const group = document.createElement('optgroup');
    group.label = 'Numbered rooms';
    for (const room of rooms.filter(r => r.numbered).sort((a,b) => a.id.localeCompare(b.id, 'en', {numeric:true}))) {
      group.append(new Option('Room '+room.id+' · '+roomLabel(room), 'room:'+room.id));
    }
    select.append(group);
    const takeoffs = document.createElement('optgroup');
    takeoffs.label = 'Floor quantities';
    if (data.objects) for (const key of Object.keys(objectNames)) takeoffs.append(new Option(objectNames[key]+' count',scopeKey({kind:'object_count',target:key})));
    if (data.apartments && data.apartmentCountComplete !== false) takeoffs.append(new Option('Apartment count',scopeKey({kind:'apartment_count'})));
    if (data.indoorRoomIds && data.floorComplete !== false) takeoffs.append(new Option('Indoor floor area',scopeKey({kind:'floor_area'})));
    for (const unit of data.apartments || []) {
      if (unit.complete) takeoffs.append(new Option('Apartment '+unit.id+' · indoor area',scopeKey({kind:'apartment_area',target:unit.id})));
    }
    select.append(takeoffs);
    select.disabled=false;
    const frequencies=new Map();
    for(const room of rooms){if(room.label)frequencies.set(room.label,(frequencies.get(room.label)||0)+1);}
    const first=[...frequencies].sort((a,b)=>b[1]-a[1])[0]?.[0]||allType;
    fitView();choose(first,'area');setQueryForSelection();
    byId('ask').disabled=false;
    byId('loading').hidden=true;
    if (roomId) {
      byId('query').value = 'What is the net floor area of room '+roomId+'?';
      submitQuery(byId('query').value);
    }
  } catch (error) {
    if (ticket!==generation) return;
    byId('loading').textContent='Could not load the drawing. Reload the page to try again.';
    byId('ask').disabled=true;
    console.error(error);
  }
}
function loadFromAddress() {
  const query=new URLSearchParams(window.location.search);
  loadSheet(query.get('sheet')||originalSheet,query.get('room'),query.get('path'));
}
byId('drawing-select').addEventListener('change',event=>{
  const stem=event.target.value;
  const address=new URL(window.location.href);
  address.searchParams.delete('path');
  if(stem===originalSheet)address.searchParams.delete('sheet');
  else address.searchParams.set('sheet',stem);
  address.searchParams.delete('room');
  window.history.pushState(null,'',address);
  loadSheet(stem);
});
window.addEventListener('popstate',loadFromAddress);
loadFromAddress();
