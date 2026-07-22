# Brito Alerts

This is a repository for the Brito Alerts project, which is designed to provide real-time notifications and alerts for various events and conditions. The project aims to enhance user experience by delivering timely and relevant information through a customizable alert system.

## Udacity pricing collection

The Udacity collector now prioritizes the **effective price shown to a regular user**:

- browser-like headers and user-agent are used in Playwright navigation;
- dynamic content waits for visible currency/price text before extraction;
- promotional/current price is stored as `price`;
- when available, `original_price`, `discount_amount`, and `discount_percent` are also persisted in `data/udacity_prices.csv`;
- telemetry logs show which selector groups were used (`[telemetry] ... details=...`).
