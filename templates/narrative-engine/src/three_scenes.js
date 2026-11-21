// CurioLoop 2.0 Three.js 3D Narrative Visual Engine
// Renders accurate, physically grounded 3D WebGL scenes for documentary storytelling.
// Replaces flat 2D vector illustrations with realistic 3D geometry, dynamic ocean waves,
// authentic wooden brigantine meshes, 3D cabins, archival logbooks, and motivated lighting.

import * as THREE from './core/three.module.js';

let renderer = null;
let threeCanvas = null;
let activeScene = null;
let camera = null;

// Reusable 3D Scene Instances
let oceanScene = null;
let helmScene = null;
let cabinScene = null;

// Dynamic Object Handles
let oceanMesh = null;
let oceanGeometry = null;
let shipGroup = null;
let shipLanternLight = null;
let sprayParticles = null;

let helmGroup = null;
let helmWheel = null;
let binnacleLight = null;
let deckLanternLight = null;

let cabinGroup = null;
let logbookMesh = null;
let candleLight = null;
let deskGroup = null;

const W = 1080;
const H = 1920;

/**
 * Initializes the Three.js WebGL Renderer and prepares all 3D narrative environments.
 */
export function initThreeVisualEngine() {
  if (renderer) return { renderer, threeCanvas };

  threeCanvas = document.createElement('canvas');
  threeCanvas.width = W;
  threeCanvas.height = H;

  renderer = new THREE.WebGLRenderer({
    canvas: threeCanvas,
    antialias: true,
    alpha: false,
    powerPreference: 'high-performance',
    preserveDrawingBuffer: true,
  });
  renderer.setSize(W, H);
  renderer.setPixelRatio(1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.35;

  camera = new THREE.PerspectiveCamera(48, W / H, 1.0, 5000);

  // Build the 3 specialized 3D narrative worlds
  oceanScene = build3DOceanEnvironment();
  helmScene = build3DQuarterdeckEnvironment();
  cabinScene = build3DCabinEnvironment();

  activeScene = oceanScene;
  return { renderer, threeCanvas };
}

export function getThreeCanvas() {
  return threeCanvas;
}

// ---------------------------------------------------------------------------
// 1. 3D OCEAN & BRIGANTINE (THE MARY CELESTE) ENVIRONMENT
// ---------------------------------------------------------------------------

function build3DOceanEnvironment() {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x060f1c);
  scene.fog = new THREE.FogExp2(0x071526, 0.00065);

  // Moonlight Key Directional Light (illuminates ship & ocean waves with real shadows)
  const moonLight = new THREE.DirectionalLight(0xb4d8fd, 3.4);
  moonLight.position.set(450, 680, 420);
  moonLight.castShadow = true;
  moonLight.shadow.mapSize.width = 1024;
  moonLight.shadow.mapSize.height = 1024;
  moonLight.shadow.camera.near = 10;
  moonLight.shadow.camera.far = 2200;
  moonLight.shadow.camera.left = -500;
  moonLight.shadow.camera.right = 500;
  moonLight.shadow.camera.top = 500;
  moonLight.shadow.camera.bottom = -500;
  moonLight.shadow.bias = -0.001;
  scene.add(moonLight);

  // Secondary Soft Fill Light from opposite horizon
  const fillLight = new THREE.DirectionalLight(0x3a6088, 1.4);
  fillLight.position.set(-400, 300, -300);
  scene.add(fillLight);

  // Ambient Ocean Skylight (keeps shadows rich, not pitch black)
  const ambientLight = new THREE.AmbientLight(0x1a2e48, 1.3);
  scene.add(ambientLight);

  // Dynamic 3D Ocean Water Mesh (Deformed per frame with wave math)
  oceanGeometry = new THREE.PlaneGeometry(3600, 3600, 72, 72);
  oceanGeometry.rotateX(-Math.PI / 2);

  const oceanMaterial = new THREE.MeshStandardMaterial({
    color: 0x081e36,
    roughness: 0.12,
    metalness: 0.85,
    flatShading: false,
  });
  oceanMesh = new THREE.Mesh(oceanGeometry, oceanMaterial);
  oceanMesh.receiveShadow = true;
  oceanMesh.position.y = -20;
  scene.add(oceanMesh);

  // 3D Mary Celeste Brigantine Vessel Group
  shipGroup = create3DBrigantineModel();
  shipGroup.position.set(0, 0, 0);
  scene.add(shipGroup);

  // Ship Stern Lantern (warm amber point light casting light on transom)
  shipLanternLight = new THREE.PointLight(0xffa834, 2.8, 280);
  shipLanternLight.position.set(0, 48, -125);
  shipGroup.add(shipLanternLight);

  // Foredeck Lantern
  const bowLantern = new THREE.PointLight(0xffbb44, 2.0, 200);
  bowLantern.position.set(0, 42, 100);
  shipGroup.add(bowLantern);

  // Atmospheric Sea Spray & Mist Particles
  sprayParticles = createSprayParticleSystem();
  scene.add(sprayParticles);

  return scene;
}

