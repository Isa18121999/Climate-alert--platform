from pathlib import Path

path = Path('dashboard/index.html')
text = path.read_text(encoding='utf-8')

if 'id="climateMapCard"' in text:
    print('Climate map already present.')
    raise SystemExit(0)

css = r'''

/* Mapa meteorológico interactivo de Perú: se inserta sin cambiar el resto del dashboard. */
.climate-map-card{margin-top:16px}
.climate-map-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}
.climate-map-title{display:flex;align-items:center;gap:10px}
.climate-map-title h2{margin:0;font-size:18px;letter-spacing:-.2px}
.climate-map-actions{display:flex;gap:8px;flex-wrap:wrap}
.climate-map-btn{border:1px solid var(--line);background:#f5fafb;color:var(--primary-dark);border-radius:10px;padding:8px 11px;font-size:11px;font-weight:800;cursor:pointer}
.climate-map-btn:hover{background:#eaf6f8}
#climateMap{height:430px;margin-top:14px;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:#eaf2f4}
.climate-map-note{margin-top:8px;color:var(--muted);font-size:11px;line-height:1.4}
.climate-popup{min-width:190px;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.climate-popup strong{color:#07516d}
.climate-popup .popup-row{display:flex;justify-content:space-between;gap:14px;margin-top:4px;font-size:11px}
.climate-popup .popup-label{color:#6d8090}
.climate-map-status{padding:8px 10px;border-radius:10px;background:#f0f8fa;color:#426277;border:1px solid #deedf1;font-size:11px;font-weight:700}
@media(max-width:650px){#climateMap{height:350px}.climate-map-actions{width:100%}.climate-map-btn{flex:1}}
'''

