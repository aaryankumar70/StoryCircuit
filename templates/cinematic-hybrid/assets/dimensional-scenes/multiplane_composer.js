/**
 * CurioLoop 2.0 - 2.5D Multi-Plane Scene Composer
 * Positions graphic layers in virtual 3D space with perspective projection and depth parallax.
 */

export class MultiplaneComposer {
    constructor(container, fov = 45.0) {
        this.container = container;
        this.fov = fov;
        this.layers = [];
    }

    addLayer(element, depthZ, parallaxFactor = 1.0) {
        this.layers.push({ element, depthZ, parallaxFactor });
    }

    updateCamera(camera) {
        const radFov = (this.fov * Math.PI) / 180.0;
        const viewDistance = 500.0 / Math.tan(radFov / 2.0);

        for (let layer of this.layers) {
            const relZ = layer.depthZ - camera.z;
            const scale = Math.max(0.05, viewDistance / (viewDistance - relZ));
            const offsetX = (camera.x * layer.parallaxFactor) * scale;
            const offsetY = (camera.y * layer.parallaxFactor) * scale;

            layer.element.style.transform = `translate3d(${-offsetX}px, ${-offsetY}px, 0px) scale(${scale}) rotate(${camera.roll}deg)`;
        }
    }
}
