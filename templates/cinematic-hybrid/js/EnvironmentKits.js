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

export const EnvironmentKitType = {
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

export const EnvironmentPresets = {
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

export class EnvironmentManager {
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
