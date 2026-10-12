// The courtroom graph from the Console's case page, replaying a sample case.
(() => {
  const root = document.getElementById("court-graph");
  if (!root) return;
  const svg = root.querySelector("svg");
  const caption = root.querySelector(".graph-caption");
  const replay = root.querySelector(".graph-replay");
  const NS = "http://www.w3.org/2000/svg";
  const W = 132, H = 54;

  const AGENTS = {
    system: ["System", "#606b85", "Tier 0 screen", -210, 200],
    clerk: ["Clerk", "#0263e0", "Evidence intake", 0, 200],
    geo: ["Geo", "#0b7a8a", "Expert witness", 210, 0],
    device: ["Device", "#0b7a8a", "Expert witness", 210, 95],
    velocity: ["Velocity", "#0b7a8a", "Expert witness", 210, 190],
    merchant: ["Merchant", "#0b7a8a", "Expert witness", 210, 285],
    graph: ["Graph", "#0b7a8a", "Expert witness", 210, 380],
    prosecutor: ["Prosecutor", "#d61f1f", "Argues BLOCK", 430, 110],
    defense: ["Defense", "#14b053", "Argues APPROVE", 430, 290],
    judge: ["Judge", "#6d2ed1", "Rules p_fraud", 650, 200],
    bailiff: ["Bailiff", "#c25700", "Witness auth", 870, 90],
    witness: ["Witness", "#121c2d", "Cardholder", 1090, 90],
    stenographer: ["Stenographer", "#4b5671", "Explains verdict", 870, 320],
  };
  const EXPERTS = ["geo", "device", "velocity", "merchant", "graph"];
  const LINKS = [
    ["system", "clerk"],
    ...EXPERTS.map((e) => ["clerk", e]),
    ...EXPERTS.flatMap((e) => [[e, "prosecutor"], [e, "defense"]]),
    ["prosecutor", "defense"], ["prosecutor", "judge"], ["defense", "judge"],
    ["judge", "bailiff"], ["bailiff", "witness"], ["witness", "judge"], ["judge", "stenographer"],
  ];

  // [agent speaking, links that light up, what happened]
  const STEPS = [
    ["system", [["system", "clerk"]], "Tier 0 scores the $4,500 payment 0.86 and sends it to court."],
    ["clerk", EXPERTS.map((e) => ["clerk", e]), "The Clerk pulls the cardholder's baselines and recent history."],
    ["geo", [["geo", "prosecutor"], ["geo", "defense"]], "Geo: the IP is 13 km from home."],
    ["device", [["device", "prosecutor"], ["device", "defense"]], "Device: never seen for this cardholder."],
    ["velocity", [["velocity", "prosecutor"], ["velocity", "defense"]], "Velocity: 36× the usual amount, at 2:14 AM."],
    ["merchant", [["merchant", "prosecutor"], ["merchant", "defense"]], "Merchant: verified, category matches."],
    ["graph", [["graph", "prosecutor"], ["graph", "defense"]], "Graph: no links to mule accounts."],
    ["prosecutor", [["prosecutor", "judge"], ["prosecutor", "defense"]], "Prosecutor: amount spike on a new device. Block."],
    ["defense", [["defense", "judge"]], "Defense: home IP and a known category. Approve."],
    ["judge", [["judge", "bailiff"]], "Judge: p_fraud 0.50, a deadlock. Subpoena the cardholder."],
    ["bailiff", [["bailiff", "witness"]], "Bailiff: no SIM swap. Question and one-time code sent."],
    ["witness", [["witness", "judge"]], "Witness: “Yes, parts for my BMW project.” Code verified."],
    ["judge", [["judge", "stenographer"]], "Judge re-rules: p_fraud 0.01."],
    ["stenographer", [], "Verdict: APPROVE, explained in plain English."],
  ];

  const el = (tag, attrs, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };

  function path(s, t) {
    const [, , , sx, sy] = AGENTS[s];
    const [, , , tx, ty] = AGENTS[t];
    if (s === "prosecutor" && t === "defense") return `M${sx + W / 2},${sy + H} L${tx + W / 2},${ty}`;
    if (tx < sx) {
      // The witness answers back to the Judge: leave from below, arrive on the right.
      const x1 = sx + W / 2, y1 = sy + H, x2 = tx + W, y2 = ty + H / 2;
      return `M${x1},${y1} C${x1},${y2 + 20} ${x2 + 120},${y2} ${x2},${y2}`;
    }
    const x1 = sx + W, y1 = sy + H / 2, x2 = tx, y2 = ty + H / 2;
    const dx = Math.max((x2 - x1) / 2, 40);
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }

  const edgeLayer = el("g", {}, svg);
  const nodeLayer = el("g", {}, svg);
  const edges = {};
  for (const [s, t] of LINKS) edges[`${s}>${t}`] = el("path", { d: path(s, t), class: "edge" }, edgeLayer);
  const nodes = {};
  for (const [id, [label, color, role, x, y]] of Object.entries(AGENTS)) {
    const g = el("g", { class: "node", transform: `translate(${x},${y})`, style: `--c:${color}` }, nodeLayer);
    el("rect", { class: "glow", x: -6, y: -6, width: W + 12, height: H + 12, rx: 14 }, g);
    el("rect", { class: "box", width: W, height: H, rx: 10 }, g);
    el("circle", { class: "dot", cx: 16, cy: 19, r: 4 }, g);
    el("text", { class: "label", x: 26, y: 23 }, g).textContent = label;
    el("text", { class: "role", x: 12, y: 42 }, g).textContent = role;
    const count = el("text", { class: "count", x: W - 10, y: 23, "text-anchor": "end" }, g);
    nodes[id] = { g, count, n: 0 };
  }

  let step = 0, timer = null, playing = false;

  function reset() {
    step = 0;
    for (const n of Object.values(nodes)) {
      n.n = 0; n.count.textContent = "";
      n.g.classList.remove("seen", "active");
    }
    for (const e of Object.values(edges)) e.classList.remove("seen", "on");
  }

  function show(i) {
    const [agent, links, text] = STEPS[i];
    for (const n of Object.values(nodes)) n.g.classList.remove("active");
    for (const e of Object.values(edges)) e.classList.remove("on");
    const n = nodes[agent];
    n.n += 1; n.count.textContent = String(n.n);
    n.g.classList.add("seen", "active");
    for (const [s, t] of links) {
      const e = edges[`${s}>${t}`];
      e.style.setProperty("--c", AGENTS[s][1]);
      e.classList.add("seen", "on");
      nodes[t].g.classList.add("seen");
    }
    caption.textContent = text;
    caption.style.setProperty("--c", AGENTS[agent][1]);
  }

  function tick() {
    if (step >= STEPS.length) {
      timer = setTimeout(() => { reset(); tick(); }, 3500);
      return;
    }
    show(step++);
    timer = setTimeout(tick, step <= 2 || step > 7 ? 1700 : 1100);
  }

  function play() {
    if (playing) return;
    playing = true;
    tick();
  }
  function pause() {
    playing = false;
    clearTimeout(timer);
  }

  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (still) {
    // No animation: the finished case, every step at once.
    STEPS.forEach((_, i) => show(i));
    for (const n of Object.values(nodes)) n.g.classList.remove("active");
    for (const e of Object.values(edges)) e.classList.remove("on");
    replay.hidden = true;
    return;
  }

  replay.addEventListener("click", () => { pause(); reset(); play(); });
  new IntersectionObserver(([entry]) => (entry.isIntersecting ? play() : pause()), { threshold: 0.35 }).observe(root);
})();
