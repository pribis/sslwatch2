import curses
import ssl
import socket
from datetime import datetime, timezone
import threading
import queue
import whois

from gui import GUI
def check_ssl_status(domain_name, result_queue):
    """
    Fetches a domain's SSL certificate and determines its expiration status.
    This method is run in a separate thread and puts the result in a queue.
    """
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain_name, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain_name) as ssock:
                cert = ssock.getpeercert()

        # Parse the expiration date string into a datetime object
        exp_date_str = cert['notAfter']
        exp_date = datetime.strptime(exp_date_str, '%b %d %H:%M:%S %Y %Z')
        # Make the expiration date timezone-aware (it's in UTC/GMT)
        exp_date = exp_date.replace(tzinfo=timezone.utc)

        # Parse the issue date string
        issue_date_str = cert['notBefore']
        issue_date = datetime.strptime(issue_date_str, '%b %d %H:%M:%S %Y %Z')
        issue_date_str_formatted = issue_date.strftime('%Y-%m-%d')

        # Get issuer and subject details
        issuer_dict = dict(x[0] for x in cert['issuer'])
        subject_dict = dict(x[0] for x in cert['subject'])

        now = datetime.now(timezone.utc)
        days_left = (exp_date - now).days
        exp_date_str_formatted = exp_date.strftime('%Y-%m-%d')

        if days_left < 0:
            status = "EXPIRED"
        elif days_left <= 10:
            status = "ALERT"
        elif days_left <= 30:
            status = "WARNING"
        else:
            status = "OK"
        message = f"Status: {status}"

        result = {
            "domain": domain_name,
            "subject_cn": subject_dict.get('commonName', 'N/A'),
            "issuer_cn": issuer_dict.get('organizationName', issuer_dict.get('commonName', 'N/A')),
            "issued_on": issue_date_str_formatted,
            "expires_on": exp_date_str_formatted,
            "days_left": days_left,
            "status": status,
            "message": message
        }

    except socket.gaierror:
        result = {"domain": domain_name, "status": "ERROR", "message": f"Could not resolve hostname: '{domain_name}'."}
    except (socket.timeout, ConnectionRefusedError):
        result = {"domain": domain_name, "status": "ERROR", "message": f"Could not connect to '{domain_name}' on port 443."}
    except ssl.SSLCertVerificationError as e:
        result = {"domain": domain_name, "status": "ERROR", "message": f"SSL verification error for '{domain_name}': {e.reason}"}
    except (ValueError, KeyError) as e:
        result = {"domain": domain_name, "status": "ERROR", "message": f"Could not parse certificate for '{domain_name}'."}
    except Exception as e:
        result = {"domain": domain_name, "status": "ERROR", "message": f"An unexpected error occurred: {e}"}

    result_queue.put(result)

def get_whois_info(domain_name, result_queue):
    """
    Fetches whois information for a domain.
    This method is run in a separate thread and puts the result in a queue.
    """
    try:
        w = whois.whois(domain_name)
        result = {"domain": domain_name, "status": "WHOIS_SUCCESS", "data": w.text}
    except Exception as e:
        result = {"domain": domain_name, "status": "WHOIS_ERROR", "data": f"Could not retrieve whois info for '{domain_name}':\n{e}"}
    result_queue.put(result)

def main(stdscr):
    """The main function to run the TUI application."""
    checker_functions = {'ssl': check_ssl_status, 'whois': get_whois_info}
    ui = GUI(stdscr, checker_functions)
    ui.run()
        
if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except curses.error as e:
        print(f"Curses error: {e}")
        print("Your terminal may not support colors or has other limitations.")
    except KeyboardInterrupt:
        print("\nExiting application.")