/**
 * Procedurally generates an authentic, detailed 3D model of a 19th-century brigantine.
 */
function create3DBrigantineModel() {
  const ship = new THREE.Group();

  // Authentic Maritime Materials
  const blackOakMaterial = new THREE.MeshStandardMaterial({
    color: 0x181716, // Black hull topsides
    roughness: 0.65,
    metalness: 0.1,
  });
  const copperBottomMaterial = new THREE.MeshStandardMaterial({
    color: 0x7c3822, // Weathered copper anti-fouling bottom
    roughness: 0.55,
    metalness: 0.35,
  });
  const goldStrakeMaterial = new THREE.MeshStandardMaterial({
    color: 0xd4af37, // Gold sheer stripe
    roughness: 0.35,
    metalness: 0.75,
  });
  const deckTeakMaterial = new THREE.MeshStandardMaterial({
    color: 0x5a412b, // Teak planking
    roughness: 0.58,
    metalness: 0.05,
  });
  const sparWoodMaterial = new THREE.MeshStandardMaterial({
    color: 0x613d22, // Varnish pine spars
    roughness: 0.68,
    metalness: 0.08,
  });
  const brassMaterial = new THREE.MeshStandardMaterial({
    color: 0xd4af37,
    roughness: 0.22,
    metalness: 0.9,
  });
  const sailMaterial = new THREE.MeshStandardMaterial({
    color: 0xded2b0, // Weathered canvas sailcloth
    roughness: 0.95,
    metalness: 0.0,
    side: THREE.DoubleSide,
  });

  // 1. Hull - Lower Copper Bottom
  const bottomGeom = new THREE.CylinderGeometry(26, 12, 260, 16, 1, false, 0, Math.PI);
  bottomGeom.rotateZ(Math.PI / 2);
  bottomGeom.rotateY(Math.PI / 2);
  const bottom = new THREE.Mesh(bottomGeom, copperBottomMaterial);
  bottom.position.y = 5;
  bottom.castShadow = true;
  bottom.receiveShadow = true;
  ship.add(bottom);

  // Hull - Upper Black Topsides
  const upperGeom = new THREE.BoxGeometry(54, 22, 260);
  const upper = new THREE.Mesh(upperGeom, blackOakMaterial);
  upper.position.y = 16;
  upper.castShadow = true;
  upper.receiveShadow = true;
  ship.add(upper);

  // Gold Sheer Line Stripe along both sides of hull
  const strakeGeom = new THREE.BoxGeometry(55, 2.5, 262);
  const strake = new THREE.Mesh(strakeGeom, goldStrakeMaterial);
  strake.position.y = 22;
  ship.add(strake);

  // Clipper Bow (Pointed wooden prow)
  const bowGeom = new THREE.ConeGeometry(27, 75, 16, 1, false, 0, Math.PI);
  bowGeom.rotateX(-Math.PI / 2);
  const bow = new THREE.Mesh(bowGeom, blackOakMaterial);
  bow.position.set(0, 15, 155);
  bow.castShadow = true;
  ship.add(bow);

  // Transom Stern (Square flat stern gallery)
  const sternGeom = new THREE.BoxGeometry(52, 36, 18);
  const stern = new THREE.Mesh(sternGeom, blackOakMaterial);
  stern.position.set(0, 20, -132);
  stern.castShadow = true;
  ship.add(stern);

  // 2. Weathered Teak Planked Deck
  const deckGeom = new THREE.BoxGeometry(50, 3, 252);
  const deck = new THREE.Mesh(deckGeom, deckTeakMaterial);
  deck.position.set(0, 25, 5);
  deck.receiveShadow = true;
  ship.add(deck);

  // Bulwarks / Deck Railings
  const portRail = new THREE.Mesh(new THREE.BoxGeometry(2.5, 10, 248), blackOakMaterial);
  portRail.position.set(-25, 30, 5);
  ship.add(portRail);

  const starRail = portRail.clone();
  starRail.position.x = 25;
  ship.add(starRail);

  // Deck Hatches & Companionways
  const hatch = new THREE.Mesh(new THREE.BoxGeometry(24, 7, 34), blackOakMaterial);
  hatch.position.set(0, 28, 20);
  ship.add(hatch);

  const aftCabin = new THREE.Mesh(new THREE.BoxGeometry(28, 14, 30), blackOakMaterial);
  aftCabin.position.set(0, 32, -65);
  ship.add(aftCabin);

  // 3. Foremast (Square-Rigged 3-Tier Mast)
  const foreMast = new THREE.Mesh(new THREE.CylinderGeometry(2.6, 3.8, 240, 12), sparWoodMaterial);
  foreMast.position.set(0, 135, 70);
  foreMast.castShadow = true;
  ship.add(foreMast);

  // Foremast Yardarms & Billowing Curved Canvas Sails
  const yards = [
    { y: 75, w: 110, r: 2.2, h: 50 },
    { y: 135, w: 90, r: 1.8, h: 48 },
    { y: 195, w: 70, r: 1.4, h: 44 },
  ];
  yards.forEach((yd) => {
    const yardGeom = new THREE.CylinderGeometry(yd.r * 0.8, yd.r, yd.w, 10);
    yardGeom.rotateZ(Math.PI / 2);
    const yard = new THREE.Mesh(yardGeom, sparWoodMaterial);
    yard.position.set(0, yd.y, 70);
    ship.add(yard);

    // Billowing Square Sail with curved surface
    const sailGeom = new THREE.PlaneGeometry(yd.w * 0.94, yd.h, 12, 10);
    const pos = sailGeom.attributes.position;
    for (let p = 0; p < pos.count; p++) {
      const vx = pos.getX(p);
      const vy = pos.getY(p);
      const curve = Math.sin((vx / (yd.w * 0.94) + 0.5) * Math.PI) * Math.sin(((vy + yd.h / 2) / yd.h) * Math.PI) * 16.0;
      pos.setZ(p, curve);
    }
    sailGeom.computeVertexNormals();

    const sail = new THREE.Mesh(sailGeom, sailMaterial);
    sail.position.set(0, yd.y - yd.h / 2, 70);
    sail.castShadow = true;
    ship.add(sail);
  });

  // 4. Mainmast (Fore-and-Aft Rigged Gaff Mast)
  const mainMast = new THREE.Mesh(new THREE.CylinderGeometry(2.8, 4.0, 270, 12), sparWoodMaterial);
  mainMast.position.set(0, 150, -35);
  mainMast.castShadow = true;
  ship.add(mainMast);

  // Boom & Gaff
  const boomGeom = new THREE.CylinderGeometry(1.8, 2.4, 115, 8);
  boomGeom.rotateX(Math.PI / 2);
  const boom = new THREE.Mesh(boomGeom, sparWoodMaterial);
  boom.position.set(0, 38, -92);
  ship.add(boom);

  const gaffGeom = new THREE.CylinderGeometry(1.4, 2.0, 95, 8);
  gaffGeom.rotateX(Math.PI / 2);
  gaffGeom.rotateZ(-0.35);
  const gaff = new THREE.Mesh(gaffGeom, sparWoodMaterial);
  gaff.position.set(0, 205, -82);
  ship.add(gaff);

  // Large Gaff Mainsail
  const gaffSailGeom = new THREE.PlaneGeometry(100, 150, 10, 10);
  gaffSailGeom.rotateY(Math.PI / 2);
  const posG = gaffSailGeom.attributes.position;
  for (let p = 0; p < posG.count; p++) {
    const vz = posG.getZ(p);
    const vy = posG.getY(p);
    const curve = Math.sin(((vz + 50) / 100) * Math.PI) * Math.sin(((vy + 75) / 150) * Math.PI) * 14.0;
    posG.setX(p, curve);
  }
  gaffSailGeom.computeVertexNormals();

  const gaffSail = new THREE.Mesh(gaffSailGeom, sailMaterial);
  gaffSail.position.set(0, 120, -88);
  gaffSail.castShadow = true;
  ship.add(gaffSail);

  // 5. Bowsprit & Jib Rigging
  const bowspritGeom = new THREE.CylinderGeometry(1.6, 2.8, 125, 8);
  bowspritGeom.rotateX(-Math.PI / 2 + 0.28);
  const bowsprit = new THREE.Mesh(bowspritGeom, sparWoodMaterial);
  bowsprit.position.set(0, 42, 200);
  ship.add(bowsprit);

  // 6. Quarterdeck Brass Ship's Wheel & Binnacle
  const wheelPedestal = new THREE.Mesh(new THREE.BoxGeometry(8, 22, 8), blackOakMaterial);
  wheelPedestal.position.set(0, 34, -100);
  ship.add(wheelPedestal);

  const wheelRim = new THREE.Mesh(new THREE.TorusGeometry(11, 1.3, 10, 24), brassMaterial);
  wheelRim.position.set(0, 45, -100);
  wheelRim.castShadow = true;
  ship.add(wheelRim);

  for (let s = 0; s < 4; s++) {
    const spokeGeom = new THREE.CylinderGeometry(0.7, 0.7, 26, 6);
    spokeGeom.rotateZ((s * Math.PI) / 4);
    const spoke = new THREE.Mesh(spokeGeom, brassMaterial);
    spoke.position.set(0, 45, -100);
    ship.add(spoke);
  }

  const binnacle = new THREE.Mesh(new THREE.CylinderGeometry(4.5, 5.5, 18, 12), brassMaterial);
  binnacle.position.set(0, 32, -86);
  ship.add(binnacle);

  return ship;
}

