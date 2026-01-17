"""
Udemy Free Courses Telegram Bot - Single File Version
Automatically collects free Udemy courses and posts them to a Telegram channel
"""

import asyncio
import sqlite3
import time
import logging
import sys
import re
import html
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ============================================================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================================================

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Get from @BotFather on Telegram
TELEGRAM_CHANNEL_ID = "@your_channel"  # Your channel username (e.g., @myudemycourses) or channel ID (e.g., -1001234567890)
SCRAPE_INTERVAL_MINUTES = 5  # How often to check for new courses (in minutes)
REQUEST_TIMEOUT = 15  # Timeout for HTTP requests (in seconds)
DB_PATH = "posted_courses.db"  # SQLite database file
COUPONAMI_URL = "https://www.couponami.com/all"  # Only track courses from this URL

# ============================================================================
# SETUP LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE CLASS
# ============================================================================

class CourseDatabase:
    """Manages database operations for tracking posted courses"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Initialize the database with required tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS posted_courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_title TEXT NOT NULL,
                    coupon_link TEXT UNIQUE NOT NULL,
                    udemy_url TEXT,
                    posted_at INTEGER NOT NULL,
                    source TEXT
                )
            ''')
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
    
    def is_posted(self, coupon_link: str, udemy_url: str = None, course_title: str = None) -> bool:
        """Check if a course has already been posted (by coupon_link, udemy_url, or course title)"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Method 1: Check by exact coupon_link (normalize URL first)
            if coupon_link:
                # Normalize coupon_link for comparison (remove query params and fragments)
                normalized_coupon = re.sub(r'[?#].*$', '', coupon_link)
                c.execute('SELECT 1 FROM posted_courses WHERE coupon_link = ? OR coupon_link LIKE ?', 
                         (coupon_link, f'{normalized_coupon}%'))
                if c.fetchone() is not None:
                    logger.debug(f"Duplicate found by coupon_link: {coupon_link[:50]}...")
                    return True
            
            # Method 2: Check by Udemy URL (extract course slug)
            if udemy_url:
                # Normalize Udemy URL first
                normalized_udemy = re.sub(r'[?#].*$', '', udemy_url)
                # Extract course slug from Udemy URL (e.g., "python-hacking-course" from full URL)
                course_slug_match = re.search(r'/course/([^/?]+)', normalized_udemy)
                if course_slug_match:
                    course_slug = course_slug_match.group(1)
                    # Check if any posted course has the same slug
                    c.execute('SELECT udemy_url FROM posted_courses WHERE udemy_url LIKE ?', (f'%{course_slug}%',))
                    if c.fetchone() is not None:
                        logger.debug(f"Duplicate found by Udemy course slug: {course_slug}")
                        return True
            
            # Method 3: Check by course title (normalized - remove special chars, lowercase)
            if course_title:
                # Normalize title for comparison
                normalized_title = re.sub(r'[^\w\s]', '', course_title.lower().strip())
                if len(normalized_title) > 10:  # Only check if title is meaningful
                    # Get all posted course titles and compare
                    c.execute('SELECT course_title FROM posted_courses')
                    posted_titles = c.fetchall()
                    for (posted_title,) in posted_titles:
                        if posted_title:
                            normalized_posted = re.sub(r'[^\w\s]', '', posted_title.lower().strip())
                            # Check if titles are very similar (90% match or more)
                            if normalized_title == normalized_posted or \
                               (len(normalized_title) > 20 and normalized_title in normalized_posted) or \
                               (len(normalized_posted) > 20 and normalized_posted in normalized_title):
                                logger.debug(f"Duplicate found by course title: {course_title[:50]}...")
                                return True
            
            return False
        except Exception as e:
            logger.error(f"Error checking if course is posted: {e}", exc_info=True)
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
    def mark_posted(self, course_title: str, coupon_link: str, udemy_url: str = None, source: str = None):
        """Mark a course as posted"""
        conn = None
        try:
            # Normalize URLs before storing (remove query params and fragments for consistency)
            normalized_coupon = re.sub(r'[?#].*$', '', coupon_link) if coupon_link else None
            normalized_udemy = re.sub(r'[?#].*$', '', udemy_url) if udemy_url else None
            
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Check if already exists first (prevent duplicates in database)
            c.execute('SELECT 1 FROM posted_courses WHERE coupon_link = ? OR coupon_link LIKE ?', 
                     (coupon_link, f'{normalized_coupon}%'))
            if c.fetchone() is not None:
                logger.debug(f"Course already in database: {course_title[:50]}...")
                return
            
            # Insert new record (store normalized URLs)
            c.execute('''
                INSERT INTO posted_courses 
                (course_title, coupon_link, udemy_url, posted_at, source)
                VALUES (?, ?, ?, ?, ?)
            ''', (course_title, normalized_coupon or coupon_link, normalized_udemy or udemy_url, int(time.time()), source))
            conn.commit()
            logger.info(f"✅ Marked course as posted: {course_title[:50]}...")
        except sqlite3.IntegrityError:
            # Duplicate entry (shouldn't happen with our check, but handle it)
            logger.warning(f"Course already exists in database: {course_title[:50]}...")
        except Exception as e:
            logger.error(f"Error marking course as posted: {e}", exc_info=True)
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
    def get_recent_courses(self, limit: int = 10) -> List[Dict]:
        """Get the most recent posted courses"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT course_title, coupon_link, udemy_url 
                FROM posted_courses 
                ORDER BY posted_at DESC 
                LIMIT ?
            ''', (limit,))
            results = c.fetchall()
            conn.close()
            
            courses = []
            for row in results:
                courses.append({
                    'title': row[0],
                    'coupon_link': row[1],
                    'udemy_url': row[2] if row[2] else '',
                    'thumbnail': None  # Thumbnail not stored in DB, will use None
                })
            return courses
        except Exception as e:
            logger.error(f"Error getting recent courses: {e}")
            return []

# ============================================================================
# UDEMY SCRAPER CLASS
# ============================================================================

class UdemyScraper:
    """Scrapes free Udemy courses from various aggregator sites"""
    
    def __init__(self, timeout: int = REQUEST_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def scrape_couponami(self) -> List[Dict]:
        """Scrape free courses from Couponami /all page only"""
        courses = []
        try:
            url = COUPONAMI_URL
            logger.info(f"Scraping Couponami: {url}")
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            logger.info(f"Response status: {response.status_code}, Content length: {len(response.text)}")
            
            # Try lxml parser first, fallback to html.parser if lxml fails
            try:
                soup = BeautifulSoup(response.text, 'lxml')
            except Exception as e:
                logger.warning(f"lxml parser failed, trying html.parser: {e}")
                soup = BeautifulSoup(response.text, 'html.parser')
            
            # Method 1: Find all links that look like course links (any category path)
            # Match any path that starts with / and contains course-related keywords or is a category
            category_links = soup.find_all('a', href=re.compile(r'/(marketing|development|design|business|it-software|personal-development|photography|music|teaching|academic|graphic-design|3d-model|ethical-hacking|after-effects|network-security|python|data-science|web-development|mobile-development|cloud|devops|cybersecurity|ai|machine-learning|blockchain|game-development|ui-ux|video-editing|animation|writing|finance|health|fitness|language|programming|database|software-engineering|testing|automation)/'))
            logger.info(f"Method 1 (category links): Found {len(category_links)} links")
            
            # Method 2: Find /go/ links (direct coupon links)
            go_links = soup.find_all('a', href=re.compile(r'/go/'))
            logger.info(f"Method 2 (/go/ links): Found {len(go_links)} links")
            
            course_links = list(category_links)
            course_links.extend(go_links)
            
            # Method 3: Find course cards/containers and extract links from them
            # Look for common course card patterns (divs with course-related classes)
            course_containers = soup.find_all(['div', 'article', 'section'], 
                class_=re.compile(r'course|card|item|post|deal|coupon', re.I))
            logger.info(f"Method 3 (course containers): Found {len(course_containers)} containers")
            
            container_link_count = 0
            existing_hrefs_method3 = {l.get('href', '') for l in course_links if l.get('href')}
            for container in course_containers:
                # Find all links within course containers
                container_links = container.find_all('a', href=True)
                for link in container_links:
                    href = link.get('href', '')
                    if href and (href.startswith('/') or 'couponami.com' in href or 'discudemy.com' in href):
                        # Check if it's a course link (not navigation, footer, etc.)
                        if not any(skip in href.lower() for skip in ['#', 'javascript:', 'mailto:', 'tel:', '/tag/', '/category/', '/author/', '/page/', '/search', '/about', '/contact', '/privacy', '/terms']):
                            # Check by href instead of object identity
                            if href not in existing_hrefs_method3:
                                course_links.append(link)
                                existing_hrefs_method3.add(href)
                                container_link_count += 1
            logger.info(f"Method 3: Added {container_link_count} new links from containers")
            
            # Method 4: Find all links that contain course-related patterns
            # Look for links that might be course pages but don't match the category pattern
            all_links = soup.find_all('a', href=True)
            logger.info(f"Method 4: Checking {len(all_links)} total links on page")
            
            existing_hrefs = {l.get('href', '') for l in course_links}
            pattern_link_count = 0
            for link in all_links:
                href = link.get('href', '')
                if href:
                    # Check if it's a potential course link (has a path structure like /something/something/)
                    if re.match(r'^/[^/]+/[^/]+', href) and href not in existing_hrefs:
                        # Exclude common non-course paths
                        if not any(skip in href.lower() for skip in ['/tag/', '/category/', '/author/', '/page/', '/search', '/about', '/contact', '/privacy', '/terms', '/login', '/register', '/wp-', '/static/', '/assets/', '/css/', '/js/', '/img/', '/images/']):
                            # Check if parent element looks like a course card (has image, title, etc.)
                            parent = link.parent
                            if parent:
                                # If parent has an image or looks like a course card, include it
                                has_img = parent.find('img') is not None
                                has_title = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) is not None
                                if has_img or has_title:
                                    course_links.append(link)
                                    existing_hrefs.add(href)
                                    pattern_link_count += 1
            logger.info(f"Method 4: Added {pattern_link_count} new links from pattern matching")
            
            logger.info(f"Total found: {len(course_links)} potential course links")
            
            seen_urls = set()  # Track to avoid duplicates
            
            for link in course_links:
                try:
                    href = link.get('href', '')
                    if not href or not isinstance(href, str):
                        continue
                    
                    # Clean href
                    href = href.strip()
                    if not href:
                        continue
                    
                    # Build full URL
                    course_url = None
                    if href.startswith('/'):
                        # Handle both couponami.com and discudemy.com
                        if 'discudemy.com' in COUPONAMI_URL:
                            course_url = "https://www.discudemy.com" + href
                        else:
                            course_url = "https://www.couponami.com" + href
                    elif href.startswith('http://') or href.startswith('https://'):
                        course_url = href
                    else:
                        continue
                    
                    # Ensure course_url is set
                    if not course_url:
                        continue
                    
                    # Normalize URL (remove fragments, query params for comparison)
                    normalized_url = re.sub(r'[?#].*$', '', course_url)
                    
                    # Skip if already seen
                    if normalized_url in seen_urls:
                        continue
                    seen_urls.add(normalized_url)
                    
                    # Extract title - try multiple methods
                    title = link.get_text(strip=True)
                    
                    # If title is empty or too short, try finding in parent elements
                    if not title or len(title) < 5:
                        parent = link.parent
                        if parent:
                            # Look for heading tags (h1-h6)
                            title_elem = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                            else:
                                # Look for title attribute
                                title = link.get('title', '') or parent.get('title', '')
                                if not title or len(title) < 5:
                                    # Try getting text from parent, but clean it up
                                    title = parent.get_text(strip=True)
                                    if title:
                                        # Remove common non-title text
                                        title = re.sub(r'\$[\d,]+.*?$', '', title)  # Remove price
                                        title = re.sub(r'\d+\s*(views?|enrolls?|students?)', '', title, flags=re.I)  # Remove view counts
                                        title = re.sub(r'\s+', ' ', title).strip()  # Normalize whitespace
                    
                    # Try finding title in nearby elements (siblings, parent's parent)
                    if not title or len(title) < 5:
                        # Check parent's parent
                        grandparent = link.parent.parent if link.parent else None
                        if grandparent:
                            title_elem = grandparent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                            if title_elem:
                                title = title_elem.get_text(strip=True)
                    
                    # Final check - skip if still no valid title
                    if not title or len(title) < 5:
                        logger.debug(f"Skipping link with no valid title: {course_url[:80]}")
                        continue
                    
                    # Extract thumbnail - try multiple methods
                    thumbnail = None
                    img_elem = link.find('img')
                    
                    # Try finding in parent
                    if not img_elem:
                        parent = link.parent
                        if parent:
                            img_elem = parent.find('img')
                    
                    # Try finding in parent's parent
                    if not img_elem:
                        grandparent = link.parent.parent if link.parent else None
                        if grandparent:
                            img_elem = grandparent.find('img')
                    
                    # Try finding in siblings
                    if not img_elem and link.parent:
                        siblings = link.parent.find_all('img')
                        if siblings:
                            img_elem = siblings[0]
                    
                    if img_elem:
                        # Try multiple src attributes
                        thumbnail = (img_elem.get('src') or 
                                    img_elem.get('data-src') or 
                                    img_elem.get('data-lazy-src') or
                                    img_elem.get('data-original') or
                                    img_elem.get('data-url'))
                        
                        if thumbnail:
                            # Clean up thumbnail URL
                            thumbnail = thumbnail.split('?')[0]  # Remove query params
                            if thumbnail.startswith('/'):
                                # Handle both couponami.com and discudemy.com
                                if 'discudemy.com' in COUPONAMI_URL:
                                    thumbnail = "https://www.discudemy.com" + thumbnail
                                else:
                                    thumbnail = "https://www.couponami.com" + thumbnail
                            elif not thumbnail.startswith('http'):
                                if 'discudemy.com' in COUPONAMI_URL:
                                    thumbnail = "https://www.discudemy.com/" + thumbnail
                                else:
                                    thumbnail = "https://www.couponami.com/" + thumbnail
                    
                    # Get course details from the course page (only if it's not a /go/ link)
                    course_details = {}
                    if '/go/' not in course_url:
                        course_details = self.get_course_details(course_url)
                    else:
                        # If it's a /go/ link, we'll get details later when processing
                        logger.debug(f"Skipping details for /go/ link, will get later")
                    
                    courses.append({
                        'title': title,
                        'coupon_link': course_url,
                        'thumbnail': thumbnail,
                        'source': 'couponami',
                        'language': course_details.get('language'),
                        'publisher': course_details.get('publisher'),
                        'rate': course_details.get('rate'),
                        'enroll': course_details.get('enroll'),
                        'price': course_details.get('price')
                    })
                    logger.debug(f"Added course: {title[:50]}...")
                    
                except Exception as e:
                    logger.warning(f"Error parsing course link: {e}")
                    continue
            
            logger.info(f"Successfully scraped {len(courses)} courses from {url}")
                    
        except Exception as e:
            logger.error(f"Error scraping Couponami: {e}", exc_info=True)
        
        return courses
    
    def get_course_details(self, course_url: str) -> Dict:
        """Scrape detailed course information from Couponami course page"""
        details = {
            'language': None,
            'publisher': None,
            'rate': None,
            'enroll': None,
            'price': None
        }
        
        try:
            response = requests.get(course_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            # Try lxml parser first, fallback to html.parser if lxml fails
            try:
                soup = BeautifulSoup(response.text, 'lxml')
            except Exception as e:
                logger.warning(f"lxml parser failed for course details, trying html.parser: {e}")
                soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all text that might contain these details
            page_text = soup.get_text()
            
            # Extract Language
            lang_match = re.search(r'Language\s*:\s*(\w+)', page_text, re.IGNORECASE)
            if lang_match:
                details['language'] = lang_match.group(1)
            
            # Extract Publisher
            pub_match = re.search(r'Publisher\s*:\s*([^\n]+)', page_text, re.IGNORECASE)
            if pub_match:
                details['publisher'] = pub_match.group(1).strip()
            
            # Extract Rate
            rate_match = re.search(r'Rate\s*:\s*([\d.]+)', page_text, re.IGNORECASE)
            if rate_match:
                details['rate'] = rate_match.group(1)
            
            # Extract Enroll count
            enroll_match = re.search(r'Enroll\s*:\s*([\d,]+)', page_text, re.IGNORECASE)
            if enroll_match:
                details['enroll'] = enroll_match.group(1)
            
            # Extract Price (original -> current)
            price_match = re.search(r'Price\s*:\s*\$?([\d,]+)\s*->\s*\$?([\d,]+)', page_text, re.IGNORECASE)
            if price_match:
                original_price = price_match.group(1)
                current_price = price_match.group(2)
                details['price'] = f"${original_price} -> ${current_price}"
            
            # Try alternative selectors if regex didn't work
            if not details['language']:
                lang_elem = soup.find(string=re.compile(r'Language', re.I))
                if lang_elem:
                    parent = lang_elem.parent
                    if parent:
                        lang_text = parent.get_text()
                        match = re.search(r'Language\s*:\s*(\w+)', lang_text, re.I)
                        if match:
                            details['language'] = match.group(1)
            
            if not details['publisher']:
                pub_elem = soup.find(string=re.compile(r'Publisher', re.I))
                if pub_elem:
                    parent = pub_elem.parent
                    if parent:
                        pub_text = parent.get_text()
                        match = re.search(r'Publisher\s*:\s*([^\n]+)', pub_text, re.I)
                        if match:
                            details['publisher'] = match.group(1).strip()
            
            logger.debug(f"Scraped course details: {details}")
            
        except Exception as e:
            logger.warning(f"Could not get course details from {course_url}: {e}")
        
        return details
    
    def get_udemy_course_info(self, coupon_link: str, recursion_depth: int = 0) -> Dict:
        """Follow the coupon link to get the actual Udemy course URL with coupon code"""
        # Prevent infinite recursion
        if recursion_depth > 3:
            logger.warning(f"Max recursion depth reached for: {coupon_link}")
            return {}
        
        if not coupon_link or not isinstance(coupon_link, str):
            return {}
        
        try:
            session = requests.Session()
            
            # For couponami.com/go/ links, follow redirects to get Udemy URL
            if '/go/' in coupon_link:
                logger.info(f"Following redirect chain from: {coupon_link}")
                
                # Follow redirects with allow_redirects=True to get final URL
                response = session.get(coupon_link, headers=self.headers, timeout=self.timeout, allow_redirects=True)
                
                # Check if final URL is Udemy
                final_url = response.url
                if 'udemy.com' in final_url:
                    logger.info(f"Found Udemy URL: {final_url}")
                    return {'udemy_url': final_url}
                
                # If not directly redirected, check the page content
                try:
                    soup = BeautifulSoup(response.text, 'lxml')
                except Exception as e:
                    logger.warning(f"lxml parser failed, trying html.parser: {e}")
                    soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for Udemy links in the page
                udemy_links = soup.find_all('a', href=re.compile(r'udemy\.com'))
                for link in udemy_links:
                    href = link.get('href', '')
                    if 'udemy.com' in href and 'couponCode=' in href:
                        # Found link with coupon code
                        if href.startswith('/'):
                            href = "https://www.udemy.com" + href
                        elif not href.startswith('http'):
                            href = "https://" + href
                        logger.info(f"Found Udemy URL with coupon: {href}")
                        return {'udemy_url': href}
                    elif 'udemy.com' in href:
                        # Found Udemy link without coupon code, use it anyway
                        if href.startswith('/'):
                            href = "https://www.udemy.com" + href
                        elif not href.startswith('http'):
                            href = "https://" + href
                        logger.info(f"Found Udemy URL: {href}")
                        return {'udemy_url': href}
                
                # Try to find button or form that contains the link
                buttons = soup.find_all('button') + soup.find_all('a', class_=re.compile(r'button|btn|get|course'))
                for btn in buttons:
                    onclick = btn.get('onclick', '')
                    if 'udemy.com' in onclick:
                        # Extract URL from onclick
                        match = re.search(r'https?://[^\s\'"]*udemy\.com[^\s\'"]*', onclick)
                        if match:
                            logger.info(f"Found Udemy URL in button: {match.group()}")
                            return {'udemy_url': match.group()}
            
            # For regular couponami course pages (not /go/ links)
            else:
                response = session.get(coupon_link, headers=self.headers, timeout=self.timeout, allow_redirects=True)
                try:
                    soup = BeautifulSoup(response.text, 'lxml')
                except Exception as e:
                    logger.warning(f"lxml parser failed, trying html.parser: {e}")
                    soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for "Get Course" button or similar
                get_button = soup.find('a', href=re.compile(r'/go/'))
                if get_button:
                    go_link = get_button.get('href', '')
                    if go_link:
                        if go_link.startswith('/'):
                            # Handle both couponami.com and discudemy.com
                            if 'discudemy.com' in COUPONAMI_URL:
                                go_link = "https://www.discudemy.com" + go_link
                            else:
                                go_link = "https://www.couponami.com" + go_link
                        # Recursively follow the /go/ link with recursion depth tracking
                        return self.get_udemy_course_info(go_link, recursion_depth + 1)
                
                # Look for direct Udemy links
                udemy_links = soup.find_all('a', href=re.compile(r'udemy\.com'))
                for link in udemy_links:
                    href = link.get('href', '')
                    if 'udemy.com' in href:
                        if href.startswith('/'):
                            href = "https://www.udemy.com" + href
                        elif not href.startswith('http'):
                            href = "https://" + href
                        logger.info(f"Found Udemy URL: {href}")
                        return {'udemy_url': href}
            
            return {}
        except Exception as e:
            logger.warning(f"Could not get Udemy URL from {coupon_link}: {e}")
            return {}
    
    def scrape_all(self) -> List[Dict]:
        """Scrape from all available sources"""
        all_courses = []
        
        # Scrape Couponami (formerly DiscUdemy)
        couponami_courses = self.scrape_couponami()
        all_courses.extend(couponami_courses)
        
        logger.info(f"Found {len(all_courses)} free courses")
        return all_courses

# ============================================================================
# TELEGRAM BOT CLASS
# ============================================================================

class TelegramChannelPoster:
    """Handles posting courses to Telegram channel"""
    
    def __init__(self, bot_token: str, channel_id: str):
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id
    
    def format_course_message(self, course: Dict) -> str:
        """Format course information as a Telegram message"""
        title = course.get('title', 'Free Udemy Course')
        coupon_link = course.get('coupon_link', '')
        udemy_url = course.get('udemy_url', '')
        
        # Escape HTML entities in title to prevent parsing issues
        title = html.escape(str(title))
        
        # Course details
        language = course.get('language')
        publisher = course.get('publisher')
        rate = course.get('rate')
        enroll = course.get('enroll')
        
        message = f"🎓 <b>{title}</b>\n\n"
        
        # Course details section - only show if available
        message += "📋 <b>Course Details:</b>\n"
        if language:
            message += f"🌐 <b>Language:</b> {html.escape(str(language))}\n"
        if publisher:
            message += f"👤 <b>Publisher:</b> {html.escape(str(publisher))}\n"
        if rate:
            message += f"⭐ <b>Rate:</b> {html.escape(str(rate))}\n"
        if enroll:
            message += f"👥 <b>Enroll:</b> {html.escape(str(enroll))}\n"
        
        message += "\n"
        
        if udemy_url:
            message += f"🔗 <b>Get Course:</b> {udemy_url}\n"
        else:
            message += f"🔗 <b>Get Course:</b> {coupon_link}\n"
        
        message += "\n⏰ <i>Limited time offer! Enroll now before it expires.</i>\n"
        message += "\n#DIU #Udemy #FreeCourse"
        
        return message
    
    async def post_course(self, course: Dict) -> bool:
        """Post a course to the Telegram channel"""
        try:
            message = self.format_course_message(course)
            thumbnail = course.get('thumbnail')
            
            if thumbnail:
                try:
                    # Try to send photo with caption
                    await self.bot.send_photo(
                        chat_id=self.channel_id,
                        photo=thumbnail,
                        caption=message,
                        parse_mode='HTML'
                    )
                    logger.info(f"Posted course with thumbnail: {course.get('title', 'Unknown')[:50]}...")
                    return True
                except TelegramError as e:
                    logger.warning(f"Failed to send photo, trying text only: {e}")
            
            # Fallback to text message if photo fails
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='HTML'
            )
            logger.info(f"Posted course as text: {course.get('title', 'Unknown')[:50]}...")
            return True
            
        except TelegramError as e:
            logger.error(f"Telegram error posting course: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error posting course: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """Test if bot can send messages to the channel"""
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text="🤖 <b>Udemy Free Courses Bot is now active!</b>\n\nI'll post free Udemy courses here regularly. Stay tuned!",
                parse_mode='HTML'
            )
            logger.info("Successfully tested bot connection")
            return True
        except Exception as e:
            logger.error(f"Failed to test bot connection: {e}")
            logger.error("Make sure your bot is added as an admin to the channel!")
            return False

# ============================================================================
# MAIN BOT CLASS
# ============================================================================

class UdemyCoursesBot:
    """Main bot class that orchestrates scraping and posting"""
    
    def __init__(self):
        self.scraper = UdemyScraper(timeout=REQUEST_TIMEOUT)
        self.db = CourseDatabase(db_path=DB_PATH)
        self.telegram = TelegramChannelPoster(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID)
        self.scheduler = AsyncIOScheduler()
        self.application = None
    
    async def process_courses(self):
        """Fetch new courses and post them to Telegram one by one"""
        logger.info("Starting course scraping and posting process...")
        logger.info("=" * 60)
        logger.info("HOW DUPLICATE DETECTION WORKS:")
        logger.info("1. Bot scrapes courses from https://www.couponami.com/all")
        logger.info("2. For each course, checks database using coupon_link")
        logger.info("3. Also checks by Udemy course slug (even if coupon link differs)")
        logger.info("4. Only NEW courses (not in database) are posted")
        logger.info("5. Each posted course is saved to database to prevent future duplicates")
        logger.info("=" * 60)
        
        try:
            # Scrape free courses from couponami.com/all
            logger.info(f"🔍 Scraping {COUPONAMI_URL} for new courses...")
            courses = self.scraper.scrape_all()
            
            if not courses:
                logger.warning("❌ No courses found during scraping")
                return
            
            logger.info(f"✅ Found {len(courses)} total courses from scraper")
            
            # Filter out already posted courses
            new_courses = []
            duplicate_count = 0
            
            for course in courses:
                coupon_link = course.get('coupon_link', '')
                course_title = course.get('title', '')
                
                # First, try to get Udemy URL to check for duplicates more accurately
                udemy_url = None
                if coupon_link:
                    try:
                        udemy_info = self.scraper.get_udemy_course_info(coupon_link)
                        if udemy_info.get('udemy_url'):
                            udemy_url = udemy_info['udemy_url']
                            course['udemy_url'] = udemy_url
                    except Exception as e:
                        logger.warning(f"Could not get Udemy URL for duplicate check: {e}")
                
                # Check if already posted (by coupon_link, udemy_url, or course_title)
                if self.db.is_posted(coupon_link, udemy_url, course_title):
                    duplicate_count += 1
                    logger.info(f"⏭️  SKIPPED (duplicate): {course_title[:50]}...")
                    continue
                
                # This is a NEW course - add to list
                new_courses.append(course)
                logger.info(f"✨ NEW course detected: {course.get('title', 'Unknown')[:50]}...")
            
            logger.info(f"📊 Summary: {len(new_courses)} new courses, {duplicate_count} duplicates skipped")
            
            if not new_courses:
                logger.info("✅ No new courses to post. All courses already posted.")
                return
            
            # Post new courses one by one
            posted_count = 0
            failed_count = 0
            
            for course in new_courses:
                coupon_link = course.get('coupon_link', '')
                course_title = course.get('title', 'Unknown')
                
                try:
                    # Get course details if missing (for /go/ links, get from the course page)
                    if not course.get('language') and '/go/' not in coupon_link:
                        logger.debug(f"📋 Getting details for: {course_title[:50]}...")
                        course_details = self.scraper.get_course_details(coupon_link)
                        if course_details.get('language'):
                            course['language'] = course_details.get('language')
                        if course_details.get('publisher'):
                            course['publisher'] = course_details.get('publisher')
                        if course_details.get('rate'):
                            course['rate'] = course_details.get('rate')
                        if course_details.get('enroll'):
                            course['enroll'] = course_details.get('enroll')
                    
                    # Post to Telegram channel
                    logger.info(f"📤 Posting to channel: {course_title[:50]}...")
                    success = await self.telegram.post_course(course)
                    
                    if success:
                        # Mark as posted in database (this prevents future duplicates)
                        self.db.mark_posted(
                            course_title=course_title,
                            coupon_link=coupon_link,
                            udemy_url=course.get('udemy_url'),
                            source=course.get('source')
                        )
                        posted_count += 1
                        logger.info(f"✅ Posted #{posted_count}: {course_title[:50]}...")
                        
                        # Add delay between posts to avoid rate limiting
                        await asyncio.sleep(2)
                    else:
                        failed_count += 1
                        logger.error(f"❌ Failed to post: {course_title[:50]}...")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"❌ Error posting course '{course_title[:50]}...': {e}", exc_info=True)
                    continue
            
            logger.info("=" * 60)
            logger.info(f"📊 FINAL SUMMARY:")
            logger.info(f"   Total scraped: {len(courses)}")
            logger.info(f"   Duplicates skipped: {duplicate_count}")
            logger.info(f"   New courses found: {len(new_courses)}")
            logger.info(f"   Successfully posted: {posted_count}")
            logger.info(f"   Failed: {failed_count}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"❌ Error in process_courses: {e}", exc_info=True)
    
    async def handle_test_command(self, update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /test command - scrape and post N recent courses from couponami.com/all"""
        logger.info("/test command received")
        
        try:
            # Delete the command message instantly
            try:
                await update.message.delete()
            except Exception as e:
                logger.warning(f"Could not delete command message: {e}")
            
            # Get number from command (default to 10 if not specified)
            num_courses = 10
            if context.args and len(context.args) > 0:
                try:
                    num_courses = int(context.args[0])
                    if num_courses < 1:
                        num_courses = 1
                    if num_courses > 50:
                        num_courses = 50  # Limit to 50 max
                except ValueError:
                    num_courses = 10
            
            logger.info(f"Scraping for {num_courses} courses...")
            
            # Scrape fresh courses from couponami.com/all
            try:
                courses = self.scraper.scrape_all()
            except Exception as e:
                logger.error(f"Error scraping courses: {e}", exc_info=True)
                return
            
            if not courses:
                logger.warning("No courses found for /test command")
                return
            
            logger.info(f"Found {len(courses)} courses from scraper")
            
            # /test command: Allow posting duplicates (old posts)
            # Simply take first N courses without any duplicate checking
            courses_to_post = courses[:num_courses]
            
            logger.info(f"Selected {len(courses_to_post)} courses to post (duplicates allowed for /test)")
            
            if not courses_to_post:
                logger.warning("No courses to post for /test command")
                return
            
            logger.info(f"Posting {len(courses_to_post)} courses to channel...")
            
            # Post each course to the channel silently (no status messages)
            posted_count = 0
            for idx, course in enumerate(courses_to_post, 1):
                try:
                    coupon_link = course.get('coupon_link', '')
                    course_title = course.get('title', 'Unknown')
                    
                    logger.info(f"[{idx}/{len(courses_to_post)}] Processing: {course_title[:50]}...")
                    
                    # Get course details if missing
                    if not course.get('language') and '/go/' not in coupon_link:
                        try:
                            course_details = self.scraper.get_course_details(coupon_link)
                            if course_details.get('language'):
                                course['language'] = course_details.get('language')
                            if course_details.get('publisher'):
                                course['publisher'] = course_details.get('publisher')
                            if course_details.get('rate'):
                                course['rate'] = course_details.get('rate')
                            if course_details.get('enroll'):
                                course['enroll'] = course_details.get('enroll')
                        except Exception as e:
                            logger.warning(f"Could not get course details: {e}")
                    
                    # Get Udemy course URL (only once, before posting)
                    if coupon_link:
                        if not course.get('udemy_url'):
                            try:
                                udemy_info = self.scraper.get_udemy_course_info(coupon_link)
                                if udemy_info.get('udemy_url'):
                                    course['udemy_url'] = udemy_info['udemy_url']
                            except Exception as e:
                                logger.warning(f"Could not get Udemy URL: {e}")
                    
                    # Post to channel
                    success = await self.telegram.post_course(course)
                    if success:
                        # Only mark as posted if not already in database (avoid unnecessary DB writes)
                        # But don't skip posting - /test allows reposting
                        if coupon_link and not self.db.is_posted(coupon_link):
                            self.db.mark_posted(
                                course_title=course_title,
                                coupon_link=coupon_link,
                                udemy_url=course.get('udemy_url'),
                                source=course.get('source')
                            )
                        posted_count += 1
                        logger.info(f"✅ Posted [{posted_count}/{len(courses_to_post)}]: {course_title[:50]}...")
                    else:
                        logger.error(f"❌ Failed to post: {course_title[:50]}...")
                    
                    # Delay between posts
                    if idx < len(courses_to_post):
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    logger.error(f"Error processing course: {e}", exc_info=True)
                    continue
            
            logger.info(f"/test command completed - posted {posted_count}/{len(courses_to_post)} courses")
            
        except Exception as e:
            logger.error(f"Error handling /test command: {e}", exc_info=True)
    
    async def handle_test_scrape_command(self, update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /test_scrape command - scrape and post 1 fresh course to test functionality"""
        logger.info("/test_scrape command received")
        
        try:
            # Delete the command message
            try:
                await update.message.delete()
            except Exception as e:
                logger.warning(f"Could not delete command message: {e}")
            
            # Send result directly (not as reply)
            status_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🔍 Scraping for a free course to test..."
            )
            
            # Scrape fresh courses
            courses = self.scraper.scrape_all()
            
            if not courses:
                await status_msg.edit_text("❌ No free courses found. Please try again later.")
                logger.warning("No courses found during /test_scrape")
                return
            
            # Take the first course
            test_course = courses[0]
            
            # Try to get Udemy course URL
            logger.info(f"Getting Udemy URL for test course: {test_course.get('title', 'Unknown')}")
            udemy_info = self.scraper.get_udemy_course_info(test_course.get('coupon_link', ''))
            if udemy_info.get('udemy_url'):
                test_course['udemy_url'] = udemy_info['udemy_url']
            
            # Show course details for verification
            course_info = f"📝 Course Details:\n"
            course_info += f"Title: {test_course.get('title', 'N/A')}\n"
            course_info += f"Thumbnail: {'✅ Yes' if test_course.get('thumbnail') else '❌ No'}\n"
            course_info += f"Coupon Link: {'✅ Yes' if test_course.get('coupon_link') else '❌ No'}\n"
            course_info += f"Udemy URL: {'✅ Yes' if test_course.get('udemy_url') else '⚠️ Will use coupon link'}\n\n"
            course_info += "Posting to channel now..."
            
            await status_msg.edit_text(course_info)
            
            # Post to channel
            success = await self.telegram.post_course(test_course)
            
            if success:
                # Mark as posted
                self.db.mark_posted(
                    course_title=test_course.get('title', ''),
                    coupon_link=test_course.get('coupon_link', ''),
                    udemy_url=test_course.get('udemy_url'),
                    source=test_course.get('source')
                )
                await status_msg.edit_text("✅ Test course posted successfully! Check your channel to verify:\n- Thumbnail image\n- Course title\n- Course link\n- Formatted message")
                logger.info(f"/test_scrape completed - posted test course: {test_course.get('title', 'Unknown')[:50]}...")
            else:
                await status_msg.edit_text("❌ Failed to post course. Check logs for details.")
                logger.error("Failed to post test course")
            
        except Exception as e:
            logger.error(f"Error handling /test_scrape command: {e}", exc_info=True)
            try:
                await status_msg.edit_text(f"❌ Error: {str(e)}")
            except:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Error: {str(e)}"
                )
    
    async def handle_test_sample_command(self, update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /test_sample command - post a sample course to test posting functionality"""
        logger.info("/test_sample command received")
        
        try:
            # Delete the command message
            try:
                await update.message.delete()
            except Exception as e:
                logger.warning(f"Could not delete command message: {e}")
            
            # Create a sample test course
            sample_course = {
                'title': 'Sample Free Udemy Course - Testing Bot Functionality',
                'coupon_link': 'https://www.udemy.com/course/sample-course',
                'udemy_url': 'https://www.udemy.com/course/sample-course',
                'thumbnail': 'https://img-c.udemycdn.com/course/240x135/placeholder.jpg',  # Placeholder thumbnail
                'source': 'test'
            }
            
            # Send result directly (not as reply)
            status_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🧪 Posting sample test course to verify functionality..."
            )
            
            # Post to channel
            success = await self.telegram.post_course(sample_course)
            
            if success:
                await status_msg.edit_text(
                    "✅ Sample course posted!\n\n"
                    "Please check your channel and verify:\n"
                    "✓ Thumbnail image appears\n"
                    "✓ Course title is displayed\n"
                    "✓ Course link is clickable\n"
                    "✓ Message formatting looks good\n\n"
                    "If all items are visible, the bot is working correctly!"
                )
                logger.info("/test_sample completed - sample course posted")
            else:
                await status_msg.edit_text("❌ Failed to post sample course. Check logs for details.")
                
        except Exception as e:
            logger.error(f"Error handling /test_sample command: {e}", exc_info=True)
            try:
                await status_msg.edit_text(f"❌ Error: {str(e)}")
            except:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Error: {str(e)}"
                )
    
    async def start(self):
        """Start the bot and scheduler"""
        logger.info("Starting Udemy Free Courses Bot...")
        
        # Set up Telegram Application for command handling
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add command handlers
        self.application.add_handler(CommandHandler("test", self.handle_test_command))
        self.application.add_handler(CommandHandler("test_scrape", self.handle_test_scrape_command))
        self.application.add_handler(CommandHandler("test_sample", self.handle_test_sample_command))
        
        # Start polling for commands
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        # Test Telegram connection
        logger.info("Testing Telegram connection...")
        if not await self.telegram.test_connection():
            logger.error("Failed to connect to Telegram. Please check your bot token and channel ID.")
            sys.exit(1)
        
        # Run immediately once
        await self.process_courses()
        
        # Schedule recurring runs every 5 minutes
        self.scheduler.add_job(
            self.process_courses,
            trigger=IntervalTrigger(minutes=SCRAPE_INTERVAL_MINUTES),
            id='scrape_and_post',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info(f"Bot started. Will check for new courses every {SCRAPE_INTERVAL_MINUTES} minutes from {COUPONAMI_URL}.")
        logger.info("Bot is now listening for /test commands.")
        logger.info("Press Ctrl+C to stop the bot.")
        
        try:
            # Keep the script running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            self.scheduler.shutdown()
            logger.info("Bot stopped.")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def main():
    """Main entry point"""
    # Validate configuration
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set your TELEGRAM_BOT_TOKEN at the top of bot.py")
        sys.exit(1)
    
    if TELEGRAM_CHANNEL_ID == "@your_channel":
        logger.error("Please set your TELEGRAM_CHANNEL_ID at the top of bot.py")
        sys.exit(1)
    
    bot = UdemyCoursesBot()
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
