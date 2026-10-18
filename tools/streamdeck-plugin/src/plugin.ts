import streamDeck from "@elgato/streamdeck";

import { CommandKey } from "./actions/action-key";
import { PanelDial } from "./actions/dial";
import { SoundKey } from "./actions/sound-key";
import { StateKey } from "./actions/state-key";
import { panel } from "./panel";

type GlobalSettings = { host?: string };

// "trace" would log every image sent to the deck; "debug" logs requests.
streamDeck.logger.setLevel("debug");

streamDeck.actions.registerAction(new StateKey());
streamDeck.actions.registerAction(new CommandKey());
streamDeck.actions.registerAction(new SoundKey());
streamDeck.actions.registerAction(new PanelDial());

// The panel's address can be changed in any action's settings pane.
streamDeck.settings.onDidReceiveGlobalSettings<GlobalSettings>((ev) => panel.setHost(ev.settings.host));

await streamDeck.connect();
const global = await streamDeck.settings.getGlobalSettings<GlobalSettings>();
panel.setHost(global.host);
panel.start();
streamDeck.logger.info(`Panelen plugin up, talking to ${panel.baseUrl}`);
