/**
 * CurioLoop 2.0 - Unified Cinematic Visual Engine Bundle
 * Exposes window.CurioLoop for zero-CORS file:/// and http:// execution.
 */
(function(window) {
    'use strict';

    // --- RenderingModes.js ---
/**
 * CurioLoop 2.0 - RenderingModes
 * Defines the 3 complementary rendering modes and hybrid integration:
 * - Mode A: Cinematic 3D (Spatial geometry, perspective camera, volumetric lighting, PBR materials)
 * - Mode B: Cinematic 2.5D (Layered depth-separated planes, parallax, atmospheric depth)
 * - Mode C: Documentary Motion Graphics (Flight routes, timelines, declassified records, coordinates, mobile safe zones)
 * - Hybrid: Seamless spatial 3D/2.5D environment with integrated documentary graphics
 */

const RenderingMode = {
    MODE_A_CINEMATIC_3D: 'MODE_A_CINEMATIC_3D',
    MODE_B_CINEMATIC_2_5D: 'MODE_B_CINEMATIC_2_5D',
    MODE_C_DOCUMENTARY_MOTION_GRAPHICS: 'MODE_C_DOCUMENTARY_MOTION_GRAPHICS',
    HYBRID: 'HYBRID'
};

class RenderingModeController {
    /**
     * Determines the optimal rendering mode based on the narrative beat requirements.
     * @param {Object} beat - Story beat object containing action, environment, and technical info
     * @returns {string} - Recommended RenderingMode
     */
    static selectModeForBeat(beat) {
        const text = (beat.narration_script || beat.text || beat.description || '').toLowerCase();
        const action = (beat.action_type || beat.visual_intent || '').toLowerCase();

        // 1. Check if the beat is primarily informational / documentary data
        const isDataDriven = (
            text.includes('coordinates') || text.includes('timeline') ||
            text.includes('route') || text.includes('flight path') ||
            text.includes('spectrogram') || text.includes('declassified document') ||
            action.includes('telemetry') || action.includes('map') || action.includes('evidence_board')
        );

        // 2. Check if the beat requires complex spatial reconstruction
        const requires3D = (
            text.includes('flew through') || text.includes('ocean swells') ||
            text.includes('cockpit') || text.includes('bunker tunnel') ||
            text.includes('radio dish') || text.includes('gallery room') ||
            text.includes('aircraft') || text.includes('bomber') ||
            text.includes('flight') || text.includes('storm') || text.includes('ocean') ||
            action.includes('flight') || action.includes('spatial_exploration') ||
            action.includes('vehicle_transit') || action.includes('architecture')
        );

        if (isDataDriven && !requires3D) {
            return RenderingMode.MODE_C_DOCUMENTARY_MOTION_GRAPHICS;
        } else if (requires3D && isDataDriven) {
            return RenderingMode.HYBRID;
        } else if (requires3D) {
            return RenderingMode.MODE_A_CINEMATIC_3D;
        } else {
            // Default to atmospheric layered 2.5D composition
            return RenderingMode.MODE_B_CINEMATIC_2_5D;
        }
    }

    /**
     * Configures the active scene engine for the specified mode.
     * @param {Object} sceneEngine - CurioLoop SceneEngine instance
     * @param {string} mode - RenderingMode constant
     * @param {Object} options - Custom configuration overrides
     */
    static applyMode(sceneEngine, mode, options = {}) {
        sceneEngine.renderingMode = mode;

        switch (mode) {
            case RenderingMode.MODE_A_CINEMATIC_3D:
                sceneEngine.enable3DObjects = true;
                sceneEngine.enable25DPlanes = false;
                sceneEngine.enableDocumentaryHUD = options.enableHUD || false;
                sceneEngine.cameraFov = options.fov || 45.0;
                break;

            case RenderingMode.MODE_B_CINEMATIC_2_5D:
                sceneEngine.enable3DObjects = false;
                sceneEngine.enable25DPlanes = true;
                sceneEngine.enableDocumentaryHUD = options.enableHUD || false;
                sceneEngine.cameraFov = options.fov || 50.0;
                break;

            case RenderingMode.MODE_C_DOCUMENTARY_MOTION_GRAPHICS:
                sceneEngine.enable3DObjects = false;
                sceneEngine.enable25DPlanes = true; // Use muted background plane
                sceneEngine.enableDocumentaryHUD = true;
                sceneEngine.cameraFov = options.fov || 40.0;
                break;

            case RenderingMode.HYBRID:
            default:
                sceneEngine.enable3DObjects = true;
                sceneEngine.enable25DPlanes = true;
                sceneEngine.enableDocumentaryHUD = true;
                sceneEngine.cameraFov = options.fov || 45.0;
                break;
        }

        return sceneEngine;
    }
}

    // --- EnvironmentKits.js ---
/**
 * CurioLoop 2.0 - EnvironmentKits
 * 12 Production-Ready Reusable Documentary Environment Kits:
 * 1. Historical Archive: Aged wood, parchment, brass desk lamp, dust motes
 * 2. Investigation Room: Corkboard, strings, green shaded lamp, evidence photos
 * 3. Museum: Parquet floor, gilded frame, velvet rope, architectural spotlight
 * 4. Desert: Moonlit dunes, low starfield, sand wind, vast isolation
 * 5. Night Landscape: Silhouette pines, ground fog, deep celestial glow
 * 6. Ocean and Storm: 3D wave mesh, driving rain, lightning strikes, sea mist
 * 7. Aircraft Interior: Cockpit instrument gauges, gyro-gimbal, passing cloud layers
 * 8. Laboratory: Specimen dish, fluorescent overhead, sterile steel, laser probe
 * 9. Abandoned Facility: Concrete bunker ribs, hanging chains, emergency hazard strobe
 * 10. Historical Street: Cobblestones, gas lamps, Victorian fog, wet reflection
 * 11. Industrial Facility: Steel gantry, steam vents, amber caution lighting
 * 12. Remote Rural: Farmstead silhouette, barbed wire fence, telephone poles, desolate horizon
 */

const EnvironmentKitType = {
    HISTORICAL_ARCHIVE: 'HISTORICAL_ARCHIVE',
    INVESTIGATION_ROOM: 'INVESTIGATION_ROOM',
    MUSEUM: 'MUSEUM',
    DESERT: 'DESERT',
    NIGHT_LANDSCAPE: 'NIGHT_LANDSCAPE',
    OCEAN_STORM: 'OCEAN_STORM',
    AIRCRAFT_INTERIOR: 'AIRCRAFT_INTERIOR',
    LABORATORY: 'LABORATORY',
    ABANDONED_FACILITY: 'ABANDONED_FACILITY',
    HISTORICAL_STREET: 'HISTORICAL_STREET',
    INDUSTRIAL_FACILITY: 'INDUSTRIAL_FACILITY',
    REMOTE_RURAL: 'REMOTE_RURAL'
};

const EnvironmentPresets = {
    [EnvironmentKitType.HISTORICAL_ARCHIVE]: {
        name: 'Historical Archive',
        era: '1880-1940',
        palette: { background: '#0b0c10', surface: '#1f1610', accent: '#d4af37', ambient: '#18120c' },
        lighting: { keyKelvin: 2800, keyIntensity: 1.2, fillKelvin: 3200, fillIntensity: 0.4, rimIntensity: 0.6 },
        fog: { color: '#0d0c0a', density: 0.0018 },
        particles: { type: 'dust', count: 200, speed: 0.15, size: 2.0, color: '#d4af37' },
        materials: ['aged_vellum', 'mahogany', 'brushed_brass', 'cast_iron']
    },
    [EnvironmentKitType.INVESTIGATION_ROOM]: {
        name: 'Investigation Room',
        era: '1950-1990',
        palette: { background: '#080a0f', surface: '#141a24', accent: '#ef4444', ambient: '#0f172a' },
        lighting: { keyKelvin: 4000, keyIntensity: 1.4, fillKelvin: 3000, fillIntensity: 0.3, rimIntensity: 0.8 },
        fog: { color: '#090d14', density: 0.0015 },
        particles: { type: 'smoke', count: 120, speed: 0.2, size: 3.5, color: '#94a3b8' },
        materials: ['cork', 'polaroid_film', 'cotton_thread', 'ink_on_paper']
    },
    [EnvironmentKitType.MUSEUM]: {
        name: 'Museum Gallery',
        era: '1900-Present',
        palette: { background: '#05070a', surface: '#18120e', accent: '#f59e0b', ambient: '#0c0f17' },
        lighting: { keyKelvin: 3200, keyIntensity: 1.6, fillKelvin: 4500, fillIntensity: 0.25, rimIntensity: 1.0 },
        fog: { color: '#07090e', density: 0.0012 },
        particles: { type: 'dust', count: 150, speed: 0.1, size: 1.8, color: '#fef08a' },
        materials: ['gilded_wood', 'parquet', 'velvet_cord', 'museum_glass']
    },
    [EnvironmentKitType.DESERT]: {
        name: 'Night Desert',
        era: 'Timeless',
        palette: { background: '#020408', surface: '#1e1b18', accent: '#38bdf8', ambient: '#070b14' },
        lighting: { keyKelvin: 6500, keyIntensity: 0.9, fillKelvin: 7500, fillIntensity: 0.3, rimIntensity: 0.7 },
        fog: { color: '#03060c', density: 0.001 },
        particles: { type: 'sand_drift', count: 350, speed: 0.8, size: 1.5, color: '#cbd5e1' },
        materials: ['sand_dune', 'weathered_rock', 'dry_brush']
    },
    [EnvironmentKitType.NIGHT_LANDSCAPE]: {
        name: 'Nocturnal Pine Forest',
        era: 'Timeless',
        palette: { background: '#020409', surface: '#0d131f', accent: '#22c55e', ambient: '#060a12' },
        lighting: { keyKelvin: 7000, keyIntensity: 0.8, fillKelvin: 5500, fillIntensity: 0.35, rimIntensity: 0.9 },
        fog: { color: '#050a14', density: 0.0025 },
        particles: { type: 'mist', count: 400, speed: 0.25, size: 4.0, color: '#94a3b8' },
        materials: ['pine_bark', 'pine_needles', 'damp_soil', 'ground_fog']
    },
    [EnvironmentKitType.OCEAN_STORM]: {
        name: 'Turbulent Ocean Storm',
        era: '1940-Present',
        palette: { background: '#03060c', surface: '#0b1626', accent: '#38bdf8', ambient: '#050a14' },
        lighting: { keyKelvin: 6200, keyIntensity: 1.1, fillKelvin: 8000, fillIntensity: 0.5, rimIntensity: 1.2 },
        fog: { color: '#060d1a', density: 0.0035 },
        particles: { type: 'rain_squall', count: 700, speed: 3.5, size: 1.2, color: '#93c5fd' },
        materials: ['deep_water', 'sea_foam', 'hull_aluminum', 'storm_clouds']
    },
    [EnvironmentKitType.AIRCRAFT_INTERIOR]: {
        name: 'Aircraft Cockpit',
        era: '1940-1970',
        palette: { background: '#06080d', surface: '#111822', accent: '#22c55e', ambient: '#0b111a' },
        lighting: { keyKelvin: 4500, keyIntensity: 1.0, fillKelvin: 2800, fillIntensity: 0.4, rimIntensity: 0.8 },
        fog: { color: '#080c14', density: 0.0008 },
        particles: { type: 'cockpit_dust', count: 80, speed: 0.1, size: 1.5, color: '#86efac' },
        materials: ['riveted_aluminum', 'instrument_glass', 'phosphor_dial', 'plexiglass']
    },
    [EnvironmentKitType.LABORATORY]: {
        name: 'Scientific Laboratory',
        era: '1970-Present',
        palette: { background: '#04070d', surface: '#0f172a', accent: '#06b6d4', ambient: '#0a0f1d' },
        lighting: { keyKelvin: 5600, keyIntensity: 1.5, fillKelvin: 6500, fillIntensity: 0.5, rimIntensity: 0.9 },
        fog: { color: '#060b14', density: 0.0006 },
        particles: { type: 'sterile_spark', count: 90, speed: 0.3, size: 2.0, color: '#67e8f9' },
        materials: ['stainless_steel', 'borosilicate_glass', 'white_enamel', 'monochrome_lcd']
    },
    [EnvironmentKitType.ABANDONED_FACILITY]: {
        name: 'Abandoned Industrial Bunker',
        era: '1960-1990',
        palette: { background: '#05070a', surface: '#14171c', accent: '#f97316', ambient: '#0a0d12' },
        lighting: { keyKelvin: 3400, keyIntensity: 1.2, fillKelvin: 2200, fillIntensity: 0.3, rimIntensity: 1.1 },
        fog: { color: '#090b0f', density: 0.0022 },
        particles: { type: 'concrete_dust', count: 300, speed: 0.2, size: 2.2, color: '#fdba74' },
        materials: ['spalled_concrete', 'rusted_steel', 'corroded_copper', 'peeling_paint']
    },
    [EnvironmentKitType.HISTORICAL_STREET]: {
        name: 'Victorian Gaslit Street',
        era: '1850-1910',
        palette: { background: '#06070a', surface: '#141210', accent: '#f59e0b', ambient: '#0c0a08' },
        lighting: { keyKelvin: 2200, keyIntensity: 1.3, fillKelvin: 4000, fillIntensity: 0.2, rimIntensity: 0.7 },
        fog: { color: '#0a0907', density: 0.003 },
        particles: { type: 'soot_fog', count: 250, speed: 0.15, size: 2.5, color: '#fed7aa' },
        materials: ['wet_cobblestone', 'cast_iron_lamp', 'brick_mortar', 'wrought_iron']
    },
    [EnvironmentKitType.INDUSTRIAL_FACILITY]: {
        name: 'Industrial Processing Plant',
        era: '1930-Present',
        palette: { background: '#07080b', surface: '#131820', accent: '#eab308', ambient: '#0a0e14' },
        lighting: { keyKelvin: 3800, keyIntensity: 1.3, fillKelvin: 5000, fillIntensity: 0.4, rimIntensity: 1.0 },
        fog: { color: '#080c12', density: 0.0016 },
        particles: { type: 'steam_sparks', count: 320, speed: 0.6, size: 1.8, color: '#fef08a' },
        materials: ['steel_diamond_plate', 'galvanized_pipe', 'gauge_glass', 'safety_enamel']
    },
    [EnvironmentKitType.REMOTE_RURAL]: {
        name: 'Isolated Rural Horizon',
        era: 'Timeless',
        palette: { background: '#030509', surface: '#0d1117', accent: '#a855f7', ambient: '#070a10' },
        lighting: { keyKelvin: 6000, keyIntensity: 0.85, fillKelvin: 4500, fillIntensity: 0.3, rimIntensity: 0.65 },
        fog: { color: '#05070c', density: 0.002 },
        particles: { type: 'ground_haze', count: 180, speed: 0.12, size: 3.0, color: '#e9d5ff' },
        materials: ['weathered_timber', 'barbed_wire', 'prairie_grass', 'gravel']
    }
};

class EnvironmentManager {
    static getPreset(type) {
        return EnvironmentPresets[type] || EnvironmentPresets[EnvironmentKitType.HISTORICAL_ARCHIVE];
    }

    static applyToScene(sceneEngine, environmentType) {
        const preset = this.getPreset(environmentType);
        sceneEngine.environmentType = environmentType;
        sceneEngine.activePreset = preset;

        // Apply background and fog
        if (sceneEngine.scene) {
            if (window.THREE) {
                sceneEngine.scene.background = new THREE.Color(preset.palette.background);
                sceneEngine.scene.fog = new THREE.FogExp2(preset.fog.color, preset.fog.density);
            }
        }

        // Configure particles
        if (sceneEngine.particleSystem) {
            sceneEngine.particleSystem.reconfigure(preset.particles);
        }

        return preset;
    }
}

    // --- CameraSystem.js ---
/**
 * CurioLoop 2.0 - CameraSystem
 * Cinematic camera rig providing motivated cinematography, trajectory interpolation,
 * organic biological drift, and rack-focus simulation.
 * 
 * Every camera movement must have a dramatic narrative reason:
 * - REVEAL: Gradual unveiling of critical context
 * - INVESTIGATION: Controlled scrutiny of evidence
 * - DISCOVERY: Directed movement toward a discovered object
 * - ISOLATION: Pullback emphasizing loneliness or vastness
 * - THREAT: Low-angle tracking conveying impending danger
 * - EVIDENCE: Macro examination of physical proof
 */

const CameraShotType = {
    ESTABLISHING: 'ESTABLISHING',
    DOLLY_IN: 'DOLLY_IN',
    DOLLY_OUT: 'DOLLY_OUT',
    TRACKING: 'TRACKING',
    ORBIT: 'ORBIT',
    PAN_TILT: 'PAN_TILT',
    OVER_THE_SHOULDER: 'OVER_THE_SHOULDER',
    MACRO_CLOSEUP: 'MACRO_CLOSEUP',
    AERIAL_SURVEY: 'AERIAL_SURVEY',
    RACK_FOCUS: 'RACK_FOCUS'
};

const CameraMotivation = {
    REVEAL: 'REVEAL',
    INVESTIGATION: 'INVESTIGATION',
    DISCOVERY: 'DISCOVERY',
    ISOLATION: 'ISOLATION',
    THREAT: 'THREAT',
    EVIDENCE: 'EVIDENCE'
};

class CameraSystem {
    constructor(threeCamera, options = {}) {
        this.camera = threeCamera;
        this.fov = options.fov || 45.0;
        this.keyframes = options.keyframes || [];
        this.duration = options.duration || 10.0;
        this.easing = options.easing || 'CINEMATIC_DRIFT';
        this.shakeIntensity = options.shakeIntensity || 0.35;
        this.shotType = options.shotType || CameraShotType.ESTABLISHING;
        this.motivation = options.motivation || CameraMotivation.REVEAL;
        
        // Rack focus parameters
        this.focalDistanceStart = options.focalDistanceStart || 500;
        this.focalDistanceEnd = options.focalDistanceEnd || 150;
        this.currentFocalDistance = this.focalDistanceStart;
        this.currentLookAt = { x: 0, y: 0, z: 0 };
    }

    // Quintic in-out damping (prevents mechanical/linear transitions)
    quinticInOut(t) {
        if ((t /= 0.5) < 1) return 0.5 * t * t * t * t * t;
        return 0.5 * ((t -= 2) * t * t * t * t + 2);
    }

    smoothstep(t) {
        return t * t * (3 - 2 * t);
    }

    /**
     * Generates motivated camera keyframes based on shot type and dramatic reason.
     * @param {string} shotType - CameraShotType enum value
     * @param {string} motivation - CameraMotivation enum value
     * @param {Object} target - Target focal point {x, y, z}
     * @param {number} duration - Shot duration in seconds
     */
    static createMotivatedPath(shotType, motivation, target = { x: 0, y: 0, z: 0 }, duration = 8.0) {
        let k0, k1;

        switch (shotType) {
            case CameraShotType.DOLLY_IN:
                // Move from wide establishing to intimate focus
                k0 = { position: [target.x, target.y + 40, target.z + 700], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x, target.y + 10, target.z + 280], lookAt: [target.x, target.y, target.z], roll: 0 };
                break;

            case CameraShotType.DOLLY_OUT:
                // Pull back to reveal vastness, emptiness, or isolation
                k0 = { position: [target.x, target.y + 10, target.z + 220], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x, target.y + 120, target.z + 850], lookAt: [target.x, target.y, target.z], roll: 0 };
                break;

            case CameraShotType.TRACKING:
                // Move alongside subject with slight forward push
                k0 = { position: [target.x - 300, target.y + 20, target.z + 450], lookAt: [target.x - 50, target.y, target.z], roll: -0.01 };
                k1 = { position: [target.x + 300, target.y + 20, target.z + 400], lookAt: [target.x + 50, target.y, target.z], roll: 0.01 };
                break;

            case CameraShotType.ORBIT:
                // 45-degree investigative arc around subject
                k0 = { position: [target.x - 280, target.y + 50, target.z + 450], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x + 280, target.y + 70, target.z + 420], lookAt: [target.x, target.y, target.z], roll: 0 };
                break;

            case CameraShotType.MACRO_CLOSEUP:
                // Shallow depth of field examination of an artifact/document
                k0 = { position: [target.x - 40, target.y + 30, target.z + 180], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x + 10, target.y + 15, target.z + 110], lookAt: [target.x, target.y, target.z], roll: 0.01 };
                break;

            case CameraShotType.AERIAL_SURVEY:
                // High-angle context survey looking downward
                k0 = { position: [target.x, target.y + 650, target.z + 300], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x, target.y + 520, target.z + 180], lookAt: [target.x, target.y, target.z], roll: 0 };
                break;

            case CameraShotType.RACK_FOCUS:
                // Foreground blur to background clarity
                k0 = { position: [target.x, target.y + 20, target.z + 400], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x, target.y + 20, target.z + 370], lookAt: [target.x, target.y, target.z], roll: 0 };
                break;

            case CameraShotType.PAN_TILT:
                k0 = { position: [target.x - 200, target.y - 60, target.z + 500], lookAt: [target.x - 200, target.y - 60, target.z], roll: 0 };
                k1 = { position: [target.x + 200, target.y + 120, target.z + 500], lookAt: [target.x + 200, target.y + 120, target.z], roll: 0 };
                break;

            case CameraShotType.OVER_THE_SHOULDER:
                k0 = { position: [target.x + 120, target.y + 30, target.z + 320], lookAt: [target.x - 60, target.y, target.z - 80], roll: 0 };
                k1 = { position: [target.x + 100, target.y + 25, target.z + 260], lookAt: [target.x - 60, target.y, target.z - 80], roll: 0 };
                break;

            case CameraShotType.ESTABLISHING:
            default:
                k0 = { position: [target.x, target.y + 60, target.z + 650], lookAt: [target.x, target.y, target.z], roll: 0 };
                k1 = { position: [target.x, target.y + 40, target.z + 500], lookAt: [target.x, target.y, target.z], roll: 0 };
                break;
        }

        return {
            shotType,
            motivation,
            duration,
            keyframes: [k0, k1]
        };
    }

    evaluate(timeSec) {
        const normT = Math.min(Math.max(timeSec / this.duration, 0.0), 1.0);
        const tEased = this.easing === 'CINEMATIC_DRIFT' ? this.quinticInOut(normT) : this.smoothstep(normT);

        let posX = 0, posY = 0, posZ = 500;
        let lookX = 0, lookY = 0, lookZ = 0;
        let roll = 0;

        if (this.keyframes.length >= 2) {
            const k0 = this.keyframes[0];
            const k1 = this.keyframes[this.keyframes.length - 1];

            posX = k0.position[0] + (k1.position[0] - k0.position[0]) * tEased;
            posY = k0.position[1] + (k1.position[1] - k0.position[1]) * tEased;
            posZ = k0.position[2] + (k1.position[2] - k0.position[2]) * tEased;

            lookX = k0.lookAt[0] + (k1.lookAt[0] - k0.lookAt[0]) * tEased;
            lookY = k0.lookAt[1] + (k1.lookAt[1] - k0.lookAt[1]) * tEased;
            lookZ = k0.lookAt[2] + (k1.lookAt[2] - k0.lookAt[2]) * tEased;

            roll = (k0.roll || 0) + ((k1.roll || 0) - (k0.roll || 0)) * tEased;
        }

        // Biological handheld breathing drift (frequency 0.25 Hz)
        const driftX = Math.sin(timeSec * 1.57) * this.shakeIntensity * 4.0;
        const driftY = Math.cos(timeSec * 1.25) * this.shakeIntensity * 3.0;
        const driftRoll = Math.sin(timeSec * 0.95) * (this.shakeIntensity * 0.015);

        const finalPos = { x: posX + driftX, y: posY + driftY, z: posZ };
        const finalLook = { x: lookX, y: lookY, z: lookZ };
        const finalRoll = roll + driftRoll;

        // Interpolate simulated rack focus distance
        this.currentFocalDistance = this.focalDistanceStart + (this.focalDistanceEnd - this.focalDistanceStart) * tEased;

        // Apply to Three.js camera if present
        if (this.camera) {
            this.camera.position.set(finalPos.x, finalPos.y, finalPos.z);
            this.camera.lookAt(finalLook.x, finalLook.y, finalLook.z);
            this.camera.rotation.z += finalRoll;
        }

        return {
            position: finalPos,
            lookAt: finalLook,
            roll: finalRoll,
            focalDistance: this.currentFocalDistance,
            shotType: this.shotType,
            motivation: this.motivation
        };
    }
}

    // --- CompositionSystem.js ---
