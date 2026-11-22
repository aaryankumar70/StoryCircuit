// Original narrative Cartoon 3D scene composer for CurioLoop.
// Characters are drawn 2D sprites placed and animated inside original Three.js sets.
import * as THREE from 'three';

const COLORS = ['#E77B4D', '#5689C7', '#E7B642', '#4FA69A', '#9368B7', '#D15A52', '#78A747'];
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const mat = (color, roughness = 0.82, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness, ...extra });
const box = (scene, color, size, pos, extra = {}) => {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat(color, 0.78, extra));
  mesh.position.set(...pos); mesh.castShadow = true; mesh.receiveShadow = true; scene.add(mesh); return mesh;
};
const hash = (s) => [...String(s)].reduce((a, c) => (a * 33 + c.charCodeAt(0)) >>> 0, 5381);

import { environmentKind } from './environment.js';
export { environmentKind };

function addTree(scene, x, z, size, hue) {
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(size * 0.07, size * 0.12, size * 0.8, 8), mat('#76533C'));
  trunk.position.set(x, size * 0.4, z); trunk.castShadow = true; scene.add(trunk);
  const crown = new THREE.Mesh(new THREE.SphereGeometry(size * 0.42, 12, 10), mat(hue));
  crown.position.set(x, size * 1.0, z); crown.castShadow = true; crown.receiveShadow = true; scene.add(crown);
  return crown;
}

