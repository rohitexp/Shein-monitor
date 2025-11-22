# Shein Category Monitor -> Telegram Alerts (Hindi)

यह प्रोजेक्ट दिए गए Shein कैटेगरी पेज को मॉनिटर करता है और नए प्रोडक्ट/साइज/स्टॉक बदलाव पर Telegram में अलर्ट भेजता है। यह Playwright (हेडलैस ब्राउज़र) का उपयोग करता है ताकि JS से लोड होने वाली चीज़ें भी पढ़ी जा सकें।

## Features
- लिस्टिंग पेज से प्रोडक्ट लिंक निकालता है
- हर प्रोडक्ट पेज खोलकर साइज/स्टॉक ट्राय करता है
- बदलाव (नया प्रोडक्ट, नया साइज, री-स्टॉक, आउट ऑफ स्टॉक) डिटेक्ट करता है
- Telegram बोट से हिंदी में मैसेज भेजता है
- `state.json` में पिछला स्नैपशॉट सेव करता है ताकि डुप्लीकेट अलर्ट न आएँ

## Folder Structure
- `shein_monitor/requirements.txt`
- `shein_monitor/.env.example`
- `shein_monitor/config.json`
- `shein_monitor/notify.py`
- `shein_monitor/monitor.py`
- `shein_monitor/state.json`

## Setup
1) Python 3.10+ इंस्टॉल करें
2) Dependencies इंस्टॉल करें:
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

3) `.env` बनाएँ (इस प्रोजेक्ट फोल्डर में) और इसमें अपने Telegram details भरें:
```
cp .env.example .env
# फिर .env फाइल खोलकर TELEGRAM_BOT_TOKEN और TELEGRAM_CHAT_ID भरें
```
> Note: अपना बॉट बनाने के लिए Telegram पर BotFather से बात करें -> नया बॉट बनाएं -> टोकन मिलेगा। आपका `chat_id` पाने के लिए एक बार बॉट को `/start` भेजें और किसी `getUpdates` टूल/बॉट का उपयोग करें, या एक छोटा स्क्रिप्ट लिख सकते हैं।

4) `config.json` में URLs और सेटिंग्स बदल सकते हैं:
- `urls`: मॉनिटर की जाने वाली कैटेगरी पेजेज
- `poll_minutes`: कितनी देर में एक बार चेक करना है
- `scroll_steps`/`scroll_pause_ms`: लिस्टिंग पर कितनी स्क्रॉलिंग करनी है
- `max_products`: कितने प्रोडक्ट्स तक डिटेल्स देखें
- `notify_on`: कौन से बदलाव पर मैसेज भेजना है

## Run
```bash
python monitor.py
```
यह लगातार चलेगा और हर `poll_minutes` पर दुबारा चेक करेगा।

## Notes
- Shein जैसे साइट्स में एंटी-बॉट मेकैनिज्म हो सकता है। ज़रूरत पड़े तो `headless: false` कर के देखें या `scroll_steps` बढ़ाएँ।
- अगर प्रोडक्ट पेज पर साइज/स्टॉक JSON से आता है, तो `monitor.py` में JSON हीयूरिस्टिक्स से निकालने की कोशिश की जाती है। यदि किसी खास साइट स्ट्रक्चर के कारण डेटा नहीं मिल रहा हो तो हम selectors/logic अपडेट कर सकते हैं।
- प्रोक्सी की ज़रूरत हो तो `.env` में `HTTP_PROXY`/`HTTPS_PROXY` सेट करें।

## Customization
- हिंदी मैसेज टेम्पलेट्स `monitor.py` की `diff_products()` में हैं।
- अगर आप सिर्फ "नए प्रोडक्ट" या सिर्फ "री-स्टॉक" चाहते हैं, तो `config.json` के `notify_on` फ्लैग्स एडिट करें।

## Troubleshooting
- अगर कोई एरर आता है या साइट स्ट्रक्चर बदला दिखता है, मुझे बताइए; हम selectors अपडेट कर देंगे।
- Playwright ब्राउज़र इंस्टॉल स्टेप जरूर चलाएँ: `python -m playwright install chromium`.
