# Stream Deck + profile for the panel

How to set up Axel's Elgato Stream Deck + (on his PC, with the Elgato
Stream Deck app) to control the panel through the web API. No code on
the Pi is involved: the API already has body-less `POST` action routes
and a `text` block in `/api/state` for exactly this. Plan and background:
`WEB_API_PLAN.md`, sections 4 and 7, in the ControlPanel project folder.

What is here:

| Path | Purpose |
|---|---|
| `icons/*.png` | Key icons, 144×144 (the key's @2x size). On/off pairs; drawn by `make_key_icons.py` |
| `lua/toggle_*.lua` | API Monkey "Action Lua Script" per state key: POSTs the toggle, returns the new state |
| `Panelen.streamDeckProfile` | The exported profile, once it exists (export it from the app after step 6) |

## 1. Requirements

- Axel's PC on the same WiFi/LAN as the Pi. Check in a browser:
  `http://192.168.150.33:8080/docs` must open.
- Use the IP, not `rpiaxpanel.local`: mDNS on Windows is less reliable.
  Reserve 192.168.150.33 for the Pi in the router so it stays.
- Stream Deck app 6.9 or later (both plugins need it).
- Nothing on the Pi: the daemon serves the API on port 8080 already.

## 2. Install the two plugins

1. **API Monkey** (ft-t): Elgato Marketplace, search "API Monkey". It
   polls a URL, picks a value out of the JSON with a GJSON selector and
   shows text or an image on the key; a press runs a Lua script that can
   send its own request. Used for the eight state keys.
2. **Advanced HTTP Client** (FlowingSPDG): download
   `dev.flowingspdg.advancedhttp.streamDeckPlugin` from
   <https://github.com/FlowingSPDG/streamdeck-advanced-http/releases>,
   double-click it, confirm. It sends one request per press, and its
   dial action has separate URLs for left, right, push and touch. Used
   for the dials and the action-only keys.

## 3. Copy the icons

Copy the `icons` folder to `C:\Panelen\icons\` on Axel's PC. API Monkey's
Response Mapping takes absolute image paths (relative names only resolve
inside the plugin's own `images` folder, which an update may replace).

## 4. The eight state keys (API Monkey)

Add an "API Monkey" action to a key and fill in the fields. The same for
every key unless the table says otherwise. Press **Save All** after
editing a key; unsaved edits are not applied.

| Field | Value |
|---|---|
| Button Action | `Execute Lua` |
| Request Type | `GET` |
| API URL | `http://192.168.150.33:8080/api/state` |
| Polling | `3` (seconds; the key refreshes itself) |
| Title Prefix | the key's label from the table below |
| JSON Selector | from the table |
| Action Lua Script | paste the matching file from `lua/` |
| Response Mapping | from the table, plus `*` → `C:\Panelen\icons\okand.png` |
| Show Success | off (the icon changes anyway) |

| Key | Title Prefix | JSON Selector | Action Lua Script | Response Mapping |
|---|---|---|---|---|
| 1 | `Säng` (uttag) | `text.bed_socket` | `toggle_bed.lua` | `På` → `uttag_on.png`, `Av` → `uttag_off.png` |
| 2 | `Byrå` (uttag) | `text.drawer_socket` | `toggle_drawer.lua` | `På` → `uttag_on.png`, `Av` → `uttag_off.png` |
| 3 | `Bakgrund` | `text.backlight` | `toggle_backlight.lua` | `På` → `bakgrund_on.png`, `Av` → `bakgrund_off.png` |
| 4 | `Knapplampor` | `text.button_leds` | `toggle_leds.lua` | `På` → `knapplampor_on.png`, `Av` → `knapplampor_off.png` |
| 5 | `Säng` (slinga) | `strips.segments.0.on` | `toggle_strip0.lua` | `true` → `slinga_on.png`, `false` → `slinga_off.png` |
| 6 | `Fönster` (slinga) | `strips.segments.1.on` | `toggle_strip1.lua` | `true` → `slinga_on.png`, `false` → `slinga_off.png` |
| 7 | `Demo` | `text.demo` | `toggle_demo.lua` | `På` → `demo_on.png`, `Av` → `demo_off.png` |
| 8 | `Släck allt` | (Advanced HTTP, see section 5) | | `slack_allt.png` |

All mapping targets are full paths, e.g. `C:\Panelen\icons\uttag_on.png`.

Notes:
- The Lua scripts return the same kind of value as the selector (`På`/`Av`
  for the `text.*` keys, `true`/`false` for the strips), so the mapping
  works for both the poll and the press.
- `strips.segments.N.on` is `null` until the daemon has read WLED once
  after a restart; the `*` fallback shows the question mark meanwhile.
- The demo key is refused with 409 while the panel's master switch is
  off; the key shows the alert, the Lua error text names the reason.
- If a mapping fails, open the plugin's `logs/log.log` (in the plugin's
  install folder under `%APPDATA%\Elgato\StreamDeck\Plugins`) and check
  the raw value the selector produced.