function buildEnvironment(scene, kind, seed) {
  const moving = [];
  const palette = {
    forest: { sky: '#14233D', ground: '#345341', fog: '#283D4A' },
    archive: { sky: '#303543', ground: '#574435', fog: '#463B37' },
    harbor: { sky: '#75A9C2', ground: '#456E73', fog: '#AEC6CA' },
    laboratory: { sky: '#A7CBD0', ground: '#657F7C', fog: '#C8DBD7' },
    interior: { sky: '#927564', ground: '#80583E', fog: '#8B6C58' },
    old_town: { sky: '#83B3C4', ground: '#A9815D', fog: '#D4B58E' },
    story_town: { sky: '#8EC2D4', ground: '#7C9A61', fog: '#C8D7BE' },
    space: { sky: '#101832', ground: '#202A50', fog: '#1C2B4B' },
  }[kind];
  scene.background = new THREE.Color(palette.sky);
  scene.fog = new THREE.Fog(palette.fog, 28, 72);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(100, 100), mat(palette.ground));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.04; ground.receiveShadow = true; scene.add(ground);

  if (kind === 'forest') {
    for (let i = 0; i < 18; i++) {
      const side = i % 2 ? 1 : -1, row = Math.floor(i / 2);
      moving.push(addTree(scene, side * (4.8 + (row % 4) * 1.55), -row * 4.0 - 5, 3.0 + (row % 3) * 0.55, i % 3 ? '#376846' : '#52794C'));
    }
    const moon = new THREE.Mesh(new THREE.SphereGeometry(1.3, 20, 16), new THREE.MeshBasicMaterial({ color: '#E8DDB7' }));
    moon.position.set(7, 8, -24); scene.add(moon);
  } else if (kind === 'archive') {
    box(scene, '#6E5747', [24, 10, 0.45], [0, 5, -15]);
    box(scene, '#45352D', [24, 0.3, 0.45], [0, 1.25, -14.72]);
    for (const x of [-7.2, 7.2]) {
      box(scene, '#49362D', [3.8, 7.0, 0.52], [x, 3.55, -11.0]);
      for (let row = 0; row < 4; row++) {
        const y = 1.25 + row * 1.55;
        box(scene, '#9A6C47', [3.6, 0.16, 1.1], [x, y, -10.45]);
        for (let col = 0; col < 6; col++) {
          const height = 0.72 + ((row * 7 + col * 3 + seed) % 5) * 0.12;
          const width = 0.28 + ((row + col) % 3) * 0.06;
          box(scene, ['#7C3F36', '#315A63', '#B18A54', '#526347', '#5B496D'][col % 5],
            [width, height, 0.34], [x - 1.35 + col * 0.53, y + 0.08 + height / 2, -10.15]);
        }
      }
    }
    box(scene, '#604530', [6.4, 0.28, 2.5], [-0.6, 1.15, -4.5]);
    for (const x of [-3.2, 2.0]) for (const z of [-5.35, -3.65]) {
      box(scene, '#49352B', [0.2, 1.12, 0.2], [x, 0.56, z]);
    }
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.22, 14, 12),
      new THREE.MeshStandardMaterial({ color: '#FFD88B', emissive: '#FFB957', emissiveIntensity: 0.7 }));
    lamp.position.set(-2.4, 1.55, -4.4); scene.add(lamp);
    const lampLight = new THREE.PointLight('#FFC77B', 1.8, 12); lampLight.position.copy(lamp.position); scene.add(lampLight);
    moving.push(lamp);
  } else if (kind === 'old_town' || kind === 'story_town') {
    for (let i = 0; i < 8; i++) {
      const x = (i - 3.5) * 4.3, height = 3.6 + ((i + seed) % 4) * 0.7;
      const facade = box(scene, ['#C77C58', '#B8A077', '#7D8B82', '#D39B68'][i % 4], [3.8, height, 3.2], [x, height / 2, -13 - (i % 2) * 3]);
      for (let wy = 1; wy < height - 0.5; wy += 1.2) for (const wx of [-1.1, 1.1]) {
        box(scene, '#344E56', [0.52, 0.72, 0.08], [x + wx, wy, -11.34 - (i % 2) * 3]);
      }
      if (i === 2 || i === 5) facade.rotation.y = i === 2 ? 0.035 : -0.04;
    }
    box(scene, '#B69A72', [5.2, 0.18, 24], [0, 0.1, -9]);
  } else if (kind === 'laboratory' || kind === 'interior') {
    box(scene, kind === 'laboratory' ? '#CCDCD3' : '#9C684C', [20, 8, 0.5], [0, 4, -12]);
    box(scene, kind === 'laboratory' ? '#89A59C' : '#6B4B3D', [20, 0.18, 14], [0, 3.2, -11.7]);
    for (let i = 0; i < 5; i++) box(scene, kind === 'laboratory' ? '#94BFB9' : '#C49B6D', [0.13, 6, 0.13], [-8 + i * 4, 4, -11.65]);
    if (kind === 'laboratory') {
      box(scene, '#785C48', [5.4, 0.28, 1.8], [0.5, 1.25, -4.8]);
      for (let i = 0; i < 4; i++) {
        const flask = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.38, 0.9, 12), mat(['#68BAC0', '#E3AC55', '#76A96A', '#B57AAE'][i]));
        flask.position.set(-1.3 + i * 1.0, 1.83, -4.85); flask.castShadow = true; scene.add(flask);
      }
    }
  } else if (kind === 'harbor') {
    const water = new THREE.Mesh(new THREE.PlaneGeometry(100, 45), mat('#347D95', 0.35, { metalness: 0.08 }));
    water.rotation.x = -Math.PI / 2; water.position.set(0, 0.015, -16); scene.add(water); moving.push(water);
    for (let i = 0; i < 10; i++) box(scene, i % 2 ? '#B39468' : '#8A6950', [0.28, 0.38, 0.75], [-8 + i * 1.8, 0.2, -3.8]);
  } else if (kind === 'space') {
    const starPositions = [];
    let s = seed || 821;
    for (let i = 0; i < 260; i++) { s = (s * 48271) % 2147483647; starPositions.push((s % 300) / 5 - 30, ((s >>> 4) % 500) / 5 - 40, -16 - (s % 550) / 10); }
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3));
    scene.add(new THREE.Points(geo, new THREE.PointsMaterial({ color: '#FFF0CC', size: 0.16, sizeAttenuation: true })));
    const planet = new THREE.Mesh(new THREE.SphereGeometry(4.2, 30, 24), mat('#4D84B7', 0.92));
    planet.position.set(6.5, 4, -23); scene.add(planet); moving.push(planet);
  }
  return moving;
}