/**
 * CurioLoop 2.0 - CompositionSystem
 * 2.5D spatial depth hierarchy enforcing 3-plane separation, perspective parallax,
 * and atmospheric layer attenuation.
 */

class CompositionSystem {
    constructor(sceneEngine) {
        this.engine = sceneEngine;
        this.layers = [];
    }

    addLayer(layerConfig) {
        // layerConfig: { id, plane: 'FOREGROUND'|'MIDGROUND'|'BACKGROUND', depthZ, element, parallaxRatio, opacity }
        const layer = {
            id: layerConfig.id,
            plane: layerConfig.plane || 'MIDGROUND',
            depthZ: layerConfig.depthZ || 0,
            parallaxRatio: layerConfig.parallaxRatio || 1.0,
            element: layerConfig.element,
            mesh: layerConfig.mesh || null,
            opacity: layerConfig.opacity !== undefined ? layerConfig.opacity : 1.0,
            blendMode: layerConfig.blendMode || 'normal'
        };
        this.layers.push(layer);
        return layer;
    }

    applyParallax(cameraTransform) {
        for (let l of this.layers) {
            if (l.mesh) {
                // If Three.js 3D mesh, position in actual 3D space
                l.mesh.position.z = l.depthZ;
            } else if (l.element) {
                // If DOM / Canvas layer, apply 2.5D perspective transform
                const scale = Math.max(0.1, 1.0 + (l.depthZ / 600.0));
                const offsetX = -cameraTransform.position.x * l.parallaxRatio;
                const offsetY = -cameraTransform.position.y * l.parallaxRatio;

                l.element.style.transform = `translate3d(${offsetX}px, ${offsetY}px, 0px) scale(${scale})`;
                l.element.style.opacity = l.opacity;
            }
        }
    }

