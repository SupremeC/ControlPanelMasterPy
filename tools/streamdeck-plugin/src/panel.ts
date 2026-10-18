/**
 * The plugin's view of the panel: one HTTP client for the daemon's web
 * API (daemon/webapi.py) and one state feed shared by every key and
 * dial. The feed listens to GET /api/events (server-sent events) and
 * falls back to polling /api/state while the stream is unavailable.
 */
import streamDeck from "@elgato/streamdeck";
import { EventEmitter } from "node:events";

export const DEFAULT_HOST = "http://192.168.150.33:8080";

export type Segment = {
	id: number;
	name: string;
	on: boolean | null;
	brightness: number | null;
	effect: number | null;
};

export type PanelState = {
	daemon: { mega_connected: boolean; night: boolean };
	switches: { master: boolean; inputs: boolean; sound: boolean; backlight: boolean };
	sockets: { bed: { on: boolean; safety: boolean }; drawer: { on: boolean; safety: boolean } };
	button_leds: boolean;
	demo: boolean;
	audio: { volume: number; muted: boolean; playing: boolean; recording: boolean };
	strips: { segments: Segment[] };
	morning: { state: string; next_alarm: string | null };
	text: Record<string, string>;
};

export type Preset = {
	pin: number;
	id: string;
	name: string;
	has_default: boolean;
	active: string;
};

/** A refused call: the daemon's HTTP status (0 = no answer) and its Swedish reason. */
export class PanelError extends Error {
	constructor(
		public readonly status: number,
		message: string,
	) {
		super(message);
	}
}

const REQUEST_TIMEOUT_MS = 5000;
const POLL_MS = 3000;
const SSE_RETRY_MS = 30000;
const SSE_SILENCE_MS = 45000; // the daemon pings every 15 s
const PRESETS_MS = 60000;

const logger = streamDeck.logger.createScope("panel");

type Events = { state: [PanelState]; offline: []; presets: [Preset[]] };

export class Panel extends EventEmitter<Events> {
	state: PanelState | null = null;
	presets: Preset[] = [];
	online = false;
	private host = DEFAULT_HOST;
	private running = false;
	private abort: AbortController | null = null;
	private presetsTimer: NodeJS.Timeout | null = null;

	get baseUrl(): string {
		return this.host;
	}

	setHost(host: string | undefined): void {
		const next = (host?.trim() || DEFAULT_HOST).replace(/\/+$/, "");
		if (next === this.host) return;
		logger.info(`host ${this.host} -> ${next}`);
		this.host = next;
		if (this.running) {
			this.stop();
			this.start();
		}
	}

	start(): void {
		if (this.running) return;
		this.running = true;
		void this.feedLoop();
		this.presetsTimer = setInterval(() => void this.refreshPresets(), PRESETS_MS);
		void this.refreshPresets();
	}

	stop(): void {
		this.running = false;
		this.abort?.abort();
		this.abort = null;
		if (this.presetsTimer) clearInterval(this.presetsTimer);
		this.presetsTimer = null;
	}

	// ---- requests -----------------------------------------------------------

	/** POST to a body-less action route; returns the JSON the daemon answers. */
	async post(path: string): Promise<Record<string, unknown>> {
		return this.request("POST", path);
	}

	async get(path: string): Promise<unknown> {
		return this.request("GET", path);
	}

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	private async request(method: string, path: string, retry = true): Promise<any> {
		const url = this.host + path;
		let res: Response;
		try {
			res = await fetch(url, {
				method,
				signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
				headers: { accept: "application/json" },
			});
		} catch (e) {
			// A keep-alive socket the daemon closed just as we wrote to it:
			// the request never reached it, so one retry is safe.
			if (retry && isStaleSocket(e)) {
				logger.warn(`${method} ${path}: ${describe(e)}, retrying once`);
				return this.request(method, path, false);
			}
			this.markOffline();
			throw new PanelError(0, `Panelen svarar inte (${describe(e)})`);
		}
		const text = await res.text();
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		let body: any = null;
		try {
			body = text ? JSON.parse(text) : null;
		} catch {
			body = text;
		}
		if (!res.ok) {
			const detail =
				typeof body?.detail === "string" ? body.detail : typeof body === "string" ? body : `HTTP ${res.status}`;
			logger.warn(`${method} ${path} -> ${res.status} ${detail}`);
			throw new PanelError(res.status, detail);
		}
		logger.debug(`${method} ${path} -> ${res.status}`);
		return body;
	}

