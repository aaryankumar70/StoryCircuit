/**
 * CurioLoop 2.0 - MotionGraphics
 * Reusable telemetry displays, timeline overlays, evidence callouts, and 9:16 safe-zone framing.
 */

export class MotionGraphics {
    static drawEvidenceTag(ctx, text, x = 40, y = 60) {
        ctx.save();
        ctx.font = 'bold 16px "Courier New", monospace';
        const textWidth = ctx.measureText(text).width;

        // Background card
        ctx.fillStyle = 'rgba(10, 16, 26, 0.9)';
        ctx.fillRect(x, y - 20, textWidth + 24, 28);

        // Amber tag border
        ctx.fillStyle = '#f59e0b';
        ctx.fillRect(x, y - 20, 4, 28);

        ctx.fillStyle = '#f59e0b';
        ctx.fillText(text, x + 12, y);
        ctx.restore();
    }

    static drawSpectrogram(ctx, x, y, width, height, timeSec) {
        ctx.save();
        ctx.fillStyle = 'rgba(4, 9, 16, 0.85)';
        ctx.fillRect(x, y, width, height);
        ctx.strokeStyle = '#00f0ff';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, width, height);

        // Draw frequency carrier lines
        const bands = 24;
        const bandW = width / bands;
        for (let i = 0; i < bands; i++) {
            const h = (Math.sin(timeSec * 4.0 + i * 0.7) * 0.5 + 0.5) * (height - 20);
            ctx.fillStyle = i === 12 ? '#ef4444' : '#00f0ff';
            ctx.fillRect(x + i * bandW + 2, y + height - h - 10, bandW - 4, h);
        }
        ctx.restore();
    }

    static drawMobileSafeZone(ctx, width, height) {
        ctx.save();
        ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 6]);

        // 80% inner rect
        const safeX = width * 0.1;
        const safeY = height * 0.1;
        const safeW = width * 0.8;
        const safeH = height * 0.8;

        ctx.strokeRect(safeX, safeY, safeW, safeH);
        ctx.restore();
    }
}