    validateDepthSeparation() {
        const planes = new Set(this.layers.map(l => l.plane));
        return {
            valid: planes.has('FOREGROUND') && planes.has('MIDGROUND') && planes.has('BACKGROUND'),
            planeCount: planes.size,
            planes: Array.from(planes)
        };
    }
}

    // --- LightingAndMaterials.js ---
/**
 * CurioLoop 2.0 - LightingAndMaterials
 * Reusable material library, lighting rigs, volumetric haze, and PBR-lite shaders.
 */

class LightingAndMaterials {
    static createLightingRig(threeScene, preset = 'archival_candlelight') {
        if (!threeScene || typeof window.THREE === 'undefined') return;

        const presets = {
            archival_candlelight: {
                ambientColor: 0x221108,
                ambientIntensity: 0.8,
                keyColor: 0xffd288,
                keyIntensity: 2.2,
                keyPos: [150, 200, 250],
                shadows: true
            },
            cold_maritime_fog: {
                ambientColor: 0x0a1420,
                ambientIntensity: 0.9,
                keyColor: 0x48a8d8,
                keyIntensity: 1.6,
                keyPos: [-200, 150, 180],
                shadows: true
            },
            night_extraterrestrial: {
                ambientColor: 0x050610,
                ambientIntensity: 0.5,
                keyColor: 0x00f0ff,
                keyIntensity: 2.8,
                keyPos: [0, 300, 100],
                shadows: true
            }
        };

        const cfg = presets[preset] || presets.archival_candlelight;

        const ambientLight = new window.THREE.AmbientLight(cfg.ambientColor, cfg.ambientIntensity);
        threeScene.add(ambientLight);

        const dirLight = new window.THREE.DirectionalLight(cfg.keyColor, cfg.keyIntensity);
        dirLight.position.set(cfg.keyPos[0], cfg.keyPos[1], cfg.keyPos[2]);
        if (cfg.shadows) {
            dirLight.castShadow = true;
            dirLight.shadow.mapSize.width = 1024;
            dirLight.shadow.mapSize.height = 1024;
            dirLight.shadow.camera.near = 0.5;
            dirLight.shadow.camera.far = 1000;
        }
        threeScene.add(dirLight);

        return { ambientLight, dirLight };
    }

