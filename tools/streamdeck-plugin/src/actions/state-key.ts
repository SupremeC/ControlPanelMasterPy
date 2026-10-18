import { action, type Action, type KeyDownEvent } from "@elgato/streamdeck";

import { keyImage, type Glyph, type Tone } from "../icons";
import { describe, panel, type PanelState } from "../panel";
import { PanelAction } from "./base";

export type ItemId = "bed_socket" | "drawer_socket" | "backlight" | "button_leds" | "strip_0" | "strip_1" | "demo";

type Settings = { item?: ItemId };

type Item = {
	label: string;
	glyph: Glyph;
	route: string;
	read: (s: PanelState) => boolean | null;
	sub?: (s: PanelState) => string | undefined;
};

export const ITEMS: Record<ItemId, Item> = {
	bed_socket: { label: "Säng", glyph: "plug", route: "/api/sockets/bed/toggle", read: (s) => s.sockets.bed.on },
	drawer_socket: { label: "Byrå", glyph: "plug", route: "/api/sockets/drawer/toggle", read: (s) => s.sockets.drawer.on },
	backlight: { label: "Bakgrund", glyph: "sun", route: "/api/backlight/toggle", read: (s) => s.switches.backlight },
	button_leds: { label: "Knapplampor", glyph: "dots", route: "/api/leds/toggle", read: (s) => s.button_leds },
	strip_0: {
		label: "Slinga säng",
		glyph: "wave",
		route: "/api/strips/0/toggle",
		read: (s) => s.strips.segments[0]?.on ?? null,
		sub: (s) => s.text.strip_0,
	},
	strip_1: {
		label: "Slinga fönster",
		glyph: "wave",
		route: "/api/strips/1/toggle",
		read: (s) => s.strips.segments[1]?.on ?? null,
		sub: (s) => s.text.strip_1,
	},
	demo: { label: "Demo", glyph: "play", route: "/api/demo/toggle", read: (s) => s.demo },
};

/** A key that shows one on/off thing on the panel and toggles it when pressed. */
@action({ UUID: "com.supremec.panelen.state" })
export class StateKey extends PanelAction<Settings> {
	protected override async render(a: Action<Settings>, settings: Settings, override?: boolean | null): Promise<void> {
		if (!a.isKey()) return;
		const item = settings.item ? ITEMS[settings.item] : undefined;
		if (!item) {
			await a.setImage(keyImage({ glyph: "question", tone: "unknown", label: "Inte vald" }));
			return;
		}
		const state = panel.state;
		if (!state || !panel.online) {
			await a.setImage(keyImage({ glyph: item.glyph, tone: "unknown", label: item.label, sub: "Ingen kontakt" }));
			return;
		}
		const on = override !== undefined ? override : item.read(state);
		const tone: Tone = on === null ? "unknown" : on ? "on" : "off";
		const sub = (override === undefined && item.sub?.(state)) || (on === null ? "?" : on ? "På" : "Av");
		await a.setImage(keyImage({ glyph: item.glyph, tone, label: item.label, sub }));
	}

	override async onKeyDown(ev: KeyDownEvent<Settings>): Promise<void> {
		const settings = ev.payload.settings;
		const item = settings.item ? ITEMS[settings.item] : undefined;
		if (!item) {
			await ev.action.showAlert();
			return;
		}
		try {
			const result = await panel.post(item.route);
			this.logger.info(`${settings.item}: ${JSON.stringify(result)}`);
			if (typeof result.on === "boolean") await this.render(ev.action, settings, result.on);
		} catch (e) {
			this.logger.warn(`${settings.item} refused: ${describe(e)}`);
			await ev.action.showAlert();
		}
	}
}
