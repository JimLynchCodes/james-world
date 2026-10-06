/**
 * Procedural game audio (Web Audio API, no asset files).
 *
 *   sources -> track gain (crossfades) -> music bus --\
 *   sfx voices --------------------------------> sfx bus --> master -> limiter -> out
 *
 * Four looping background tracks, one per Mood: three are synthesised live
 * by a small look-ahead step sequencer (Happy, Spooky, Relaxed) and one is a
 * CC0 recording (Chillin, public/audio/, see CREDITS.md) decoded into an
 * AudioBuffer and looped. Both kinds go through the same per-track gain ->
 * music bus, so the sliders and the mood crossfade treat them alike. The AudioContext is only created/resumed from a
 * user gesture (browser autoplay policy): see installGestureUnlock().
 */

import type { Mood, Settings } from "./settings";

export type Sfx = "swing" | "hit" | "join" | "leave" | "step" | "bananaStep" | "click";

const CROSSFADE_S = 1.5;
const LOOKAHEAD_S = 0.15;
const SCHEDULER_MS = 25;
/** Overall levels of the two buses at 100% (headroom for the mix). */
const MUSIC_LEVEL = 1.0;
const SFX_LEVEL = 0.9;

const hz = (midi: number) => 440 * 2 ** ((midi - 69) / 12);

/** 0-100 slider value -> gain, with a perceptual (squared) curve. */
const sliderGain = (value: number) => (Math.min(100, Math.max(0, value)) / 100) ** 2;

interface ToneOpts {
  type?: OscillatorType;
  gain?: number;
  attack?: number;
  /** seconds held at full level after the attack */
  hold?: number;
  /** exponential release time (seconds) */
  release?: number;
  /** low-pass cutoff (Hz) */
  filter?: number;
  detune?: number;
  /** glide the pitch to this frequency over the hold */
  glideTo?: number;
  /** [rate Hz, depth Hz] */
  vibrato?: [number, number];
}

interface NoiseOpts {
  gain?: number;
  attack?: number;
  release?: number;
  filter?: BiquadFilterType;
  freq?: number;
  q?: number;
  /** sweep the filter frequency to this over attack + release */
  sweepTo?: number;
}

/** Tiny synth voices rendered into one destination node. */
class Synth {
  constructor(
    readonly ctx: AudioContext,
    readonly dest: AudioNode,
    private readonly noiseBuffer: AudioBuffer
  ) {}

  tone(t: number, freq: number, o: ToneOpts = {}) {
    const { ctx } = this;
    const attack = o.attack ?? 0.005;
    const hold = o.hold ?? 0;
    const release = o.release ?? 0.2;
    const end = t + attack + hold + release;

    const osc = ctx.createOscillator();
    osc.type = o.type ?? "sine";
    osc.frequency.setValueAtTime(freq, t);
    if (o.glideTo) osc.frequency.exponentialRampToValueAtTime(o.glideTo, t + attack + hold);
    if (o.detune) osc.detune.value = o.detune;

    const env = ctx.createGain();
    env.gain.setValueAtTime(0, t);
    env.gain.linearRampToValueAtTime(o.gain ?? 0.2, t + attack);
    env.gain.setValueAtTime(o.gain ?? 0.2, t + attack + hold);
    env.gain.exponentialRampToValueAtTime(0.0001, end);

    let head: AudioNode = osc;
    if (o.filter) {
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = o.filter;
      osc.connect(lp);
      head = lp;
    }
    head.connect(env).connect(this.dest);

    if (o.vibrato) {
      const lfo = ctx.createOscillator();
      const depth = ctx.createGain();
      lfo.frequency.value = o.vibrato[0];
      depth.gain.value = o.vibrato[1];
      lfo.connect(depth).connect(osc.frequency);
      lfo.start(t);
      lfo.stop(end + 0.05);
    }
    osc.start(t);
    osc.stop(end + 0.05);
  }

