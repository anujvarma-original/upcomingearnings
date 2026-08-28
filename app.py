import streamlit as st
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime
import smtplib
from email.message import EmailMessage
import time
import re


# =========================================================
# CONFIGURATION
# =========================================================

# Keep the ticker list beside this script so UI changes are retained even
# when Streamlit is launched from a different working directory.
TICKER_FILE = Path(__file__).resolve().parent / "tickers.txt"

# Alert on earnings occurring within the next 10 days
DAYS_AHEAD = 10


# =========================================================
# STREAMLIT CONFIG
# =========================================================

st.set_page_config(
    page_title="Earnings Alert Monitor",
    layout="wide"
)

st.title("Earnings Alert Monitor")

st.caption(
    f"Checks for earnings occurring within the next "
    f"{DAYS_AHEAD} calendar days and sends an email "
    f"for every qualifying ticker."
)


# =========================================================
# EMAIL CONFIGURATION
#
# Streamlit Secrets:
#
# [gmail]
# address = "yourgmail@gmail.com"
# app_password = "xxxx xxxx xxxx xxxx"
# alert_email = "destination@email.com"
# =========================================================

try:
    GMAIL_ADDRESS = st.secrets["gmail"]["address"]
    GMAIL_APP_PASSWORD = st.secrets["gmail"]["app_password"]
    ALERT_EMAIL = st.secrets["gmail"]["alert_email"]

    EMAIL_CONFIGURED = True

except Exception:
    GMAIL_ADDRESS = ""
    GMAIL_APP_PASSWORD = ""
    ALERT_EMAIL = ""

    EMAIL_CONFIGURED = False


# =========================================================
# LOAD TICKERS
# =========================================================

def normalize_tickers(raw_tickers):

    """Normalize, validate, and de-duplicate ticker symbols."""

    if isinstance(raw_tickers, str):
        candidates = re.split(r"[\s,;]+", raw_tickers)
    else:
        candidates = raw_tickers

    valid_tickers = []
    invalid_tickers = []

    for value in candidates:

        ticker = str(value).strip().upper()

        if not ticker:
            continue

        # Supports common Yahoo symbols such as BRK-B, BTC-USD, ^GSPC,
        # 0005.HK and futures symbols ending in =F.
        if re.fullmatch(r"[A-Z0-9.^=+-]+", ticker):
            valid_tickers.append(ticker)
        else:
            invalid_tickers.append(ticker)

    return (
        list(dict.fromkeys(valid_tickers)),
        list(dict.fromkeys(invalid_tickers))
    )


def load_tickers(filename):

    path = Path(filename)

    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        contents = f.read()

    tickers, _ = normalize_tickers(contents)
    return tickers


def save_tickers(filename, raw_tickers):

    tickers, invalid_tickers = normalize_tickers(raw_tickers)

    if invalid_tickers:
        return (
            False,
            tickers,
            "Invalid ticker symbol(s): "
            + ", ".join(invalid_tickers)
        )

    if not tickers:
        return False, [], "Enter at least one ticker symbol."

    path = Path(filename)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write a clean, predictable file with one ticker per line.
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(tickers) + "\n")

        return True, tickers, None

    except OSError as e:
        return False, tickers, f"Could not save tickers: {e}"


# =========================================================
# SEND EMAIL
# =========================================================

def send_email(subject, body):

    if not EMAIL_CONFIGURED:
        return False, "Gmail configuration missing."

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
# GET EARNINGS DATE FROM YAHOO CALENDAR
# =========================================================

def get_date_from_calendar(stock):

    try:

        calendar = stock.calendar

        if calendar is None:
            return None

        # -------------------------------------------------
        # Dictionary response
        # -------------------------------------------------

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

        # -------------------------------------------------
        # DataFrame response
        # -------------------------------------------------

        if isinstance(
            calendar,
            pd.DataFrame
        ):

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

                    date = clean_date(
                        value
                    )

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

                    date = clean_date(
                        value
                    )

                    if date is not None:
                        return date

    except Exception:
        pass

    return None


# =========================================================
# METHOD 2:
# GET DATE FROM UPCOMING / HISTORICAL EARNINGS
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

            date = clean_date(
                value
            )

            if date is None:
                continue

            if date.normalize() >= today:

                future_dates.append(
                    date
                )

        if future_dates:
            return min(future_dates)

    except Exception:
        pass

    return None


