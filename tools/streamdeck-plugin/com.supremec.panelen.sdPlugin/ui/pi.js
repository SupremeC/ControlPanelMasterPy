/* Settings pane shared by the four actions. Fills every element with a
 * data-setting attribute from the action's settings and writes changes
 * back; the "host" field is a global setting (the panel's address). */
let ws;
let uuid;
let settings = {};

window.connectElgatoStreamDeckSocket = function (port, inUuid, registerEvent, _info, actionInfo) {
	uuid = inUuid;
	const info = JSON.parse(actionInfo);
	settings = (info.payload && info.payload.settings) || {};
	ws = new WebSocket("ws://127.0.0.1:" + port);
	ws.onopen = () => {
		send({ event: registerEvent, uuid });
		send({ event: "getGlobalSettings", context: uuid });
		bind();
	};
	ws.onmessage = (m) => {
		const msg = JSON.parse(m.data);
		if (msg.event === "didReceiveGlobalSettings") {
			const host = document.getElementById("host");
			if (host) host.value = (msg.payload.settings && msg.payload.settings.host) || "";
		}
	};
};

function send(message) {
	ws.send(JSON.stringify(message));
}

function bind() {
	for (const el of document.querySelectorAll("[data-setting]")) {
		const key = el.dataset.setting;
		if (settings[key] !== undefined) el.value = String(settings[key]);
		el.addEventListener("change", () => {
			settings[key] = el.dataset.type === "number" ? Number(el.value) : el.value;
			send({ event: "setSettings", context: uuid, payload: settings });
		});
	}
	const host = document.getElementById("host");
	if (host) {
		host.addEventListener("change", () => {
			send({ event: "setGlobalSettings", context: uuid, payload: { host: host.value.trim() } });
		});
	}
}