  noise(t: number, o: NoiseOpts = {}) {
    const { ctx } = this;
    const attack = o.attack ?? 0.002;
    const release = o.release ?? 0.08;
    const src = ctx.createBufferSource();
    src.buffer = this.noiseBuffer;
    // Start somewhere random in the buffer so repeated hits don't sound identical.
    const offset = Math.random() * (this.noiseBuffer.duration - 0.5);

    const filter = ctx.createBiquadFilter();
    filter.type = o.filter ?? "highpass";
    filter.frequency.setValueAtTime(o.freq ?? 6000, t);
    if (o.sweepTo) filter.frequency.exponentialRampToValueAtTime(o.sweepTo, t + attack + release);
    filter.Q.value = o.q ?? 0.7;

    const env = ctx.createGain();
    env.gain.setValueAtTime(0, t);
    env.gain.linearRampToValueAtTime(o.gain ?? 0.1, t + attack);
    env.gain.exponentialRampToValueAtTime(0.0001, t + attack + release);

    src.connect(filter).connect(env).connect(this.dest);
    src.start(t, offset);
    src.stop(t + attack + release + 0.05);
  }

  /** Sine with a fast pitch drop: kick drum / heartbeat thump. */
  kick(t: number, gain: number, from = 150, to = 45, release = 0.22) {
    this.tone(t, from, { gain, attack: 0.003, release, glideTo: to });
  }
}

interface StepInfo {
  syn: Synth;
  /** start time of this step (seconds, AudioContext clock), swing applied */
  t: number;
  bar: number;
  /** 16th-note step within the bar, 0-15 */
  s: number;
  /** seconds per 16th */
  dur: number;
}

interface TrackDef {
  bpm: number;
  bars: number;
  /** delay of every other 8th note, as a fraction of a 16th */
  swing?: number;
  step(info: StepInfo): void;
}

// --- Happy: bouncy C-major chiptune, 132 bpm (C G Am F) -------------------
const HAPPY_CHORDS = [
  [60, 64, 67],
  [55, 59, 62],
  [57, 60, 64],
  [53, 57, 60],
];
const HAPPY_BASS = [36, 43, 45, 41];
const _ = 0;
const HAPPY_LEAD = [
  [76, _, 79, _, 84, _, 79, _, 76, _, 79, _, 81, 79, _, _],
  [79, _, 83, _, 86, _, 83, _, 79, _, 77, _, 76, _, 74, _],
  [76, _, 81, _, 84, _, 81, _, 76, _, 72, _, 74, 76, _, _],
  [77, _, 81, _, 84, _, 81, _, 79, _, 77, _, 76, _, 74, _],
];

const HAPPY: TrackDef = {
  bpm: 132,
  bars: 4,
  step({ syn, t, bar, s, dur }) {
    const chord = HAPPY_CHORDS[bar];
    const root = HAPPY_BASS[bar];
    const lead = HAPPY_LEAD[bar][s];
    if (lead) {
      syn.tone(t, hz(lead), { type: "square", gain: 0.045, hold: dur * 1.1, release: 0.07, filter: 3400 });
    }
    // Offbeat arpeggio sparkle.
    if (s % 2 === 1) {
      syn.tone(t, hz(chord[(s >> 1) % 3] + 12), { type: "triangle", gain: 0.03, release: 0.08 });
    }
    // Bouncing octave bass.
    if (s % 4 === 0 || s === 14) {
      const note = s === 14 ? root + 7 : s % 8 === 4 ? root + 12 : root;
      syn.tone(t, hz(note), { type: "square", gain: 0.07, hold: dur * 1.4, release: 0.05, filter: 700 });
    }
    // Drums: kick on 1 & 3, snare on 2 & 4, closed hats on 8ths.
    if (s === 0 || s === 8 || (bar === 3 && s === 11)) syn.kick(t, 0.5);
    if (s === 4 || s === 12) syn.noise(t, { filter: "bandpass", freq: 1900, q: 0.9, gain: 0.16, release: 0.11 });
    if (s % 2 === 0) syn.noise(t, { freq: 7500, gain: s % 4 === 2 ? 0.05 : 0.03, release: 0.03 });
  },
};

