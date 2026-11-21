// CurioLoop 2.0 Narrative-Driven Scene Choreographer
// Executes grounded visual storytelling: Cinematic 2.5D, Selective 3D, Archival Imagery,
// Documentary Motion Graphics, and Subject-Specific Procedural Environments.
// Strictly retires legacy radar_scan, archive_map, and stick-story templates.

import { ctx, C, W, H, TAU, clamp, lerp, seg, eo, eio, eob, rnd, rr, circle, ell, line, fillAll, bigText, drawCurioLoopBadge } from './core/lib.js';
import { renderThreeNarrativeFrame, getThreeCanvas } from './three_scenes.js';

function quinticInOut(t) {
  t = clamp(t, 0, 1);
  return t < 0.5 ? 16 * Math.pow(t, 5) : 1 - Math.pow(-2 * t + 2, 5) / 2;
}

export function buildNarrativeShots(script, storyboard) {
  const shots = [];
  const cues = [];
  const sbScenes = storyboard?.scenes || [];

  for (let idx = 0; idx < sbScenes.length; idx++) {
    const sc = sbScenes[idx];
    const at = sc.narration.start_s;
    const end = sc.narration.end_s;
    const dur = sc.narration.duration_sec || (end - at);

    // Audio cue matching narrative action
    const action = (sc.primary_subject?.action || '').toLowerCase();
    if (action.includes('ring') || action.includes('bell')) {
      cues.push({ t: at + 0.1, type: 'tock', volume: 0.8 });
    } else if (action.includes('approach') || action.includes('search')) {
      cues.push({ t: at + 0.1, type: 'whoosh', volume: 0.6 });
    } else if (action.includes('ink') || action.includes('ledger') || action.includes('key')) {
      cues.push({ t: at + 0.1, type: 'slide', volume: 0.7 });
    } else {
      cues.push({ t: at + 0.1, type: 'pop', volume: 0.5 });
    }

    shots.push({
      id: sc.scene_id,
      at: at,
      end: end,
      dur: dur,
      scene: sc,
      draw: (lt, d, t) => {
        drawNarrativeScene(sc, lt, d, t, idx, sbScenes.length);
      }
    });
  }

  return { shots, cues };
}

function drawNarrativeScene(scene, lt, d, t, idx, total) {
  const normT = clamp(lt / Math.max(0.1, d), 0, 1);

  // 1. Render physically-grounded 3D WebGL scene via Three.js
  renderThreeNarrativeFrame(idx, lt, d, t, scene);

  // 2. Composite Three.js 3D WebGL canvas onto 2D context
  const threeCv = getThreeCanvas();
  if (threeCv) {
    ctx.drawImage(threeCv, 0, 0, W, H);
  }

  // 3. Subtle Top Safe-Zone Chapter Pill (y = 220, safe zone)
  drawSceneBadge(scene, idx, total, normT);
}

// ── Narrative Visual Renderers ──