	// ---- the feed ----------------------------------------------------------

	private setState(state: PanelState): void {
		this.state = state;
		if (!this.online) logger.info("panel online");
		this.online = true;
		this.emit("state", state);
	}

	private markOffline(): void {
		if (this.online) logger.warn("panel offline");
		this.online = false;
		this.emit("offline");
	}

	private async feedLoop(): Promise<void> {
		while (this.running) {
			const started = Date.now();
			try {
				await this.listen();
				logger.info("event stream ended");
			} catch (e) {
				if (!this.running) break;
				logger.warn(`event stream failed: ${describe(e)}`);
			}
			if (!this.running) break;
			// Poll until it is time to try the stream again.
			const until = Math.max(started + SSE_RETRY_MS, Date.now() + POLL_MS);
			while (this.running && Date.now() < until) {
				await this.pollOnce();
				await sleep(POLL_MS);
			}
		}
	}

	private async pollOnce(): Promise<void> {
		try {
			const state = (await this.get("/api/state")) as PanelState;
			this.setState(state);
		} catch (e) {
			this.markOffline();
			logger.debug(`poll failed: ${describe(e)}`);
		}
	}

	/** One connection to /api/events; resolves when the server closes it. */
	private async listen(): Promise<void> {
		const abort = new AbortController();
		this.abort = abort;
		const silence = () => abort.abort(new Error(`no event for ${SSE_SILENCE_MS / 1000} s`));
		let watchdog = setTimeout(silence, SSE_SILENCE_MS);
		try {
			const res = await fetch(this.host + "/api/events", {
				signal: abort.signal,
				headers: { accept: "text/event-stream" },
			});
			if (!res.ok || !res.body) throw new PanelError(res.status, `HTTP ${res.status}`);
			logger.info("event stream connected");
			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buf = "";
			for (;;) {
				const { value, done } = await reader.read();
				if (done) break;
				clearTimeout(watchdog);
				watchdog = setTimeout(silence, SSE_SILENCE_MS);
				buf += decoder.decode(value, { stream: true });
				let i: number;
				while ((i = buf.indexOf("\n\n")) >= 0) {
					const chunk = buf.slice(0, i);
					buf = buf.slice(i + 2);
					this.handleEvent(chunk);
				}
			}
		} finally {
			clearTimeout(watchdog);
			if (this.abort === abort) this.abort = null;
			this.markOffline();
		}
	}

	private handleEvent(chunk: string): void {
		let event = "message";
		const data: string[] = [];
		for (const raw of chunk.split("\n")) {
			const line = raw.replace(/\r$/, "");
			if (line.startsWith(":")) continue; // a ping
			const colon = line.indexOf(":");
			const field = colon < 0 ? line : line.slice(0, colon);
			const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
			if (field === "event") event = value;
			else if (field === "data") data.push(value);
		}
		if (event !== "state" || data.length === 0) return;
		try {
			this.setState(JSON.parse(data.join("\n")) as PanelState);
		} catch (e) {
			logger.warn(`bad state event: ${describe(e)}`);
		}
	}

	async refreshPresets(): Promise<void> {
		try {
			const list = (await this.get("/api/presets")) as Preset[];
			if (Array.isArray(list)) {
				this.presets = list;
				this.emit("presets", list);
			}
		} catch (e) {
			logger.debug(`presets failed: ${describe(e)}`);
		}
	}

	preset(pin: number): Preset | undefined {
		return this.presets.find((p) => p.pin === pin);
	}
}

export function describe(e: unknown): string {
	if (e instanceof Error) {
		const cause = (e as { cause?: { code?: string; message?: string } }).cause;
		const extra = cause?.code ?? cause?.message;
		return extra ? `${e.message} (${extra})` : e.message;
	}
	return String(e);
}

function isStaleSocket(e: unknown): boolean {
	const cause = (e as { cause?: { code?: string } })?.cause;
	return ["ECONNRESET", "EPIPE", "UND_ERR_SOCKET"].includes(cause?.code ?? "");
}

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

/** The one panel every action shares. */
export const panel = new Panel();
