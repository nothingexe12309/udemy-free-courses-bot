# Udemy Free Courses Telegram Bot

A Python bot that automatically scrapes free Udemy courses from Couponami/DiscUdemy and posts them to a Telegram channel. The bot includes duplicate detection, scheduled scraping, and multiple course detection methods.

## Features

- 🤖 **Automated Scraping**: Automatically scrapes free Udemy courses from Couponami.com
- 📱 **Telegram Integration**: Posts courses directly to your Telegram channel
- 🔍 **Smart Duplicate Detection**: Prevents posting the same course multiple times using:
  - Coupon link matching
  - Udemy course slug matching
  - Course title similarity matching
- ⏰ **Scheduled Updates**: Checks for new courses every 5 minutes (configurable)
- 🎨 **Rich Messages**: Posts courses with thumbnails, course details, and formatted messages
- 📊 **Database Tracking**: Uses SQLite to track posted courses
- 🛠️ **Multiple Detection Methods**: Uses 4 different methods to find all courses on the page

## Prerequisites

- Python 3.7 or higher
- A Telegram Bot Token (get from [@BotFather](https://t.me/BotFather))
- A Telegram Channel ID (where the bot will post courses)
- The bot must be added as an admin to your Telegram channel

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/nothingexe12309/udemy-free-courses-bot.git
   cd udemy-free-courses-bot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the bot:**
   - Open `botcode.py` (or rename it to `bot.py`)
   - Edit the configuration section at the top:
     ```python
     TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
     TELEGRAM_CHANNEL_ID = "@your_channel"  # or channel ID like "-1001234567890"
     SCRAPE_INTERVAL_MINUTES = 5  # How often to check for new courses
     ```

4. **Run the bot:**
   ```bash
   python "botcode.py"
   ```
   Or if you renamed it:
   ```bash
   python bot.py
   ```

## Configuration

Edit these variables in the script:

```python
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Get from @BotFather
TELEGRAM_CHANNEL_ID = "@your_channel"  # Your channel username or ID
SCRAPE_INTERVAL_MINUTES = 5  # Scraping interval in minutes
REQUEST_TIMEOUT = 15  # HTTP request timeout in seconds
DB_PATH = "posted_courses.db"  # SQLite database file path
COUPONAMI_URL = "https://www.couponami.com/all"  # URL to scrape
```

## Getting Your Telegram Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` command
3. Follow the instructions to create your bot
4. Copy the bot token provided

## Getting Your Channel ID

### Method 1: Using Channel Username
- Create a public channel (e.g., `@myudemycourses`)
- Use the username: `TELEGRAM_CHANNEL_ID = "@myudemycourses"`

### Method 2: Using Channel ID
- Add [@userinfobot](https://t.me/userinfobot) to your channel
- The bot will show the channel ID (e.g., `-1001234567890`)
- Use the ID: `TELEGRAM_CHANNEL_ID = "-1001234567890"`

**Important:** Make sure your bot is added as an admin to the channel!

## Bot Commands

The bot supports these commands when sent in a private chat with the bot:

- `/test [number]` - Scrape and post N courses (default: 10, max: 50). Allows reposting duplicates.
- `/test_scrape` - Scrape and post 1 fresh course to test functionality
- `/test_sample` - Post a sample course to test posting functionality

## How It Works

1. **Scraping**: The bot scrapes courses from Couponami.com using multiple detection methods:
   - Category-based link detection
   - Direct `/go/` coupon links
   - Course card container detection
   - Pattern-based link matching

2. **Duplicate Detection**: For each course, the bot checks:
   - If the coupon link was already posted
   - If the Udemy course slug matches any posted course
   - If the course title is similar to any posted course

3. **Posting**: New courses are posted to Telegram with:
   - Course thumbnail image
   - Course title and details
   - Direct Udemy course link
   - Formatted message with HTML

4. **Scheduling**: The bot runs automatically every 5 minutes (configurable)

## Project Structure

```
udemy-free-courses-bot/
├── botcode.py         # Main bot script (rename to bot.py if preferred)
├── requirements.txt      # Python dependencies
├── README.md            # This file
├── .gitignore          # Git ignore file
└── posted_courses.db   # SQLite database (created automatically)
```

## Dependencies

- `requests` - HTTP library for web scraping
- `beautifulsoup4` - HTML parsing
- `python-telegram-bot` - Telegram Bot API wrapper
- `apscheduler` - Task scheduling
- `lxml` - Fast XML/HTML parser (recommended)

## Troubleshooting

### Bot not posting to channel
- Make sure the bot is added as an admin to your channel
- Verify the channel ID is correct
- Check that the bot token is valid

### No courses found
- Check your internet connection
- Verify the Couponami URL is accessible
- Check the logs for error messages

### Database errors
- Make sure you have write permissions in the script directory
- Delete `posted_courses.db` if it's corrupted (will reset duplicate tracking)

## License

This project is open source and available for personal use.

## Disclaimer

This bot is for educational purposes only. Make sure to comply with:
- Couponami/DiscUdemy's terms of service
- Telegram's terms of service
- Respect rate limits and don't overload servers

## Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

## Support

If you encounter any issues, please:
1. Check the logs for error messages
2. Verify your configuration is correct
3. Make sure all dependencies are installed
4. Open an issue on GitHub

---

**Note:** Remember to keep your bot token and channel ID private. Never commit them to GitHub!