# =========================================================
# METHOD 3:
# GET DATE FROM YAHOO QUOTE METADATA
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

            return clean_date(
                date
            )

    except Exception:
        pass

    return None


# =========================================================
# MAIN EARNINGS LOOKUP
# =========================================================

def get_next_earnings_date(ticker):

    stock = yf.Ticker(ticker)

    # -----------------------------------------------------
    # Method 1 - Yahoo Calendar
    # -----------------------------------------------------

    date = get_date_from_calendar(
        stock
    )

    if date is not None:

        return (
            date,
            "Yahoo Calendar"
        )

    # -----------------------------------------------------
    # Method 2 - Earnings Dates
    # -----------------------------------------------------

    date = get_date_from_earnings_history(
        stock
    )

    if date is not None:

        return (
            date,
            "Yahoo Earnings Dates"
        )

    # -----------------------------------------------------
    # Method 3 - Quote Metadata
    # -----------------------------------------------------

    date = get_date_from_info(
        stock
    )

    if date is not None:

        return (
            date,
            "Yahoo Quote Metadata"
        )

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
    days_ahead,
    send_alerts=True
):

    today = pd.Timestamp.now().normalize()

    end_date = (
        today
        + pd.Timedelta(
            days=days_ahead
        )
    )

    results = []
    failures = []
    sent_alerts = []

    progress_bar = st.progress(0)
    status = st.empty()

    total = len(tickers)

    for i, ticker in enumerate(tickers):

        status.text(
            f"Checking {ticker} "
            f"({i + 1} of {total})..."
        )

        try:

            earnings_date, source = (
                get_next_earnings_date(
                    ticker
                )
            )

            # ---------------------------------------------
            # No earnings date returned
            # ---------------------------------------------

            if earnings_date is None:

                failures.append(
                    {
                        "Ticker": ticker,
                        "Reason":
                            "No earnings date returned"
                    }
                )

            else:

                earnings_day = (
                    earnings_date.normalize()
                )

                days_until = (
                    earnings_day - today
                ).days

                # -----------------------------------------
                # Only earnings from today through
                # DAYS_AHEAD
                # -----------------------------------------

                if (
                    today
                    <= earnings_day
                    <= end_date
                ):

                    results.append(
                        {
                            "Ticker":
                                ticker,

                            "Earnings Date":
                                earnings_date,

                            "Days Away":
                                days_until,

                            "Source":
                                source
                        }
                    )

                    # =====================================
                    # ALWAYS SEND EMAIL
                    #
                    # No duplicate protection.
                    # Every qualifying ticker gets an email
                    # every time this app runs.
                    # =====================================

                    if send_alerts:

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

                        else:

                            failures.append(
                                {
                                    "Ticker":
                                        ticker,

                                    "Reason":
                                        f"Email failed: "
                                        f"{error}"
                                }
                            )

        except Exception as e:

            failures.append(
                {
                    "Ticker":
                        ticker,

                    "Reason":
                        str(e)
                }
            )

        progress_bar.progress(
            (i + 1) / total
        )

        # Helps reduce Yahoo throttling
        time.sleep(0.15)

    progress_bar.empty()
    status.empty()

    return (
        pd.DataFrame(results),
        pd.DataFrame(failures),
        sent_alerts
    )


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.header(
    "Monitor Status"
)

st.sidebar.metric(
    "Alert Window",
    f"{DAYS_AHEAD} Days"
)


# =========================================================
# EMAIL STATUS
# =========================================================

if EMAIL_CONFIGURED:

    st.sidebar.success(
        "Gmail configured"
    )

    st.sidebar.caption(
        f"Alerts → {ALERT_EMAIL}"
    )

else:

    st.sidebar.error(
        "Gmail not configured"
    )


# =========================================================
# LOAD TICKERS
# =========================================================

tickers = load_tickers(
    TICKER_FILE
)

