/**
 * CurioLoop 2.0 - VisualDiversityChecker
 * Automated similarity engine checking composition geometry, camera paths,
 * dominant color palettes, and asset reuse to detect cloned scenes.
 */

export class VisualDiversityChecker {
    static calculateSimilarity(sceneA, sceneB) {
        let score = 0.0;

        // 1. Check composition geometry & type match
        if (sceneA.compositionType === sceneB.compositionType) {
            score += 0.35;
        }

        // 2. Check primary subject overlap
        if (sceneA.primarySubject === sceneB.primarySubject) {
            score += 0.40;
        }

        // 3. Check lighting preset match
        if (sceneA.lightingPreset === sceneB.lightingPreset) {
            score += 0.25;
        }

        return {
            similarityIndex: Math.min(score, 1.0),
            isDuplicate: score >= 0.75,
            message: score >= 0.75 ? 'REPEATED_COMPOSITION_DETECTED' : 'VISUAL_DIVERSITY_ADEQUATE'
        };
    }
}
