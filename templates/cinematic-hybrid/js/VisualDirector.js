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

import { RenderingMode, RenderingModeController } from './RenderingModes.js';
import { CameraShotType, CameraMotivation } from './CameraSystem.js';
import { EnvironmentKitType } from './EnvironmentKits.js';

export class VisualDirector {
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