function drawHistoricalMaryCeleste(lt, d, t, normT, p) {
  fillAll('#07111e'); // Deep Atlantic twilight
  
  // Distant horizon clouds & squall line (z = -450)
  const squallGrad = ctx.createLinearGradient(0, 300, 0, 800);
  squallGrad.addColorStop(0, '#0a1728');
  squallGrad.addColorStop(1, '#0e233d');
  ctx.fillStyle = squallGrad;
  ctx.fillRect(-200, 300, W + 400, 600);

  // Layered Atlantic Swell (Background waves)
  drawOceanSwell(760, '#0f2942', t * 1.2, 34);
  drawOceanSwell(830, '#133554', t * 1.5 + 1.2, 42);

  // The Mary Celeste Hull & Rigging (Midground Subject, z = 0)
  ctx.save();
  // Ship pitch and roll on ocean swells
  const shipPitch = Math.sin(t * 1.4) * 0.045;
  const shipHeave = Math.cos(t * 1.4) * 18;
  ctx.translate(540, 780 + shipHeave);
  ctx.rotate(shipPitch);

  // Wooden Hull
  ctx.fillStyle = '#1c130d';
  ctx.strokeStyle = '#382519';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.moveTo(-320, 60);
  ctx.bezierCurveTo(-150, 100, 150, 100, 340, 30);
  ctx.lineTo(310, 120);
  ctx.bezierCurveTo(120, 180, -120, 180, -290, 100);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // Bulwarks and deck fixtures
  ctx.strokeStyle = '#5a3d2b';
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(-300, 50); ctx.lineTo(320, 20);
  ctx.stroke();

  // Fore-Mast & Square Billowing Sails
  ctx.strokeStyle = '#2d1e15';
  ctx.lineWidth = 10;
  ctx.beginPath(); ctx.moveTo(-110, 60); ctx.lineTo(-110, -380); ctx.stroke();
  // Yardarms
  ctx.lineWidth = 6;
  ctx.beginPath(); ctx.moveTo(-210, -320); ctx.lineTo(-10, -320); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-230, -220); ctx.lineTo(10, -220); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-240, -100); ctx.lineTo(20, -100); ctx.stroke();
  // Billowing Sails
  ctx.fillStyle = 'rgba(214, 203, 182, 0.88)';
  ctx.strokeStyle = '#8a7d65';
  ctx.lineWidth = 2;
  // Top sail
  ctx.beginPath(); ctx.moveTo(-200, -315); ctx.quadraticCurveTo(-110, -300 + Math.sin(t*2)*6, -20, -315); ctx.lineTo(-25, -230); ctx.quadraticCurveTo(-110, -210, -195, -230); ctx.closePath(); ctx.fill(); ctx.stroke();
  // Lower sail
  ctx.beginPath(); ctx.moveTo(-225, -215); ctx.quadraticCurveTo(-110, -195 + Math.sin(t*2)*8, -5, -215); ctx.lineTo(-10, -110); ctx.quadraticCurveTo(-110, -85, -220, -110); ctx.closePath(); ctx.fill(); ctx.stroke();

  // Main-Mast & Gaff Rigging
  ctx.strokeStyle = '#2d1e15';
  ctx.lineWidth = 11;
  ctx.beginPath(); ctx.moveTo(130, 50); ctx.lineTo(130, -420); ctx.stroke();
  // Main boom & gaff
  ctx.lineWidth = 6;
  ctx.beginPath(); ctx.moveTo(130, -350); ctx.lineTo(310, -280); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(130, -20); ctx.lineTo(340, -10); ctx.stroke();
  // Main gaff canvas
  ctx.beginPath(); ctx.moveTo(130, -340); ctx.lineTo(300, -270); ctx.lineTo(330, -15); ctx.lineTo(130, -25); ctx.closePath(); ctx.fill(); ctx.stroke();

  // Abandoned Quarterdeck & Ship's Helm Wheel
  ctx.fillStyle = '#110b07';
  ctx.fillRect(-240, 25, 45, 30);
  ctx.strokeStyle = '#d4af37'; // Weathered brass
  ctx.lineWidth = 3;
  ctx.beginPath(); ctx.arc(-218, 12, 18, 0, TAU); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-218, -6); ctx.lineTo(-218, 30); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(-236, 12); ctx.lineTo(-200, 12); ctx.stroke();

  ctx.restore();

  // Foreground Atlantic Wave Crests (z = 180, parallax)
  drawOceanSwell(920, '#174066', t * 1.8 + 2.5, 52);
  drawOceanSwell(1040, '#0d2842', t * 2.1, 60);
}

