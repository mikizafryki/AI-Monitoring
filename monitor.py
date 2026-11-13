import imaplib
import email
from email.header import decode_header
import urllib.request
import urllib.parse
import json
import os
import datetime
import ssl

IMAP_SERVERS = {
    "wp.pl": "imap.wp.pl",
    "o2.pl": "poczta.o2.pl",
    "tlen.pl": "poczta.o2.pl",
    "interia.pl": "poczta.interia.pl",
    "interia.eu": "poczta.interia.pl",
    "int.pl": "poczta.interia.pl",
    "onet.pl": "imap.poczta.onet.pl",
    "op.pl": "imap.poczta.onet.pl",
    "vp.pl": "imap.poczta.onet.pl",
    "gmail.com": "imap.gmail.com",
    "gazeta.pl": "imap.gazeta.pl",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "icloud.com": "imap.mail.me.com"
}

KEYWORDS = [
    "kupił", "kupiono", "sprzedano", "wiadomość", "oferta", "ofertę",
    "etykiet", "przesyłk", "zamówien", "nadaj", "paczkomat", "inpost"
]

def decode_str(header_val):
    if not header_val:
        return ""
    decoded_parts = decode_header(header_val)
    result = []
    for content, encoding in decoded_parts:
        if isinstance(content, bytes):
            result.append(content.decode(encoding or "utf-8", errors="ignore"))
        else:
            result.append(str(content))
    return "".join(result)

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=15)

def connect_imap(imap_host):
    try:
        return imaplib.IMAP4_SSL(imap_host, 993, timeout=30)
    except Exception:
        mail = imaplib.IMAP4(imap_host, 143, timeout=30)
        mail.starttls(ssl_context=ssl.create_default_context())
        return mail

def check_account(acc, tg_token, tg_chat_id):
    label = acc.get("konto", "Konto")
    user_email = acc["email"].strip()
    password = acc["haslo"]
    domain = user_email.split("@")[-1].lower()
    imap_host = acc.get("imap") or IMAP_SERVERS.get(domain)

    if not imap_host:
        return False, f"{label}: nieznana domena ({domain})"

    try:
        mail = connect_imap(imap_host)
        mail.login(user_email, password)
        mail.select("INBOX")

        since_date = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%d-%b-%Y")
        status, response = mail.search(None, f'(UNSEEN SINCE "{since_date}")')

        if status == "OK" and response[0]:
            msg_nums = response[0].split()
            for num in msg_nums:
                res, msg_data = mail.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
                if res != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_header = msg_data[0][1]
                msg = email.message_from_bytes(raw_header)
                subject = decode_str(msg.get("Subject", "")).strip()
                sender = decode_str(msg.get("From", "")).lower()

                if "vinted" in sender or any(k in subject.lower() for k in KEYWORDS):
                    sub_low = subject.lower()
                    if any(w in sub_low for w in ["kupił", "kupiono", "sprzedano", "etykiet", "nadaj"]):
                        icon = "💰 SPRZEDANE!"
                    elif any(w in sub_low for w in ["ofert", "proponuje"]):
                        icon = "🏷️ NOWA OFERTA!"
                    else:
                        icon = "💬 WIADOMOŚĆ / INFO"

                    alert = f"{icon}\n👤 Profil: {label}\n📧 Mail: {user_email}\n📌 Temat: {subject}"
                    send_telegram(tg_token, tg_chat_id, alert)
                    mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return True, None
    except Exception as e:
        return False, f"{label} ({user_email}): {e}"

def main():
    tg_token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    accounts_raw = os.environ.get("ACCOUNTS_JSON", "").strip()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    if not (tg_token and tg_chat_id and accounts_raw):
        print("Brak skonfigurowanych sekretów w GitHub Secrets!")
        return

    accounts = json.loads(accounts_raw)
    if isinstance(accounts, str):
        accounts = json.loads(accounts)
    if isinstance(accounts, dict):
        if "email" in accounts:
            accounts = [accounts]
        else:
            for v in accounts.values():
                if isinstance(v, list):
                    accounts = v
                    break

    ok_count = 0
    errors = []

    for acc in accounts:
        if not isinstance(acc, dict) or "email" not in acc:
            continue
        ok, err = check_account(acc, tg_token, tg_chat_id)
        if ok:
            ok_count += 1
        else:
            errors.append(err)
            print("Błąd:", err)

    if event_name == "workflow_dispatch":
        msg = f"✅ Test monitoringu zakończony!\nPołączono poprawnie z {ok_count}/{len(accounts)} skrzynkami."
        if errors:
            msg += "\n\n⚠️ Błędy logowania:\n" + "\n".join(errors[:10])
        send_telegram(tg_token, tg_chat_id, msg)

if __name__ == "__main__":
    main()
