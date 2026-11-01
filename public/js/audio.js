/**
 * PANODROME — Spatial Audio Engine (fully procedural, WebAudio)
 *
 *  - Ambience beds per room profile: room_tone / hall_air / city_hum /
 *    cafe_murmur / cellar_drip / birds_wind  (synthesized, no audio files)
 *  - Footstep synthesizer tuned per floor material:
 *    wood / stone / concrete / carpet / gravel
 *  - Convolution reverb with a generated impulse response (length by room)
 *  - Portal transition whoosh + arrival chime
 */
export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.muted = false;
    this._ambience = null;      // {nodes:[], timers:[], gain}
    this._room = null;
  }

  /** Must be called from a user gesture. */
  init() {
    if (this.ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();

    this.master = this.ctx.createGain();
    this.master.gain.value = 0.9;
    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.ratio.value = 6;
    this.master.connect(comp).connect(this.ctx.destination);

    // reverb bus
    this.reverb = this.ctx.createConvolver();
    this.reverbGain = this.ctx.createGain();
    this.reverbGain.gain.value = 0.8;
    this.reverb.connect(this.reverbGain).connect(this.master);

    // noise buffers
    this._white = this._noiseBuffer(2, () => Math.random() * 2 - 1);
    this._pink = this._noiseBuffer(2, pinkSample);
    this._brown = this._noiseBuffer(4, brownSample);
  }

  get ready() {
    return !!this.ctx;
  }

  // ---------------------------------------------------------------- room ambience
  setRoom(profile) {
    if (!this.ctx) return;
    this._room = profile;
    this._clearAmbience(1.0);
    this._setIR(profile.reverb ?? 0.3);

    const g = this.ctx.createGain();
    g.gain.value = 0;
    g.connect(this.master);
    g.connect(this.reverb);
    const timers = [];
    const nodes = [g];

    const amb = profile.ambient || "room_tone";
    if (amb === "room_tone" || amb === "hall_air" || amb === "city_hum") {
      const src = this.ctx.createBufferSource();
      src.buffer = amb === "city_hum" ? this._brown : this._pink;
      src.loop = true;
      const lp = this.ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = amb === "hall_air" ? 240 : amb === "city_hum" ? 220 : 380;
      const gain = this.ctx.createGain();
      gain.gain.value = amb === "hall_air" ? 0.045 : amb === "city_hum" ? 0.075 : 0.06;
      // slow breathing LFO
      const lfo = this.ctx.createOscillator();
      lfo.frequency.value = 0.07 + Math.random() * 0.05;
      const lfoGain = this.ctx.createGain();
      lfoGain.gain.value = 0.014;
      lfo.connect(lfoGain).connect(gain.gain);
      lfo.start();
      src.connect(lp).connect(gain).connect(g);
      src.start();
      nodes.push(src, lp, gain, lfo, lfoGain);
    }

    if (amb === "cafe_murmur") {
      const src = this.ctx.createBufferSource();
      src.buffer = this._pink;
      src.loop = true;
      const bp = this.ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = 420;
      bp.Q.value = 0.6;
      const gain = this.ctx.createGain();
      gain.gain.value = 0.05;
      const lfo = this.ctx.createOscillator();
      lfo.frequency.value = 0.9;
      const lfoG = this.ctx.createGain();
      lfoG.gain.value = 0.02;
      lfo.connect(lfoG).connect(gain.gain);
      lfo.start();
      src.connect(bp).connect(gain).connect(g);
      src.start();
      nodes.push(src, bp, gain, lfo, lfoG);
      timers.push(this._every(5 + Math.random() * 9, () => this._clink(g)));
    }

    if (amb === "cellar_drip") {
      const pad = this.ctx.createBufferSource();
      pad.buffer = this._brown;
      pad.loop = true;
      const lp = this.ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = 160;
      const gain = this.ctx.createGain();
      gain.gain.value = 0.05;
      pad.connect(lp).connect(gain).connect(g);
      pad.start();
      nodes.push(pad, lp, gain);
      timers.push(this._every(7 + Math.random() * 11, () => this._drip()));
    }

    if (amb === "birds_wind") {
      const wind = this.ctx.createBufferSource();
      wind.buffer = this._brown;
      wind.loop = true;
      const lp = this.ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = 500;
      const gain = this.ctx.createGain();
      gain.gain.value = 0.05;
      const lfo = this.ctx.createOscillator();
      lfo.frequency.value = 0.16;
      const lfoG = this.ctx.createGain();
      lfoG.gain.value = 0.028; // gusts
      lfo.connect(lfoG).connect(gain.gain);
      lfo.start();
      wind.connect(lp).connect(gain).connect(g);
      wind.start();
      nodes.push(wind, lp, gain, lfo, lfoG);
      timers.push(this._every(2.2 + Math.random() * 5, () => this._chirp()));
    }

    // fade in
    g.gain.linearRampToValueAtTime(1, this.ctx.currentTime + 1.2);
    this._ambience = { nodes, timers, gain: g };
  }

  // ---------------------------------------------------------------- footsteps
  step(material) {
    if (!this.ctx || this.muted) return;
    const t = this.ctx.currentTime;
    const out = this.ctx.createGain();
    out.gain.value = 0.9;
    out.connect(this.master);
    if (this._room) {
      const send = this.ctx.createGain();
      send.gain.value = 0.25 + (this._room.reverb ?? 0.3) * 0.5;
      out.connect(send).connect(this.reverb);
    }
    const r = (a, b) => a + Math.random() * (b - a);
    const vol = r(0.85, 1.15);

    const noise = (dur, filterType, freq, q, gain, when = 0) => {
      const src = this.ctx.createBufferSource();
      src.buffer = this._white;
      src.playbackRate.value = r(0.92, 1.08);
      const f = this.ctx.createBiquadFilter();
      f.type = filterType;
      f.frequency.value = freq;
      f.Q.value = q;
      const env = this.ctx.createGain();
      env.gain.setValueAtTime(0, t + when);
      env.gain.linearRampToValueAtTime(gain * vol, t + when + 0.008);
      env.gain.exponentialRampToValueAtTime(0.0001, t + when + dur);
      src.connect(f).connect(env).connect(out);
      src.start(t + when, Math.random() * 1.5);
      src.stop(t + when + dur + 0.05);
    };
    const thump = (f0, f1, dur, gain, when = 0) => {
      const o = this.ctx.createOscillator();
      o.type = "sine";
      o.frequency.setValueAtTime(f0, t + when);
      o.frequency.exponentialRampToValueAtTime(f1, t + when + dur);
      const env = this.ctx.createGain();
      env.gain.setValueAtTime(0, t + when);
      env.gain.linearRampToValueAtTime(gain * vol, t + when + 0.01);
      env.gain.exponentialRampToValueAtTime(0.0001, t + when + dur);
      o.connect(env).connect(out);
      o.start(t + when);
      o.stop(t + when + dur + 0.05);
    };

    switch (material) {
      case "wood":
        thump(82, 46, 0.1, 0.42);
        noise(0.06, "bandpass", 240, 1.4, 0.3);
        if (Math.random() < 0.14) { // occasional creak
          const o = this.ctx.createOscillator();
          o.type = "sawtooth";
          const f0 = r(85, 135);
          o.frequency.setValueAtTime(f0, t + 0.02);
          o.frequency.linearRampToValueAtTime(f0 * r(1.1, 1.5), t + 0.16);
          const lp = this.ctx.createBiquadFilter();
          lp.type = "lowpass";
          lp.frequency.value = 420;
          const env = this.ctx.createGain();
          env.gain.setValueAtTime(0, t + 0.02);
          env.gain.linearRampToValueAtTime(0.05, t + 0.05);
          env.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
          o.connect(lp).connect(env).connect(out);
          o.start(t + 0.02);
          o.stop(t + 0.2);
        }
        break;
      case "stone":
        noise(0.028, "highpass", 1900, 0.8, 0.28);
        noise(0.055, "bandpass", 350, 2.0, 0.26);
        thump(120, 80, 0.05, 0.16);
        break;
      case "concrete":
        noise(0.045, "bandpass", 190, 1.0, 0.4);
        thump(105, 70, 0.07, 0.22);
        break;
      case "carpet":
        noise(0.085, "lowpass", 430, 0.7, 0.2);
        break;
      case "gravel":
      case "grass":
        noise(0.1, "lowpass", 950, 0.8, 0.28);
        noise(0.07, "lowpass", 1500, 0.8, 0.14, 0.018);
        thump(95, 60, 0.05, 0.1);
        break;
      default:
        noise(0.05, "bandpass", 220, 1.0, 0.3);
    }
  }

  // ---------------------------------------------------------------- transitions
  portalWhoosh() {
    if (!this.ctx || this.muted) return;
    const t = this.ctx.currentTime;
    const src = this.ctx.createBufferSource();
    src.buffer = this._pink;
    const bp = this.ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.Q.value = 1.1;
    bp.frequency.setValueAtTime(220, t);
    bp.frequency.exponentialRampToValueAtTime(2400, t + 0.9);
    const env = this.ctx.createGain();
    env.gain.setValueAtTime(0.0001, t);
    env.gain.exponentialRampToValueAtTime(0.16, t + 0.55);
    env.gain.exponentialRampToValueAtTime(0.0001, t + 1.05);
    src.connect(bp).connect(env).connect(this.master);
    src.connect(bp).connect(env).connect(this.reverb);
    src.start(t);
    src.stop(t + 1.1);
  }

  chime() {
    if (!this.ctx || this.muted) return;
    const t = this.ctx.currentTime;
    [523.25, 659.25, 987.77].forEach((f, i) => {
      const o = this.ctx.createOscillator();
      o.type = "sine";
      o.frequency.value = f;
      const env = this.ctx.createGain();
      env.gain.setValueAtTime(0, t + i * 0.07);
      env.gain.linearRampToValueAtTime(0.05 / (i + 1), t + i * 0.07 + 0.02);
      env.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.07 + 1.1);
      o.connect(env).connect(this.master);
      o.connect(env).connect(this.reverb);
      o.start(t + i * 0.07);
      o.stop(t + i * 0.07 + 1.2);
    });
  }

  setMuted(m) {
    this.muted = m;
    if (this.ctx) this.master.gain.linearRampToValueAtTime(m ? 0 : 0.9, this.ctx.currentTime + 0.2);
  }

  resume() {
    if (this.ctx && this.ctx.state === "suspended") this.ctx.resume();
  }

  // ---------------------------------------------------------------- internals
  _setIR(amount) {
    const len = Math.max(0.15, 0.25 + amount * 2.0) * this.ctx.sampleRate;
    const buf = this.ctx.createBuffer(2, Math.floor(len), this.ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < d.length; i++) {
        d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / d.length, 2.4 + amount * 1.5);
      }
    }
    this.reverb.buffer = buf;
  }

  _clearAmbience(fade = 0.8) {
    if (!this._ambience) return;
    const { nodes, timers, gain } = this._ambience;
    timers.forEach(clearTimeout);
    const t = this.ctx.currentTime;
    gain.gain.cancelScheduledValues(t);
    gain.gain.setValueAtTime(gain.gain.value, t);
    gain.gain.linearRampToValueAtTime(0, t + fade);
    setTimeout(() => {
      nodes.forEach((n) => { try { n.stop ? n.stop() : n.disconnect(); } catch (e) {} });
      try { gain.disconnect(); } catch (e) {}
    }, fade * 1000 + 120);
    this._ambience = null;
  }

  _every(minSec, fn) {
    const tick = () => {
      fn();
      const id = setTimeout(tick, (minSec + Math.random() * minSec * 1.6) * 1000);
      if (this._ambience) this._ambience.timers.push(id);
      else clearTimeout(id);
    };
    return setTimeout(tick, (minSec + Math.random() * minSec) * 1000);
  }

  _clink(out) {
    if (!this.ctx || this.muted) return;
    const t = this.ctx.currentTime;
    const o = this.ctx.createOscillator();
    o.type = "sine";
    o.frequency.value = 1700 + Math.random() * 1100;
    const env = this.ctx.createGain();
    env.gain.setValueAtTime(0.028, t);
    env.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
    const pan = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;
    if (pan) pan.pan.value = Math.random() * 1.6 - 0.8;
    o.connect(env);
    if (pan) { env.connect(pan).connect(out); env.connect(pan).connect(this.reverb); }
    else { env.connect(out); env.connect(this.reverb); }
    o.start(t);
    o.stop(t + 0.4);
  }

  _drip() {
    if (!this.ctx || this.muted) return;
    const t = this.ctx.currentTime;
    const o = this.ctx.createOscillator();
    o.type = "sine";
    o.frequency.setValueAtTime(920, t);
    o.frequency.exponentialRampToValueAtTime(430, t + 0.07);
    const env = this.ctx.createGain();
    env.gain.setValueAtTime(0.05, t);
    env.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(env).connect(this.reverb);
    o.connect(env).connect(this.master);
    o.start(t);
    o.stop(t + 0.3);
  }

  _chirp() {
    if (!this.ctx || this.muted) return;
    const t0 = this.ctx.currentTime;
    const notes = 2 + Math.floor(Math.random() * 3);
    const base = 2700 + Math.random() * 1400;
    const pan = this.ctx.createStereoPanner ? this.ctx.createStereoPanner() : null;
    if (pan) pan.pan.value = Math.random() * 1.8 - 0.9;
    for (let i = 0; i < notes; i++) {
      const t = t0 + i * (0.07 + Math.random() * 0.06);
      const o = this.ctx.createOscillator();
      o.type = "sine";
      const f = base * (0.85 + Math.random() * 0.3);
      o.frequency.setValueAtTime(f * 1.12, t);
      o.frequency.exponentialRampToValueAtTime(f * 0.94, t + 0.09);
      const env = this.ctx.createGain();
      env.gain.setValueAtTime(0, t);
      env.gain.linearRampToValueAtTime(0.016, t + 0.015);
      env.gain.exponentialRampToValueAtTime(0.0001, t + 0.11);
      o.connect(env);
      if (pan) env.connect(pan).connect(this.master);
      else env.connect(this.master);
      o.start(t);
      o.stop(t + 0.13);
    }
  }

  _noiseBuffer(seconds, gen) {
    const len = Math.floor(this.ctx.sampleRate * seconds);
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    const state = {};
    for (let i = 0; i < len; i++) d[i] = gen(state);
    return buf;
  }
}

/* ---- noise generators (Paul Kellet pink / leaky-integrator brown) ---- */
function pinkSample(s) {
  if (!s.b) s.b = [0, 0, 0, 0, 0, 0, 0];
  const b = s.b;
  const white = Math.random() * 2 - 1;
  b[0] = 0.99886 * b[0] + white * 0.0555179;
  b[1] = 0.99332 * b[1] + white * 0.0750759;
  b[2] = 0.969 * b[2] + white * 0.153852;
  b[3] = 0.8665 * b[3] + white * 0.3104856;
  b[4] = 0.55 * b[4] + white * 0.5329522;
  b[5] = -0.7616 * b[5] - white * 0.016898;
  const out = b[0] + b[1] + b[2] + b[3] + b[4] + b[5] + b[6] + white * 0.5362;
  b[6] = white * 0.115926;
  return out * 0.11;
}

function brownSample(s) {
  if (s.l === undefined) s.l = 0;
  const white = Math.random() * 2 - 1;
  s.l = (s.l + 0.02 * white) / 1.02;
  return s.l * 3.5;
}
