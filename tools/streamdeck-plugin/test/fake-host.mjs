/**
 * Plays the Stream Deck app: starts a WebSocket server, launches the
 * built plugin against it (bin/plugin.js, so run `npm run build` first),
 * then sends the events a real deck would and checks what the plugin
 * draws and what the panel does. Needs the Pi reachable; toggles the
 * button LEDs twice and nudges the volume up and back down, nothing
 * else visible.
 *
 *     node test/fake-host.mjs            (PANEL_HOST overrides the address)
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const HOST = process.env.PANEL_HOST ?? "http://192.168.150.33:8080";
const PLUGIN_DIR = fileURLToPath(new URL("../com.supremec.panelen.sdPlugin/", import.meta.url));
const UUID = "com.supremec.panelen";
const DEVICE = "fake-device";

const results = [];
function check(name, ok, detail = "") {
	results.push({ name, ok, detail });
	console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}

async function api(method, path) {
	const res = await fetch(HOST + path, { method, signal: AbortSignal.timeout(5000) });
	const text = await res.text();
	return { status: res.status, body: text ? JSON.parse(text) : null };
}

async function untilState(pred, ms = 4000) {
	const end = Date.now() + ms;
	let state;
	while (Date.now() < end) {
		state = (await api("GET", "/api/state")).body;
		if (pred(state)) return state;
		await new Promise((r) => setTimeout(r, 250));
	}
	return null;
}

// ---- the fake app ------------------------------------------------------------

const wss = new WebSocketServer({ host: "127.0.0.1", port: 0 });
await new Promise((resolve) => wss.once("listening", resolve));
const port = wss.address().port;
const info = {
	application: { font: "Segoe UI", language: "sv", platform: "windows", platformVersion: "10", version: "7.6.0" },
	colors: {
		buttonMouseOverBackgroundColor: "#464646",
		buttonPressedBackgroundColor: "#303030",
		buttonPressedBorderColor: "#646464",
		buttonPressedTextColor: "#969696",
		highlightColor: "#0078ff",
	},
	devicePixelRatio: 2,
	devices: [{ id: DEVICE, name: "Fake Stream Deck +", size: { columns: 4, rows: 2 }, type: 7 }],
	plugin: { uuid: UUID, version: "0.1.0" },
};

const waiting = []; // { test(msg) -> bool, resolve }
const received = [];
function expectMessage(test, ms, label) {
	return new Promise((resolve) => {
		const hit = received.find(test);
		if (hit) return resolve(hit);
		const timer = setTimeout(() => {
			const i = waiting.findIndex((w) => w.resolve === resolve);
			if (i >= 0) waiting.splice(i, 1);
			resolve(null);
		}, ms);
		waiting.push({
			test,
			resolve: (msg) => {
				clearTimeout(timer);
				resolve(msg);
			},
			label,
		});
	});
}

let socket = null;
const connected = new Promise((resolve) => {
	wss.on("connection", (ws) => {
		socket = ws;
		ws.on("message", (raw) => {
			const msg = JSON.parse(raw.toString());
			if (msg.event === "logMessage") {
				console.log(`  plugin: ${msg.payload?.message}`);
			} else if (msg.event === "getGlobalSettings") {
				ws.send(JSON.stringify({ event: "didReceiveGlobalSettings", payload: { settings: {} } }));
			} else if (msg.event === "registerPlugin") {
				resolve(msg);
			}
			received.push(msg);
			for (const w of [...waiting]) {
				if (w.test(msg)) {
					waiting.splice(waiting.indexOf(w), 1);
					w.resolve(msg);
				}
			}
		});
	});
});

function send(msg) {
	socket.send(JSON.stringify(msg));
}

function appear(context, action, settings, controller = "Keypad", coordinates = { column: 0, row: 0 }) {
	send({
		event: "willAppear",
		action: `${UUID}.${action}`,
		context,
		device: DEVICE,
		payload: { settings, coordinates, controller, isInMultiAction: false, state: 0, resources: {} },
	});
}

function keyPress(context, action, settings) {
	const base = { action: `${UUID}.${action}`, context, device: DEVICE, payload: { settings, coordinates: { column: 0, row: 0 }, state: 0, isInMultiAction: false } };
	send({ ...base, event: "keyDown" });
	send({ ...base, event: "keyUp" });
}

function dialRotate(context, settings, ticks) {
	send({
		event: "dialRotate",
		action: `${UUID}.dial`,
		context,
		device: DEVICE,
		payload: { settings, coordinates: { column: 0, row: 0 }, controller: "Encoder", ticks, pressed: false },
	});
}

const imageOf = (context) => (m) => m.event === "setImage" && m.context === context;
/** The SVG behind a `data:image/svg+xml;base64,` URI (what the plugin sends), else the string. */
function svgOf(image) {
	const prefix = "data:image/svg+xml;base64,";
	return image.startsWith(prefix) ? Buffer.from(image.slice(prefix.length), "base64").toString("utf8") : image;
}
const imageWith = (context, text) => (m) => imageOf(context)(m) && svgOf(m.payload.image).includes(text);
const feedbackWith = (context, value) => (m) => m.event === "setFeedback" && m.context === context && m.payload.value === value;

