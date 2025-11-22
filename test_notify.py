from notify import send_telegram_message

if __name__ == "__main__":
    ok = send_telegram_message("✅ Test message from shein_monitor bot")
    print("send_telegram_message returned:", ok)