function characterCanvas(name, mood, phase) {
  const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 384;
  const c = canvas.getContext('2d'), color = COLORS[hash(name) % COLORS.length];
  c.clearRect(0, 0, 256, 384); c.lineCap = 'round'; c.lineJoin = 'round';
  const path = (fn, fill, width = 9) => { c.beginPath(); fn(); c.fillStyle = fill; c.fill(); c.lineWidth = width; c.strokeStyle = '#17202A'; c.stroke(); };
  const walk = Math.sin(phase) * 15, arm = mood === 'shocked' ? -34 : mood === 'worried' ? 22 : Math.sin(phase * 0.7) * 16;
  path(() => { c.moveTo(103, 272); c.lineTo(84 + walk, 355); c.lineTo(112 + walk, 356); c.lineTo(133, 282); c.lineTo(151 - walk, 355); c.lineTo(178 - walk, 355); c.lineTo(164, 269); }, '#394F6B');
  path(() => { c.moveTo(99, 161); c.quadraticCurveTo(65, 174, 76, 275); c.quadraticCurveTo(124, 298, 177, 272); c.quadraticCurveTo(183, 181, 153, 160); }, color);
  c.lineWidth = 17; c.strokeStyle = color; c.beginPath(); c.moveTo(87, 183); c.lineTo(52, 218 + arm); c.lineTo(45, 241 + arm); c.stroke();
  c.strokeStyle = '#17202A'; c.lineWidth = 5; c.beginPath(); c.moveTo(87, 183); c.lineTo(52, 218 + arm); c.lineTo(45, 241 + arm); c.stroke();
  c.lineWidth = 17; c.strokeStyle = color; c.beginPath(); c.moveTo(164, 183); c.lineTo(200, 213 - arm); c.lineTo(207, 236 - arm); c.stroke();
  c.strokeStyle = '#17202A'; c.lineWidth = 5; c.beginPath(); c.moveTo(164, 183); c.lineTo(200, 213 - arm); c.lineTo(207, 236 - arm); c.stroke();
  path(() => { c.arc(128, 111, 61, 0, Math.PI * 2); }, '#F5D1AE');
  c.fillStyle = '#3C2D2B'; c.beginPath(); c.ellipse(128, 62, 60, 25, 0, Math.PI, Math.PI * 2); c.fill();
  const blink = (phase % 5.6) < 0.12;
  c.fillStyle = '#17202A'; c.beginPath(); c.ellipse(105, 111, 6, blink ? 1.3 : 8, 0, 0, Math.PI * 2); c.fill();
  c.beginPath(); c.ellipse(151, 111, 6, blink ? 1.3 : 8, 0, 0, Math.PI * 2); c.fill();
  c.strokeStyle = '#713D3C'; c.lineWidth = 5; c.beginPath(); c.arc(128, mood === 'shocked' ? 152 : 141, mood === 'shocked' ? 12 : 14, mood === 'shocked' ? 0 : 0.1, mood === 'shocked' ? Math.PI * 2 : Math.PI - 0.1); c.stroke();
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; texture.needsUpdate = true;
  return { canvas, texture, mood, phase, color };
}