function drawCabinFourOutpost(lt, d, t, normT, p) {
  fillAll('#070b12'); // Deep nocturnal forest

  // Pine tree canopy silhouettes in deep background (z = -450)
  ctx.fillStyle = '#0a1320';
  for (let x = -80; x < W + 100; x += 90) {
    drawPineTreeSilhouette(x, 480, 1.4);
  }
  ctx.fillStyle = '#0f1c2e';
  for (let x = -40; x < W + 100; x += 110) {
    drawPineTreeSilhouette(x, 560, 1.1);
  }

  // Cabin Four Timber Structure (Midground, z = 0)
  ctx.save();
  ctx.translate(540, 820);

  // Weathered Wood Logs
  const cabinW = 680, cabinH = 500;
  ctx.fillStyle = '#1c140d';
  ctx.strokeStyle = '#0c0805';
  ctx.lineWidth = 8;
  rr(-cabinW/2, -cabinH/2, cabinW, cabinH, 12);
  ctx.fill(); ctx.stroke();

  // Log siding lines
  ctx.strokeStyle = '#2c1f15';
  ctx.lineWidth = 4;
  for (let y = -cabinH/2 + 50; y < cabinH/2; y += 50) {
    line([[-cabinW/2, y], [cabinW/2, y]], '#120d09', 4);
  }

  // Heavy Pitched Shingle Roof
  ctx.fillStyle = '#140e09';
  ctx.beginPath();
  ctx.moveTo(0, -cabinH/2 - 160);
  ctx.lineTo(-cabinW/2 - 60, -cabinH/2 + 20);
  ctx.lineTo(cabinW/2 + 60, -cabinH/2 + 20);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = '#080503'; ctx.lineWidth = 10; ctx.stroke();

  // Padlocked Boarded Doorway
  const doorW = 200, doorH = 320;
  ctx.fillStyle = '#0a0704';
  ctx.fillRect(-doorW/2, cabinH/2 - doorH, doorW, doorH);
  ctx.strokeRect(-doorW/2, cabinH/2 - doorH, doorW, doorH);

  // Heavy Diagonal Timber Cross-Planks
  ctx.fillStyle = '#3a271a';
  ctx.save(); ctx.rotate(-0.1);
  ctx.fillRect(-doorW/2 - 20, 60, doorW + 40, 38);
  ctx.restore();
  ctx.save(); ctx.rotate(0.12);
  ctx.fillRect(-doorW/2 - 20, 160, doorW + 40, 38);
  ctx.restore();

  // Iron Chains & Heavy Padlock
  ctx.strokeStyle = '#64748b';
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.ellipse(0, 110, 55, 20, 0, 0, TAU);
  ctx.stroke();
  ctx.beginPath();
  ctx.ellipse(0, 130, 50, 18, 0, 0, TAU);
  ctx.stroke();

  // Padlock
  ctx.fillStyle = '#334155';
  rr(-22, 130, 44, 48, 6); ctx.fill();
  ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 5;
  ctx.beginPath(); ctx.arc(0, 130, 16, Math.PI, 0); ctx.stroke();

  // Stenciled Brass "CABIN 4" Plaque
  ctx.fillStyle = '#b45309';
  rr(-70, -cabinH/2 + 90, 140, 44, 4); ctx.fill();
  ctx.strokeStyle = '#fef3c7'; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = '#1c1917';
  ctx.font = '900 24px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('CABIN 4', 0, -cabinH/2 + 121);

  // Frosted Dusty Window
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(170, -60, 120, 130);
  ctx.strokeStyle = '#2c1f15'; ctx.lineWidth = 6; ctx.strokeRect(170, -60, 120, 130);
  ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 3;
  line([[230, -60], [230, 70]], '#2c1f15', 4);
  line([[170, 5], [290, 5]], '#2c1f15', 4);

  ctx.restore();

  // Cold Ground Fog Layer in Foreground (z = 180)
  drawGroundFog(960, t);
}

