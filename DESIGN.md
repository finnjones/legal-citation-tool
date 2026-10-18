---
name: AGLC4 Citation Tool
description: Chambers. A calm, editorial page where the citation text is the only thing set with any ceremony.
colors:
  paper: "#F7F4EE"
  sheet: "#FFFFFF"
  sheet-2: "#FBF9F5"
  ink: "#172033"
  muted: "#5B6577"
  hairline: "#E3DED3"
  hairline-strong: "#CFC8BA"
  accent: "#1F3A5F"
  accent-deep: "#162B47"
  on-accent: "#FFFFFF"
  deletion: "#A33A32"
  insertion: "#2F6B4F"
  check: "#B45309"
  dark-paper: "#11151C"
  dark-sheet: "#181D26"
  dark-sheet-2: "#1D2330"
  dark-ink: "#E9E5DC"
  dark-muted: "#A3ABB9"
  dark-hairline: "#2C333F"
  dark-hairline-strong: "#3B4350"
  dark-accent: "#A9C1E3"
  dark-accent-deep: "#C3D5EE"
  dark-on-accent: "#0E1726"
  dark-deletion: "#EC9A92"
  dark-insertion: "#8FCDA9"
  dark-check: "#F2A860"
typography:
  wordmark:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "1.25rem"
    fontWeight: 600
    letterSpacing: "-0.01em"
  display:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "clamp(2.125rem, 1.4rem + 2.6vw, 3.25rem)"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.018em"
  page-title:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "2.5rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  page-title-mobile:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: 1.15
  headline:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "1.875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.012em"
  subhead:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.25
  subhead-small:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.3
  lede:
    fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.6
  title:
    fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  ui:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 500
    lineHeight: 1.5
  body-small:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "0.875rem"
    lineHeight: 1.5
  label:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.4
  badge:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.01em"
  citation:
    fontFamily: "'Source Serif 4', 'Iowan Old Style', Charter, Georgia, serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  badge: "4px"
  control: "6px"
  card: "8px"
  switch: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
  2xl: "64px"
  3xl: "96px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "12px 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.accent-deep}"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "40px"
  dropzone:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "28px 24px"
  card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "24px"
  badge-amended:
    textColor: "{colors.accent}"
    rounded: "{rounded.badge}"
    padding: "4px 7px"
  badge-check:
    textColor: "{colors.check}"
    rounded: "{rounded.badge}"
    padding: "4px 7px"
  badge-unchanged:
    textColor: "{colors.muted}"
    rounded: "{rounded.badge}"
    padding: "4px 7px"
  pay-bar:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    padding: "12px 24px"
---

# Design System: AGLC4 Citation Tool

## Overview

**Creative North Star: "Chambers"**

The page should feel like a well-run set of barristers' chambers or a good law review: quiet, exact, unhurried, and confident enough not to decorate. A student arrives close to a deadline and is about to pay for something that touches their assessment, so every surface earns trust by restraint. The citation text is the one thing set with ceremony, in a serif whose italics are faithful; everything around it is calm Inter UI on warm paper, divided by 1px hairlines.

The landing page and the tool are one page. The hero holds the upload itself, so the first thing a visitor can do is the job. Below it, the page proves the mechanism with three real footnotes in redline, then explains how it works, what it fixes (with AGLC4 rule numbers that the code and tests actually cover), the price, and the questions a careful student asks. After processing, the marketing steps aside and the register takes over.

This replaces "The Registry" (buff backsheet, pink tape, rotated stamps, Courier typed lines), which read as a prop rather than a paid product.

**Key Characteristics:**
- Warm paper ground, white sheets, ink-navy text, one navy accent.
- Structure from 1px hairlines and one tonal step (paper to sheet), almost no shadow.
- Serif for display headings and every citation; Inter for all UI.
- Status is a quiet word badge: Amended, Check, Unchanged.
- Red means deletion, green means insertion, amber means Check. Nothing else uses them.

## Colors

