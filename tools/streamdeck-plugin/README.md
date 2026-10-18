# Panelen – Stream Deck + plugin

A plugin for Elgato's Stream Deck app that drives the panel through its
web API (`daemon/webapi.py`, port 8080). It replaces the API Monkey /
Advanced HTTP Client setup that was tried in October 2026: those plugins
froze on stale keep-alive sockets, could not press and show state in the
same key without Lua, and could not draw on the dials' touch strip.

Four actions, in Swedish, under the category **Panelen**:

| Action | Key / dial | Settings | Does |
|---|---|---|---|
| Brytare (`.state`) | key | what: uttag säng/byrå, bakgrund, knapplampor, slinga säng/fönster, demo | shows På/Av (amber/grey) from the panel, press toggles |
| Kommando (`.command`) | key | släck allt, sänglampa, stoppa ljud, tyst | one POST per press, green tick on success |
| Ljud (`.sound`) | key | knapp 2–11 | plays the clip; the key shows the clip's name from `/api/presets` |
| Ratt (`.dial`) | dial | volym, ljus säng/fönster, effekt säng/fönster | rotate steps, push stops/toggles, touch mutes/effect off; the strip shows the value and a bar |

The plugin keeps one connection to `GET /api/events` (server-sent
events) so every key follows the panel within half a second, and polls
`/api/state` every 3 s while the stream is unavailable. A red alert on a
key means the panel refused the call (409: panel or sound off) or did
not answer; the reason is in the plugin log (`logs/` in the plugin
folder) and in the Pi's journal (`web: ... -> 409 from ...`).

## Install on a PC (Axel's)

Requirements: Windows 10/11 or macOS 12+, Stream Deck app 7.1 or later,
the PC on the same LAN as the Pi (`http://192.168.150.33:8080/docs` must
open in a browser), internet once (the app downloads its Node.js 24
runtime the first time a Node plugin starts).

1. Double-click `com.supremec.panelen.streamDeckPlugin`, confirm the
   install prompt. The category "Panelen" appears in the actions list.
2. Double-click `Panelen.streamDeckProfile`, confirm. A profile
   "Panelen" with three pages appears for the Stream Deck +:
   page 1 the switches and "Släck allt", page 2 sounds 2–8 and stop,
   page 3 sounds 9–11, sänglampa, tyst and stop; the four dials
   (volym, ljus säng, ljus fönster, effekt säng) on every page. Swipe
   the touch strip to change page.
3. If the Pi has another address, open any key's settings and set
   "Panelens adress" (a global setting, shared by all keys).

Updating: install the new `.streamDeckPlugin` over the old one (the app
asks to replace). The profile only holds settings, it rarely changes.

## Development (this folder)

```
npm install
python make_images.py        # the static PNGs in the manifest (Pillow)
npm run build                # rollup -> com.supremec.panelen.sdPlugin/bin/plugin.js
streamdeck link com.supremec.panelen.sdPlugin   # once; symlink into the app's Plugins folder
streamdeck restart com.supremec.panelen         # after every build (or `npm run watch`)
node test/fake-host.mjs      # plays the Stream Deck app against the real Pi
python make_profile.py       # -> Panelen.streamDeckProfile
streamdeck pack com.supremec.panelen.sdPlugin --force   # -> com.supremec.panelen.streamDeckPlugin
```

`streamdeck` is `@elgato/cli` (`npm i -g @elgato/cli`); `streamdeck dev`
enables developer mode once per machine. The test harness needs daytime
on the panel: it toggles the button LEDs twice and nudges the volume up
and back down.

Layout: `src/panel.ts` (HTTP client, state feed), `src/icons.ts` (key
and strip images as SVG data URIs; the app does not accept a bare SVG
string), `src/actions/*.ts` (the four actions, sharing `base.ts`),
`layouts/dial.json` (the touch-strip layout: title, icon, value, bar),
`ui/*.html` + `pi.js` (the settings panes). Things learned:

- Images must be data URIs (`data:image/svg+xml;base64,…`) or files;
  a raw `<svg>` string is silently dropped by Stream Deck 7.6.
- A layout pixmap needs a default `value` (a file), or the app logs
  "cannot set property 'default'" on every redraw.
- The SDK caps logging at `debug` unless the plugin runs in debug mode;
  `setLevel("trace")` logs nothing at all.
- A `.streamDeckProfile` is a zip of a `<uuid>.sdProfile` folder:
  `manifest.json` (device model `20GBD9901` = Stream Deck +, page ids)
  and `Profiles/<PAGE>/manifest.json` with `Controllers` for `Keypad`
  (`"col,row"`) and `Encoder` (`"dial,0"`); see `make_profile.py`.
