import streamlit as st
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime
import smtplib
from email.message import EmailMessage
import json
import time


# =========================================================
# CONFIGURATION
# =========================================================

TICKER_FILE = "tickers.txt"
STATE_FILE = "earnings_alert_state.json"

DEFAULT_DAYS_AHEAD = 90


# =========================================================
# STREAMLIT CONFIG
# =========================================================

st.set_page_config(
    page_title="Earnings Alert Monitor",
    layout="wide"
)

st.title("Earnings Alert Monitor")


# =========================================================
# EMAIL CONFIGURATION
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

@st.cache_data
def load_tickers(filename):

    path = Path(filename)

    if not path.exists():
        return []

    with open(path, "r") as f:

        tickers = [
            line.strip().upper()
            for line in f
            if line.strip()
        ]

    return list(dict.fromkeys(tickers))


# =========================================================
# ALERT STATE
# =========================================================

def load_alert_state():

    path = Path(STATE_FILE)

    if not path.exists():
        return {}

    try:

        with open(path, "r") as f:
            return json.load(f)

    except Exception:
        return {}


def save_alert_state(state):

    try:

        with open(STATE_FILE, "w") as f:

            json.dump(
                state,
                f,
                indent=4
            )

    except Exception as e:

        st.warning(
            f"Could not save alert state: {e}"
        )


# =========================================================
# EMAIL
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
# PARSE DATE
# =========================================================

def clean_date(value):

    if value is None:
        return None

    try:

        # Some yfinance fields return a list
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
# GET DATE FROM CALENDAR
# =========================================================

def get_date_from_calendar(stock):

    try:

        calendar = stock.calendar

        if calendar is None:
            return None


        # -------------------------------------------------
        # Newer yfinance versions often return dict
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
        # Some versions return DataFrame
        # -------------------------------------------------

        if isinstance(
            calendar,
            pd.DataFrame
        ):

            # Index based
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


            # Column based
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

    except Exception:

        pass

    return None


# =========================================================
# GET DATE FROM EARNINGS DATES
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

        now = pd.Timestamp.now().normalize()

        future_dates = []

        for value in earnings.index:

            date = clean_date(value)

            if date is None:
                continue

            if date.normalize() >= now:

                future_dates.append(
                    date
                )

        if future_dates:

            return min(
                future_dates
            )

    except Exception:

        pass

    return None


# =========================================================
# FALLBACK USING YAHOO INFO
# =========================================================

def get_date_from_info(stock):

    try:

        info = stock.info

        # Yahoo may expose one of these fields
        timestamp = (
            info.get("earningsTimestamp")
            or info.get(
                "earningsTimestampStart"
            )
        )

        if timestamp:

            date = pd.to_datetime(
                timestamp,
                unit="s"
            )

            return clean_date(date)

    except Exception:

        pass

    return None


# =========================================================
# MAIN EARNINGS LOOKUP
# =========================================================

def get_next_earnings_date(ticker):

    stock = yf.Ticker(ticker)

    # -----------------------------------------------------
    # METHOD 1
    # Yahoo calendar
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
    # METHOD 2
    # Earnings date history / upcoming
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
    # METHOD 3
    # Quote metadata
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
        f"Earnings Alert: "
        f"{ticker} - "
        f"{formatted_date}"
    )

    body = f"""
Upcoming Earnings Announcement

Ticker:
{ticker}

Earnings Date:
{formatted_date}

Days Away:
{days_until}

Data Source:
{source}

Detected:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Earnings Alert Monitor
"""

    return send_email(
        subject,
        body
    )


# =========================================================
# SCAN TICKERS
# =========================================================