with st.sidebar.expander(
    "Manage Tickers",
    expanded=not bool(tickers)
):

    st.caption(
        "Add, edit, or remove symbols below. "
        "Use one ticker per line, or separate them with commas."
    )

    with st.form("ticker_manager_form"):

        ticker_text = st.text_area(
            "Monitored tickers",
            value="\n".join(tickers),
            height=220,
            placeholder="NVDA\nAMD\nMSFT"
        )

        save_ticker_button = st.form_submit_button(
            "Save Tickers",
            use_container_width=True
        )

    if save_ticker_button:

        success, saved_tickers, error = save_tickers(
            TICKER_FILE,
            ticker_text
        )

        if success:
            tickers = saved_tickers
            st.success(
                f"Saved {len(tickers)} ticker(s). "
                "They will be retained for future runs."
            )
        else:
            st.error(error)


st.sidebar.metric(
    "Tickers Loaded",
    len(tickers)
)


with st.sidebar.expander(
    "View Saved Tickers"
):

    if tickers:
        st.write(", ".join(tickers))
    else:
        st.caption("No tickers have been saved yet.")


if not tickers:

    st.error(
        "No tickers are configured. Open **Manage Tickers** "
        "in the sidebar, enter the symbols to monitor, and save them."
    )

    st.stop()


# =========================================================
# TEST SINGLE TICKER
# =========================================================

st.sidebar.divider()

st.sidebar.subheader(
    "Test Earnings Lookup"
)

test_ticker = (
    st.sidebar.text_input(
        "Ticker",
        value="NVDA"
    )
    .strip()
    .upper()
)


if st.sidebar.button(
    "Test Ticker"
):

    date, source = (
        get_next_earnings_date(
            test_ticker
        )
    )

    if date:

        st.sidebar.success(
            f"{test_ticker}: "
            f"{date.strftime('%b %d, %Y')}"
        )

        st.sidebar.caption(
            f"Source: {source}"
        )

    else:

        st.sidebar.error(
            f"No earnings date "
            f"found for {test_ticker}"
        )


# =========================================================
# AUTOMATIC SCAN
#
# This runs every time Streamlit executes this script.
# =========================================================

st.subheader(
    "Today's Earnings Scan"
)

st.info(
    f"Checking {len(tickers)} tickers for "
    f"earnings occurring within the next "
    f"{DAYS_AHEAD} days."
)

scan_started = datetime.now()

df, failures, sent_alerts = (
    scan_earnings(
        tickers,
        DAYS_AHEAD,
        send_alerts=True
    )
)

scan_finished = datetime.now()


# =========================================================
# SCAN SUMMARY
# =========================================================

st.caption(
    "Last scan: "
    + scan_finished.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
)


# =========================================================
# EMAIL SUMMARY
# =========================================================

if sent_alerts:

    st.success(
        f"Sent {len(sent_alerts)} email alert(s): "
        + ", ".join(sent_alerts)
    )

else:

    st.info(
        "No email alerts were sent."
    )


# =========================================================
# UPCOMING EARNINGS TABLE
# =========================================================

if df.empty:

    st.warning(
        f"No earnings found within "
        f"the next {DAYS_AHEAD} days."
    )

else:

    df = (
        df.sort_values(
            by=[
                "Earnings Date",
                "Ticker"
            ]
        )
        .reset_index(
            drop=True
        )
    )

    display_df = df.copy()

    display_df[
        "Earnings Date"
    ] = (
        pd.to_datetime(
            display_df[
                "Earnings Date"
            ]
        )
        .dt.strftime(
            "%a %b %d, %Y"
        )
    )

    st.subheader(
        "Upcoming Earnings"
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Upcoming Earnings",
        len(display_df)
    )

    c2.metric(
        "Alert Window",
        f"{DAYS_AHEAD} Days"
    )

    c3.metric(
        "Emails Sent",
        len(sent_alerts)
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    csv = (
        display_df
        .to_csv(
            index=False
        )
        .encode("utf-8")
    )

    st.download_button(
        label="Download CSV",
        data=csv,
        file_name="upcoming_earnings.csv",
        mime="text/csv"
    )


# =========================================================
# FAILURES / NO DATE
# =========================================================

if not failures.empty:

    with st.expander(
        f"Lookup / Email Issues "
        f"({len(failures)})"
    ):

        st.dataframe(
            failures,
            use_container_width=True,
            hide_index=True
        )