// ---------------------------------------------------------------------------
// 2. 3D QUARTERDECK & UNMANNED HELM ENVIRONMENT (SCENE 4 CLOSE-UP)
// ---------------------------------------------------------------------------

function build3DQuarterdeckEnvironment() {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x060d1a);
  scene.fog = new THREE.FogExp2(0x071526, 0.001);

  // Cold Directional Moonlight from Side
  const moonLight = new THREE.DirectionalLight(0xa5cbfa, 2.8);
  moonLight.position.set(-220, 380, 260);
  moonLight.castShadow = true;
  moonLight.shadow.mapSize.width = 1024;
  moonLight.shadow.mapSize.height = 1024;
  scene.add(moonLight);

  const ambient = new THREE.AmbientLight(0x182c44, 1.2);
  scene.add(ambient);

  helmGroup = new THREE.Group();

  // Wet Deck Floor Planks with glossy specular reflections
  const deckGeom = new THREE.PlaneGeometry(400, 500, 24, 24);
  deckGeom.rotateX(-Math.PI / 2);
  const deckMat = new THREE.MeshStandardMaterial({
    color: 0x362519,
    roughness: 0.18, // Wet glossy wood
    metalness: 0.35,
  });
  const deck = new THREE.Mesh(deckGeom, deckMat);
  deck.receiveShadow = true;
  helmGroup.add(deck);

  // Bulwarks and Taffrail behind the helm
  const taffMat = new THREE.MeshStandardMaterial({ color: 0x1f140c, roughness: 0.75 });
  const taffrail = new THREE.Mesh(new THREE.BoxGeometry(320, 30, 10), taffMat);
  taffrail.position.set(0, 38, -190);
  taffrail.castShadow = true;
  helmGroup.add(taffrail);

  // Heavy Teak Steering Pedestal
  const ped = new THREE.Mesh(new THREE.BoxGeometry(18, 56, 18), taffMat);
  ped.position.set(0, 28, 0);
  ped.castShadow = true;
  helmGroup.add(ped);

  // Polished Turned Brass Helm / Wheel
  const brassMat = new THREE.MeshStandardMaterial({
    color: 0xd4af37,
    roughness: 0.22,
    metalness: 0.92,
  });
  helmWheel = new THREE.Group();
  helmWheel.position.set(0, 56, 10);

  const hub = new THREE.Mesh(new THREE.CylinderGeometry(5, 5, 10, 16), brassMat);
  hub.rotation.x = Math.PI / 2;
  helmWheel.add(hub);

  const rim = new THREE.Mesh(new THREE.TorusGeometry(35, 3.0, 14, 32), brassMat);
  rim.castShadow = true;
  helmWheel.add(rim);

  // 8 Spokes with Handles extending beyond the rim
  for (let i = 0; i < 8; i++) {
    const angle = (i * Math.PI) / 4;
    const spokeGeom = new THREE.CylinderGeometry(1.4, 2.0, 84, 8);
    const spoke = new THREE.Mesh(spokeGeom, brassMat);
    spoke.rotation.z = angle;
    spoke.castShadow = true;
    helmWheel.add(spoke);
  }
  helmGroup.add(helmWheel);

  // Brass Compass Binnacle with Glowing Internal Oil Lamp
  const binnacle = new THREE.Mesh(new THREE.CylinderGeometry(12, 16, 50, 16), brassMat);
  binnacle.position.set(0, 25, 55);
  binnacle.castShadow = true;
  helmGroup.add(binnacle);

  const compassDome = new THREE.Mesh(
    new THREE.SphereGeometry(11, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0x90caf9, roughness: 0.05, metalness: 0.2, transparent: true, opacity: 0.8 })
  );
  compassDome.position.set(0, 50, 55);
  helmGroup.add(compassDome);

  // Warm Amber Binnacle Light (Illuminates the Wheel and Deck)
  binnacleLight = new THREE.PointLight(0xffa834, 3.2, 220);
  binnacleLight.position.set(0, 52, 55);
  binnacleLight.castShadow = true;
  helmGroup.add(binnacleLight);

  // Side Deck Lantern on Bulwark
  deckLanternLight = new THREE.PointLight(0xff9922, 2.6, 260);
  deckLanternLight.position.set(-90, 65, -40);
  deckLanternLight.castShadow = true;
  helmGroup.add(deckLanternLight);

  // Hemp Rope Coils on Deck
  const ropeMat = new THREE.MeshStandardMaterial({ color: 0x7a634a, roughness: 0.95 });
  const ropeCoil = new THREE.Mesh(new THREE.TorusGeometry(20, 6, 8, 20), ropeMat);
  ropeCoil.rotation.x = Math.PI / 2;
  ropeCoil.position.set(70, 3, 20);
  helmGroup.add(ropeCoil);

  scene.add(helmGroup);
  return scene;
}

