import {
	action,
	type Action,
	type DialDownEvent,
	type DialRotateEvent,
	type FeedbackPayload,
	type TouchTapEvent,
} from "@elgato/streamdeck";

import { stripIcon, type Glyph, type Tone } from "../icons";
import { describe, panel, type PanelState, type Segment } from "../panel";
import { PanelAction } from "./base";

export type DialKind = "volume" | "strip_0" | "strip_1" | "effect_0" | "effect_1";

type Settings = { kind?: DialKind };

const VOLUME_STEP = 5; // percent per tick
const BRIGHTNESS_STEP = 16; // of 255 per tick

const STRIP_NAMES = ["säng", "fönster"];

function segmentOf(kind: DialKind): number {
	return kind.endsWith("_1") ? 1 : 0;
}

function stripName(kind: DialKind, state: PanelState | null): string {
	const n = segmentOf(kind);
	const name = state?.strips.segments[n]?.name || STRIP_NAMES[n] || `${n}`;
	return name.charAt(0).toUpperCase() + name.slice(1);
}

function percent(brightness: number | null): number {
	return brightness === null ? 0 : Math.round((brightness * 100) / 255);
}

/** What the touch strip shows for a dial: title, icon, value and the bar. */
export function dialFeedback(kind: DialKind, state: PanelState | null, online: boolean): FeedbackPayload {
	const unknown = !online || !state;
	let title: string;
	let glyph: Glyph;
	let tone: Tone;
	let value: string;
	let indicator: FeedbackPayload[string];
	if (kind === "volume") {
		title = "Volym";
		const muted = state?.audio.muted ?? false;
		glyph = muted ? "mute" : "speaker";
		tone = unknown ? "unknown" : muted ? "off" : "on";
		value = unknown ? "–" : muted ? "Tyst" : `${state.audio.volume} %`;
		indicator = { value: unknown || muted ? 0 : state.audio.volume, enabled: true };
	} else {
		const seg: Segment | undefined = state?.strips.segments[segmentOf(kind)];
		const isEffect = kind.startsWith("effect");
		title = `${isEffect ? "Effekt" : "Ljus"} ${stripName(kind, state).toLowerCase()}`;
		glyph = isEffect ? "sparkle" : "wave";
		const on = seg?.on ?? null;
		tone = unknown || on === null ? "unknown" : on ? "on" : "off";
		if (unknown || !seg || on === null) {
			value = unknown ? "–" : "?";
			indicator = { value: 0, enabled: !isEffect };
		} else if (isEffect) {
			value = !on ? "Av" : seg.effect === null ? "?" : seg.effect === 0 ? "Ingen" : `Nr ${seg.effect}`;
			indicator = { enabled: false };
		} else {
			value = !on ? "Av" : `${percent(seg.brightness)} %`;
			indicator = { value: on ? percent(seg.brightness) : 0, enabled: true };
		}
	}
	return { title, value, indicator, icon: stripIcon(glyph, tone) };
}

/** Routes for the three gestures. */
function routes(kind: DialKind, state: PanelState | null) {
	if (kind === "volume") {
		return {
			rotate: (ticks: number) =>
				`/api/audio/volume/${ticks > 0 ? "up" : "down"}?step=${Math.min(100, VOLUME_STEP * Math.abs(ticks))}`,
			push: "/api/audio/stop",
			tap: state?.audio.muted ? "/api/audio/unmute" : "/api/audio/mute",
		};
	}
	const n = segmentOf(kind);
	if (kind.startsWith("effect")) {
		return {
			rotate: (ticks: number) => `/api/strips/${n}/effect/${ticks > 0 ? "next" : "prev"}`,
			push: `/api/strips/${n}/effect/off`,
			tap: `/api/strips/${n}/toggle`,
		};
	}
	return {
		rotate: (ticks: number) =>
			`/api/strips/${n}/brightness/${ticks > 0 ? "up" : "down"}?step=${Math.min(255, BRIGHTNESS_STEP * Math.abs(ticks))}`,
		push: `/api/strips/${n}/toggle`,
		tap: `/api/strips/${n}/effect/off`,
	};
}

/** A dial: volume, a strip's brightness or a strip's effect; the strip slot shows the value. */
@action({ UUID: "com.supremec.panelen.dial" })
export class PanelDial extends PanelAction<Settings> {
	/** Ticks that arrived while a request was in flight, per dial. */
	private readonly pending = new Map<string, { ticks: number; busy: boolean }>();

	protected override async render(a: Action<Settings>, settings: Settings): Promise<void> {
		if (!a.isDial()) return;
		if (!settings.kind) {
			await a.setFeedback({ title: "Ratt", value: "Inte vald", icon: stripIcon("question", "unknown"), indicator: { enabled: false } });
			return;
		}
		await a.setFeedback(dialFeedback(settings.kind, panel.state, panel.online));
	}

	override async onDialRotate(ev: DialRotateEvent<Settings>): Promise<void> {
		const { kind } = ev.payload.settings;
		if (!kind || ev.payload.ticks === 0) return;
		const id = ev.action.id;
		const q = this.pending.get(id) ?? { ticks: 0, busy: false };
		this.pending.set(id, q);
		q.ticks += ev.payload.ticks;
		if (q.busy) return;
		q.busy = true;
		try {
			while (q.ticks !== 0) {
				const ticks = q.ticks;
				q.ticks = 0;
				const result = await panel.post(routes(kind, panel.state).rotate(ticks));
				this.logger.debug(`${kind} ${ticks > 0 ? "+" : ""}${ticks}: ${JSON.stringify(result)}`);
			}
		} catch (e) {
			q.ticks = 0;
			this.logger.warn(`${kind} rotate refused: ${describe(e)}`);
			if (ev.action.isDial()) await ev.action.showAlert();
		} finally {
			q.busy = false;
		}
	}

	override async onDialDown(ev: DialDownEvent<Settings>): Promise<void> {
		const { kind } = ev.payload.settings;
		if (!kind) return;
		await this.run(ev.action, kind, routes(kind, panel.state).push);
	}

	override async onTouchTap(ev: TouchTapEvent<Settings>): Promise<void> {
		const { kind } = ev.payload.settings;
		if (!kind || ev.payload.hold) return;
		await this.run(ev.action, kind, routes(kind, panel.state).tap);
	}

	private async run(a: Action<Settings>, kind: DialKind, route: string): Promise<void> {
		try {
			const result = await panel.post(route);
			this.logger.info(`${kind} ${route}: ${JSON.stringify(result)}`);
		} catch (e) {
			this.logger.warn(`${kind} ${route} refused: ${describe(e)}`);
			if (a.isDial()) await a.showAlert();
		}
	}
}
