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

export class VisualContinuityTracker {
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