// ---------------------------------------------------------------------------
// 3. 3D CAPTAIN'S CABIN & OPEN ARCHIVAL LOGBOOK (SCENE 5 MACRO CLOSE-UP)
// ---------------------------------------------------------------------------

function build3DCabinEnvironment() {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x120a06);

  // Rich Warm Ambient Tone for Wood & Parchment
  const ambient = new THREE.AmbientLight(0x4a2a16, 1.8);
  scene.add(ambient);

  // Realistic Flickering Candlelight (Key Warm Light)
  candleLight = new THREE.PointLight(0xffaa44, 4.8, 480);
  candleLight.position.set(45, 65, 30);
  candleLight.castShadow = true;
  candleLight.shadow.mapSize.width = 1024;
  candleLight.shadow.mapSize.height = 1024;
  candleLight.shadow.bias = -0.002;
  scene.add(candleLight);

  // Cool Moonlight Rim through cabin skylight
  const skylight = new THREE.DirectionalLight(0x6b9cd2, 1.5);
  skylight.position.set(-140, 240, 110);
  scene.add(skylight);

  cabinGroup = new THREE.Group();

  // Dark Oak Bulkhead Walls
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x22140c, roughness: 0.8 });
  const backWall = new THREE.Mesh(new THREE.PlaneGeometry(700, 600), wallMat);
  backWall.position.set(0, 160, -180);
  cabinGroup.add(backWall);

  // Captain's Heavy Mahogany Writing Desk
  const deskMat = new THREE.MeshStandardMaterial({
    color: 0x482412,
    roughness: 0.38,
    metalness: 0.15,
  });
  const deskTop = new THREE.Mesh(new THREE.BoxGeometry(340, 16, 240), deskMat);
  deskTop.position.set(0, 0, 0);
  deskTop.receiveShadow = true;
  deskTop.castShadow = true;
  cabinGroup.add(deskTop);

  // Open 3D Leather-Bound Maritime Logbook Ledger
  const logbookGroup = create3DOpenLogbookModel();
  logbookGroup.position.set(0, 9, 5);
  logbookGroup.receiveShadow = true;
  logbookGroup.castShadow = true;
  cabinGroup.add(logbookGroup);

  // Brass Gimbal Candlestick with Flame
  const brassMat = new THREE.MeshStandardMaterial({ color: 0xd4af37, roughness: 0.22, metalness: 0.9 });
  const candleBase = new THREE.Mesh(new THREE.CylinderGeometry(14, 16, 6, 16), brassMat);
  candleBase.position.set(45, 11, 30);
  candleBase.castShadow = true;
  cabinGroup.add(candleBase);

  const wax = new THREE.Mesh(new THREE.CylinderGeometry(3.8, 4.2, 38, 12), new THREE.MeshStandardMaterial({ color: 0xfdf7e7, roughness: 0.4 }));
  wax.position.set(45, 32, 30);
  wax.castShadow = true;
  cabinGroup.add(wax);

  const flame = new THREE.Mesh(new THREE.ConeGeometry(2.8, 10, 8), new THREE.MeshBasicMaterial({ color: 0xffbb22 }));
  flame.position.set(45, 55, 30);
  cabinGroup.add(flame);

  // Antique Brass Navigational Dividers on Desk
  const dividerGeom = new THREE.CylinderGeometry(0.9, 0.9, 52, 6);
  dividerGeom.rotateZ(0.28);
  const leg1 = new THREE.Mesh(dividerGeom, brassMat);
  leg1.position.set(-70, 9, 22);
  leg1.castShadow = true;
  cabinGroup.add(leg1);

  const leg2 = new THREE.Mesh(dividerGeom, brassMat);
  dividerGeom.rotateZ(-0.52);
  leg2.position.set(-58, 9, 22);
  leg2.castShadow = true;
  cabinGroup.add(leg2);

  // Cut-Glass Inkwell and Goose Quill Pen
  const inkwell = new THREE.Mesh(new THREE.CylinderGeometry(8, 9, 15, 12), new THREE.MeshStandardMaterial({ color: 0x141a24, roughness: 0.1, metalness: 0.35 }));
  inkwell.position.set(-80, 15, -45);
  cabinGroup.add(inkwell);

  const quillGeom = new THREE.CylinderGeometry(0.6, 1.6, 72, 6);
  quillGeom.rotateX(0.42);
  quillGeom.rotateZ(-0.32);
  const quill = new THREE.Mesh(quillGeom, new THREE.MeshStandardMaterial({ color: 0xf7ede2, roughness: 0.75 }));
  quill.position.set(-82, 42, -40);
  quill.castShadow = true;
  cabinGroup.add(quill);

  scene.add(cabinGroup);
  return scene;
}

