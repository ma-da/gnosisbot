/**
 * Explore historical outcomes by SIMILARITY, not quantum probability.
 * No clustering/ranking is used for a fresh traditional casting.
 */
export function distance(a,b) {
  let total = 0;
  for (let i = 0; i < 6; i++) {
    const x=a.values[i], y=b.values[i];
    const yangX=(x===7 || x===9), yangY=(y===7 || y===9);
    const movingX=(x===6 || x===9), movingY=(y===6 || y===9);
    total += (yangX!==yangY ? 2 : 0) + (movingX!==movingY ? 1 : 0);
  }
  return total;
}
export function clusterReadings(readings, requested=11) {
  if (!readings.length) return {clusters:[],bestIndex:0,assignments:new Map()};
  const n=readings.length, k=Math.max(1,Math.min(n,requested));
  const dist=Array.from({length:n},(_,i)=>Array.from({length:n},(_,j)=>distance(readings[i],readings[j])));
  const mean=i=>dist[i].reduce((sum,v)=>sum+v,0)/n;
  const first=readings.map((_,i)=>i).sort((a,b)=>mean(a)-mean(b)||a-b)[0];
  const centers=[first];
  while(centers.length<k){
    const ranked=readings.map((_,i)=>i).filter(i=>!centers.includes(i))
      .sort((a,b)=>Math.min(...centers.map(c=>dist[b][c]))-Math.min(...centers.map(c=>dist[a][c]))||a-b);
    centers.push(ranked[0]);
  }
  const assign=()=>readings.map((_,i)=>centers.map((c,j)=>[dist[i][c],j]).sort((a,b)=>a[0]-b[0]||a[1]-b[1])[0][1]);
  let grouping=assign();
  for(let loop=0;loop<7;loop++){
    let changed=false;
    for(let c=0;c<k;c++){
      const indices=readings.map((_,i)=>i).filter(i=>grouping[i]===c);
      if(!indices.length)continue;
      const medoid=indices.slice().sort((a,b)=>
        indices.reduce((sum,j)=>sum+dist[a][j],0)-indices.reduce((sum,j)=>sum+dist[b][j],0)||a-b)[0];
      if(centers[c]!==medoid){centers[c]=medoid;changed=true;}
    }
    grouping=assign();
    if(!changed)break;
  }
  const clusters=centers.map((center,id)=>{
    const members=readings.map((r,i)=>({...r,_position:i})).filter((_,i)=>grouping[i]===id);
    const medoid=readings[center];
    members.sort((a,b)=>dist[a._position][center]-dist[b._position][center] || a.index-b.index);
    return {id,center,medoid,members,size:members.length};
  }).filter(c=>c.size>0);
  // One-dimensional display order: King Wen Now number of cluster medoid.
  // Proximity within each cluster is meaningful; distances across band are not a continuous metric.
  clusters.sort((a,b)=>a.medoid.now-b.medoid.now||a.medoid.becoming-b.medoid.becoming);
  const assignments=new Map();
  clusters.forEach((c,i)=>{c.displayOrder=i;c.members.forEach(m=>assignments.set(m.index,c));});
  // Global medoid of the entire batch: minimum total similarity distance.
  // No presentation quality, moving-line preference, or flag-agreement bonus.
  // Ties resolve by first measured shot index, matching backend ibm_medoid.py.
  const globalScores=readings.map((r,i)=>({r,score:dist[i].reduce((s,d)=>s+d,0),position:i}));
  const ranked=globalScores.sort((a,b)=>a.score-b.score||a.position-b.position);
  return {clusters,assignments,bestIndex:ranked[0].r.index,ranked};
}