function drawVintageCopperTelephone(lt, d, t, normT, p) {
  fillAll('#0a0d14'); // Dark interior room

  ctx.save();
  ctx.translate(540, 780);

  // Handcrafted Oak Telephone Box
  const boxW = 380, boxH = 640;
  ctx.fillStyle = '#451a03'; // Warm vintage oak
  ctx.strokeStyle = '#1f0a01';
  ctx.lineWidth = 8;
  rr(-boxW/2, -boxH/2, boxW, boxH, 18); ctx.fill(); ctx.stroke();

  // Inner beveled wooden frame
  ctx.strokeStyle = '#78350f'; ctx.lineWidth = 4;
  rr(-boxW/2 + 18, -boxH/2 + 18, boxW - 36, boxH - 36, 12); ctx.stroke();

  // Dual Solid Copper Bells (Top)
  const bellR = 68;
  // Acoustic vibration shake
  const vib = Math.sin(t * 38) * 3.5;
  drawCopperBell(-85 + vib, -boxH/2 + 120, bellR);
  drawCopperBell(85 - vib, -boxH/2 + 120, bellR);

  // Vibrating Central Striker
  ctx.fillStyle = '#e2e8f0';
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 3;
  circle(0 + vib * 1.5, -boxH/2 + 120, 14, '#f8fafc');
  line([[0, -boxH/2 + 120], [0, -boxH/2 + 180]], '#94a3b8', 6);

  // Concentric Acoustic Ring Waves (Narrative Audio Telemetry)
  ctx.strokeStyle = 'rgba(245, 158, 11, ' + (0.5 + 0.5 * Math.sin(t * 12)) + ')';
  ctx.lineWidth = 4;
  ctx.beginPath(); ctx.arc(-85, -boxH/2 + 120, bellR + 25 + (t * 80 % 60), Math.PI * 0.7, Math.PI * 1.3); ctx.stroke();
  ctx.beginPath(); ctx.arc(85, -boxH/2 + 120, bellR + 25 + (t * 80 % 60), -Math.PI * 0.3, Math.PI * 0.3); ctx.stroke();

  // Bakelite Transmitter Mouthpiece
  ctx.fillStyle = '#0f172a';
  circle(0, 80, 52, '#020617');
  ctx.strokeStyle = '#334155'; ctx.lineWidth = 6; ctx.stroke();
  circle(0, 80, 36, '#0f172a');
  circle(0, 80, 12, '#1e293b');

  // Left Receiver Cradle & Handset
  ctx.strokeStyle = '#64748b'; ctx.lineWidth = 12; ctx.lineCap = 'round';
  line([[-boxW/2, 20], [-boxW/2 - 60, 20]], '#64748b', 12);
  line([[-boxW/2 - 60, 20], [-boxW/2 - 60, 60]], '#64748b', 12);

  // Hanging Bakelite Earpiece
  ctx.fillStyle = '#0f172a';
  rr(-boxW/2 - 90, 60, 60, 240, 14); ctx.fill();
  ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 4; ctx.stroke();

  // Braided Cotton Cord
  ctx.strokeStyle = '#78350f'; ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.moveTo(-boxW/2 - 60, 300);
  ctx.bezierCurveTo(-boxW/2 - 20, 420, -boxW/2 + 40, 430, -boxW/2 + 30, 340);
  ctx.stroke();

  ctx.restore();
}

function drawArchivalOpenLedger(lt, d, t, normT, p) {
  fillAll('#0c0906'); // Candlelit study desk

  ctx.save();
  ctx.translate(540, 780);

  // Weathered Oak Desk
  const deskW = 920, deskH = 680;
  ctx.fillStyle = '#1c130c';
  rr(-deskW/2, -deskH/2, deskW, deskH, 14); ctx.fill();
  ctx.strokeStyle = '#0f0a06'; ctx.lineWidth = 8; ctx.stroke();

  // Leather Journal Binding
  const bookW = 740, bookH = 480;
  ctx.fillStyle = '#3f2113';
  rr(-bookW/2, -bookH/2, bookW, bookH, 12); ctx.fill();

  // Open Folio Pages (Aged Vellum)
  const pageW = 345, pageH = 450;
  const pageGrad = ctx.createLinearGradient(-pageW, 0, pageW, 0);
  pageGrad.addColorStop(0, '#d8cbb0');
  pageGrad.addColorStop(0.48, '#f5edd8');
  pageGrad.addColorStop(0.50, '#9e8d71'); // Spine crease
  pageGrad.addColorStop(0.52, '#f5edd8');
  pageGrad.addColorStop(1, '#d8cbb0');
  ctx.fillStyle = pageGrad;
  rr(-bookW/2 + 15, -bookH/2 + 15, bookW - 30, bookH - 30, 6); ctx.fill();

  // Left Page: Historical Faded Script
  ctx.strokeStyle = 'rgba(74, 45, 27, 0.38)';
  ctx.lineWidth = 3; ctx.lineCap = 'round';
  for (let l = 0; l < 8; l++) {
    const ly = -bookH/2 + 80 + l * 44;
    line([[-pageW + 40, ly], [-30, ly]]);
  }

  // Right Page: Fresh Black Ink Incident Entry
  const inkReveal = clamp(lt * 1.5, 0, 1);
  ctx.fillStyle = '#09090b';
  ctx.font = '900 24px monospace';
  ctx.textAlign = 'left';
  ctx.fillText('ENTRY: 21-NOV', 30, -bookH/2 + 85);

  ctx.strokeStyle = '#09090b'; ctx.lineWidth = 4;
  line([[30, -bookH/2 + 130], [280, -bookH/2 + 130]]);
  line([[30, -bookH/2 + 175], [260, -bookH/2 + 175]]);

  // Handwritten Name "Officer Miller" in cursive
  ctx.font = 'italic bold 38px Georgia, serif';
  ctx.fillText('Officer Miller', 30, -bookH/2 + 250);
  circle(250, -bookH/2 + 245, 4, '#09090b');

  // Recovered Wet Brass River Key (Right Fore-Stage)
  ctx.save();
  ctx.translate(140, 80);
  ctx.rotate(0.35);
  // Key Ring & Stem
  ctx.strokeStyle = '#ca8a04'; ctx.lineWidth = 14;
  circle(0, 0, 36, 'none'); ctx.stroke();
  ctx.fillStyle = '#ca8a04';
  ctx.fillRect(28, -8, 120, 16);
  // Key Bit / Teeth
  ctx.fillRect(115, 8, 16, 26);
  ctx.fillRect(135, 8, 12, 18);
  // Wet Gleam highlight
  ctx.fillStyle = '#fef08a';
  circle(-12, -12, 5, '#fef08a');
  ctx.restore();

  ctx.restore();
}