/**
 * Creates an open 3D logbook with realistic curved paper pages, ruled lines,
 * 1872 Victorian cursive handwriting texture, and an official red wax seal.
 */
function create3DOpenLogbookModel() {
  const book = new THREE.Group();

  // Leather Outer Binding
  const leatherMat = new THREE.MeshStandardMaterial({
    color: 0x3d1b0c,
    roughness: 0.78,
    metalness: 0.12,
  });
  const cover = new THREE.Mesh(new THREE.BoxGeometry(164, 4, 114), leatherMat);
  cover.position.y = 2;
  book.add(cover);

  // Procedural Canvas Texture for 1872 Cursive Handwriting & Wax Seal
  const pageTexture = generateLogbookTexture();

  const pageMat = new THREE.MeshStandardMaterial({
    map: pageTexture,
    roughness: 0.82,
    metalness: 0.02,
  });

  // Left Page Block (Curved upward from spine)
  const leftPageGeom = new THREE.PlaneGeometry(76, 104, 12, 12);
  leftPageGeom.rotateX(-Math.PI / 2);
  const posL = leftPageGeom.attributes.position;
  for (let i = 0; i < posL.count; i++) {
    const x = posL.getX(i);
    const arch = Math.sin(((x + 38) / 76) * Math.PI) * 4.8;
    posL.setY(i, arch);
  }
  leftPageGeom.computeVertexNormals();
  const leftPage = new THREE.Mesh(leftPageGeom, pageMat);
  leftPage.position.set(-40, 5.0, 0);
  book.add(leftPage);

  // Right Page Block
  const rightPageGeom = new THREE.PlaneGeometry(76, 104, 12, 12);
  rightPageGeom.rotateX(-Math.PI / 2);
  const posR = rightPageGeom.attributes.position;
  for (let i = 0; i < posR.count; i++) {
    const x = posR.getX(i);
    const arch = Math.sin(((x + 38) / 76) * Math.PI) * 4.8;
    posR.setY(i, arch);
  }
  rightPageGeom.computeVertexNormals();
  const rightPage = new THREE.Mesh(rightPageGeom, pageMat);
  rightPage.position.set(40, 5.0, 0);
  book.add(rightPage);

  // Embossed Red Wax Seal
  const waxSealGeom = new THREE.CylinderGeometry(7.5, 8.5, 3.0, 16);
  const waxMat = new THREE.MeshStandardMaterial({ color: 0x991b1b, roughness: 0.42, metalness: 0.25 });
  const seal = new THREE.Mesh(waxSealGeom, waxMat);
  seal.position.set(54, 10.5, 36);
  seal.castShadow = true;
  book.add(seal);

  return book;
}

function generateLogbookTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');

  // Aged Parchment Vellum Background
  ctx.fillStyle = '#f8f1de';
  ctx.fillRect(0, 0, 1024, 1024);

  // Vignette and sepia aging
  const grad = ctx.createRadialGradient(512, 512, 180, 512, 512, 600);
  grad.addColorStop(0, 'rgba(248, 241, 222, 0)');
  grad.addColorStop(1, 'rgba(196, 166, 122, 0.65)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 1024, 1024);

  // Ruled Ledger Lines
  ctx.strokeStyle = 'rgba(154, 128, 92, 0.55)';
  ctx.lineWidth = 2.5;
  for (let y = 140; y < 960; y += 46) {
    ctx.beginPath();
    ctx.moveTo(60, y);
    ctx.lineTo(964, y);
    ctx.stroke();
  }

  // Vertical Red Margin Line
  ctx.strokeStyle = 'rgba(214, 80, 80, 0.55)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(180, 80);
  ctx.lineTo(180, 980);
  ctx.stroke();

  // Authentic 1872 Cursive Handwriting
  ctx.fillStyle = '#22140a';
  ctx.font = 'italic bold 32px "Georgia", serif';
  ctx.fillText('BRIGANTINE MARY CELESTE — OFFICIAL LOG', 110, 100);

  ctx.font = 'italic 26px "Georgia", serif';
  ctx.fillText('Nov 24, 1872: St. Mary’s bearing W.S.W. 35 miles distant.', 200, 232);
  ctx.fillText('Wind Fresh at S.S.W. Sea heavy. Ship under shortened canvas.', 200, 278);
  ctx.fillText('Nov 25, 1872: At 8 AM. Tacked ship to the Northward.', 200, 370);
  ctx.fillText('Latitude 37°01’ N. Longitude 25°01’ W.', 200, 416);
  ctx.fillText('Final recorded entry in hand of first mate.', 200, 462);

  ctx.font = 'bold 22px "Courier New", monospace';
  ctx.fillStyle = '#6b4122';
  ctx.fillText('[AD 1872 / REGISTER OF BRITISH SHIPPING]', 200, 600);

  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

function createSprayParticleSystem() {
  const count = 1200;
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);

  for (let i = 0; i < count * 3; i += 3) {
    positions[i] = (Math.random() - 0.5) * 1400;
    positions[i + 1] = Math.random() * 250;
    positions[i + 2] = (Math.random() - 0.5) * 1400;
  }
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

  const material = new THREE.PointsMaterial({
    color: 0x90caf9,
    size: 2.5,
    transparent: true,
    opacity: 0.55,
  });

  return new THREE.Points(geometry, material);
}