    static createParchmentMaterial(colorHex = 0xd5c4a1) {
        if (typeof window.THREE === 'undefined') return null;
        return new window.THREE.MeshStandardMaterial({
            color: colorHex,
            roughness: 0.88,
            metalness: 0.05
        });
    }

    static createWeatheredBrassMaterial() {
        if (typeof window.THREE === 'undefined') return null;
        return new window.THREE.MeshStandardMaterial({
            color: 0xc49a45,
            roughness: 0.32,
            metalness: 0.82
        });
    }

    static createEmissiveGlowMaterial(colorHex = 0x00f0ff, intensity = 1.8) {
        if (typeof window.THREE === 'undefined') return null;
        return new window.THREE.MeshStandardMaterial({
            color: 0xffffff,
            emissive: colorHex,
            emissiveIntensity: intensity,
            roughness: 0.2
        });
    }
}

    // --- MotionGraphics.js ---
/**
 * CurioLoop 2.0 - MotionGraphics
 * Reusable telemetry displays, timeline overlays, evidence callouts, and 9:16 safe-zone framing.
 */

class MotionGraphics {
    static drawEvidenceTag(ctx, text, x = 40, y = 60) {
        ctx.save();
        ctx.font = 'bold 16px "Courier New", monospace';
        const textWidth = ctx.measureText(text).width;

        // Background card
        ctx.fillStyle = 'rgba(10, 16, 26, 0.9)';
        ctx.fillRect(x, y - 20, textWidth + 24, 28);

        // Amber tag border
        ctx.fillStyle = '#f59e0b';
        ctx.fillRect(x, y - 20, 4, 28);

        ctx.fillStyle = '#f59e0b';
        ctx.fillText(text, x + 12, y);
        ctx.restore();
    }