function drawNightWatchmanPatrol(lt, d, t, normT, p) {
  fillAll('#04070c'); // Cold nocturnal forest perimeter

  // Pine Trees in Background
  ctx.fillStyle = '#08101a';
  for (let x = -60; x < W + 80; x += 100) {
    drawPineTreeSilhouette(x, 600, 1.3);
  }

  ctx.save();
  // Volumetric Flashlight Cone (Motivated investigative lighting)
  const beamAngle = 0.45 + Math.sin(t * 1.8) * 0.12;
  const fX = 320, fY = 880;
  ctx.save();
  ctx.translate(fX, fY);
  ctx.rotate(beamAngle);
  const flashGrad = ctx.createRadialGradient(0, 0, 10, 500, 0, 600);
  flashGrad.addColorStop(0, 'rgba(254, 240, 138, 0.75)');
  flashGrad.addColorStop(0.35, 'rgba(254, 240, 138, 0.35)');
  flashGrad.addColorStop(1, 'rgba(254, 240, 138, 0)');
  ctx.fillStyle = flashGrad;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.arc(0, 0, 700, -0.28, 0.28);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Watchman Silhouette with Flashlight
  ctx.fillStyle = '#0f172a';
  ctx.strokeStyle = '#020617'; ctx.lineWidth = 4;
  // Body torso
  rr(240, 760, 120, 240, 18); ctx.fill(); ctx.stroke();
  // Head & Watchman Cap
  circle(300, 700, 42, '#0f172a');
  rr(250, 675, 100, 22, 6); ctx.fill(); // Cap brim
  // Arm holding flashlight
  ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 26; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(290, 790); ctx.lineTo(fX, fY); ctx.stroke();
  // Flashlight Torch
  ctx.fillStyle = '#334155';
  ctx.save(); ctx.translate(fX, fY); ctx.rotate(beamAngle);
  ctx.fillRect(-20, -10, 40, 20);
  circle(20, 0, 14, '#fef08a');
  ctx.restore();

  ctx.restore();
}

function drawCinematicMultiplaneScene(scene, lt, d, t, normT, p) {
  fillAll('#080d17');
  // Dynamic multiplane with layered atmospheric depth
  const env = scene.environment?.name || 'Story Setting';
  ctx.save();
  ctx.translate(540, 800);
  // Elegant architectural or landscape geometry
  ctx.fillStyle = '#101c2e';
  rr(-380, -260, 760, 520, 24); ctx.fill();
  ctx.strokeStyle = '#1e3a5f'; ctx.lineWidth = 6; ctx.stroke();

  // Focal subject badge
  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 36px Georgia, serif';
  ctx.textAlign = 'center';
  ctx.fillText(scene.primary_subject?.name || 'Narrative Evidence', 0, -60);

  ctx.fillStyle = '#38bdf8';
  ctx.font = '900 22px monospace';
  ctx.fillText((scene.primary_subject?.action || 'Story Progression').toUpperCase(), 0, 20);

  ctx.restore();
}

