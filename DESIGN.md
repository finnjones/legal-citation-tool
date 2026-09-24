---
name: AGLC4 Citation Tool
description: The Registry. An essay is lodged like a brief, and every footnote is entered in a register and stamped.
colors:
  ground: "oklch(0.93 0.008 150)"
  sheet: "oklch(0.995 0.002 100)"
  ink: "oklch(0.22 0.02 260)"
  ink-2: "oklch(0.46 0.02 260)"
  rule: "oklch(0.86 0.01 250)"
  buff: "oklch(0.87 0.055 82)"
  buff-ink: "oklch(0.3 0.04 60)"
  tape: "oklch(0.74 0.12 2)"
  stamp: "oklch(0.45 0.16 295)"
  refer: "oklch(0.52 0.19 25)"
  tape-shadow: "oklch(0.3 0.05 20 / 0.25)"
  sheet-shadow: "oklch(0.3 0.02 250 / 0.12)"
  board-shadow: "oklch(0.3 0.04 60 / 0.3)"
  knob-shadow: "oklch(0 0 0 / 0.25)"
typography:
  section-title:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
  wordmark:
    fontFamily: "system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 700
  ui-small:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.875rem"
  caption:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.8125rem"
  label:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 700
    letterSpacing: "0.14em"
  stamp-date:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.625rem"
    fontWeight: 800
  citation:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "1.0625rem"
    lineHeight: 1.55
  ui:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "0.9375rem"
    lineHeight: 1.5
  typed:
    fontFamily: "'Courier Prime', 'Courier New', monospace"
    fontSize: "1.25rem"
  stamp:
    fontFamily: "system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 800
    letterSpacing: "0.14em"
rounded:
  hairline: "1px"
  tag: "2px"
  switch: "9px"
  sheet: "3px"
  control: "4px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    padding: "10px 18px"
  backsheet:
    backgroundColor: "{colors.buff}"
    textColor: "{colors.buff-ink}"
    rounded: "{rounded.sheet}"
  stamp-amended:
    textColor: "{colors.stamp}"
  stamp-refer:
    textColor: "{colors.refer}"
---

## Overview
The Registry. A single-page Operate tool that treats the essay as a brief lodged at a court registry. The only board in the world is the buff backsheet tied with pink tape, and it is where the document is dropped. After processing, each footnote is entered in a register on white sheets: its marginal number, the original struck through, the AGLC4 result, and a rubber-stamp status. Everything except the stamps and the backsheet is restrained, so the citation text stays the content.

## Colors
Restrained. The ground is a cool registry-counter grey, and the sheets are near-white like Word. Violet stamp ink is the single accent and means "amended" or "inserted". Refer red is reserved for footnotes that need the student's attention and for errors. Buff and tape appear only on the backsheet. Dark mode (for late-night deadline work) keeps the same roles and lightens the inks.

## Typography
Citation text (footnotes and bibliography) is set in Source Serif 4 because italics carry legal meaning. UI is the system sans. The typed backsheet line (matter title and status) uses Courier Prime and appears nowhere else. Stamps use heavy, tracked sans capitals.

## Layout
A 1080px column. The lodge row has the backsheet on the left and a short explanation of how the tool works on the right, stacked on mobile. The register is an ordered list with a marginal number column, the text, and a stamp column. Its strip stays pinned while scrolling and holds the filters, the markup toggle and Download.

## Elevation & Depth
Sheets sit on the ground with a short, soft offset shadow (paper on a counter). The backsheet adds one step of depth. Nothing floats beyond the pinned strip.

## Shapes
Near-square corners (3–4px). Stamps are rectangles with a double rule, rotated slightly and masked with ink grain.

## Components
- **Backsheet:** the drop zone, file picker, options and Process action.
- **Stamp:** AMENDED (violet), UNCHANGED (ink-2), REFER (red), WARNING (general notes, red), FORMATTED (the date stamp on the backsheet after processing). Redline deletions strike in ink-2 so red means Refer only.
- **Register entry:** marginal number, `.was` (struck), `.now` (result, or a redline diff when markup is on) and notes.
- **Strip:** filter buttons with counts, a markup switch and the primary Download.

## Do's and Don'ts
- Do keep the stamp as the only status signal on each entry, together with its word. Colour is never the sole signal.
- Do render `<em>` in citations faithfully everywhere.
- Don't spread buff or tape beyond the backsheet.
- Don't use Courier Prime outside the backsheet's typed lines.
- Don't add colored side-stripe borders to entries or alerts.