// --- Spooky: slow, minor / diminished, eerie, 70 bpm (Am Bb Am G#dim7) ------
const SPOOKY_CHORDS = [
  [57, 60, 64],
  [58, 62, 65],
  [57, 60, 64],
  [56, 59, 62, 65],
];
const SPOOKY_BELLS: Record<number, number>[] = [
  { 0: 76, 6: 84, 11: 75 },
  { 0: 77, 7: 82, 12: 76 },
  { 0: 76, 6: 84, 11: 87 },
  { 0: 80, 5: 77, 10: 74, 14: 71 },
];

const SPOOKY: TrackDef = {
  bpm: 70,
  bars: 4,
  step({ syn, t, bar, s, dur }) {
    const barLen = dur * 16;
    if (s === 0) {
      // Breathy detuned pad that swells in and out over the bar.
      for (const note of SPOOKY_CHORDS[bar]) {
        for (const detune of [-9, 9]) {
          syn.tone(t, hz(note), {
            type: "triangle", gain: 0.032, attack: barLen * 0.45, hold: barLen * 0.35,
            release: barLen * 0.5, filter: 1300, detune,
          });
        }
      }
      // Low A drone.
      syn.tone(t, hz(33), { gain: 0.12, attack: 1.2, hold: barLen - 1.2, release: 1.5 });
      syn.tone(t, hz(45), { type: "triangle", gain: 0.03, attack: 1.5, hold: barLen - 1.5, release: 1.5, filter: 500 });
    }
    // Heartbeat: lub-dub.
    if (s === 0) syn.kick(t, 0.32, 90, 38, 0.3);
    if (s === 2) syn.kick(t, 0.2, 80, 36, 0.3);
    // Music-box bells with an inharmonic partial.
    const bell = SPOOKY_BELLS[bar][s];
    if (bell) {
      syn.tone(t, hz(bell), { gain: 0.06, release: 2.4 });
      syn.tone(t, hz(bell) * 2.76, { gain: 0.018, release: 1.2 });
    }
    // Theremin wail sliding down on bars 2 and 4.
    if ((bar === 1 || bar === 3) && s === 4) {
      syn.tone(t, hz(bar === 1 ? 76 : 77), {
        gain: 0.05, attack: 0.6, hold: barLen * 0.5, release: 1.2,
        glideTo: hz(bar === 1 ? 71 : 68), vibrato: [5.5, 7],
      });
    }
    // Wind gust.
    if (bar === 0 && s === 8) {
      syn.noise(t, { filter: "bandpass", freq: 350, sweepTo: 1100, q: 3, gain: 0.05, attack: 1.4, release: 2.2 });
    }
  },
};

// --- Relaxed: lo-fi, mellow 7th chords, swung, 76 bpm (Fmaj7 Em7 Dm7 Cmaj7) --
// (This was the "Chillin" mood before Chillin became the CC0 recording.)
const CHILL_CHORDS = [
  [53, 57, 60, 64],
  [52, 55, 59, 62],
  [50, 53, 57, 60],
  [48, 52, 55, 59],
];
const CHILL_BASS = [41, 40, 38, 36];
const CHILL_MELODY: Record<number, number>[] = [
  { 2: 72, 5: 74, 8: 69 },
  { 3: 71, 8: 67 },
  { 2: 69, 6: 72, 9: 74, 12: 72 },
  { 4: 67, 8: 64 },
];
/** Deterministic hash in [0,1) for vinyl crackle placement. */
const crackle = (bar: number, s: number) => ((Math.sin(bar * 91.7 + s * 12.9898) * 43758.5453) % 1 + 1) % 1;