js = r'''

/*
 * Mapa climático interactivo.
 * Usa Leaflet + OpenStreetMap y consulta /weather para cada punto.
 * Los comentarios explican la función de cada parte para facilitar el trabajo en equipo.
 */
const CLIMATE_MAP_POINTS=[
  {name:'Tumbes',lat:-3.57,lon:-80.45},
  {name:'Piura',lat:-5.19,lon:-80.63},
  {name:'Chiclayo',lat:-6.77,lon:-79.84},
  {name:'Trujillo',lat:-8.11,lon:-79.03},
  {name:'Lima',lat:-12.05,lon:-77.04},
  {name:'Ica',lat:-14.07,lon:-75.73},
  {name:'Arequipa',lat:-16.40,lon:-71.54},
  {name:'Cusco',lat:-13.53,lon:-71.97},
  {name:'Iquitos',lat:-3.75,lon:-73.25},
  {name:'Tarapoto',lat:-6.49,lon:-76.37}
];

function loadClimateMapLibrary(done){
  if(window.L){done();return}
  if(!document.getElementById('climate-leaflet-css')){
    const css=document.createElement('link');
    css.id='climate-leaflet-css';css.rel='stylesheet';
    css.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(css);
  }
  const existing=document.getElementById('climate-leaflet-js');
  if(existing){existing.addEventListener('load',done,{once:true});return}
  const script=document.createElement('script');
  script.id='climate-leaflet-js';script.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  script.onload=done;script.onerror=()=>console.warn('No se pudo cargar Leaflet para el mapa climático.');
  document.head.appendChild(script);
}

function climateMapApiBase(w,d){
  const api=d.getElementById('api');
  return (api&&api.value?api.value:'https://climate-alert-platform-api.onrender.com').replace(/\/$/,'');
}

async function climateMapWeather(w,d,point){
  const base=climateMapApiBase(w,d);
  try{
    const response=await fetch(base+'/weather?lat='+encodeURIComponent(point.lat)+'&lon='+encodeURIComponent(point.lon),{cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const data=await response.json();
    const c=data.current||{};
    return {temperature:c.temperature_2m,rain:c.rain,precipitation:c.precipitation,wind:c.wind_speed_10m,humidity:c.relative_humidity_2m};
  }catch(error){
    console.warn('No se pudo consultar el clima de '+point.name+':',error);
    return null;
  }
}

function climateMapPopup(point,weather,selected){
  const temp=weather&&Number.isFinite(Number(weather.temperature))?Number(weather.temperature).toFixed(1)+' °C':'—';
  const rain=weather&&Number.isFinite(Number(weather.rain))?Number(weather.rain).toFixed(1)+' mm':'—';
  const precipitation=weather&&Number.isFinite(Number(weather.precipitation))?Number(weather.precipitation).toFixed(1)+' mm':'—';
  const wind=weather&&Number.isFinite(Number(weather.wind))?Number(weather.wind).toFixed(1)+' km/h':'—';
  const humidity=weather&&Number.isFinite(Number(weather.humidity))?Number(weather.humidity).toFixed(0)+' %':'—';
  return '<div class="climate-popup"><strong>📍 '+point.name+(selected?' · ubicación seleccionada':'')+'</strong>'+
    '<div class="popup-row"><span class="popup-label">Temperatura</span><b>'+temp+'</b></div>'+
    '<div class="popup-row"><span class="popup-label">Lluvia</span><b>'+rain+'</b></div>'+
    '<div class="popup-row"><span class="popup-label">Precipitación</span><b>'+precipitation+'</b></div>'+
    '<div class="popup-row"><span class="popup-label">Viento</span><b>'+wind+'</b></div>'+
    '<div class="popup-row"><span class="popup-label">Humedad</span><b>'+humidity+'</b></div></div>';
}

async function initClimateMap(){
  const f=document.getElementById('app');
  let d=null,w=null;
  try{w=f&&f.contentWindow;d=f&&f.contentDocument}catch(e){return}
  if(!d||!w||d.getElementById('climateMapCard'))return;
  const summary=d.querySelector('.summary');
  if(!summary)return;

  loadClimateMapLibrary(async()=>{
    if(d.getElementById('climateMapCard')||!w.L)return;
    summary.insertAdjacentHTML('afterend',
      '<section class="card climate-map-card" id="climateMapCard">'+
        '<div class="climate-map-head">'+
          '<div><div class="climate-map-title"><span>🗺️</span><div><h2>Mapa meteorológico de Perú</h2><div class="card-kicker">Ubicación seleccionada y puntos meteorológicos de referencia</div></div></div></div>'+
          '<div class="climate-map-actions"><button class="climate-map-btn" id="climateMapCenter" type="button">📍 Centrar ubicación</button><button class="climate-map-btn" id="climateMapPeru" type="button">🇵🇪 Ver Perú</button></div>'+
        '</div>'+
        '<div id="climateMapStatus" class="climate-map-status" style="margin-top:12px">Cargando condiciones meteorológicas…</div>'+
        '<div id="climateMap"></div>'+ 
        '<div class="climate-map-note">Fuente meteorológica: Open-Meteo a través del backend de Climate Alert Platform. Haz clic en cualquier punto del mapa para consultar esa ubicación.</div>'+ 
      '</section>'
    );

    const map=w.L.map(d.getElementById('climateMap'),{zoomControl:true,scrollWheelZoom:true}).setView([-9.19,-75.02],5);
    w.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
    w.__climateMap=map;
    w.__climateMapMarkers=[];
    const peruBounds=w.L.latLngBounds([[-18.5,-81.5],[0.5,-68.5]]);
    const status=d.getElementById('climateMapStatus');
    const latInput=d.getElementById('lat'),lonInput=d.getElementById('lon');
    let selectedMarker=null;

    function selectedPoint(){
      const lat=Number(latInput&&latInput.value),lon=Number(lonInput&&lonInput.value);
      if(!Number.isFinite(lat)||!Number.isFinite(lon))return null;
      return {name:'Ubicación seleccionada',lat,lon};
    }

    async function updateSelected(){
      const point=selectedPoint();if(!point)return;
      if(selectedMarker)map.removeLayer(selectedMarker);
      selectedMarker=w.L.marker([point.lat,point.lon]).addTo(map);
      selectedMarker.bindPopup('<div class="climate-popup"><strong>📍 Ubicación seleccionada</strong><div class="popup-row"><span class="popup-label">Latitud</span><b>'+point.lat.toFixed(4)+'</b></div><div class="popup-row"><span class="popup-label">Longitud</span><b>'+point.lon.toFixed(4)+'</b></div><div class="popup-row"><span class="popup-label">Estado</span><b>Cargando…</b></div></div>');
      const weather=await climateMapWeather(w,d,point);
      selectedMarker.setPopupContent(climateMapPopup(point,weather,true));
      if(status)status.textContent='Ubicación: '+point.lat.toFixed(4)+', '+point.lon.toFixed(4)+' · condiciones meteorológicas actualizadas';
    }

    await updateSelected();

    for(const point of CLIMATE_MAP_POINTS){
      const marker=w.L.circleMarker([point.lat,point.lon],{radius:7,weight:2,fillOpacity:.85});
      marker.bindPopup('<div class="climate-popup"><strong>📍 '+point.name+'</strong><div class="popup-row"><span class="popup-label">Estado</span><b>Cargando…</b></div></div>');
      marker.addTo(map);
      w.__climateMapMarkers.push(marker);
      climateMapWeather(w,d,point).then(weather=>marker.setPopupContent(climateMapPopup(point,weather,false)));
    }

    d.getElementById('climateMapCenter').onclick=()=>{const p=selectedPoint();if(p)map.setView([p.lat,p.lon],9)};
    d.getElementById('climateMapPeru').onclick=()=>map.fitBounds(peruBounds,{padding:[20,20]});

    map.on('click',async event=>{
      if(latInput)latInput.value=event.latlng.lat.toFixed(4);
      if(lonInput)lonInput.value=event.latlng.lng.toFixed(4);
      await updateSelected();
      if(typeof w.refreshAll==='function'){try{w.refreshAll()}catch(e){console.warn('No se pudo actualizar el dashboard tras seleccionar el mapa:',e)}}
    });

    setInterval(async()=>{
      if(!w.__climateMap)return;
      for(const markerPoint of CLIMATE_MAP_POINTS){
        const marker=w.__climateMapMarkers.find(m=>{const p=m.getLatLng();return Math.abs(p.lat-markerPoint.lat)<.001&&Math.abs(p.lng-markerPoint.lon)<.001});
        if(!marker)continue;
        const weather=await climateMapWeather(w,d,markerPoint);
        marker.setPopupContent(climateMapPopup(markerPoint,weather,false));
      }
      updateSelected();
    },60000);
  });
}

document.getElementById('app')?.addEventListener('load',()=>setTimeout(initClimateMap,1000));
setTimeout(initClimateMap,2500);
'''

text = text.replace('</style>', css + '\n</style>', 1)
text = text.replace('</script>', js + '\n</script>', 1)
path.write_text(text, encoding='utf-8')
print('Interactive climate map injected into dashboard/index.html')
