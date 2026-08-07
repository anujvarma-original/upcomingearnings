import os
import sys
import time
import smtplib
from pathlib import Path
from datetime import datetime
from email.message import EmailMessage

import pandas as pd
import yfinance as yf


# =========================================================
# CONFIGURATION
# =========================================================

TICKER_FILE = "tickers.txt"

# Alert on earnings occurring within the next 10 days
DAYS_AHEAD = 10


# =========================================================
# EMAIL CONFIGURATION
#
# GitHub Actions environment variables:
#
# GMAIL_ADDRESS
# GMAIL_APP_PASSWORD
# ALERT_EMAIL
# =========================================================

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")


# =========================================================
# LOAD TICKERS
# =========================================================

def load_tickers(filename):

    path = Path(filename)

    if not path.exists():
        raise FileNotFoundError(
            f"Ticker file not found: {filename}"
        )

    with open(path, "r") as f:
        tickers = [
            line.strip().upper()
            for line in f
            if line.strip()
        ]

    return list(dict.fromkeys(tickers))


# =========================================================
# EMAIL CONFIG CHECK
# =========================================================

def validate_email_configuration():

    missing = []

    if not GMAIL_ADDRESS:
        missing.append("GMAIL_ADDRESS")

    if not GMAIL_APP_PASSWORD:
        missing.append("GMAIL_APP_PASSWORD")

    if not ALERT_EMAIL:
        missing.append("ALERT_EMAIL")

    if missing:
        raise RuntimeError(
            "Missing environment variable(s): "
            + ", ".join(missing)
        )


# =========================================================
# SEND EMAIL
# =========================================================

def send_email(subject, body):

    try:

        msg = EmailMessage()

        msg["From"] = GMAIL_ADDRESS
        msg["To"] = ALERT_EMAIL
        msg["Subject"] = subject

        msg.set_content(body)

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465
        ) as smtp:

            smtp.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            smtp.send_message(msg)

        return True, None

    except Exception as e:
        return False, str(e)


# =========================================================
# CLEAN / NORMALIZE DATE
# =========================================================

def clean_date(value):

    if value is None:
        return None

    try:

        if isinstance(
            value,
            (list, tuple)
        ):

            if not value:
                return None

            value = value[0]

        date = pd.Timestamp(value)

        if date.tzinfo is not None:
            date = date.tz_localize(None)

        return date

    except Exception:
        return None


# =========================================================
# METHOD 1:
# YAHOO CALENDAR
# =========================================================

def get_date_from_calendar(stock):

    try:

        calendar = stock.calendar

        if calendar is None:
            return None

        if isinstance(calendar, dict):

            for key in [
                "Earnings Date",
                "EarningsDate",
                "earningsDate"
            ]:

                if key in calendar:

                    date = clean_date(
                        calendar[key]
                    )

                    if date is not None:
                        return date

        if isinstance(calendar, pd.DataFrame):

            for key in [
                "Earnings Date",
                "EarningsDate"
            ]:

                if key in calendar.index:

                    value = (
                        calendar
                        .loc[key]
                        .iloc[0]
                    )

                    date = clean_date(value)

                    if date is not None:
                        return date

            for key in [
                "Earnings Date",
                "EarningsDate"
            ]:

                if key in calendar.columns:

                    value = (
                        calendar[key]
                        .iloc[0]
                    )

                    date = clean_date(value)

                    if date is not None:
                        return date

    except Exception as e:
        print(
            f"Calendar lookup error: {e}"
        )

    return None


# =========================================================
# METHOD 2:
# UPCOMING / HISTORICAL EARNINGS
# =========================================================

def get_date_from_earnings_history(stock):

    try:

        earnings = stock.get_earnings_dates(
            limit=12
        )

        if (
            earnings is None
            or earnings.empty
        ):
            return None

        today = pd.Timestamp.now().normalize()

        future_dates = []

        for value in earnings.index:

            date = clean_date(value)

            if date is None:
                continue

            if date.normalize() >= today:

                future_dates.append(date)

        if future_dates:
            return min(future_dates)

    except Exception as e:
        print(
            f"Earnings history lookup error: {e}"
        )

    return None


# =========================================================
# METHOD 3:
# YAHOO QUOTE METADATA
# =========================================================

def get_date_from_info(stock):

    try:

        info = stock.info

        timestamp = (
            info.get("earningsTimestamp")
            or info.get("earningsTimestampStart")
        )

        if timestamp:

            date = pd.to_datetime(
                timestamp,
                unit="s"
            )

            return clean_date(date)

    except Exception as e:
        print(
            f"Quote metadata lookup error: {e}"
        )

    return None


# =========================================================
# MAIN EARNINGS LOOKUP
# =========================================================

