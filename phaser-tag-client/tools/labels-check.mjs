// Label stack check: for every kid (local + remote), the visible lines go
// IT, (4px gap), YOU, name bottom-up without overlapping; and no two idle
// kids' stacks overlap after joining. Scenarios: fresh joins (2 browsers + a
// raw ws player), every skin, IT gained / lost at runtime, top wall.
//
// Run with the dev server (vite, :5199) and backend (:8000) up:
//   node --experimental-websocket tools/labels-check.mjs
// Env: PLAYWRIGHT (path to playwright's index.js, default "playwright"),
//      CLIENT_URL, WS_URL, SHOTS (screenshot dir, default /tmp).
const { default: pkg } = await import(process.env.PLAYWRIGHT ?? "playwright");
const { chromium } = pkg;
const SHOTS = process.env.SHOTS ?? "/tmp";
const SKINS = ["james", "banana", "trex", "tuxedo", "pirate"];
const TIGHTEN = 5, IT_GAP = 4, EPS = 0.6;
const browser = await chromium.launch({ headless: true });
let failures = 0;
const fail = (m) => { failures++; console.log("  FAIL " + m); };

const spy = new WebSocket((process.env.WS_URL ?? "ws://127.0.0.1:8000/ws"));
spy.onopen = () => spy.send(JSON.stringify({ type: "Join", data: { room_id: "default", skin: "james" } }));