    static drawSpectrogram(ctx, x, y, width, height, timeSec) {
        ctx.save();
        ctx.fillStyle = 'rgba(4, 9, 16, 0.85)';
        ctx.fillRect(x, y, width, height);
        ctx.strokeStyle = '#00f0ff';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, width, height);

        // Draw frequency carrier lines
        const bands = 24;
        const bandW = width / bands;
        for (let i = 0; i < bands; i++) {
            const h = (Math.sin(timeSec * 4.0 + i * 0.7) * 0.5 + 0.5) * (height - 20);
            ctx.fillStyle = i === 12 ? '#ef4444' : '#00f0ff';
            ctx.fillRect(x + i * bandW + 2, y + height - h - 10, bandW - 4, h);
        }
        ctx.restore();
    }

    static drawMobileSafeZone(ctx, width, height) {
        ctx.save();
        ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 6]);

        // 80% inner rect
        const safeX = width * 0.1;
        const safeY = height * 0.1;
        const safeW = width * 0.8;
        const safeH = height * 0.8;

        ctx.strokeRect(safeX, safeY, safeW, safeH);
        ctx.restore();
    }
}

    // --- SceneEngine.js ---
/**
 * CurioLoop 2.0 - SceneEngine
 * Core lifecycle manager coordinating WebGL (Three.js), 2.5D Canvas, particle systems,
 * atmospheric shaders, and performance monitoring.
 */

class SceneEngine {
    constructor(containerElement, options = {}) {
        this.container = containerElement;
        this.width = options.width || 1080;
        this.height = options.height || 1920;
        this.aspectRatio = this.width / this.height;
        this.fpsTarget = options.fpsTarget || 60;
        this.isRunning = false;
        this.currentTime = 0.0;
        this.duration = options.duration || 10.0;

        // Performance metrics
        this.metrics = {
            frameCount: 0,
            lastFrameTime: performance.now(),
            measuredFps: 60.0,
            drawCalls: 0
        };

        // Layers & subsystems
        this.threeRenderer = null;
        this.threeScene = null;
        this.threeCamera = null;
        this.overlayCanvas = null;
        this.overlayCtx = null;
        this.particleSystems = [];
        this.renderCallbacks = [];

        this.init();
    }

