import { action, type Action, type KeyDownEvent, type WillAppearEvent } from "@elgato/streamdeck";

import { keyImage } from "../icons";
import { describe, panel } from "../panel";
import { PanelAction } from "./base";

type Settings = { pin?: number | string };

function pinOf(settings: Settings): number | undefined {
	const pin = Number(settings.pin);
	return Number.isInteger(pin) && pin >= 2 && pin <= 11 ? pin : undefined;
}

/** A key that plays one of the ten preset clips (buttons 2-11 on the panel). */
@action({ UUID: "com.supremec.panelen.sound" })
export class SoundKey extends PanelAction<Settings> {
	override async onWillAppear(ev: WillAppearEvent<Settings>): Promise<void> {
		await super.onWillAppear(ev);
		if (panel.presets.length === 0) void panel.refreshPresets();
	}

	protected override async render(a: Action<Settings>, settings: Settings): Promise<void> {
		if (!a.isKey()) return;
		const pin = pinOf(settings);
		if (pin === undefined) {
			await a.setImage(keyImage({ glyph: "question", tone: "unknown", label: "Inte vald" }));
			return;
		}
		const preset = panel.preset(pin);
		const label = preset?.name || `Knapp ${pin}`;
		if (!panel.online) {
			await a.setImage(keyImage({ glyph: "note", tone: "unknown", label, sub: "Ingen kontakt" }));
			return;
		}
		const hasClip = preset ? preset.active === "default" || preset.active === "recording" : true;
		const playing = panel.state?.audio.playing ?? false;
		await a.setImage(
			keyImage({
				glyph: "note",
				tone: hasClip ? (playing ? "on" : "neutral") : "unknown",
				label,
				sub: hasClip ? (playing ? "Spelar…" : undefined) : "Inget klipp",
			}),
		);
	}

	override async onKeyDown(ev: KeyDownEvent<Settings>): Promise<void> {
		const pin = pinOf(ev.payload.settings);
		if (pin === undefined) {
			await ev.action.showAlert();
			return;
		}
		try {
			const result = await panel.post(`/api/sounds/btn_${pin}`);
			this.logger.info(`btn_${pin}: ${JSON.stringify(result)}`);
		} catch (e) {
			this.logger.warn(`btn_${pin} refused: ${describe(e)}`);
			await ev.action.showAlert();
		}
	}
}