const RELAXED: TrackDef = {
  bpm: 76,
  bars: 4,
  swing: 0.33,
  step({ syn, t, bar, s, dur }) {
    const chord = CHILL_CHORDS[bar];
    const root = CHILL_BASS[bar];
    // Soft electric-piano chords, gently strummed.
    if (s === 0 || s === 10) {
      chord.forEach((note, i) => {
        const at = t + i * 0.014;
        const release = s === 0 ? 1.9 : 1.1;
        syn.tone(at, hz(note), { gain: 0.04, attack: 0.012, release, filter: 1500 });
        syn.tone(at, hz(note + 12), { type: "triangle", gain: 0.008, attack: 0.012, release: release * 0.6, filter: 1800 });
      });
    }
    // Round bass.
    if (s === 0 || s === 6 || s === 10) {
      const note = s === 10 ? root + 7 : root;
      syn.tone(t, hz(note), { gain: 0.13, attack: 0.01, hold: dur * 2, release: 0.35, filter: 400 });
    }
    // Sparse pentatonic melody.
    const lead = CHILL_MELODY[bar][s];
    if (lead) syn.tone(t, hz(lead), { type: "triangle", gain: 0.03, attack: 0.02, release: 0.7, filter: 2000 });
    // Dusty drums.
    if (s === 0 || s === 7 || s === 10) syn.kick(t, 0.3, 110, 45, 0.25);
    if (s === 4 || s === 12) syn.noise(t, { filter: "bandpass", freq: 1300, q: 0.8, gain: 0.07, release: 0.16 });
    if (s % 2 === 0) syn.noise(t, { freq: 6500, gain: 0.014, release: 0.035 });
    // Vinyl crackle.
    if (crackle(bar, s) < 0.35) syn.noise(t + dur * crackle(s, bar), { freq: 2500, gain: 0.012, release: 0.008 });
  },
};

/** A recorded loop: tried in order, first format the browser can play wins. */
interface FileTrackDef {
  urls: { url: string; type: string }[];
  /** level trim so it sits with the synth tracks */
  gain: number;
}

const BASE = import.meta.env.BASE_URL;

const TRACKS: Record<Mood, TrackDef | FileTrackDef> = {
  happy: HAPPY,
  spooky: SPOOKY,
  relaxed: RELAXED,
  // "Lofi Hip Hop Loop" by omfgdude (OMF-Games), CC0 - public/audio/CREDITS.md
  chillin: {
    urls: [
      { url: `${BASE}audio/lofi-hip-hop-loop.ogg`, type: 'audio/ogg; codecs="vorbis"' },
      { url: `${BASE}audio/lofi-hip-hop-loop.mp3`, type: "audio/mpeg" },
    ],
    gain: 0.9,
  },
};

const isFileTrack = (def: TrackDef | FileTrackDef): def is FileTrackDef => "urls" in def;

type LoadStatus = "idle" | "loading" | "ready" | "error";

/** What GameAudio needs from a playing track (synth or file). */
interface Track {
  readonly mood: Mood;
  readonly out: GainNode;
  /** steps scheduled (synth) or loops started (file), for inspection */
  readonly scheduled: number;
  start(at: number): void;
  stop(): void;
  dispose(): void;
}

/** A decoded recording looping forever into its own gain node. */
class FileTrack implements Track {
  readonly out: GainNode;
  private source: AudioBufferSourceNode | null = null;
  scheduled = 0;

  constructor(
    private readonly ctx: AudioContext,
    dest: AudioNode,
    private readonly buffer: AudioBuffer,
    readonly mood: Mood,
    private readonly trim: number
  ) {
    this.out = ctx.createGain();
    this.out.connect(dest);
  }

  start(at: number) {
    const src = this.ctx.createBufferSource();
    src.buffer = this.buffer;
    src.loop = true;
    const trim = this.ctx.createGain();
    trim.gain.value = this.trim;
    src.connect(trim).connect(this.out);
    src.start(at);
    this.source = src;
    this.scheduled = 1;
  }