def get_next_earnings_date(ticker):

    stock = yf.Ticker(ticker)

    # Method 1
    date = get_date_from_calendar(stock)

    if date is not None:
        return date, "Yahoo Calendar"

    # Method 2
    date = get_date_from_earnings_history(stock)

    if date is not None:
        return date, "Yahoo Earnings Dates"

    # Method 3
    date = get_date_from_info(stock)

    if date is not None:
        return date, "Yahoo Quote Metadata"

    return None, "Not Found"


# =========================================================
# SEND EARNINGS ALERT
# =========================================================

def send_earnings_alert(
    ticker,
    earnings_date,
    days_until,
    source
):

    formatted_date = (
        earnings_date.strftime(
            "%A, %B %d, %Y"
        )
    )

    subject = (
        f"{ticker} Earnings in "
        f"{days_until} Days - "
        f"{formatted_date}"
    )

    body = f"""
UPCOMING EARNINGS ALERT

Ticker:
{ticker}

Earnings Date:
{formatted_date}

Days Until Earnings:
{days_until}

Data Source:
{source}

Checked:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

This alert was generated automatically by the
Earnings Alert Monitor.
"""

    return send_email(
        subject,
        body
    )


# =========================================================
# SCAN EARNINGS
# =========================================================

def scan_earnings(
    tickers,
    days_ahead
):

    today = pd.Timestamp.now().normalize()

    end_date = (
        today
        + pd.Timedelta(
            days=days_ahead
        )
    )

    qualifying = []
    sent_alerts = []
    failures = []

    total = len(tickers)

    print()
    print("=" * 60)
    print("EARNINGS ALERT SCAN")
    print("=" * 60)

    print(
        f"Checking {total} ticker(s) for earnings "
        f"between {today.date()} and "
        f"{end_date.date()}."
    )

    print()

    for i, ticker in enumerate(
        tickers,
        start=1
    ):

        print(
            f"[{i}/{total}] Checking {ticker}..."
        )

        try:

            earnings_date, source = (
                get_next_earnings_date(
                    ticker
                )
            )

            if earnings_date is None:

                print(
                    f"    No earnings date found."
                )

                failures.append(
                    {
                        "Ticker": ticker,
                        "Reason":
                            "No earnings date returned"
                    }
                )

                continue

            earnings_day = (
                earnings_date.normalize()
            )

            days_until = (
                earnings_day - today
            ).days

            print(
                f"    Earnings: "
                f"{earnings_day.date()} "
                f"({days_until} days)"
            )

            print(
                f"    Source: {source}"
            )

            # =================================================
            # QUALIFYING WINDOW
            # =================================================

            if (
                today
                <= earnings_day
                <= end_date
            ):

                qualifying.append(
                    {
                        "Ticker": ticker,
                        "Earnings Date":
                            earnings_date,
                        "Days Away":
                            days_until,
                        "Source":
                            source
                    }
                )

                print(
                    "    QUALIFIES - sending email..."
                )

                # =============================================
                # ALWAYS SEND
                #
                # There is deliberately NO duplicate tracking.
                #
                # Every ticker qualifying on every execution
                # receives another email.
                # =============================================

                success, error = (
                    send_earnings_alert(
                        ticker,
                        earnings_date,
                        days_until,
                        source
                    )
                )

                if success:

                    sent_alerts.append(
                        ticker
                    )

                    print(
                        "    EMAIL SENT"
                    )

                else:

                    failures.append(
                        {
                            "Ticker": ticker,
                            "Reason":
                                f"Email failed: {error}"
                        }
                    )

                    print(
                        f"    EMAIL FAILED: {error}"
                    )

            else:

                print(
                    "    Outside alert window."
                )

        except Exception as e:

            failures.append(
                {
                    "Ticker": ticker,
                    "Reason": str(e)
                }
            )

            print(
                f"    ERROR: {e}"
            )

        # Reduce Yahoo throttling
        time.sleep(0.15)

    return (
        pd.DataFrame(qualifying),
        pd.DataFrame(failures),
        sent_alerts
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        f"Scan started: "
        f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    )

    try:

        validate_email_configuration()

        tickers = load_tickers(
            TICKER_FILE
        )

        if not tickers:

            print(
                "No tickers found."
            )

            return 1

        print(
            f"Loaded {len(tickers)} ticker(s)."
        )

        df, failures, sent_alerts = (
            scan_earnings(
                tickers,
                DAYS_AHEAD
            )
        )

        print()
        print("=" * 60)
        print("SCAN COMPLETE")
        print("=" * 60)

        print(
            f"Qualifying earnings: {len(df)}"
        )

        print(
            f"Emails sent: {len(sent_alerts)}"
        )

        if sent_alerts:

            print(
                "Alerts: "
                + ", ".join(sent_alerts)
            )

        if not failures.empty:

            print()
            print(
                f"Issues: {len(failures)}"
            )

            for _, row in failures.iterrows():

                print(
                    f"  {row['Ticker']}: "
                    f"{row['Reason']}"
                )

        print()
        print(
            f"Scan finished: "
            f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        )

        return 0

    except Exception as e:

        print(
            f"FATAL ERROR: {e}"
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