function makeActor(scene, name, x, index, lineText) {
  const group = new THREE.Group(); group.position.set(x, 0, -2.4 - index * 0.35); scene.add(group);
  const mood = /reveal|discover|found|realize|surpris|shocking/.test(lineText) ? 'shocked' : /fear|danger|vanish|missing|crash|storm|threat/.test(lineText) ? 'worried' : 'curious';
  const figure = characterCanvas(name, mood, hash(name) % 20);
  const sprite = new THREE.Mesh(new THREE.PlaneGeometry(1.85, 2.77), new THREE.MeshBasicMaterial({ map: figure.texture, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
  sprite.position.y = 1.45; group.add(sprite);
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.75, 24), new THREE.MeshBasicMaterial({ color: '#18232D', transparent: true, opacity: 0.28, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.025; group.add(shadow);
  return { group, sprite, figure, shadow, lineText, baseX: x };
}

function addProps(scene, text, spec) {
  const desc = `${text} ${(spec.props || []).join(' ')} ${(spec.visual_cues || []).join(' ')}`.toLowerCase();
  const made = [];
  const add = (mesh, x = 1.4, y = 0, z = -3.5, scale = 1) => { mesh.position.set(x, y, z); mesh.scale.setScalar(scale); mesh.castShadow = true; scene.add(mesh); made.push(mesh); return mesh; };
  if (/bell|alarm/.test(desc) && !/telephone|phone/.test(desc)) {
    const bell = new THREE.Group();
    const dome = new THREE.Mesh(new THREE.SphereGeometry(0.48, 18, 14, 0, Math.PI * 2, 0, Math.PI / 2), mat('#D8B85F', 0.28, { metalness: 0.55 })); dome.position.y = 0.5; bell.add(dome);
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.49, 0.49, 0.12, 20), mat('#E7CC7F', 0.24, { metalness: 0.55 })); rim.position.y = 0.46; bell.add(rim);
    const handle = new THREE.Mesh(new THREE.SphereGeometry(0.1, 12, 10), mat('#E7CC7F', 0.28, { metalness: 0.4 })); handle.position.y = 1.0; bell.add(handle); add(bell, 1.5, 0, -3.7, 1.25);
  } else if (/telephone|phone|ringing/.test(desc)) {
    const base = new THREE.Group();
    const plinth = new THREE.Mesh(new THREE.BoxGeometry(1.25, 0.28, 0.85), mat('#3C2C28')); plinth.position.y = 0.28; base.add(plinth);
    const dial = new THREE.Mesh(new THREE.CylinderGeometry(0.31, 0.31, 0.08, 24), mat('#D5C49E')); dial.rotation.x = Math.PI / 2; dial.position.set(0, 0.48, 0.18); base.add(dial);
    const horn = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.25, 0.64, 14), mat('#312D2B')); horn.position.set(0, 0.83, -0.18); base.add(horn); add(base, 1.45, 0, -3.7, 1.1);
  } else if (/key|latch|lock/.test(desc)) {
    const key = new THREE.Group();
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.065, 0.065, 1.1, 12), mat('#E4B953', 0.3, { metalness: 0.55 })); shaft.rotation.z = Math.PI / 2; key.add(shaft);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.065, 10, 24), mat('#F2CB68', 0.25, { metalness: 0.6 })); ring.position.x = -0.48; key.add(ring);
    for (let i = 0; i < 2; i++) { const tooth = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.2, 0.12), mat('#E4B953')); tooth.position.set(0.32 + i * 0.22, -0.1, 0); key.add(tooth); }
    add(key, 1.25, 0.9, -3.5, 1.3);
  } else if (/monitor|receiver|display|screen|signal/.test(desc)) {
    const monitor = new THREE.Group();
    const frame = new THREE.Mesh(new THREE.BoxGeometry(1.75, 1.22, 0.2), mat('#26303B', 0.42, { metalness: 0.2 }));
    frame.position.y = 1.28; monitor.add(frame);
    const screenMaterial = new THREE.MeshStandardMaterial({ color: '#174C72', emissive: '#157DC7', emissiveIntensity: 0.72,
      roughness: 0.3, metalness: 0.12 });
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.48, 0.91), screenMaterial);
    screen.position.set(0, 1.3, 0.108); monitor.add(screen);
    const signalDot = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 12),
      new THREE.MeshBasicMaterial({ color: '#79E7FF' }));
    signalDot.position.set(0.35, 1.38, 0.13); monitor.add(signalDot);
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.18, 0.52, 12), mat('#3D4852'));
    stem.position.y = 0.56; monitor.add(stem);
    const foot = new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.12, 0.48), mat('#303A42'));
    foot.position.y = 0.27; monitor.add(foot);
    monitor.userData.signalScreen = screenMaterial;
    monitor.userData.signalDot = signalDot;
    monitor.userData.signalOff = /went dark|goes dark|turned off|shut off|no signal/.test(desc);
    add(monitor, 1.5, 0.0, -3.7, 1.2);
  } else if (/ledger|book|journal|letter|log|manuscript|document|record/.test(desc)) {
    const book = new THREE.Group();
    const cover = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.16, 0.86), mat('#7C3F36')); cover.position.y = 0.55; book.add(cover);
    const pages = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.04, 0.78), mat('#E8DDBE')); pages.position.y = 0.65; book.add(pages);
    const line = new THREE.Mesh(new THREE.BoxGeometry(0.68, 0.018, 0.025), mat('#695B47')); line.position.set(0, 0.68, -0.12); book.add(line); add(book, 1.45, 0, -3.7, 1.25);
  } else if (/ship|boat|vessel|wreck|sail/.test(desc)) {
    const ship = new THREE.Group();
    const hull = new THREE.Mesh(new THREE.CapsuleGeometry(0.46, 1.8, 5, 12), mat('#78583E')); hull.rotation.z = Math.PI / 2; hull.position.y = 0.4; ship.add(hull);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.065, 2.25, 8), mat('#503A2F')); mast.position.set(0, 1.65, 0); ship.add(mast);
    const sail = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 1.4), mat('#F0E1C1', 0.95, { side: THREE.DoubleSide })); sail.position.set(0.2, 1.65, 0.02); ship.add(sail); add(ship, 1.6, 0.1, -4.1, 1.15);
  } else if (/telescope|astronom|star|planet|orbit|spacecraft|astronaut|galaxy|moon/.test(desc)) {
    const orb = new THREE.Mesh(new THREE.SphereGeometry(1.2, 24, 20), mat('#548FC2', 0.7)); add(orb, 1.9, 2.8, -6.5, 1.0);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.65, 0.045, 8, 60), mat('#E3C775', 0.34, { metalness: 0.3 })); ring.rotation.x = Math.PI / 2.9; add(ring, 1.9, 2.8, -6.5, 1.0);
  } else if (/aircraft|plane|airplane|bomber|glider/.test(desc)) {
    const plane = new THREE.Group();
    const fuselage = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 2.4, 4, 10), mat('#52748D')); fuselage.rotation.z = Math.PI / 2; plane.add(fuselage);
    const wing = new THREE.Mesh(new THREE.BoxGeometry(0.75, 0.12, 2.5), mat('#D55C45')); plane.add(wing); add(plane, 1.4, 2.0, -5.0, 1.25);
  } else if (/microscope|experiment|scientific|laboratory|lab/.test(desc)) {
    const stand = box(scene, '#536E75', [0.18, 1.6, 0.18], [1.4, 0.9, -4.1]); made.push(stand);
    const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.25, 1.0, 16), mat('#779B9E', 0.42, { metalness: 0.25 })); tube.position.set(1.55, 1.75, -4.1); tube.rotation.z = -0.55; tube.castShadow = true; scene.add(tube); made.push(tube);
  } else if (/door|gate|cabin/.test(desc)) {
    const door = box(scene, '#71513E', [1.8, 3.2, 0.24], [1.75, 1.6, -5.6]); made.push(door);
    const knob = new THREE.Mesh(new THREE.SphereGeometry(0.11, 12, 10), mat('#E4B75C', 0.25, { metalness: 0.55 })); knob.position.set(2.35, 1.45, -5.42); knob.castShadow = true; scene.add(knob); made.push(knob);
  }
  return made;
}