  stop() {
    try {
      this.source?.stop();
    } catch {
      // already stopped
    }
    this.source = null;
  }

  dispose() {
    this.stop();
    this.out.disconnect();
  }
}

/** One running synth track: a look-ahead step scheduler feeding its own gain node. */
class SynthTrack implements Track {
  readonly out: GainNode;
  private readonly syn: Synth;
  private timer: number | null = null;
  private next = 0;
  private step = 0;
  /** steps scheduled so far (debug/inspection) */
  scheduled = 0;

  constructor(
    private readonly ctx: AudioContext,
    dest: AudioNode,
    noise: AudioBuffer,
    readonly mood: Mood,
    private readonly def: TrackDef
  ) {
    this.out = ctx.createGain();
    this.out.connect(dest);
    this.syn = new Synth(ctx, this.out, noise);
  }

  start(at: number) {
    this.next = at;
    this.pump();
    this.timer = window.setInterval(() => this.pump(), SCHEDULER_MS);
  }

  private pump() {
    const def = this.def;
    const dur = 60 / def.bpm / 4;
    const now = this.ctx.currentTime;
    // Timers are throttled in background tabs: rather than firing a burst
    // of late notes, skip ahead.
    if (this.next < now - 0.1) this.next = now + 0.05;
    while (this.next < now + LOOKAHEAD_S) {
      const s = this.step % 16;
      const swing = def.swing && s % 4 === 2 ? def.swing * dur : 0;
      def.step({
        syn: this.syn,
        t: this.next + swing,
        bar: Math.floor(this.step / 16) % def.bars,
        s,
        dur,
      });
      this.scheduled++;
      this.next += dur;
      this.step = (this.step + 1) % (16 * def.bars);
    }
  }

  stop() {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
  }

  dispose() {
    this.stop();
    this.out.disconnect();
  }
}

export interface AudioDebugState {
  context: AudioContextState | "none";
  mood: Mood;
  /** mood of the track currently fading in / playing */
  playing: Mood | null;
  /** tracks still fading out */
  fadingOut: Mood[];
  scheduledSteps: number;
  /** "synth" or "file" for the current track */
  source: "synth" | "file" | null;
  /** load state of each recorded track */
  files: Partial<Record<Mood, LoadStatus>>;
  /** which URL the recorded track was decoded from */
  fileUrl: Partial<Record<Mood, string>>;
  gains: { master: number; music: number; sfx: number };
  sfxPlayed: number;
  /** last sound effect played (debug / tests) */
  lastSfx: Sfx | null;
}

export class GameAudio {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private music!: GainNode;
  private sfx!: GainNode;
  private noise!: AudioBuffer;
  private sfxSynth!: Synth;
  private track: Track | null = null;
  private fading: Track[] = [];
  private settings: Settings;
  private sfxPlayed = 0;
  private lastSfx: Sfx | null = null;
  /** Banana James alternates feet: left / right squeak at slightly different pitches. */
  private bananaFoot = false;
  private lastJoin = 0;
  private buffers = new Map<Mood, AudioBuffer>();
  private loads = new Map<Mood, LoadStatus>();
  private loadedFrom = new Map<Mood, string>();

  constructor(settings: Settings) {
    this.settings = { ...settings };
  }

  /**
   * Create / resume the AudioContext on the first click, tap or key press
   * (browsers refuse to start audio before a user gesture).
   */
  installGestureUnlock(target: Window = window) {
    const events = ["pointerdown", "keydown", "touchend"] as const;
    const onGesture = () => {
      this.unlock();
      if (this.ctx?.state === "running") {
        events.forEach(e => target.removeEventListener(e, onGesture, true));
      }
    };
    events.forEach(e => target.addEventListener(e, onGesture, true));

    // Pause the synth while the tab is hidden; pick up again when visible.
    document.addEventListener("visibilitychange", () => {
      if (!this.ctx) return;
      if (document.hidden) void this.ctx.suspend();
      else void this.ctx.resume();
    });
  }

