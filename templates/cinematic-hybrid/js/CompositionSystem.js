/**
 * CurioLoop 2.0 - CompositionSystem
 * 2.5D spatial depth hierarchy enforcing 3-plane separation, perspective parallax,
 * and atmospheric layer attenuation.
 */

export class CompositionSystem {
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