def scan_earnings(
    tickers,
    days_ahead,
    send_alerts
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
    new_alerts = []

    state = load_alert_state()

    progress = st.progress(0)
    status = st.empty()

    total = len(tickers)


    for i, ticker in enumerate(tickers):

        status.text(
            f"Checking {ticker} "
            f"({i + 1} of {total})"
        )

        try:

            earnings_date, source = (
                get_next_earnings_date(
                    ticker
                )
            )


            # =============================================
            # NO DATE
            # =============================================

            if earnings_date is None:

                failures.append(
                    {
                        "Ticker": ticker,
                        "Reason":
                            "No earnings date returned"
                    }
                )

                progress.progress(
                    (i + 1) / total
                )

                continue


            earnings_day = (
                earnings_date.normalize()
            )


            # =============================================
            # DATE WITHIN REQUESTED RANGE
            # =============================================

            if (
                today
                <= earnings_day
                <= end_date
            ):

                days_until = (
                    earnings_day
                    - today
                ).days


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


                # =========================================
                # UNIQUE ALERT
                # =========================================

                date_string = (
                    earnings_day.strftime(
                        "%Y-%m-%d"
                    )
                )

                alert_key = (
                    f"{ticker}_{date_string}"
                )


                # =========================================
                # SEND EMAIL ONLY ONCE
                # =========================================

                if (
                    send_alerts
                    and alert_key
                    not in state
                ):

                    success, error = (
                        send_earnings_alert(
                            ticker,
                            earnings_date,
                            days_until,
                            source
                        )
                    )


                    if success:

                        state[alert_key] = {
                            "ticker":
                                ticker,

                            "earnings_date":
                                date_string,

                            "source":
                                source,

                            "alert_sent":
                                datetime.now()
                                .isoformat()
                        }

                        save_alert_state(
                            state
                        )

                        new_alerts.append(
                            ticker
                        )

                    else:

                        st.warning(
                            f"Email failed "
                            f"for {ticker}: "
                            f"{error}"
                        )


        except Exception as e:

            failures.append(
                {
                    "Ticker": ticker,
                    "Reason": str(e)
                }
            )


        progress.progress(
            (i + 1) / total
        )


        # Avoid hammering Yahoo
        time.sleep(0.15)


    progress.empty()
    status.empty()


    return (
        pd.DataFrame(results),
        pd.DataFrame(failures),
        new_alerts
    )


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.header(
    "Scanner Settings"
)


days_ahead = st.sidebar.selectbox(
    "Upcoming earnings period",
    [
        7,
        14,
        30,
        60,
        90,
        120
    ],
    index=4
)


send_alerts = (
    st.sidebar.checkbox(
        "Send email alerts",
        value=True
    )
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
# TICKERS
# =========================================================

tickers = load_tickers(
    TICKER_FILE
)


if not tickers:

    st.error(
        f"No tickers found in "
        f"{TICKER_FILE}"
    )

    st.stop()


st.sidebar.metric(
    "Tickers Loaded",
    len(tickers)
)


with st.sidebar.expander(
    "View Tickers"
):

    st.write(
        ", ".join(tickers)
    )


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
# RUN SCAN
# =========================================================

if st.button(
    "Scan Earnings",
    type="primary"
):

    df, failures, new_alerts = (
        scan_earnings(
            tickers,
            days_ahead,
            send_alerts
        )
    )


    # =====================================================
    # ALERT SUMMARY
    # =====================================================

    if new_alerts:

        st.success(
            f"Sent {len(new_alerts)} "
            f"new email alert(s): "
            + ", ".join(new_alerts)
        )


    # =====================================================
    # RESULTS
    # =====================================================

    if df.empty:

        st.warning(
            f"No earnings found "
            f"in the next "
            f"{days_ahead} days."
        )

    else:

        df = (
            df.sort_values(
                [
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


        c1, c2 = st.columns(2)

        c1.metric(
            "Upcoming Earnings",
            len(display_df)
        )

        c2.metric(
            "Days Scanned",
            days_ahead
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
            "Download CSV",
            csv,
            "upcoming_earnings.csv",
            "text/csv"
        )


    # =====================================================
    # DIAGNOSTICS
    # =====================================================

    if not failures.empty:

        with st.expander(
            f"Tickers with no date "
            f"({len(failures)})"
        ):

            st.dataframe(
                failures,
                use_container_width=True,
                hide_index=True
            )


# =========================================================
# ALERT HISTORY
# =========================================================

st.divider()

with st.expander(
    "Email Alert History"
):

    state = load_alert_state()

    if not state:

        st.write(
            "No alerts sent yet."
        )

    else:

        history = []

        for value in state.values():

            history.append(
                {
                    "Ticker":
                        value.get(
                            "ticker"
                        ),

                    "Earnings Date":
                        value.get(
                            "earnings_date"
                        ),

                    "Source":
                        value.get(
                            "source"
                        ),

                    "Alert Sent":
                        value.get(
                            "alert_sent"
                        )
                }
            )


        history_df = (
            pd.DataFrame(
                history
            )
            .sort_values(
                "Alert Sent",
                ascending=False
            )
        )


        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True
        )
