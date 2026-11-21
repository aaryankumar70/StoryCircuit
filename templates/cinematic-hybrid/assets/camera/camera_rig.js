/**
 * CurioLoop 2.0 - Cinematic 2.5D Camera Rig
 * Smooth easing interpolator with quintic damping, Perlin drift, and bokeh projection.
 */

export class CinematicCameraRig {
    constructor(config) {
        this.fov = config.fov_degrees || 45.0;
        this.duration = config.total_duration_sec || 10.0;
        this.keyframes = config.keyframes || [];
        this.easing = config.easing_type || 'CINEMATIC_DRIFT';
    }

    // Quintic in-out easing for organic mechanical inertia
    quinticInOut(t) {
        if ((t /= 0.5) < 1) return 0.5 * t * t * t * t * t;
        return 0.5 * ((t -= 2) * t * t * t * t + 2);
    }

    // Smoothstep interpolation
    smoothstep(t) {
        return t * t * (3 - 2 * t);
    }

    // Evaluate camera position and orientation at normalized time t (0.0 to 1.0)
    evaluate(timeSec) {
        const normTime = Math.min(Math.max(timeSec / this.duration, 0.0), 1.0);
        const easedT = this.easing === 'CINEMATIC_DRIFT' ? this.quinticInOut(normTime) : this.smoothstep(normTime);

        if (this.keyframes.length === 0) {
            return { x: 0, y: 0, z: 400, lookX: 0, lookY: 0, lookZ: 0, roll: 0 };
        }
        if (this.keyframes.length === 1) {
            const k = this.keyframes[0];
            return {
                x: k.position_xyz[0], y: k.position_xyz[1], z: k.position_xyz[2],
                lookX: k.look_at_xyz[0], lookY: k.look_at_xyz[1], lookZ: k.look_at_xyz[2],
                roll: k.roll_degrees
            };
        }

        const k0 = this.keyframes[0];
        const k1 = this.keyframes[this.keyframes.length - 1];

        // Subtle organic breathing drift (0.2 Hz)
        const driftAngle = Math.sin(timeSec * 1.25) * 0.35;
        const driftY = Math.cos(timeSec * 0.8) * 1.5;

        return {
            x: k0.position_xyz[0] + (k1.position_xyz[0] - k0.position_xyz[0]) * easedT,
            y: k0.position_xyz[1] + (k1.position_xyz[1] - k0.position_xyz[1]) * easedT + driftY,
            z: k0.position_xyz[2] + (k1.position_xyz[2] - k0.position_xyz[2]) * easedT,
            lookX: k0.look_at_xyz[0] + (k1.look_at_xyz[0] - k0.look_at_xyz[0]) * easedT,
            lookY: k0.look_at_xyz[1] + (k1.look_at_xyz[1] - k0.look_at_xyz[1]) * easedT,
            lookZ: k0.look_at_xyz[2] + (k1.look_at_xyz[2] - k0.look_at_xyz[2]) * easedT,
            roll: k0.roll_degrees + (k1.roll_degrees - k0.roll_degrees) * easedT + driftAngle
        };
    }
}