function lighting(scene, spec, profile) {
  scene.add(new THREE.HemisphereLight('#D8E7F5', '#4B4038', profile === 'mystery' ? 1.15 : 1.6));
  const low = /night|moon|cool|blue|storm/.test(String(spec.lighting || '').toLowerCase());
  const key = new THREE.DirectionalLight(low ? '#AFCBFF' : '#FFD6A0', low ? 2.2 : 3.1);
  key.position.set(-4.5, 8, 5); key.castShadow = true; key.shadow.mapSize.set(512, 512); key.shadow.camera.left = -12; key.shadow.camera.right = 12; key.shadow.camera.top = 12; key.shadow.camera.bottom = -12; scene.add(key);
  const rim = new THREE.DirectionalLight(profile === 'space' ? '#7EC8FF' : '#9AB8EB', 1.1); rim.position.set(5, 4, -7); scene.add(rim);
  return { key, rim };
}

function shotWorld(script, spec, index) {
  const spoken = String(spec.narration || '');
  const description = `${script.topic || ''} ${script.title || ''} ${spoken} ${spec.environment || ''} ${spec.visual_description || ''}`.toLowerCase();
  const profile = script.visual_profile?.profile || 'historical';
  const kind = environmentKind(description, profile);
  const scene = new THREE.Scene(), motion = buildEnvironment(scene, kind, hash(spoken + index));
  const lights = lighting(scene, spec, profile);
  const names = (Array.isArray(spec.characters) ? spec.characters : spec.characters ? [spec.characters] : []).map(String).filter(Boolean).slice(0, 2);
  if (!names.length) names.push(String(script.topic || script.title || 'Story narrator'));
  const actors = names.map((name, i) => makeActor(scene, name, (i - (names.length - 1) / 2) * 1.65 - 0.8, i, spoken));
  const props = addProps(scene, spoken, spec);
  const targetObject = props[0] || actors[0].group;
  const camera = new THREE.PerspectiveCamera(34, 1080 / 1920, 0.1, 110);
  const cameraText = String(spec.camera || 'slow push in').toLowerCase();
  const wide = /wide|establishing/.test(cameraText), close = /close.?up|detail/.test(cameraText);
  const distance = wide ? 15 : close ? 6.2 : 9.5;
  const side = index % 2 ? -1 : 1;
  const from = V(side * (2.6 + index % 3), 3.0 + (index % 2) * 0.45, distance - 1.2);
  const to = V(side * (index % 2 ? -0.6 : 0.9), 2.7, distance - 2.7);
  if (/overhead|top.?down/.test(cameraText)) { from.y = 10; to.y = 7.6; }
  const focusPoint = targetObject.position.clone(); focusPoint.y += props.length ? 1.0 : 1.35;
  return { scene, camera, actors, props, motion, lights, from, to, focusPoint, kind, spec, spoken, cameraText };
}

