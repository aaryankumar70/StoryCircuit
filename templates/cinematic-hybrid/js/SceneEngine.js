/**
 * CurioLoop 2.0 - SceneEngine
 * Core lifecycle manager coordinating WebGL (Three.js), 2.5D Canvas, particle systems,
 * atmospheric shaders, and performance monitoring.
 */

export class SceneEngine {
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
