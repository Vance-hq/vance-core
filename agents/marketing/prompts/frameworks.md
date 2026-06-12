# Copywriting Frameworks Reference

This document is loaded as system context for every LLM copy generation call.
Apply the framework indicated by `framework_mode`. Do not blend frameworks unless
the selection table explicitly calls for it.

---

## Framework 1: Hormozi Value Equation + Grand Slam Offer

**Value Equation:**
`Value = (Dream Outcome × Perceived Likelihood of Achievement) / (Time Delay × Effort & Sacrifice)`

Levers in copy:
- Dream Outcome: name the specific transformation, not the feature
- Perceived Likelihood: use specificity, proof, guarantees to increase belief
- Time Delay: shrink the perceived time to first result ("by Friday", "in 5 minutes")
- Effort & Sacrifice: eliminate friction — "we handle it" / "takes 2 clicks"

**Grand Slam Offer Checklist:**
1. Name the dream outcome in the headline (not the product)
2. Stack the value: list what's included, anchor against what it would cost to do it manually
3. Add a risk-reversal: money-back guarantee, free trial, or "we do it for you"
4. Create scarcity or urgency that is genuine (limited spots, closing date, real deadline)
5. One clear call to action — no competing options

**Starpio-specific anchor (reviews product):**
- "AI handles your reviews 24/7" (dream outcome) vs "hiring someone to manage reviews"
  (manual alternative anchor = $3,000–$5,000/month for a marketing coordinator)
- The Grand Slam: AI-powered review management + response drafts + alert monitoring,
  all for less than one hour of a marketing employee's time per month.
- Risk-reversal: "If you don't get a response drafted within 60 seconds of a new review,
  we refund that month."

---

## Framework 2: Brunson Hook-Story-Offer

### Hook
- One sentence or question that stops the scroll
- Targets a specific pain, fear, or desired identity
- Does NOT reveal the answer — creates a curiosity gap
- Examples: "Most 5-star businesses aren't actually the best in town."
            "Your competitors are getting reviews you don't even know about."

### Story (Epiphany Bridge — 7 steps)
1. **The Character**: a person the audience identifies with (not the founder, unless the founder IS the audience)
2. **The Desire**: what they want more than anything
3. **The Conflict**: the wall they hit — what blocks the desire
4. **The Epiphany**: the moment of insight that changes everything
5. **The Plan**: the simple path that opened up after the epiphany
6. **The Conflict Resolved**: show the transformation
7. **The Achievement**: the dream outcome, made concrete and specific

Epiphany Bridge rule: the reader must reach the AHA themselves. Do not state the conclusion —
lead them there through the story.

### Offer
- Present the offer ONLY after the story lands
- Lead with the dream outcome, not the feature list
- Use "You get..." not "We provide..."
- Close with one action (no menu of options)

### Soap Opera Sequence (email series pattern)
- **Email 1** (day 0 — report/lead magnet delivery): pure value, no sell. Deliver the thing. Set expectations for what comes next.
- **Email 2** (day 3): open loop — reveal a surprising problem they didn't know they had. End without resolution.
- **Email 3** (day 7): social proof story — a character like them who solved the problem. Light CTA at the end.
- **Email 4** (day 14): objection handling — address the #1 reason they haven't acted yet. Offer a low-friction first step.
- **Email 5** (day 21): close the loop — real scarcity (access ends, price changes, spots fill). One CTA only.

---

## Framework 3: Kern Direct Response Rules

1. **One idea per message.** If it takes two sentences to describe what the email is about, cut one.
2. **Reader is the hero.** You (the writer) are the guide. Your product is the sword. Never make it about you.
3. **Specificity beats cleverness.** "37% more inbound calls in 30 days" beats "dramatic results".
4. **Subject lines:** curiosity-based for cold/nurture; benefit-based for warm/close.
   - Curiosity: "The review you almost missed" / "What your star rating is actually saying"
   - Benefit: "Get 10 more reviews this month — here's how" / "Your free GBP audit is ready"
5. **Every sentence earns the next.** If a sentence doesn't make the reader want to read the next one, cut it.
6. **One CTA, maximum contrast.** Bold the link. Name the action ("Start your free trial" not "Learn more").
7. **P.S. line.** Always. Restate the single most important thing in one sentence. Most readers scan to the P.S.

---

## Framework Selection Logic

| framework_mode    | Lead framework            | Secondary rules                              |
|-------------------|---------------------------|----------------------------------------------|
| cold_outreach     | Brunson Hook only         | Kern: curiosity subject, one idea, no offer yet |
| sequence_early    | Brunson Soap Opera #2-#3  | Kern: reader-is-hero, open loop, social proof   |
| sequence_offer    | Hormozi Grand Slam Offer  | Brunson: story before offer; Kern: benefit subject + urgency |
| landing_page      | Brunson Hook-Story-Offer  | Hormozi: full value equation + Grand Slam checklist |
| reengagement      | Kern direct response      | One idea: come back. No features. Acknowledge the gap. |
| winback           | Kern direct response      | One idea: one new concrete reason to return. Last touch. |
| viral             | Brunson Hook only         | Kern: specificity + one idea per piece; no offer |
| grader_nurture    | Brunson Epiphany Bridge   | Kern: reader-is-hero, curiosity subject, lead to AHA |
| review_response   | Kern reader-is-hero       | Customer is always the hero. You are accountable, not defensive. |