  unlock() {
    if (!this.ctx) {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return;
      const ctx = new Ctor();
      this.ctx = ctx;
      this.master = ctx.createGain();
      this.music = ctx.createGain();
      this.sfx = ctx.createGain();
      this.music.connect(this.master);
      this.sfx.connect(this.master);
      // Gentle limiter so everything at 100% can't clip.
      const limiter = ctx.createDynamicsCompressor();
      limiter.threshold.value = -6;
      limiter.knee.value = 6;
      limiter.ratio.value = 12;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.2;
      this.master.connect(limiter).connect(ctx.destination);

      this.noise = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
      const data = this.noise.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
      this.sfxSynth = new Synth(ctx, this.sfx, this.noise);

      this.applyVolumes(true);
    }
    if (this.ctx.state === "suspended") {
      void this.ctx.resume().then(() => this.ensureMusic());
    } else {
      this.ensureMusic();
    }
  }

  /** Apply changed settings: volumes glide, a new mood crossfades. */
  apply(settings: Readonly<Settings>) {
    this.settings = { ...settings };
    if (!this.ctx) return;
    this.applyVolumes(false);
    this.ensureMusic();
  }

  playSfx(name: Sfx, volume = 1) {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== "running" || volume <= 0) return;
    const t = ctx.currentTime + 0.005;
    const syn = this.sfxSynth;
    const v = Math.min(1, volume);
    switch (name) {
      case "swing": // whoosh
        syn.noise(t, { filter: "bandpass", freq: 500, sweepTo: 2800, q: 1.6, gain: 0.5 * v, attack: 0.04, release: 0.16 });
        break;
      case "hit": // boing + sparkle + click
        syn.tone(t, 560, { type: "square", gain: 0.13 * v, hold: 0.03, release: 0.14, glideTo: 170, filter: 2600 });
        syn.tone(t + 0.04, 1320, { gain: 0.08 * v, release: 0.18 });
        syn.noise(t, { freq: 3000, gain: 0.25 * v, release: 0.025 });
        break;
      case "join": { // bright two-note blip (throttled: bots join in a burst)
        if (t - this.lastJoin < 0.15) return;
        this.lastJoin = t;
        syn.tone(t, 880, { type: "square", gain: 0.07 * v, release: 0.07, filter: 4000 });
        syn.tone(t + 0.075, 1320, { type: "square", gain: 0.07 * v, release: 0.1, filter: 4000 });
        break;
      }
      case "leave":
        syn.tone(t, 660, { type: "square", gain: 0.06 * v, release: 0.07, filter: 3000 });
        syn.tone(t + 0.075, 440, { type: "square", gain: 0.06 * v, release: 0.1, filter: 3000 });
        break;
      case "step": // soft footstep tick
        syn.noise(t, { filter: "lowpass", freq: 700 + Math.random() * 400, gain: 0.22 * v, release: 0.035 });
        syn.tone(t, 110 + Math.random() * 20, { gain: 0.07 * v, release: 0.04 });
        break;
      case "bananaStep": { // Banana James: squelchy squish + rubbery squeak-boing
        this.bananaFoot = !this.bananaFoot;
        const base = (this.bananaFoot ? 330 : 270) * (0.94 + Math.random() * 0.12);
        syn.noise(t, { filter: "bandpass", freq: 1500, sweepTo: 320, q: 2.4, gain: 0.32 * v, attack: 0.004, release: 0.075 });
        syn.tone(t + 0.012, base, {
          type: "triangle",
          glideTo: base * 2.2,
          attack: 0.008,
          hold: 0.045,
          release: 0.1,
          gain: 0.1 * v,
          vibrato: [30, 28],
          filter: 2800,
        });
        syn.tone(t, 95, { gain: 0.06 * v, release: 0.05 });
        break;
      }
      case "click":
        syn.tone(t, 1250, { type: "triangle", gain: 0.08 * v, release: 0.035 });
        break;
    }
    this.sfxPlayed++;
    this.lastSfx = name;
  }

  /** Snapshot for debugging / tests. */
  get state(): AudioDebugState {
    return {
      context: this.ctx?.state ?? "none",
      mood: this.settings.mood,
      playing: this.track?.mood ?? null,
      fadingOut: this.fading.map(t => t.mood),
      scheduledSteps: this.track?.scheduled ?? 0,
      source: this.track ? (this.track instanceof FileTrack ? "file" : "synth") : null,
      files: Object.fromEntries(this.loads),
      fileUrl: Object.fromEntries(this.loadedFrom),
      gains: this.ctx
        ? { master: this.master.gain.value, music: this.music.gain.value, sfx: this.sfx.gain.value }
        : { master: 0, music: 0, sfx: 0 },
      sfxPlayed: this.sfxPlayed,
      lastSfx: this.lastSfx,
    };
  }

  private applyVolumes(immediate: boolean) {
    const ctx = this.ctx!;
    const set = (param: AudioParam, value: number) => {
      if (immediate) param.value = value;
      else param.setTargetAtTime(value, ctx.currentTime, 0.04);
    };
    set(this.master.gain, sliderGain(this.settings.masterVolume));
    set(this.music.gain, sliderGain(this.settings.musicVolume) * MUSIC_LEVEL);
    set(this.sfx.gain, sliderGain(this.settings.sfxVolume) * SFX_LEVEL);
  }

  /** Start the track for the current mood, crossfading from any other. */
  private ensureMusic() {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== "running") return;
    const mood = this.settings.mood;
    if (this.track?.mood === mood) return;

    // A recorded track has to be fetched and decoded first; keep the old
    // music playing meanwhile, then crossfade as usual once it's ready.
    const def = TRACKS[mood];
    if (isFileTrack(def) && !this.buffers.has(mood)) {
      if (this.loads.get(mood) !== "loading") void this.loadFile(mood, def);
      return;
    }

    const now = ctx.currentTime;
    const old = this.track;
    if (old) {
      const g = old.out.gain;
      g.cancelScheduledValues(now);
      g.setValueAtTime(g.value, now);
      g.linearRampToValueAtTime(0, now + CROSSFADE_S);
      this.fading.push(old);
      window.setTimeout(() => {
        old.dispose();
        this.fading = this.fading.filter(t => t !== old);
      }, CROSSFADE_S * 1000 + 600);
      // Stop scheduling new notes once it's mostly faded.
      window.setTimeout(() => old.stop(), CROSSFADE_S * 1000);
    }

    const track: Track = isFileTrack(def)
      ? new FileTrack(ctx, this.music, this.buffers.get(mood)!, mood, def.gain)
      : new SynthTrack(ctx, this.music, this.noise, mood, def);
    track.out.gain.setValueAtTime(0, now);
    track.out.gain.linearRampToValueAtTime(1, now + (old ? CROSSFADE_S : 0.6));
    track.start(now + 0.05);
    this.track = track;
  }

  /** Fetch + decode a recorded track (first playable format), then start it. */
  private async loadFile(mood: Mood, def: FileTrackDef) {
    const ctx = this.ctx!;
    this.loads.set(mood, "loading");
    const probe = document.createElement("audio");
    // Formats the browser says it can play first, the rest as a fallback.
    const candidates = [...def.urls].sort(
      (a, b) => Number(!probe.canPlayType(a.type)) - Number(!probe.canPlayType(b.type))
    );
    for (const { url } of candidates) {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const buffer = await ctx.decodeAudioData(await response.arrayBuffer());
        this.buffers.set(mood, buffer);
        this.loadedFrom.set(mood, url);
        this.loads.set(mood, "ready");
        this.ensureMusic(); // crossfades in if this mood is still selected
        return;
      } catch (error) {
        console.warn(`[audio] couldn't load ${url}:`, error);
      }
    }
    this.loads.set(mood, "error");
  }
}