// ---------------------------------------------------------------------------
// 4. ACTIVE FRAME UPDATE & 3D CAMERA ORCHESTRATION
// ---------------------------------------------------------------------------

function quinticInOut(t) {
  t = Math.max(0, Math.min(1, t));
  return t < 0.5 ? 16 * Math.pow(t, 5) : 1 - Math.pow(-2 * t + 2, 5) / 2;
}

/**
 * Updates 3D world physics and renders the current narrative frame.
 */
export function renderThreeNarrativeFrame(beatIdx, localTime, duration, globalTime, sceneSpec) {
  if (!renderer || !camera) {
    initThreeVisualEngine();
  }

  const normT = Math.max(0, Math.min(1, localTime / Math.max(0.1, duration)));
  const pEased = quinticInOut(normT);

  const text = (sceneSpec?.narration?.text || '').toLowerCase();

  // Select the appropriate 3D environment for the beat
  if (text.includes('logbook') || text.includes('cabin') || text.includes('entry') || text.includes('desk')) {
    activeScene = cabinScene;
    updateCabinFrame(localTime, duration, globalTime, pEased);
  } else if (text.includes('helm') || text.includes('unmanned') || text.includes('deck') || text.includes('soul vanished')) {
    activeScene = helmScene;
    updateHelmFrame(localTime, duration, globalTime, pEased);
  } else {
    activeScene = oceanScene;
    updateOceanFrame(localTime, duration, globalTime, pEased, beatIdx);
  }

  // Render 3D WebGL scene
  renderer.render(activeScene, camera);
}

