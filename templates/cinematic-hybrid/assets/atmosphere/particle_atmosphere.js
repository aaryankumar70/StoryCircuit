/**
 * CurioLoop 2.0 - Particle Atmosphere Engine
 * High-performance 2D Canvas / WebGL atmospheric particle emitter.
 * Supports: Dust Motes, Heavy Rain, Gentle Snow, Smoke Drift.
 */

export class AtmosphericEmitter {
    constructor(canvas, mode = 'dust', options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.mode = mode;
        this.particleCount = options.count || 120;
        this.particles = [];
        this.width = canvas.width;
        this.height = canvas.height;
        this.windX = options.windX || 0.15;
        this.init();
    }

    init() {
        this.particles = [];
        for (let i = 0; i < this.particleCount; i++) {
            this.particles.push(this.createParticle());
        }
    }

    createParticle() {
        const p = {
            x: Math.random() * this.width,
            y: Math.random() * this.height,
            z: Math.random() * 200 - 100, // depth Z
            alpha: Math.random() * 0.6 + 0.2,
            size: Math.random() * 2.5 + 0.8,
            vx: 0,
            vy: 0
        };

        if (this.mode === 'dust') {
            p.vx = (Math.random() - 0.5) * 0.3 + this.windX;
            p.vy = (Math.random() - 0.5) * 0.2 - 0.05;
        } else if (this.mode === 'rain') {
            p.vx = this.windX * 4.0;
            p.vy = Math.random() * 12.0 + 16.0;
            p.length = Math.random() * 18.0 + 10.0;
        } else if (this.mode === 'snow') {
            p.vx = Math.sin(Math.random() * Math.PI) * 0.8 + this.windX;
            p.vy = Math.random() * 1.2 + 0.6;
        }
        return p;
    }

    update() {
        for (let p of this.particles) {
            p.x += p.vx;
            p.y += p.vy;

            // wrap around
            if (p.x < 0) p.x = this.width;
            if (p.x > this.width) p.x = 0;
            if (p.y < 0) p.y = this.height;
            if (p.y > this.height) p.y = 0;
        }
    }

    render() {
        this.ctx.clearRect(0, 0, this.width, this.height);
        for (let p of this.particles) {
            // scale with depth Z
            const scale = 1.0 + p.z / 300.0;
            this.ctx.fillStyle = `rgba(235, 230, 215, ${p.alpha * scale})`;

            if (this.mode === 'rain') {
                this.ctx.strokeStyle = `rgba(180, 205, 230, ${p.alpha * 0.6})`;
                this.ctx.lineWidth = 1.2 * scale;
                this.ctx.beginPath();
                this.ctx.moveTo(p.x, p.y);
                this.ctx.lineTo(p.x + p.vx * 1.5, p.y + p.length);
                this.ctx.stroke();
            } else {
                this.ctx.beginPath();
                this.ctx.arc(p.x, p.y, Math.max(0.5, p.size * scale), 0, Math.PI * 2);
                this.ctx.fill();
            }
        }
    }
}