export function buildShots(script, timing) {
  const lines = script.lines || [], timeline = timing.lines || [], groups = [];
  lines.forEach((line, i) => {
    if (!line || !String(line.text || '').trim()) return;
    const spec = line.scene && typeof line.scene === 'object' ? line.scene : {};
    const id = String(spec.scene_id || `scene_${i + 1}`);
    const prior = groups[groups.length - 1];
    if (prior && prior.id === id) prior.rows.push({ line, spec, index: i });
    else groups.push({ id, rows: [{ line, spec, index: i }] });
  });
  if (!groups.length) throw new Error('The validated script contains no renderable narration scenes.');
  const cues = [], shots = groups.map((group, index) => {
    const first = group.rows[0], last = group.rows[group.rows.length - 1];
    const spec = { ...first.spec, narration: group.rows.map((row) => row.line.text).join(' ') };
    const start = +(timeline[first.index]?.start ?? index * 3.5), end = +(timeline[last.index]?.end ?? start + 3.5);
    const world = shotWorld(script, spec, index);
    const text = spec.narration.toLowerCase();
    const cue = /bell|ring|alarm/.test(text) ? 'bell' : /reveal|discover|found|finally|realize/.test(text) ? 'sparkle' : /crash|impact|fall|slam/.test(text) ? 'impact' : index ? 'whoosh' : 'soft_hit';
    cues.push({ t: +(start + 0.06).toFixed(3), type: cue, gain: cue === 'soft_hit' ? 0.20 : 0.28 });
    return { id: group.id, at: start, end: Math.max(start + 0.35, end), note: `${world.kind}: ${String(spec.visual_description || spec.environment || spec.narration).slice(0, 180)}`,
      draw(local, duration, absolute, render, ctx) {
        const u = Math.max(0, Math.min(1, local / Math.max(duration, 0.01))), ease = 1 - (1 - u) ** 3;
        world.camera.position.copy(world.from.clone().lerp(world.to, ease));
        world.camera.lookAt(world.focusPoint);
        world.camera.rotation.z = /dutch|tilt/.test(world.cameraText) ? 0.035 * Math.sin(u * Math.PI) : 0;
        world.actors.forEach((actor, j) => {
          const phase = local * (/run|race/.test(world.spoken.toLowerCase()) ? 10 : 5.2) + j * 1.7;
          actor.group.position.y = Math.max(0, Math.sin(phase) * (/walk|run|approach|arrive|leave/.test(world.spoken.toLowerCase()) ? 0.09 : 0.035));
          actor.group.position.x = actor.baseX + Math.sin(local * 0.24 + j) * 0.08;
          actor.sprite.lookAt(world.camera.position);
          const c = actor.figure.canvas.getContext('2d');
          characterCanvasFrame(c, actor.figure, phase);
          actor.figure.texture.needsUpdate = true;
        });
        world.motion.forEach((object, i) => {
          if (object.isMesh && object.geometry.type === 'SphereGeometry') object.rotation.y = absolute * 0.035;
          else if (object.geometry.type === 'PlaneGeometry' && world.kind === 'harbor') object.position.y = 0.015 + Math.sin(absolute * 1.7) * 0.025;
          else if (object.geometry.type === 'SphereGeometry' && world.kind === 'forest') object.rotation.z = Math.sin(absolute * 0.7 + i) * 0.015;
        });
        world.props.forEach((object) => {
          const screen = object.userData?.signalScreen, dot = object.userData?.signalDot;
          if (!screen) return;
          const pulse = 0.42 + 0.46 * (0.5 + 0.5 * Math.sin(absolute * 7.0));
          screen.emissiveIntensity = object.userData.signalOff ? 0.025 : pulse;
          if (dot) dot.visible = !object.userData.signalOff && pulse > 0.58;
        });
        const focus = world.camera.position.distanceTo(world.focusPoint);
        render(world.scene, world.camera, { focus, aperture: 0.0018, maxblur: 0.004, exposure: world.kind === 'space' ? 1.08 : 1.0 });
        const transition = String(world.spec.transition || '').toLowerCase();
        return /fade|dissolve|whip/.test(transition) && local < 0.2
          ? { alpha: (1 - local / 0.2) * (transition.includes('whip') ? 0.55 : 0.75), color: transition.includes('whip') ? '#D9E4F2' : '#111725' }
          : null;
      } };
  });
  return { shots, cues };
}

