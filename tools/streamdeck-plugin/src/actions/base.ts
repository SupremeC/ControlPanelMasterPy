import streamDeck, {
	SingletonAction,
	type Action,
	type DidReceiveSettingsEvent,
	type WillAppearEvent,
	type WillDisappearEvent,
} from "@elgato/streamdeck";

import { describe, panel } from "../panel";

import type { JsonObject } from "@elgato/utils";

/**
 * Shared plumbing: remembers each visible instance's settings and redraws
 * every instance whenever the panel's state (or reachability) changes.
 */
export abstract class PanelAction<S extends JsonObject> extends SingletonAction<S> {
	protected readonly settingsOf = new Map<string, S>();
	protected readonly logger = streamDeck.logger.createScope(this.constructor.name);

	constructor() {
		super();
		const refresh = () => this.refreshAll();
		panel.on("state", refresh);
		panel.on("offline", refresh);
		panel.on("presets", refresh);
	}

	override async onWillAppear(ev: WillAppearEvent<S>): Promise<void> {
		this.settingsOf.set(ev.action.id, ev.payload.settings);
		await this.safeRender(ev.action, ev.payload.settings);
	}

	override onWillDisappear(ev: WillDisappearEvent<S>): void {
		this.settingsOf.delete(ev.action.id);
	}

	override async onDidReceiveSettings(ev: DidReceiveSettingsEvent<S>): Promise<void> {
		this.settingsOf.set(ev.action.id, ev.payload.settings);
		await this.safeRender(ev.action, ev.payload.settings);
	}

	refreshAll(): void {
		for (const action of this.actions) {
			const settings = this.settingsOf.get(action.id);
			if (settings) void this.safeRender(action, settings);
		}
	}

	protected async safeRender(action: Action<S>, settings: S): Promise<void> {
		try {
			await this.render(action, settings);
		} catch (e) {
			this.logger.error(`render failed: ${describe(e)}`);
		}
	}

	/** Draws one instance from `panel.state` and its settings. */
	protected abstract render(action: Action<S>, settings: S): Promise<void>;
}
