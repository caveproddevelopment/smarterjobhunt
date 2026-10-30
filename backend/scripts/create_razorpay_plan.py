#!/usr/bin/env python3
"""Create the weekly INR plan on Razorpay that Indian subscribers are billed
on, priced as the USD Stripe price converted to rupees. Run it once (in test
mode with test keys, again in live mode with live keys), then put the plan
ID it prints into RAZORPAY_PLAN_ID_WEEKLY.

    cd backend
    python scripts/create_razorpay_plan.py --dry-run     # show the price only
    python scripts/create_razorpay_plan.py               # create the plan
    python scripts/create_razorpay_plan.py --inr 189     # pick the price yourself

Reads RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET, and STRIPE_SECRET_KEY /
STRIPE_PRICE_WEEKLY to look up the USD price (or pass --usd 1.99).
The rupee price is rounded UP to a whole rupee.

Razorpay plans can't be edited. To change the price later, run this again
and switch RAZORPAY_PLAN_ID_WEEKLY to the new plan: new subscriptions use
it, existing ones stay on their old price.
"""
import argparse
import math
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def usd_weekly_price():
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    price = stripe.Price.retrieve(os.environ["STRIPE_PRICE_WEEKLY"])
    if price.currency.lower() != "usd":
        sys.exit(f"Stripe price is in {price.currency.upper()}, not USD -- pass --usd instead.")
    return price.unit_amount / 100


def usd_to_inr_rate():
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        sys.exit(f"Couldn't fetch the USD->INR rate ({e.__class__.__name__}). Pass --inr <rupees> instead.")
    if data.get("result") != "success":
        sys.exit(f"Exchange-rate lookup failed: {data}")
    return float(data["rates"]["INR"])


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--usd", type=float, help="USD weekly price (default: read from Stripe)")
    p.add_argument("--inr", type=int, help="Weekly price in whole rupees (skips conversion)")
    p.add_argument("--name", default="JobBeggar Weekly")
    p.add_argument("--dry-run", action="store_true", help="Print the price, create nothing")
    args = p.parse_args()

    if args.inr:
        inr = args.inr
        print(f"Price: Rs {inr}/week (given)")
    else:
        usd = args.usd if args.usd is not None else usd_weekly_price()
        rate = usd_to_inr_rate()
        inr = math.ceil(usd * rate)
        print(f"Price: ${usd:.2f}/week x {rate:.2f} INR/USD = Rs {inr}/week (rounded up)")

    if args.dry_run:
        return

    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not (key_id and key_secret):
        sys.exit("Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET first.")

    resp = requests.post(
        "https://api.razorpay.com/v1/plans",
        auth=(key_id, key_secret),
        json={
            "period": "weekly",
            "interval": 1,
            "item": {
                "name": args.name,
                "amount": inr * 100,  # paise
                "currency": "INR",
                "description": "Weekly access to JobBeggar. First 7 days free.",
            },
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        sys.exit(f"Razorpay error {resp.status_code}: {resp.text}")
    plan = resp.json()
    mode = "TEST" if key_id.startswith("rzp_test_") else "LIVE"
    print(f"Created {mode} plan {plan['id']} -- set RAZORPAY_PLAN_ID_WEEKLY={plan['id']}")


if __name__ == "__main__":
    main()
