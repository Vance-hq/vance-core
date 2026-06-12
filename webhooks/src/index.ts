/**
 * Vance webhook server — inbound event handlers.
 * Handles: Mailcow reply callbacks, Stripe events, future integrations.
 */

import express from "express";

const app = express();
const PORT = parseInt(process.env.WEBHOOKS_PORT ?? "3001", 10);

// Raw body needed for Stripe signature verification
app.use("/webhooks/stripe", express.raw({ type: "application/json" }));
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "vance-webhooks" });
});

// TODO Phase 6: mount individual webhook routers
// app.use("/webhooks/stripe", stripeRouter);
// app.use("/webhooks/mailcow", mailcowRouter);

app.listen(PORT, () => {
  console.log(`[webhooks] listening on :${PORT}`);
});