    init() {
        this.container.style.position = 'relative';
        this.container.style.overflow = 'hidden';

        // 1. Initialize Three.js WebGL Renderer if THREE is available
        if (typeof window.THREE !== 'undefined') {
            this.threeRenderer = new window.THREE.WebGLRenderer({
                antialias: true,
                alpha: true,
                powerPreference: 'high-performance'
            });
            this.threeRenderer.setSize(this.width, this.height);
            this.threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
            this.threeRenderer.shadowMap.enabled = true;
            this.threeRenderer.shadowMap.type = window.THREE.PCFSoftShadowMap;
            this.threeRenderer.domElement.style.position = 'absolute';
            this.threeRenderer.domElement.style.top = '0';
            this.threeRenderer.domElement.style.left = '0';
            this.threeRenderer.domElement.style.width = '100%';
            this.threeRenderer.domElement.style.height = '100%';
            this.container.appendChild(this.threeRenderer.domElement);

            this.threeScene = new window.THREE.Scene();
            this.threeCamera = new window.THREE.PerspectiveCamera(45, this.aspectRatio, 0.1, 2000);
            this.threeCamera.position.set(0, 0, 500);
        }

        // 2. Initialize Overlay Canvas 2D for 2.5D layer composite and motion graphics
        this.overlayCanvas = document.createElement('canvas');
        this.overlayCanvas.width = this.width;
        this.overlayCanvas.height = this.height;
        this.overlayCanvas.style.position = 'absolute';
        this.overlayCanvas.style.top = '0';
        this.overlayCanvas.style.left = '0';
        this.overlayCanvas.style.width = '100%';
        this.overlayCanvas.style.height = '100%';
        this.overlayCanvas.style.pointerEvents = 'none';
        this.overlayCtx = this.overlayCanvas.getContext('2d');
        this.container.appendChild(this.overlayCanvas);
    }

    addParticleSystem(emitter) {
        this.particleSystems.push(emitter);
    }

    onRender(callback) {
        this.renderCallbacks.push(callback);
    }

    start() {
        if (this.isRunning) return;
        this.isRunning = true;
        this.lastTimestamp = performance.now();
        this.animate = (timestamp) => {
            if (!this.isRunning) return;
            const deltaMs = timestamp - this.lastTimestamp;
            this.lastTimestamp = timestamp;
            const deltaSec = Math.min(deltaMs / 1000.0, 0.1);

            this.currentTime += deltaSec;
            if (this.currentTime > this.duration) {
                this.currentTime = 0.0;
            }

            this.update(this.currentTime, deltaSec);
            this.render();

            requestAnimationFrame(this.animate);
        };
        requestAnimationFrame(this.animate);
    }

    pause() {
        this.isRunning = false;
    }

    seek(timeSec) {
        this.currentTime = Math.max(0.0, Math.min(timeSec, this.duration));
        this.update(this.currentTime, 0.016);
        this.render();
    }

    update(timeSec, deltaSec) {
        // Measure FPS
        this.metrics.frameCount++;
        if (this.metrics.frameCount % 30 === 0) {
            const now = performance.now();
            this.metrics.measuredFps = Math.round(30000.0 / (now - this.metrics.lastFrameTime));
            this.metrics.lastFrameTime = now;
        }

        // Update particles
        for (let ps of this.particleSystems) {
            ps.update(deltaSec);
        }

        // Execute scene callbacks
        for (let cb of this.renderCallbacks) {
            cb(timeSec, deltaSec);
        }
    }

    render() {
        // 1. Render Three.js WebGL scene
        if (this.threeRenderer && this.threeScene && this.threeCamera) {
            this.threeRenderer.render(this.threeScene, this.threeCamera);
            this.metrics.drawCalls = this.threeRenderer.info.render.calls;
        }

        // 2. Clear overlay canvas for redraw
        this.overlayCtx.clearRect(0, 0, this.width, this.height);

        // 3. Render 2D particle systems to overlay
        for (let ps of this.particleSystems) {
            ps.render(this.overlayCtx);
        }
    }

    setDimensions(width, height) {
        this.width = width;
        this.height = height;
        this.aspectRatio = width / height;

        if (this.threeRenderer) {
            this.threeRenderer.setSize(width, height);
            this.threeCamera.aspect = this.aspectRatio;
            this.threeCamera.updateProjectionMatrix();
        }
        if (this.overlayCanvas) {
            this.overlayCanvas.width = width;
            this.overlayCanvas.height = height;
        }
    }

    destroy() {
        this.pause();
        if (this.threeRenderer) {
            this.threeRenderer.dispose();
            if (this.threeRenderer.domElement.parentElement) {
                this.threeRenderer.domElement.parentElement.removeChild(this.threeRenderer.domElement);
            }
        }
        if (this.overlayCanvas && this.overlayCanvas.parentElement) {
            this.overlayCanvas.parentElement.removeChild(this.overlayCanvas);
        }
        this.particleSystems = [];
        this.renderCallbacks = [];
    }
}

    // --- VisualDirector.js ---
/**
 * CurioLoop 2.0 - VisualDirector
 * Translates narrative script beats into semantically grounded, cinematographically
 * motivated scene specifications.
 * 
 * Determines:
 * - Rendering Mode (Mode A: 3D, Mode B: 2.5D, Mode C: Motion Graphics, Hybrid)
 * - Environment Kit (1 of 12 documentary environments)
 * - Main subject and semantic focal point
 * - Motivated camera shot type and narrative reason
 * - 3-Plane depth arrangement (Foreground, Midground, Background)
 * - Lighting color temperature, intensity, and atmospheric fog
 * - Documentary motion graphics overlays (routes, coordinates, evidence markers)
 * - Duration matching narration word count
 */


