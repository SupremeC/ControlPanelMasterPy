import { action, type Action, type KeyDownEvent } from "@elgato/streamdeck";

import { keyImage, type Glyph, type Tone } from "../icons";
import { describe, panel, type PanelState } from "../panel";
import { PanelAction } from "./base";

export type CommandId = "all_off" | "bedlamp" | "stop" | "mute";

type Settings = { command?: CommandId };

type Look = { label: string; glyph: Glyph; tone: Tone; sub?: string; route: string };

/** What each command looks like and does, given the current state (if any). */
export function commandLook(id: CommandId, state: PanelState | null): Look {
	switch (id) {
		case "all_off":
			return { label: "Släck allt", glyph: "power", tone: "neutral", route: "/api/all-off" };
		case "bedlamp":
			return { label: "Sänglampa", glyph: "lamp", tone: "neutral", route: "/api/bedlamp/toggle" };
		case "stop":
			return {
				label: "Stoppa ljud",
				glyph: "stop",
				tone: state?.audio.playing ? "on" : "neutral",
				sub: state?.audio.playing ? "Spelar…" : undefined,
				route: "/api/audio/stop",
			};
		case "mute": {
			const muted = state?.audio.muted ?? false;
			return {
				label: "Ljud",
				glyph: muted ? "mute" : "speaker",
				tone: muted ? "off" : "neutral",
				sub: muted ? "Avstängt" : state ? state.text.volume : undefined,
				route: muted ? "/api/audio/unmute" : "/api/audio/mute",
			};
		}
	}
}

/** A key that runs one command on the panel: all off, the bed lamp, stop, mute. */
@action({ UUID: "com.supremec.panelen.command" })
export class CommandKey extends PanelAction<Settings> {
	protected override async render(a: Action<Settings>, settings: Settings): Promise<void> {
		if (!a.isKey()) return;
		if (!settings.command) {
			await a.setImage(keyImage({ glyph: "question", tone: "unknown", label: "Inte vald" }));
			return;
		}
		const look = commandLook(settings.command, panel.online ? panel.state : null);
		const tone: Tone = panel.online ? look.tone : "unknown";
		await a.setImage(keyImage({ glyph: look.glyph, tone, label: look.label, sub: panel.online ? look.sub : "Ingen kontakt" }));
	}

	override async onKeyDown(ev: KeyDownEvent<Settings>): Promise<void> {
		const { command } = ev.payload.settings;
		if (!command) {
			await ev.action.showAlert();
			return;
		}
		const look = commandLook(command, panel.state);
		try {
			const result = await panel.post(look.route);
			this.logger.info(`${command}: ${JSON.stringify(result)}`);
			await ev.action.showOk();
		} catch (e) {
			this.logger.warn(`${command} refused: ${describe(e)}`);
			await ev.action.showAlert();
		}
	}
}
