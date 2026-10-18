/**
 * Key and dial images drawn as SVG strings, so a key can say "Säng · På"
 * in amber or "Säng · Av" in grey without any image files. Stream Deck
 * accepts an SVG string in setImage and in a layout pixmap.
 */
export type Glyph =
	| "plug"
	| "sun"
	| "dots"
	| "wave"
	| "play"
	| "power"
	| "lamp"
	| "desklamp"
	| "note"
	| "stop"
	| "speaker"
	| "mute"
	| "sparkle"
	| "question";

export type Tone = "on" | "off" | "unknown" | "neutral";

const COLORS: Record<Tone, string> = {
	on: "#ffb347",
	off: "#6b6e7a",
	unknown: "#4a4a55",
	neutral: "#9fc5ff",
};

const FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif";

/** The glyph paths live in a 72×72 box; strokes are 6 px, round. "C" is the colour. */
const GLYPHS: Record<Glyph, string> = {
	plug: '<path d="M24 8v16M48 8v16M14 24h44v12a22 22 0 0 1-44 0zM36 58v8" fill="none" stroke="C" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>',
	sun: '<circle cx="36" cy="36" r="12" fill="none" stroke="C" stroke-width="6"/><path d="M36 6v8M36 58v8M6 36h8M58 36h8M15 15l6 6M51 51l6 6M15 57l6-6M51 21l6-6" stroke="C" stroke-width="6" stroke-linecap="round"/>',
	dots: '<g fill="C"><circle cx="18" cy="18" r="6"/><circle cx="36" cy="18" r="6"/><circle cx="54" cy="18" r="6"/><circle cx="18" cy="36" r="6"/><circle cx="36" cy="36" r="6"/><circle cx="54" cy="36" r="6"/><circle cx="18" cy="54" r="6"/><circle cx="36" cy="54" r="6"/><circle cx="54" cy="54" r="6"/></g>',
	wave: '<path d="M6 36c8-18 16-18 24 0s16 18 24 0s8-10 12-10" fill="none" stroke="C" stroke-width="6" stroke-linecap="round"/><g fill="C"><circle cx="18" cy="24" r="4"/><circle cx="42" cy="48" r="4"/><circle cx="60" cy="30" r="4"/></g>',
	play: '<path d="M22 12l32 24-32 24z" fill="C" stroke="C" stroke-width="6" stroke-linejoin="round"/>',
	power: '<path d="M36 8v26" stroke="C" stroke-width="6" stroke-linecap="round"/><path d="M22 18a22 22 0 1 0 28 0" fill="none" stroke="C" stroke-width="6" stroke-linecap="round"/>',
	lamp: '<path d="M14 38h44L48 10H24zM36 38v20M22 62h28" fill="none" stroke="C" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>',
	desklamp:
		'<path d="M30 64h32M46 64L33 28" fill="none" stroke="C" stroke-width="6" stroke-linecap="round"/><path d="M8 30L20 8h18l-2 22z" fill="C" stroke="C" stroke-width="4" stroke-linejoin="round"/><path d="M14 40v9M24 40v9" stroke="C" stroke-width="4" stroke-linecap="round"/>',
	note: '<path d="M48 8v36M26 16v36M26 16l22-8" fill="none" stroke="C" stroke-width="6" stroke-linecap="round"/><circle cx="17" cy="52" r="9" fill="C"/><circle cx="39" cy="44" r="9" fill="C"/>',
	stop: '<rect x="14" y="14" width="44" height="44" rx="8" fill="C"/>',
	speaker:
		'<path d="M8 28h12l14-12v40L20 44H8z" fill="C" stroke="C" stroke-width="4" stroke-linejoin="round"/><path d="M46 24a16 16 0 0 1 0 24M54 16a26 26 0 0 1 0 40" fill="none" stroke="C" stroke-width="6" stroke-linecap="round"/>',
	mute: '<path d="M8 28h12l14-12v40L20 44H8z" fill="C" stroke="C" stroke-width="4" stroke-linejoin="round"/><path d="M48 28l16 16M64 28L48 44" fill="none" stroke="C" stroke-width="6" stroke-linecap="round"/>',
	sparkle: '<path d="M36 6l6 20 20 6-20 6-6 20-6-20-20-6 20-6z" fill="C"/><path d="M58 50l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" fill="C"/>',
	question: `<text x="36" y="58" text-anchor="middle" font-family="${FONT}" font-size="60" font-weight="700" fill="C">?</text>`,
};

export type KeyImageOptions = {
	glyph: Glyph;
	tone: Tone;
	label: string;
	/** A second, smaller line under the label, e.g. "På" or "52 %". */
	sub?: string;
};

function esc(text: string): string {
	return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function glyphMarkup(glyph: Glyph, color: string): string {
	return GLYPHS[glyph].replaceAll('"C"', `"${color}"`);
}

/** What Stream Deck accepts for images: a data URI, base64, mime declared. */
export function dataUri(svg: string): string {
	return `data:image/svg+xml;base64,${Buffer.from(svg, "utf8").toString("base64")}`;
}

/** The SVG inside a data URI from {@link dataUri}, or the string itself. */
export function undataUri(image: string): string {
	const prefix = "data:image/svg+xml;base64,";
	return image.startsWith(prefix) ? Buffer.from(image.slice(prefix.length), "base64").toString("utf8") : image;
}

/** A 144×144 key image, as a data URI. */
export function keyImage(options: KeyImageOptions): string {
	return dataUri(keySvg(options));
}

/** The key image's SVG markup. */
export function keySvg({ glyph, tone, label, sub }: KeyImageOptions): string {
	const color = COLORS[tone];
	const ring =
		tone === "on"
			? `<circle cx="72" cy="56" r="44" fill="${color}" fill-opacity="0.16" stroke="${color}" stroke-opacity="0.5" stroke-width="2"/>`
			: "";
	const labelSize = label.length > 12 ? 15 : label.length > 9 ? 17 : 20;
	const subLine = sub
		? `<text x="72" y="136" text-anchor="middle" font-family="${FONT}" font-size="15" fill="${tone === "on" ? color : "#9a9ca8"}">${esc(sub)}</text>`
		: "";
	return (
		`<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">` +
		`<rect width="144" height="144" rx="22" fill="#15161a"/>` +
		ring +
		`<g transform="translate(36 20)">${glyphMarkup(glyph, color)}</g>` +
		`<text x="72" y="${sub ? 116 : 124}" text-anchor="middle" font-family="${FONT}" font-size="${labelSize}" font-weight="600" fill="#e8e8ec">${esc(label)}</text>` +
		subLine +
		`</svg>`
	);
}

/** A small glyph for the dial's touch-strip slot (the layout's pixmap), as a data URI. */
export function stripIcon(glyph: Glyph, tone: Tone): string {
	return dataUri(
		`<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 72 72">` +
			glyphMarkup(glyph, COLORS[tone]) +
			`</svg>`,
	);
}