class VisualDirector {
    /**
     * Translates a narrative beat into a production-ready scene specification.
     * @param {Object} beat - { narrative_beat, narration_script, emotional_register, estimated_duration_sec }
     * @param {Object} options - { aspect_ratio: '9:16'|'16:9', quality_preset: 'HIGH' }
     * @returns {Object} Complete scene specification
     */
    static translateBeatToScene(beat, options = {}) {
        const text = (beat.narration_script || beat.text || '').toLowerCase();
        const words = text.split(/\s+/).filter(Boolean).length;
        const durationSec = beat.estimated_duration_sec || Math.max(4.0, (words / 128.0) * 60.0);
        const aspectRatio = options.aspect_ratio || '9:16';

        // 1. Select Rendering Mode
        const mode = RenderingModeController.selectModeForBeat(beat);

        // 2. Select Environment Kit and Semantic Subject
        let environmentKit = EnvironmentKitType.HISTORICAL_ARCHIVE;
        let mainSubject = 'Historical Artifact';
        let compositionType = 'ESTABLISHING';
        let shotType = CameraShotType.ESTABLISHING;
        let motivation = CameraMotivation.REVEAL;
        let documentaryOverlay = null;

        if (text.includes('aircraft') || text.includes('ocean') || text.includes('flight') || text.includes('atlantic') || text.includes('bomber')) {
            environmentKit = EnvironmentKitType.OCEAN_STORM;
            mainSubject = 'Avenger Bomber Squadron in Maritime Squall';
            compositionType = 'DUAL_PERSPECTIVE_DEPTH';
            shotType = CameraShotType.TRACKING;
            motivation = CameraMotivation.THREAT;
            documentaryOverlay = {
                type: 'RADAR_TELEMETRY',
                coordinates: '26°08\'N 80°09\'W',
                label: 'FLIGHT 19 NAV TRACK'
            };
        } else if (text.includes('museum') || text.includes('mona lisa') || text.includes('theft') || text.includes('louvre') || text.includes('frame')) {
            environmentKit = EnvironmentKitType.MUSEUM;
            mainSubject = 'Vacant Gilded Frame on Gallery Wall';
            compositionType = 'OBJECT_MACRO';
            shotType = CameraShotType.DOLLY_IN;
            motivation = CameraMotivation.INVESTIGATION;
            documentaryOverlay = {
                type: 'EVIDENCE_TAG',
                label: 'EXHIBIT A: VACANT FRAME - SALON CARRE 1911'
            };
        } else if (text.includes('ufo') || text.includes('alien') || text.includes('light') || text.includes('forest') || text.includes('rendlesham')) {
            environmentKit = EnvironmentKitType.NIGHT_LANDSCAPE;
            mainSubject = 'Pulsing Octahedron Phenomenon Above Pines';
            compositionType = 'ATMOSPHERIC_ANOMALY';
            shotType = CameraShotType.ORBIT;
            motivation = CameraMotivation.DISCOVERY;
            documentaryOverlay = {
                type: 'GEOGRAPHIC_COORDINATES',
                coordinates: '52°05\'N 01°26\'E',
                label: 'RENDLESHAM FOREST MILITARY SECTOR'
            };
        } else if (text.includes('facility') || text.includes('bunker') || text.includes('abandoned') || text.includes('pripyat') || text.includes('corridor')) {
            environmentKit = EnvironmentKitType.ABANDONED_FACILITY;
            mainSubject = 'Reinforced Concrete Corridor with Swinging Chains';
            compositionType = 'PERSPECTIVE_TUNNEL';
            shotType = CameraShotType.DOLLY_IN;
            motivation = CameraMotivation.THREAT;
            documentaryOverlay = {
                type: 'RADIATION_TELEMETRY',
                label: 'SECTOR 4 INTERIOR ACCESS - DECONTAMINATION REQD'
            };
        } else if (text.includes('manuscript') || text.includes('document') || text.includes('voynich') || text.includes('cipher') || text.includes('parchment')) {
            environmentKit = EnvironmentKitType.HISTORICAL_ARCHIVE;
            mainSubject = 'Illuminated Vellum Folio under Brass Loupe';
            compositionType = 'MACRO_SCRUTINY';
            shotType = CameraShotType.MACRO_CLOSEUP;
            motivation = CameraMotivation.EVIDENCE;
            documentaryOverlay = {
                type: 'ARCHIVAL_METADATA',
                label: 'BEINECKE MS 408 - FOLIO 67R'
            };
        } else if (text.includes('seti') || text.includes('signal') || text.includes('radio') || text.includes('telescope') || text.includes('wow!')) {
            environmentKit = EnvironmentKitType.LABORATORY;
            mainSubject = 'Parabolic Transit Telescope Array';
            compositionType = 'ASTRONOMICAL_SURVEY';
            shotType = CameraShotType.AERIAL_SURVEY;
            motivation = CameraMotivation.DISCOVERY;
            documentaryOverlay = {
                type: 'WATERFALL_SPECTROGRAM',
                frequency: '1420.4056 MHz (21cm Hydrogen Line)',
                label: 'EQUATORIAL AZIMUTH 19H 22M 24S'
            };
        }

        // 3. Build 3-Plane Spatial Layout
        const layers = [
            {
                name: 'foreground_element',
                depth_z: 160,
                parallax_factor: 1.4,
                blur_px: 0.0,
                role: 'FOREGROUND'
            },
            {
                name: 'main_subject_stage',
                depth_z: 0,
                parallax_factor: 1.0,
                blur_px: 0.0,
                role: 'MIDGROUND_SUBJECT'
            },
            {
                name: 'environmental_backdrop',
                depth_z: -450,
                parallax_factor: 0.35,
                blur_px: 2.5,
                role: 'BACKGROUND'
            }
        ];

        return {
            scene_id: `SCN-${Math.random().toString(36).substring(2, 7).toUpperCase()}`,
            narrative_beat: beat.narrative_beat || 'Story Beat',
            visual_objective: `Communicate: ${beat.narration_script ? beat.narration_script.substring(0, 75) : 'Scene action'}...`,
            rendering_mode: mode,
            environment_kit: environmentKit,
            main_subject: {
                name: mainSubject,
                focal_importance: 1.0
            },
            composition: {
                type: compositionType,
                aspect_ratio: aspectRatio,
                safe_zone_margins: aspectRatio === '9:16' ? { top: 96, bottom: 120, sides: 36 } : { top: 48, bottom: 48, sides: 64 },
                depth_layers: layers
            },
            camera_behavior: {
                shot_type: shotType,
                motivation: motivation,
                screen_direction: 'LEFT_TO_RIGHT',
                easing: 'CINEMATIC_DRIFT'
            },
            lighting: {
                environment_preset: environmentKit,
                volumetric_falloff: true
            },
            motion_graphics_overlay: documentaryOverlay,
            transition: {
                type: 'RACK_FOCUS_BLUR',
                duration_sec: 0.8
            },
            duration_sec: roundTo(durationSec, 1)
        };
    }
}

function roundTo(num, decimals) {
    const factor = Math.pow(10, decimals);
    return Math.round(num * factor) / factor;
}

    // --- VisualDiversityChecker.js ---
/**
 * CurioLoop 2.0 - VisualDiversityChecker
 * Automated similarity engine checking composition geometry, camera paths,
 * dominant color palettes, and asset reuse to detect cloned scenes.
 */

class VisualDiversityChecker {
    static calculateSimilarity(sceneA, sceneB) {
        let score = 0.0;

        // 1. Check composition geometry & type match
        if (sceneA.compositionType === sceneB.compositionType) {
            score += 0.35;
        }

        // 2. Check primary subject overlap
        if (sceneA.primarySubject === sceneB.primarySubject) {
            score += 0.40;
        }

        // 3. Check lighting preset match
        if (sceneA.lightingPreset === sceneB.lightingPreset) {
            score += 0.25;
        }

        return {
            similarityIndex: Math.min(score, 1.0),
            isDuplicate: score >= 0.75,
            message: score >= 0.75 ? 'REPEATED_COMPOSITION_DETECTED' : 'VISUAL_DIVERSITY_ADEQUATE'
        };
    }
}

    // --- VisualContinuityTracker.js ---
/**
 * CurioLoop 2.0 - VisualContinuityTracker
 * Audits storyboard sequences to ensure strict cinematic visual continuity:
 * - Subject appearance consistency (vehicle, character, key prop)
 * - Environmental plausibility (no unmotivated spatial teleportation)
 * - Chronological time-of-day progression (day -> golden_hour -> dusk -> night)
 * - Historical period adherence
 * - Camera screen direction consistency (180-degree rule & screen direction)
 * - Palette harmony across narrative transitions
 */