async function client(skin) {
  const ctx = await browser.newContext({ viewport: { width: 1024, height: 700 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on("pageerror", e => fail("pageerror " + e.message));
  await page.addInitScript(s => localStorage.setItem("tag26.settings", JSON.stringify({ controlMode: "keyboard", skin: s })), skin);
  await page.goto((process.env.CLIENT_URL ?? "http://127.0.0.1:5199/"));
  await page.waitForSelector(".title-start"); await page.click(".title-start");
  await page.waitForFunction(() => window.__scene?.player);
  await page.waitForTimeout(800);
  return page;
}

// Ink box of a label line = its text bounds minus the stroke padding that
// LABEL_TIGHTEN overlaps by design.
const stacks = (page) => page.evaluate(() => {
  const s = window.__scene, out = [];
  const add = (who, a) => {
    const L = a.labels, lines = [];
    for (const k of ["name", "you", "it"]) {
      const t = L[k]; if (!t.visible) continue;
      lines.push({ k, top: t.y - t.height, bottom: t.y, left: t.x - t.width / 2, right: t.x + t.width / 2, h: t.height });
    }
    out.push({ who, skin: a.currentSkin, x: a.x, y: a.y, moving: a.moving, lines, headTop: a.feetY - 0 });
  };
  if (s.player) add("local", s.player);
  for (const [id, r] of s.remotePlayers) add("remote " + r.snapshot.name, r.avatar);
  return out;
});

function checkStack(st, label) {
  const ls = st.lines; // bottom-up order: name, you, it
  for (let i = 1; i < ls.length; i++) {
    const lower = ls[i - 1], upper = ls[i];
    const inkLowerTop = lower.top + TIGHTEN / 2, inkUpperBottom = upper.bottom - TIGHTEN / 2;
    const need = upper.k === "it" ? IT_GAP : 0;
    const gap = inkLowerTop - inkUpperBottom;
    if (gap < need - EPS) fail(`${label} ${st.who} [${st.skin}]: ${upper.k} over ${lower.k} gap ${gap.toFixed(1)} < ${need}`);
  }
  if (ls.length && ls[ls.length - 1].top + TIGHTEN / 2 < 0) fail(`${label} ${st.who}: stack above the world top`);
}
function inkBox(st) {
  const ls = st.lines; if (!ls.length) return null;
  return { l: Math.min(...ls.map(l => l.left)) + 2, r: Math.max(...ls.map(l => l.right)) - 2, t: ls[ls.length - 1].top + 2.5, b: ls[0].bottom - 2.5 };
}
function checkCross(all, label) {
  const idle = all.filter(s => !s.moving);
  for (let i = 0; i < idle.length; i++) for (let j = i + 1; j < idle.length; j++) {
    const a = inkBox(idle[i]), b = inkBox(idle[j]); if (!a || !b) continue;
    if (a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b)
      fail(`${label}: stacks of ${idle[i].who} and ${idle[j].who} overlap (at ${Math.round(idle[i].x)},${Math.round(idle[i].y)} / ${Math.round(idle[j].x)},${Math.round(idle[j].y)})`);
  }
}
async function checkPage(page, label, cross = false) {
  const all = await stacks(page);
  for (const st of all) checkStack(st, label);
  if (cross) checkCross(all, label);
  return all;
}

// 1. Fresh joins: A, B and the raw ws player all idle near the spawn.
const A = await client("pirate");
const B = await client("james");
await B.waitForTimeout(600);
console.log("1. fresh joins (2 browsers + ws player)");
for (const [n, p] of [["A", A], ["B", B]]) {
  const all = await checkPage(p, "join/" + n, true);
  const humans = all.filter(s => !s.who.startsWith("remote James") || true).filter(s => Math.hypot(s.x - 400, s.y - 300) < 400);
  console.log(`   ${n}: kids near spawn ${humans.map(h => `${h.who}@${Math.round(h.x)},${Math.round(h.y)}`).join(" | ")}`);
}

// 1b. Sanity: the check does catch the original bug (two idle kids on one spot).
{
  const before = failures;
  const all = await B.evaluate(() => { const s = window.__scene; const r = [...s.remotePlayers.values()].find(r => !r.snapshot.is_bot); return r ? [r.avatar.x, r.avatar.y] : null; });
  const saved = await B.evaluate(() => [window.__scene.player.x, window.__scene.player.y]);
  await B.evaluate(([x, y]) => { const p = window.__scene.player; p.x = x; p.y = y; p.moving = false; p.update(); }, all);
  const quiet = console.log; console.log = (...a) => { if (!String(a[0]).includes("FAIL sanity")) quiet(...a); };
  const st = await stacks(B); checkCross(st.map(s => ({ ...s, moving: false })), "sanity"); console.log = quiet;
  const caught = failures - before; failures = before;
  console.log(`1b. sanity: co-located kids flagged: ${caught > 0 ? "yes" : "NO (check is broken)"}`);
  if (!caught) fail("sanity check did not detect co-located stacks");
  await B.evaluate(([x, y]) => { const p = window.__scene.player; p.x = x; p.y = y; p.update(); }, saved);
}
spy.close();  // the ws player leaves: IT moves on and the bots start tagging

// 2. Every skin x IT on/off, local and remote (forced + real update()).
console.log("2. every skin, IT gained / lost, local + remote");
for (const skin of SKINS) {
  for (const it of [true, false, true]) {
    const res = await A.evaluate(([skin, it]) => {
      const s = window.__scene;
      const kids = [s.player, ...[...s.remotePlayers.values()].map(r => r.avatar)];
      for (const k of kids) {
        k.setSkin(skin);
        const name = k.labels.name.text;
        k.setLabels({ name, you: k === s.player, it });
        k.update();
      }
      return true;
    }, [skin, it]);
    void res;
    await checkPage(A, `skin ${skin} it=${it}`);
  }
}
// restore real skins / labels from the next snapshots
await A.evaluate(() => { const s = window.__scene; s.player.setSkin(s.localSkin); });
await A.waitForTimeout(300);

// 3. Real IT changes mid-game (server-driven): B walks into whoever is IT
// until tagged (gain), then chases the nearest kid and tags it (loss).
console.log("3. live IT gain + loss for B's local player, sampling both pages");
const info = (p) => p.evaluate(() => {
  const s = window.__scene, me = s.player;
  const kids = [...s.remotePlayers.values()].map(r => ({ x: r.avatar.x, y: r.avatar.y, it: r.snapshot.is_it, name: r.snapshot.name }));
  return { x: me.x, y: me.y, it: me.labels.it.visible, kids };
});
async function step(p, tx, ty, ms = 140) {
  const me = await info(p); const keys = [];
  if (Math.abs(tx - me.x) > 8) keys.push(tx < me.x ? "ArrowLeft" : "ArrowRight");
  if (Math.abs(ty - me.y) > 8) keys.push(ty < me.y ? "ArrowUp" : "ArrowDown");
  for (const k of keys) await p.keyboard.down(k);
  await p.waitForTimeout(ms);
  for (const k of keys) await p.keyboard.up(k);
}
let gained = 0, lost = 0, lastIt = (await info(B)).it, remoteItSeen = new Set(), aSawRemoteIt = 0;
const sample = async () => {
  for (const [n, p] of [["A", A], ["B", B]]) {
    const all = await checkPage(p, "live/" + n);
    for (const s of all) if (s.who !== "local" && s.lines.some(l => l.k === "it")) { remoteItSeen.add(n + ":" + s.who); }
  }
  const now = (await info(B)).it;
  if (now !== lastIt) { now ? gained++ : lost++; if (now && gained === 1) await B.screenshot({ path: `${SHOTS}/labels_live_it.png` }); }
  lastIt = now;
};
const t0 = Date.now();
while (Date.now() - t0 < 120000 && !(gained && lost)) {
  const me = await info(B);
  if (!me.it) { const it = me.kids.find(k => k.it); if (it) await step(B, it.x, it.y, Math.hypot(it.x - me.x, it.y - me.y) > 150 ? 350 : 140); }
  else if (!gained) { gained++; } // already IT at start: count once, go tag
  else {
    const a = await info(A); // chase A (an idle human, never the kid who just tagged B)
    await step(B, a.x, a.y, Math.hypot(a.x - me.x, a.y - me.y) > 150 ? 350 : 90);
    if (Math.hypot(a.x - me.x, a.y - me.y) < 45) await B.keyboard.press("Space");
  }
  await sample();
}
if (!gained) fail("never saw B's local player gain IT at runtime");
if (!lost) fail("never saw B's local player lose IT at runtime");
await B.waitForTimeout(400); await sample();
console.log(`   A's local player IT after B's tag: ${(await info(A)).it}`);
console.log(`   B local IT gained ${gained}x, lost ${lost}x in ${((Date.now() - t0) / 1000).toFixed(1)}s; remote kids seen as IT (A/B views): ${remoteItSeen.size}`);
await B.screenshot({ path: `${SHOTS}/labels_live.png` });

// 4. Top wall: walk A up against the fence, IT forced on for the tallest stack.
console.log("4. top wall");
await A.keyboard.down("ArrowUp"); await A.waitForTimeout(3500); await A.keyboard.up("ArrowUp");
await A.waitForTimeout(400);
for (const skin of SKINS) {
  await A.evaluate((skin) => { const s = window.__scene; s.player.setSkin(skin); s.player.setLabels({ name: s.player.labels.name.text, you: true, it: true }); s.player.update(); }, skin);
  const all = await checkPage(A, "topwall " + skin);
  const loc = all.find(s => s.who === "local");
  console.log(`   ${skin}: player y ${Math.round(loc.y)}, stack top ${Math.round(loc.lines.at(-1).top)}`);
}
// screenshot (pirate, IT+YOU+name) zoomed at the wall
await A.evaluate(() => { const s = window.__scene; s.player.setSkin("pirate"); s.player.setLabels({ name: s.player.labels.name.text, you: true, it: true }); s.player.update(); });
const wall = await A.evaluate(() => { const s = window.__scene, c = s.cameras.main, p = s.player; return { x: (p.x - c.scrollX) * c.zoom, y: (p.feetY - c.scrollY) * c.zoom, top: (p.labelTop - c.scrollY) * c.zoom }; });
await A.screenshot({ path: `${SHOTS}/labels_topwall_full.png` });
console.log("   wall screen", JSON.stringify(wall));

console.log(failures ? `FAILURES ${failures}` : "ALL LABEL CHECKS PASSED");
await browser.close(); process.exit(failures ? 1 : 0);