// ---- the run -----------------------------------------------------------------

const child = spawn(
	process.execPath,
	["bin/plugin.js", "-port", String(port), "-pluginUUID", "fake-plugin", "-registerEvent", "registerPlugin", "-info", JSON.stringify(info)],
	{ cwd: PLUGIN_DIR, stdio: ["ignore", "inherit", "inherit"] },
);
child.on("exit", (code) => console.log(`plugin exited with ${code}`));

try {
	const reg = await Promise.race([connected, new Promise((r) => setTimeout(() => r(null), 10000))]);
	check("plugin registers with the app", !!reg, reg ? `uuid ${reg.uuid}` : "no registerPlugin in 10 s");
	if (!reg) throw new Error("no plugin");

	const before = (await api("GET", "/api/state")).body;
	console.log(`panel: leds=${before.button_leds} volume=${before.audio.volume} night=${before.daemon.night}`);
	if (before.daemon.night) throw new Error("the panel is in night mode; not testing anything visible");

	// State key: draws the label, then the state once the feed has it.
	appear("k1", "state", { item: "button_leds" });
	const drawn = await expectMessage(imageWith("k1", "Knapplampor"), 5000);
	check("state key draws its label", !!drawn);
	const word = before.button_leds ? ">På<" : ">Av<";
	const withState = await expectMessage(imageWith("k1", word), 8000);
	check("state key shows the panel's state", !!withState, `expected ${word}`);

	// Press: the LEDs flip, the key follows, press again to restore.
	keyPress("k1", "state", { item: "button_leds" });
	const flipped = await untilState((s) => s.button_leds !== before.button_leds);
	check("pressing the key toggles the button LEDs", !!flipped);
	const flippedWord = before.button_leds ? ">Av<" : ">På<";
	const followed = await expectMessage(imageWith("k1", flippedWord), 4000);
	check("the key redraws after the toggle", !!followed, `expected ${flippedWord}`);
	keyPress("k1", "state", { item: "button_leds" });
	const restored = await untilState((s) => s.button_leds === before.button_leds);
	check("second press restores the LEDs", !!restored);

	// Dial: volume feedback, one tick up, one tick down.
	appear("d1", "dial", { kind: "volume" }, "Encoder");
	const fb = await expectMessage(feedbackWith("d1", `${before.audio.volume} %`), 5000);
	check("dial shows the volume on the strip", !!fb, `expected "${before.audio.volume} %"`);
	dialRotate("d1", { kind: "volume" }, 1);
	const up = await untilState((s) => s.audio.volume === before.audio.volume + 5);
	check("one tick raises the volume 5 %", !!up, up ? `${up.audio.volume} %` : "no change in 4 s");
	if (up) {
		const fbUp = await expectMessage(feedbackWith("d1", `${up.audio.volume} %`), 4000);
		check("the strip follows the volume", !!fbUp);
	}
	dialRotate("d1", { kind: "volume" }, -1);
	const down = await untilState((s) => s.audio.volume === before.audio.volume);
	check("one tick back restores the volume", !!down);

	// Sound key: the clip's name from /api/presets.
	const presets = (await api("GET", "/api/presets")).body;
	const p5 = presets.find((p) => p.pin === 5);
	appear("s1", "sound", { pin: 5 });
	const named = await expectMessage(imageWith("s1", p5?.name ?? "Knapp 5"), 6000);
	check("sound key shows the clip's name", !!named, `expected "${p5?.name}"`);

	// Command key: mute shows the volume text.
	appear("c1", "command", { command: "mute" });
	const cmd = await expectMessage(imageWith("c1", "Ljud"), 5000);
	check("command key draws", !!cmd);

	// A refused call shows the alert: demo with the master switch off is 409,
	// otherwise an unknown sound id is 404.
	appear("x1", "sound", { pin: 2 });
	send({ event: "keyDown", action: `${UUID}.sound`, context: "x1", device: DEVICE, payload: { settings: { pin: 99 }, coordinates: { column: 0, row: 0 }, state: 0, isInMultiAction: false } });
	const alert = await expectMessage((m) => m.event === "showAlert" && m.context === "x1", 5000);
	check("a bad request shows the alert", !!alert);
} catch (e) {
	check("run completed", false, e.message);
} finally {
	child.kill();
	wss.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
