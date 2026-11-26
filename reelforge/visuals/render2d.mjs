#!/usr/bin/env node
/**
 * Headless Chromium 2D Canvas -> FFmpeg renderer for ReelForge (StoryCircuit).
 * Supports single frame PNG, opaque video spans, and transparent overlay compositing onto HD B-roll MP4s.
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    if (k.startsWith("--")) {
      const key = k.slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
      out[key] = val;
    }
  }
  return out;
}

async function launchBrowser() {
  const chromeBin = process.env.REELFORGE_CHROMIUM_BIN || "chromium";
  const chrome = spawn(
    chromeBin,
    [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--mute-audio",
      "--remote-debugging-port=0",
      "about:blank",
    ],
    { stdio: ["ignore", "pipe", "pipe"] }
  );

  const wsUrl = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Timed out starting Chromium")), 15000);
    let errBuf = "";
    chrome.stderr.on("data", (chunk) => {
      errBuf += chunk.toString();
      const m = errBuf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1]);
      }
    });
    chrome.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Chromium exited early (${code}): ${errBuf}`));
    });
  });

  const port = new URL(wsUrl).port;
  const targets = await new Promise((resolve, reject) => {
    http
      .get(`http://127.0.0.1:${port}/json/list`, (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => resolve(JSON.parse(body)));
      })
      .on("error", reject);
  });

  const pageTarget = targets.find((t) => t.type === "page") || targets[0];
  if (!pageTarget || !pageTarget.webSocketDebuggerUrl) {
    chrome.kill();
    throw new Error("No DevTools page target found");
  }

  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  let nextId = 1;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message || "CDP error"));
      else resolve(msg.result);
    }
  };

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  return { chrome, ws, send };
}

async function runFfmpegSpan(send, { startSec, frames, fps, bgVideo, outMp4, preset, crf }) {
  const isOverlay = Boolean(bgVideo);
  const ffArgs = ["-y"];
  if (isOverlay) {
    ffArgs.push("-i", bgVideo);
  }
  ffArgs.push(
    "-f", "image2pipe",
    "-vcodec", isOverlay ? "png" : "mjpeg",
    "-framerate", String(fps),
    "-i", "-"
  );
  if (isOverlay) {
    ffArgs.push("-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1,format=yuv420p[vout]", "-map", "[vout]");
  } else {
    ffArgs.push("-pix_fmt", "yuv420p");
  }
  ffArgs.push(
    "-c:v", "libx264",
    "-preset", preset,
    "-crf", String(crf),
    "-r", String(fps),
    "-an",
    outMp4
  );

  const ff = spawn("ffmpeg", ffArgs, { stdio: ["pipe", "pipe", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (c) => (ffErr += c.toString()));
  ff.stdin.on("error", () => {});

  const ffDone = new Promise((resolve, reject) => {
    ff.on("error", reject);
    ff.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`ffmpeg exited with code ${code}: ${ffErr.slice(-600)}`));
    });
  });

  const fmt = isOverlay ? "png" : "jpeg";
  const transFlag = isOverlay ? "true" : "false";
  for (let f = 0; f < frames; f++) {
    const tSec = startSec + f / fps;
    const res = await send("Runtime.evaluate", {
      expression: `window.renderAtTime(${tSec.toFixed(4)}, "${fmt}", 0.95, ${transFlag})`,
      returnByValue: true,
    });
    if (!res || !res.result || typeof res.result.value !== "string") {
      throw new Error(`stage2d renderAtTime returned invalid frame at ${tSec.toFixed(2)}s`);
    }
    const buf = Buffer.from(res.result.value, "base64");
    if (ff.stdin.destroyed || ff.stdin.writableEnded) break;
    if (!ff.stdin.write(buf)) {
      await new Promise((r) => ff.stdin.once("drain", r));
    }
    if (f > 0 && f % Math.max(30, Math.floor(frames / 5)) === 0) {
      process.stdout.write(`PROGRESS ${f}/${frames}\n`);
    }
  }
  if (!ff.stdin.destroyed && !ff.stdin.writableEnded) {
    ff.stdin.end();
  }
  await ffDone;
  process.stdout.write(`PROGRESS ${frames}/${frames}\n`);
}

async function main() {
  const args = parseArgs(process.argv);
  const manifestPath = args.manifest;
  const mode = args.mode || "video";
  if (!manifestPath || !fs.existsSync(manifestPath)) {
    throw new Error("Missing --manifest JSON file");
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
  const width = Number(manifest.width || 1080);
  const height = Number(manifest.height || 1920);
  const fps = Number(manifest.fps || 30);
  const preset = manifest.encode_preset || "medium";
  const crf = Number(manifest.encode_crf || 18);
  const stageFile = path.resolve(__dirname, "stage2d.html");

  const { chrome, ws, send } = await launchBrowser();
  try {
    await send("Page.enable");
    await send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    if (mode === "segments" || args.bg_video) {
      await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
    }

    await send("Page.navigate", { url: "file://" + stageFile });
    await new Promise((r) => setTimeout(r, 120));

    await send("Runtime.evaluate", {
      expression: `(async () => {
        for (let i = 0; i < 40 && typeof window.setManifest !== 'function'; i++) {
          await new Promise(r => setTimeout(r, 25));
        }
        return await window.setManifest(${JSON.stringify(manifest)});
      })()`,
      awaitPromise: true,
      returnByValue: true,
    });

    if (mode === "frame") {
      const tSec = Number(args.time || 0.5);
      const outPng = args.out;
      if (!outPng) throw new Error("Missing --out path for frame mode");
      const res = await send("Runtime.evaluate", {
        expression: `window.renderAtTime(${tSec}, "png", 1.0, false)`,
        returnByValue: true,
      });
      fs.mkdirSync(path.dirname(outPng), { recursive: true });
      fs.writeFileSync(outPng, Buffer.from(res.result.value, "base64"));
      return;
    }

    if (mode === "segments") {
      // Render an array of {start_sec, frames, bg_video, out} in a single Chromium session
      const segs = manifest.segments || [];
      for (let i = 0; i < segs.length; i++) {
        const s = segs[i];
        fs.mkdirSync(path.dirname(s.out), { recursive: true });
        await runFfmpegSpan(send, {
          startSec: Number(s.start_sec),
          frames: Number(s.frames),
          fps,
          bgVideo: s.bg_video || null,
          outMp4: s.out,
          preset,
          crf,
        });
        process.stdout.write(`SEGMENT ${i + 1}/${segs.length}\n`);
      }
      return;
    }

    const outMp4 = args.out;
    if (!outMp4) throw new Error("Missing --out path for video mode");
    fs.mkdirSync(path.dirname(outMp4), { recursive: true });
    const totalDur = Math.max(1.0, Number(manifest.duration_sec || 10.0));
    const totalFrames = Math.max(18, Math.round(totalDur * fps));
    await runFfmpegSpan(send, {
      startSec: 0,
      frames: totalFrames,
      fps,
      bgVideo: args.bg_video || null,
      outMp4,
      preset,
      crf,
    });
  } finally {
    try { ws.close(); } catch (_) {}
    try { chrome.kill(); } catch (_) {}
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