Restrained: warm neutrals, one navy accent, and three semantic inks that only ever describe the redline and the Check state.

### Primary
- **Chambers Navy** (#1F3A5F; dark #A9C1E3): primary buttons, links, focus rings, the selected filter, the Amended badge. Its deeper step (#162B47; dark #C3D5EE) is the hover state. It is the only accent.

### Semantic
- **Deletion Red** (#A33A32; dark #EC9A92): struck text in the redline, and nothing else. Errors are not red (or amber): they are an `error` banner, ink text in a Hairline Strong box with a plain label.
- **Insertion Green** (#2F6B4F; dark #8FCDA9): inserted text in the redline (underlined, with a faint wash).
- **Check Amber** (#B45309; dark #F2A860): the Check badge, Check notes and the failed-footnotes banner label.

### Neutral
- **Paper** (#F7F4EE; dark #11151C): the page ground.
- **Sheet** (#FFFFFF; dark #181D26): cards, the drop zone, the register, the pay bar. The step from paper to sheet is the main depth cue.
- **Sheet 2** (#FBF9F5; dark #1D2330): hover rows and the register's column header.
- **Ink** (#172033; dark #E9E5DC): body text and headings.
- **Muted** (#5B6577; dark #A3ABB9): secondary text, original citations, captions. At least 4.5:1 on paper and sheet.
- **Hairline** (#E3DED3; dark #2C333F): every divider and card edge. **Hairline Strong** (#CFC8BA; dark #3B4350) is for secondary-button and error-banner edges, where the label carries the meaning. Edges that must read on their own use Muted instead: the drop zone's dashed edge (Muted mixed 70% into Sheet 2) and the Show changes switch's off track (Muted).

### Named Rules
**The One Accent Rule.** Navy is the only accent. Green, red and amber are meanings, not decoration; never use them for a button, a heading or an illustration.

**The Red Means Deletion Rule.** Red marks struck text in a redline and nothing else, so a student never wonders whether red is an error or a change.

## Typography

**Display and citation font:** Source Serif 4 (with Iowan Old Style, Charter, Georgia)
**UI font:** Inter (with system-ui)

**Character:** A text serif with true italics carries the legal content and the headlines, so the page reads like a journal; Inter keeps every control plain and familiar.

### Hierarchy
- **Display** (600, clamp(2.125rem → 3.25rem), 1.1): the hero headline only. Balanced, at most about 18 words.
- **Page title** (600, 2.5rem, 1.15; 2rem under 600px): the h1 of a static page, and the price on the pricing card.
- **Headline** (600, 1.875rem, 1.2): landing section headings; the document title in the results view.
- **Subhead** (600, 1.5rem, 1.25): static-page h2, the Bibliography heading, the How it works step numbers. **Subhead small** (600, 1.375rem) is the "What it marks Check" heading.
- **Lede** (Inter 400, 1.125rem, 1.6): the sentence under the hero headline and under a static page's title, in Muted.
- **Title** (Inter 600, 1.0625rem, 1.4): step titles, FAQ questions, card titles.
- **Body** (Inter 400, 1rem, 1.6): prose, held to 65–72ch.
- **UI** (Inter 500, 0.9375rem, 1.5): buttons, nav links, options, table text, banners.
- **Body small** (Inter 0.875rem, 1.5): limits, captions, notes, the privacy line.
- **Label** (Inter 500, 0.8125rem): column headers and field labels. Sentence case; no tracked capitals.
- **Citation** (Source Serif 4 400, 1.0625rem, 1.6): every footnote and bibliography entry, original and result. `<em>` renders as true italic everywhere.

### Named Rules
**The Faithful Italics Rule.** Citation italics are content (case names, titles). Never fake them, never drop them in a diff, never set citation text in Inter.

**The Wordmark Rule.** The brand name is a placeholder held in one constant (`BRAND` in `aglc/site.py`), set in the serif at 600. Swap it there; no logo mark, no icon.

## Layout

A 1120px container with a 24px gutter (16px under 600px). The hero is a grid. On desktop it has two columns (about 1fr / 440px): the headline and lede, with the three facts under them, on the left; the upload card spans both rows on the right. On mobile it stacks headline, upload card, then facts, so the action is never below the facts. Landing sections are separated by a hairline and 96px of space (64px on mobile), with more space above a heading than below it.

The results view replaces the landing sections. The register is a table-like list: number, original, result and status on desktop; on mobile each footnote is a stacked card (number and badge, then Original, then Result) with no horizontal scroll. The toolbar (filters, Show changes, Next Check (N), Copy bibliography, Download) sticks to the top while scrolling. While the document is locked, a pay bar sticks to the bottom; `scroll-padding` on the root keeps any focused element clear of both.

## Elevation & Depth

Flat by default. Depth comes from the tonal step between paper and sheet and from 1px hairlines. Two shadows exist: the upload card (`0 1px 2px rgb(23 32 51 / .04), 0 8px 24px -12px rgb(23 32 51 / .12)`), because it is the page's one action, and the sticky pay bar (`0 -6px 18px -12px rgb(23 32 51 / .18)`), so it reads as above the register. Nothing else floats.

## Shapes

Soft but squared: 6px controls, 8px cards and the drop zone, 4px badges. The only round shape is the Show changes switch. Borders are always 1px, except the drop zone's 1.5px dashed edge.

## Components

- **Upload card:** sheet card holding the drop zone, the limits line (".docx up to 10 MB · A$4 per document · first 3 fixes free"), two options, the primary action, a one-line privacy note and "Try a sample essay". The drop zone is a real `<button>`: Enter or Space or a click opens the file picker; dropping a file also works.
- **Processing stages:** an ordered list of named stages (Uploading your document, Reading footnotes with the AI model, Formatting to AGLC4, Checking nothing was dropped or invented, Writing Word tracked changes). Each is pending, current or done, with the elapsed time on the current one. No spinner.
- **Badge:** a word in a 1px tinted border: Amended (navy), Check (amber), Unchanged (muted). Never rotated, never the only signal: the word is always there.
- **Register entry:** footnote number, original (muted serif), result (serif, or redline when Show changes is on), notes and rule chips. Locked entries show the original and a plain "Result hidden until you unlock" line, no blur.
- **Rule chip:** "r 1.4.3 Ibid" in badge type with a hairline border; its `title` names the rule. Only shown where the result or a warning says which rule applied (today rr 1.1.6, 1.4.1, 1.4.3, 1.4.4); the landing example uses only chips the app can produce.
- **Banner:** a hairline box with a plain label. Kinds: plain (Free preview, Body text), `check` (amber label and wash: Couldn't read N footnotes, general Check notes), `error` (ink label, Hairline Strong edge: upload, checkout, download and re-run failures, payment not confirmed) and `ok` (navy label: Payment received, with the re-download link). The failed-footnotes banner groups every unread footnote and carries the free re-run.
- **Pay bar:** sticky bottom bar: "Unlock all N corrections and the .docx — A$4". When the document isn't payable, it offers "Try again (free)" and shows no price.
- **Redline:** deletions struck in Deletion Red; insertions underlined in Insertion Green with a 10% wash. Deletions before insertions, as Word shows them.

## Do's and Don'ts

- Do keep the word on every status. Colour is never the only signal.
- Do render `<em>` in citations faithfully everywhere, including the redline.
- Do keep targets at least 24px, and primary actions 44px tall.
- Do show the price once, plainly, wherever the student is asked to pay.
- Don't use AI gradients, sparkle icons, glowing edges or "magic" language.
- Don't use stock legal imagery (gavels, scales, columns, books).
- Don't invent badges, logos, ratings, testimonials, user counts or benchmarks.
- Don't use countdowns, urgency copy or pre-ticked upsells.
- Don't use paper, tape, stamp or typewriter props, rotated elements or monospace costume.
- Don't add coloured side-stripe borders to entries or banners.
- Don't let raw error or exception text reach the page.