function characterCanvasFrame(ctx, figure, phase) {
  const mood = figure.mood, color = figure.color, walk = Math.sin(phase) * 15;
  ctx.clearRect(0, 0, 256, 384); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  const strokePath = (fn, fill, width = 9) => { ctx.beginPath(); fn(); ctx.fillStyle = fill; ctx.fill(); ctx.lineWidth = width; ctx.strokeStyle = '#17202A'; ctx.stroke(); };
  strokePath(() => { ctx.moveTo(103, 272); ctx.lineTo(84 + walk, 355); ctx.lineTo(112 + walk, 356); ctx.lineTo(133, 282); ctx.lineTo(151 - walk, 355); ctx.lineTo(178 - walk, 355); }, '#394F6B');
  strokePath(() => { ctx.moveTo(99, 161); ctx.quadraticCurveTo(65, 174, 76, 275); ctx.quadraticCurveTo(124, 298, 177, 272); ctx.quadraticCurveTo(183, 181, 153, 160); }, color);
  const arm = mood === 'shocked' ? -34 : mood === 'worried' ? 22 : Math.sin(phase * 0.7) * 16;
  for (const [sx, ex, ey] of [[87, 52, 218 + arm], [164, 200, 213 - arm]]) {
    ctx.beginPath(); ctx.lineWidth = 17; ctx.strokeStyle = color; ctx.moveTo(sx, 183); ctx.lineTo(ex, ey); ctx.lineTo(ex + (sx < 100 ? -7 : 7), ey + 23); ctx.stroke();
    ctx.beginPath(); ctx.lineWidth = 5; ctx.strokeStyle = '#17202A'; ctx.moveTo(sx, 183); ctx.lineTo(ex, ey); ctx.lineTo(ex + (sx < 100 ? -7 : 7), ey + 23); ctx.stroke();
  }
  strokePath(() => { ctx.arc(128, 111, 61, 0, Math.PI * 2); }, '#F5D1AE');
  ctx.fillStyle = '#3C2D2B'; ctx.beginPath(); ctx.ellipse(128, 62, 60, 25, 0, Math.PI, Math.PI * 2); ctx.fill();
  const blink = (phase % 5.6) < 0.12;
  ctx.fillStyle = '#17202A'; ctx.beginPath(); ctx.ellipse(105, 111, 6, blink ? 1.3 : 8, 0, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(151, 111, 6, blink ? 1.3 : 8, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = '#713D3C'; ctx.lineWidth = 5; ctx.beginPath(); ctx.arc(128, mood === 'shocked' ? 152 : 141, mood === 'shocked' ? 12 : 14, mood === 'shocked' ? 0 : 0.1, mood === 'shocked' ? Math.PI * 2 : Math.PI - 0.1); ctx.stroke();
  return true;
}