function updateOceanFrame(lt, dur, t, p, beatIdx) {
  // 1. Dynamic Ocean Swell Displacements
  if (oceanGeometry) {
    const pos = oceanGeometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const wave =
        Math.sin(x * 0.005 + t * 1.8) * 22.0 +
        Math.cos(z * 0.007 + t * 1.4) * 16.0 +
        Math.sin((x + z) * 0.012 + t * 2.2) * 6.0;
      pos.setY(i, wave);
    }
    oceanGeometry.computeVertexNormals();
    oceanGeometry.attributes.position.needsUpdate = true;
  }

  // 2. Physical Ship Buoyancy & Swaying
  if (shipGroup) {
    const shipWave = Math.sin(t * 1.8) * 14.0 + Math.cos(t * 1.4) * 8.0;
    shipGroup.position.y = shipWave;
    shipGroup.rotation.z = Math.sin(t * 1.4) * 0.07; // Roll
    shipGroup.rotation.x = Math.cos(t * 1.8) * 0.045; // Pitch
    shipGroup.position.x = Math.sin(t * 0.4) * 15.0; // Slow drift
  }

  // 3. Spray Particles Motion
  if (sprayParticles) {
    const pos = sprayParticles.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      let x = pos.getX(i) + 1.2;
      let y = pos.getY(i) - 0.8;
      if (y < 0) y = 200 + Math.random() * 50;
      if (x > 700) x = -700;
      pos.setX(i, x);
      pos.setY(i, y);
    }
    sprayParticles.geometry.attributes.position.needsUpdate = true;
  }

  // 4. Motivated 3D Camera Kinematics (Three-Quarter Broadside Angles)
  const shakeX = Math.sin(t * 1.57) * 2.8;
  const shakeY = Math.cos(t * 1.25) * 2.2;
  const shakeRoll = Math.sin(t * 0.95) * 0.006;

  if (beatIdx === 0) {
    // Beat 1: Establishing Shot - Three-Quarter Perspective Broadside View
    const camX = 340 + p * 40 + shakeX;
    const camY = 140 + p * 20 + shakeY;
    const camZ = 520 - p * 120;
    camera.position.set(camX, camY, camZ);
    camera.lookAt(0, 65, 0);
  } else if (beatIdx === 1) {
    // Beat 2: Swells battering wooden hull - Dynamic low-angle prow view
    const camX = -280 + p * 50 + shakeX;
    const camY = 40 + p * 35 + shakeY;
    const camZ = 380 - p * 80;
    camera.position.set(camX, camY, camZ);
    camera.lookAt(0, 90, 60);
  } else if (beatIdx === 2) {
    // Beat 3: Boarding crew hails silent deck - Tracking across starboard quarter
    const camX = 260 - p * 80 + shakeX;
    const camY = 130 + shakeY;
    const camZ = 460 - p * 140;
    camera.position.set(camX, camY, camZ);
    camera.lookAt(0, 60, -20);
  } else {
    // Beat 6: Final Resolution / Isolation Dolly-Out
    const camX = 240 + p * 220 + shakeX;
    const camY = 160 + p * 280 + shakeY;
    const camZ = 520 + p * 480;
    camera.position.set(camX, camY, camZ);
    camera.lookAt(0, 40, 0);
  }
  camera.rotation.z += shakeRoll;
}

function updateHelmFrame(lt, dur, t, p) {
  // Sway the unmanned helm back and forth naturally with the ocean swell
  if (helmWheel) {
    helmWheel.rotation.z = Math.sin(t * 1.6) * 0.28;
  }
  if (binnacleLight) {
    binnacleLight.intensity = 3.0 + Math.sin(t * 8.0) * 0.35; // Oil lamp flicker
  }
  if (deckLanternLight) {
    deckLanternLight.intensity = 2.4 + Math.cos(t * 10.0) * 0.3;
  }

  // Camera: Dramatic Three-Quarter Dolly-In onto the abandoned ship's wheel
  const shakeX = Math.sin(t * 1.57) * 1.5;
  const shakeY = Math.cos(t * 1.25) * 1.2;
  const camX = 35 + p * 10 + shakeX;
  const camY = 62 + p * 8 + shakeY;
  const camZ = 165 - p * 65;

  camera.position.set(camX, camY, camZ);
  camera.lookAt(-10, 50, 5);
}

function updateCabinFrame(lt, dur, t, p) {
  // Flickering candlelight
  if (candleLight) {
    candleLight.intensity = 4.5 + Math.sin(t * 12.0) * 0.45 + Math.cos(t * 22.0) * 0.25;
  }

  // Camera: Macro close-up slowly pushing down toward the cursive logbook entry
  const shakeX = Math.sin(t * 1.57) * 0.8;
  const shakeY = Math.cos(t * 1.25) * 0.6;
  const camX = -15 + p * 10 + shakeX;
  const camY = 68 - p * 18 + shakeY;
  const camZ = 110 - p * 28;

  camera.position.set(camX, camY, camZ);
  camera.lookAt(0, 8, 5);
}