## 5. Action-only keys (Advanced HTTP Client)

Add an "HTTP REQUEST" action, METHOD `POST`, BODY empty, no auth, and
set **URL (Press)**; leave **URL (Release)** empty. Turn on the WARNING
notification so a failed call shows.

| Key | Title | URL (Press) | Icon |
|---|---|---|---|
| 8 | Släck allt | `http://192.168.150.33:8080/api/all-off` | `slack_allt.png` |
| extra | Sänglampa | `http://192.168.150.33:8080/api/bedlamp/toggle` | `sanglampa.png` |

"Släck allt" has no second-tap confirm on the deck (the page has one).
Put it in a corner. It turns off the sockets as well.

**Page 2, sounds**: a folder (or a second page) with one key per clip,
METHOD `POST`, URL (Press) `http://192.168.150.33:8080/api/sounds/btn_2`
… `btn_11`, icon `ljud.png`, and a key "Stoppa ljud" →
`http://192.168.150.33:8080/api/audio/stop`, icon `stopp.png`. A sound key
fails with 409 "Ljudet är avstängt på panelen" while the panel's sound
switch is off or the volume pot is at 0.

To show the button names Axel gives the clips on the page, use API
Monkey for those keys instead: Button Action `Execute Lua` with a script
that POSTs `/api/sounds/btn_N`, API URL `http://192.168.150.33:8080/api/presets`,
JSON Selector `#(pin==N).name`, Polling `60`.

## 6. The four dials (Advanced HTTP Client, dial action)

Add an "HTTP REQUEST(DIAL)" action to each dial. METHOD `POST`, BODY
empty, no auth. The plugin sends one request per tick; the daemon folds
quick ticks into one WLED command per 100 ms and volume steps are silent.

| Dial | URL(left) | URL(right) | URL(push) | URL(touch) |
|---|---|---|---|---|
| 1 Volym | `…/api/audio/volume/down` | `…/api/audio/volume/up` | `…/api/audio/stop` | `…/api/audio/mute` |
| 2 Ljus säng | `…/api/strips/0/brightness/down` | `…/api/strips/0/brightness/up` | `…/api/strips/0/toggle` | `…/api/strips/0/effect/off` |
| 3 Ljus fönster | `…/api/strips/1/brightness/down` | `…/api/strips/1/brightness/up` | `…/api/strips/1/toggle` | `…/api/strips/1/effect/off` |
| 4 Effekt säng | `…/api/strips/0/effect/prev` | `…/api/strips/0/effect/next` | `…/api/strips/0/effect/off` | `…/api/sounds/btn_2` |

`…` = `http://192.168.150.33:8080`. Leave URL(release) empty. Steps are
5 % (volume) and 16 of 255 (brightness) per tick; add `?step=10` to a
URL for bigger steps. The volume set from the deck lasts until the
panel's own pot is turned. The dial action shows nothing on the touch
strip; that needs the custom plugin from the plan (optional).

## 7. Test

1. Each state key shows the right icon within a few seconds of the
   page (`http://192.168.150.33:8080/`) showing the same thing.
2. Press each state key: the panel changes, the icon follows, the page
   follows within 2 s.
3. Spin dial 2 quickly: the strip dims smoothly; the Pi's journal
   (`journalctl -u service_cp -f`) shows no "SendQueue was full" or WLED
   queue drops.
4. Unplug the Pi's network or stop the daemon: the keys show the alert
   state, nothing hangs; plug back, they recover on the next poll.
5. Export the profile (Stream Deck app → profile menu → Export) and
   save it as `tools/streamdeck/Panelen.streamDeckProfile` in this repo.
   It contains the IP and the icon paths, nothing secret.

## Troubleshooting

- Key shows a red alert: the plugin log (`logs/log.log`) names the
  failure. Usual causes: PC not on the LAN, mapping without a `*`
  fallback, a selector that matched nothing.
- Everything works from the page but not from the deck: the PC is on
  another network (guest WiFi) or the IP changed (reserve it).
- Sound keys fail: the panel's sound switch is off.
- `curl -X POST http://192.168.150.33:8080/api/backlight/toggle` from the
  PC tells whether the API is reachable at all.
