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

export const CameraShotType = {
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

export const CameraMotivation = {
    REVEAL: 'REVEAL',
    INVESTIGATION: 'INVESTIGATION',
    DISCOVERY: 'DISCOVERY',
    ISOLATION: 'ISOLATION',
    THREAT: 'THREAT',
    EVIDENCE: 'EVIDENCE'
};

export class CameraSystem {
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
