/**
 * CurioLoop 2.0 - LightingAndMaterials
 * Reusable material library, lighting rigs, volumetric haze, and PBR-lite shaders.
 */

export class LightingAndMaterials {
    static createLightingRig(threeScene, preset = 'archival_candlelight') {
        if (!threeScene || typeof window.THREE === 'undefined') return;

        const presets = {
            archival_candlelight: {
                ambientColor: 0x221108,
                ambientIntensity: 0.8,
                keyColor: 0xffd288,
                keyIntensity: 2.2,
                keyPos: [150, 200, 250],
                shadows: true
            },
            cold_maritime_fog: {
                ambientColor: 0x0a1420,
                ambientIntensity: 0.9,
                keyColor: 0x48a8d8,
                keyIntensity: 1.6,
                keyPos: [-200, 150, 180],
                shadows: true
            },
            night_extraterrestrial: {
                ambientColor: 0x050610,
                ambientIntensity: 0.5,
                keyColor: 0x00f0ff,
                keyIntensity: 2.8,
                keyPos: [0, 300, 100],
                shadows: true
            }
        };

        const cfg = presets[preset] || presets.archival_candlelight;

        const ambientLight = new window.THREE.AmbientLight(cfg.ambientColor, cfg.ambientIntensity);
        threeScene.add(ambientLight);

        const dirLight = new window.THREE.DirectionalLight(cfg.keyColor, cfg.keyIntensity);
        dirLight.position.set(cfg.keyPos[0], cfg.keyPos[1], cfg.keyPos[2]);
        if (cfg.shadows) {
            dirLight.castShadow = true;
            dirLight.shadow.mapSize.width = 1024;
            dirLight.shadow.mapSize.height = 1024;
            dirLight.shadow.camera.near = 0.5;
            dirLight.shadow.camera.far = 1000;
        }
        threeScene.add(dirLight);

        return { ambientLight, dirLight };
    }

    static createParchmentMaterial(colorHex = 0xd5c4a1) {
        if (typeof window.THREE === 'undefined') return null;
        return new window.THREE.MeshStandardMaterial({
            color: colorHex,
            roughness: 0.88,
            metalness: 0.05
        });
    }

    static createWeatheredBrassMaterial() {
        if (typeof window.THREE === 'undefined') return null;
        return new window.THREE.MeshStandardMaterial({
            color: 0xc49a45,
            roughness: 0.32,
            metalness: 0.82
        });
    }

    static createEmissiveGlowMaterial(colorHex = 0x00f0ff, intensity = 1.8) {
        if (typeof window.THREE === 'undefined') return null;
        return new window.THREE.MeshStandardMaterial({
            color: 0xffffff,
            emissive: colorHex,
            emissiveIntensity: intensity,
            roughness: 0.2
        });
    }
}