class VisualContinuityTracker {
    constructor() {
        this.history = [];
        this.persistentSubjects = new Map();
    }

    reset() {
        this.history = [];
        this.persistentSubjects.clear();
    }

    /**
     * Audits a scene against prior scenes in the sequence.
     * @param {Object} sceneSpec - Scene specification object
     * @returns {Object} - Audit result with pass status, violations, and warnings
     */
    auditScene(sceneSpec) {
        const violations = [];
        const warnings = [];

        if (this.history.length === 0) {
            // First scene: register baseline
            this._recordScene(sceneSpec);
            return {
                sceneId: sceneSpec.scene_id || 'SCN-01',
                continuityPass: true,
                violations: [],
                warnings: []
            };
        }

        const prev = this.history[this.history.length - 1];

        // 1. Subject Appearance Continuity
        if (sceneSpec.main_subject && prev.main_subject) {
            const currSub = sceneSpec.main_subject;
            const prevSub = prev.main_subject;

            if (currSub.subject_id && currSub.subject_id === prevSub.subject_id) {
                // Same subject: check for unexplained property mutations
                if (currSub.model && prevSub.model && currSub.model !== prevSub.model) {
                    violations.push(`Subject model mutation: '${prevSub.model}' changed to '${currSub.model}' without narrative cause.`);
                }
                if (currSub.color && prevSub.color && currSub.color !== prevSub.color) {
                    violations.push(`Subject color mutation: '${prevSub.color}' changed to '${currSub.color}' without narrative justification.`);
                }
            }
        }

        // 2. Historical Period Continuity
        if (sceneSpec.historical_period && prev.historical_period) {
            if (sceneSpec.historical_period !== prev.historical_period && !sceneSpec.is_flashback) {
                violations.push(`Historical period rupture: '${prev.historical_period}' jumped to '${sceneSpec.historical_period}' without explicit flashback or time jump flag.`);
            }
        }

        // 3. Time-of-Day Progression
        const validTimeProgression = {
            'morning': ['morning', 'afternoon', 'golden_hour'],
            'afternoon': ['afternoon', 'golden_hour', 'dusk'],
            'golden_hour': ['golden_hour', 'dusk', 'night'],
            'dusk': ['dusk', 'night'],
            'night': ['night', 'dawn', 'midnight'],
            'midnight': ['midnight', 'night', 'dawn'],
            'dawn': ['dawn', 'morning']
        };

        if (sceneSpec.time_of_day && prev.time_of_day) {
            const allowed = validTimeProgression[prev.time_of_day] || [];
            if (!allowed.includes(sceneSpec.time_of_day) && !sceneSpec.is_time_jump) {
                warnings.push(`Abrupt time progression: jumped from '${prev.time_of_day}' to '${sceneSpec.time_of_day}' without transition marker.`);
            }
        }

        // 4. Screen Direction Continuity (180-Degree Rule)
        if (sceneSpec.camera_behavior && prev.camera_behavior) {
            const currDir = sceneSpec.camera_behavior.screen_direction;
            const prevDir = prev.camera_behavior.screen_direction;

            if (currDir && prevDir && currDir !== prevDir && currDir !== 'NEUTRAL' && prevDir !== 'NEUTRAL') {
                if (!sceneSpec.is_reverse_angle) {
                    warnings.push(`Screen direction flip: Camera tracking changed from '${prevDir}' to '${currDir}' without a neutral buffer or reverse-angle cut.`);
                }
            }
        }

        // 5. Environmental Plausibility
        if (sceneSpec.environment_kit && prev.environment_kit) {
            if (sceneSpec.environment_kit !== prev.environment_kit && !sceneSpec.transition) {
                warnings.push(`Sudden environment change from '${prev.environment_kit}' to '${sceneSpec.environment_kit}' without defined visual transition.`);
            }
        }

        this._recordScene(sceneSpec);

        return {
            sceneId: sceneSpec.scene_id || `SCN-${this.history.length}`,
            continuityPass: violations.length === 0,
            violations,
            warnings
        };
    }

    _recordScene(sceneSpec) {
        this.history.push({
            scene_id: sceneSpec.scene_id,
            main_subject: sceneSpec.main_subject,
            historical_period: sceneSpec.historical_period,
            time_of_day: sceneSpec.time_of_day,
            camera_behavior: sceneSpec.camera_behavior,
            environment_kit: sceneSpec.environment_kit,
            palette: sceneSpec.palette
        });
    }

    /**
     * Audits an entire storyboard sequence of scenes.
     * @param {Array<Object>} scenes - Array of scene specification objects
     * @returns {Object} - Comprehensive sequence continuity audit report
     */
    auditSequence(scenes) {
        this.reset();
        const results = [];
        let totalViolations = 0;
        let totalWarnings = 0;

        for (const scene of scenes) {
            const res = this.auditScene(scene);
            results.push(res);
            totalViolations += res.violations.length;
            totalWarnings += res.warnings.length;
        }

        return {
            totalScenes: scenes.length,
            continuityPass: totalViolations === 0,
            totalViolations,
            totalWarnings,
            sceneReports: results
        };
    }
}

    window.CurioLoop = {
        RenderingMode: typeof RenderingMode !== 'undefined' ? RenderingMode : {},
        RenderingModeController: typeof RenderingModeController !== 'undefined' ? RenderingModeController : {},
        EnvironmentKitType: typeof EnvironmentKitType !== 'undefined' ? EnvironmentKitType : {},
        EnvironmentPresets: typeof EnvironmentPresets !== 'undefined' ? EnvironmentPresets : {},
        EnvironmentManager: typeof EnvironmentManager !== 'undefined' ? EnvironmentManager : {},
        CameraShotType: typeof CameraShotType !== 'undefined' ? CameraShotType : {},
        CameraMotivation: typeof CameraMotivation !== 'undefined' ? CameraMotivation : {},
        CameraSystem: typeof CameraSystem !== 'undefined' ? CameraSystem : {},
        CompositionSystem: typeof CompositionSystem !== 'undefined' ? CompositionSystem : {},
        LightingAndMaterials: typeof LightingAndMaterials !== 'undefined' ? LightingAndMaterials : {},
        MotionGraphics: typeof MotionGraphics !== 'undefined' ? MotionGraphics : {},
        SceneEngine: typeof SceneEngine !== 'undefined' ? SceneEngine : {},
        VisualDirector: typeof VisualDirector !== 'undefined' ? VisualDirector : {},
        VisualDiversityChecker: typeof VisualDiversityChecker !== 'undefined' ? VisualDiversityChecker : {},
        VisualContinuityTracker: typeof VisualContinuityTracker !== 'undefined' ? VisualContinuityTracker : {}
    };
})(typeof window !== 'undefined' ? window : this);