// ── Utility Helpers ──

function drawOceanSwell(yBase, color, timeOffset, amp) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(-100, H);
  ctx.lineTo(-100, yBase);
  for (let x = -100; x <= W + 100; x += 30) {
    const y = yBase + Math.sin(x * 0.008 + timeOffset) * amp + Math.cos(x * 0.016 + timeOffset * 1.5) * (amp * 0.35);
    ctx.lineTo(x, y);
  }
  ctx.lineTo(W + 100, H);
  ctx.closePath();
  ctx.fill();
}

function drawPineTreeSilhouette(x, yBase, scale = 1.0) {
  ctx.save();
  ctx.translate(x, yBase);
  ctx.scale(scale, scale);
  // 3-tiered pine foliage
  ctx.beginPath();
  ctx.moveTo(0, -220); ctx.lineTo(-45, -140); ctx.lineTo(-20, -140);
  ctx.lineTo(-65, -60); ctx.lineTo(-30, -60);
  ctx.lineTo(-80, 0); ctx.lineTo(80, 0);
  ctx.lineTo(30, -60); ctx.lineTo(65, -60);
  ctx.lineTo(20, -140); ctx.lineTo(45, -140);
  ctx.closePath();
  ctx.fill();
  // Trunk
  ctx.fillRect(-10, 0, 20, 45);
  ctx.restore();
}

function drawCopperBell(x, y, r) {
  ctx.save();
  ctx.translate(x, y);
  const bellGrad = ctx.createRadialGradient(-r*0.2, -r*0.3, r*0.1, 0, 0, r);
  bellGrad.addColorStop(0, '#fed7aa');
  bellGrad.addColorStop(0.4, '#ea580c');
  bellGrad.addColorStop(0.85, '#9a3412');
  bellGrad.addColorStop(1, '#431407');
  ctx.fillStyle = bellGrad;
  circle(0, 0, r, bellGrad);
  ctx.strokeStyle = '#431407'; ctx.lineWidth = 4; ctx.stroke();
  circle(0, 0, r * 0.22, '#fed7aa');
  ctx.restore();
}

function drawGroundFog(yBase, t) {
  ctx.save();
  const fogGrad = ctx.createLinearGradient(0, yBase - 120, 0, yBase + 120);
  fogGrad.addColorStop(0, 'rgba(255, 255, 255, 0)');
  fogGrad.addColorStop(0.5, 'rgba(148, 163, 184, 0.28)');
  fogGrad.addColorStop(1, 'rgba(148, 163, 184, 0)');
  ctx.fillStyle = fogGrad;
  ctx.fillRect(-100, yBase - 120, W + 200, 240);
  ctx.restore();
}

function drawAtmosphericParticles(env, t) {
  ctx.save();
  const count = 36;
  ctx.fillStyle = 'rgba(254, 240, 138, 0.45)';
  for (let i = 0; i < count; i++) {
    const px = ((t * (25 + rnd(i) * 35) + rnd(i + 7) * 1100) % (W + 80)) - 40;
    const py = 400 + rnd(i + 13) * 780 + Math.sin(t * 1.5 + i) * 22;
    circle(px, py, 1.5 + rnd(i + 2) * 2.5);
  }
  ctx.restore();
}

function drawSceneBadge(scene, idx, total, prog) {
  // Top chapter bar & narrative objective (y = 230 safe zone)
  const trackW = 540, tx0 = (W - trackW) / 2, ty = 220;
  ctx.fillStyle = 'rgba(255,255,255,0.12)';
  rr(tx0, ty, trackW, 4, 2); ctx.fill();
  const frac = total > 1 ? (idx + prog) / total : prog;
  ctx.fillStyle = '#f59e0b';
  rr(tx0, ty, Math.max(10, trackW * frac), 4, 2); ctx.fill();

  const title = (scene.story_event || scene.primary_subject?.name || 'Narrative Scene').toUpperCase().slice(0, 32);
  ctx.font = '900 22px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillStyle = '#94a3b8';
  ctx.fillText(title, 540, 260);
}
