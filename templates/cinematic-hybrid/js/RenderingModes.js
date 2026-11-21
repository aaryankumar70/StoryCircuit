/**
 * CurioLoop 2.0 - RenderingModes
 * Defines the 3 complementary rendering modes and hybrid integration:
 * - Mode A: Cinematic 3D (Spatial geometry, perspective camera, volumetric lighting, PBR materials)
 * - Mode B: Cinematic 2.5D (Layered depth-separated planes, parallax, atmospheric depth)
 * - Mode C: Documentary Motion Graphics (Flight routes, timelines, declassified records, coordinates, mobile safe zones)
 * - Hybrid: Seamless spatial 3D/2.5D environment with integrated documentary graphics
 */

export const RenderingMode = {
    MODE_A_CINEMATIC_3D: 'MODE_A_CINEMATIC_3D',
    MODE_B_CINEMATIC_2_5D: 'MODE_B_CINEMATIC_2_5D',
    MODE_C_DOCUMENTARY_MOTION_GRAPHICS: 'MODE_C_DOCUMENTARY_MOTION_GRAPHICS',
    HYBRID: 'HYBRID'
};

export class RenderingModeController {
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
