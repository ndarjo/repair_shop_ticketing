import os
from datetime import timedelta
import logging
from dotenv import load_dotenv, find_dotenv

# Load environment variables from env.local file as early as possible
load_dotenv(find_dotenv('env.local'))

# Define base directory of the project for absolute path resolutions
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# FIXED: Ensure the instance folder directory exists before database initialization
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

# Ensure logs directory exists
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Ensure backups directory exists
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
os.makedirs(BACKUP_DIR, exist_ok=True)

# Ensure static uploads directory exists for logos and dynamic assets
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Ensure subdirectory for shop logos exists
LOGOS_DIR = os.path.join(UPLOAD_DIR, 'logos')
os.makedirs(LOGOS_DIR, exist_ok=True)

class Config:
    """Base configuration"""
    # SECURITY: Use a strong secret key for session signing
    # Force production to crash if SECRET_KEY is missing, fall back safely for dev
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    # SECURITY: Salt for blind indexing. Separate from SECRET_KEY so session rotation 
    # doesn't break database searchability.
    BLIND_INDEX_SALT = os.getenv('BLIND_INDEX_SALT', SECRET_KEY)

    # GDPR/Security: Key for PII encryption at rest (Customer phone/address)
    # In production, this MUST be a 32-byte Base64-encoded key
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '39iJ2h3vR5uY8_a1zX-9kL0mN2pQ4rS6tU8vW0xY2zA=')
    
    # Absolute database directory resolution targeting the auto-verified folder path
    # Primarily uses DATABASE_URL; otherwise constructs it from individual components
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        db_user = os.getenv('DB_USER', 'postgres')
        db_pass = os.getenv('DB_PASSWORD', '')
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'repair_shop')
        SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}" # type: ignore
    
    # SECURITY FIX: Mask the database password in console logs to prevent credential leakage
    try:
        from sqlalchemy.engine import make_url
        masked_uri = make_url(SQLALCHEMY_DATABASE_URI).render_as_string(hide_password=True)
        print(f"DEBUG: Using SQLALCHEMY_DATABASE_URI: {masked_uri}")
    except Exception:
        print("DEBUG: SQLALCHEMY_DATABASE_URI is set (Password Hidden)")

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SECURITY: Absolute session timeout (24 hours)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_REFRESH_EACH_REQUEST = False

    # Internationalization settings
    # Master mapping of language codes to display names.
    # The app will only show languages that have a compiled .mo file in the translations/ folder.
    SUPPORTED_LANGUAGES = {
        'en': 'English',
        'id': 'Bahasa Indonesia',
        'es': 'Español',
        'pl': 'Polski',
        'bg': 'Български',
        'hr': 'Hrvatski',
        'fr': 'Français',
        'de': 'Deutsch',
        'it': 'Italiano',
        'pt': 'Português',
        'ru': 'Русский',
        'ja': '日本語',
        'zh': '中文'
    }
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_TRANSLATION_DIRECTORIES = 'translations'

    # SECURITY: Limit file upload size (e.g., 2MB for logos/assets)
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024

    BACKUP_DIR = BACKUP_DIR
    UPLOAD_DIR = UPLOAD_DIR
    LOGOS_DIR = LOGOS_DIR

    # Scheduler Configuration
    BACKUP_HOUR = int(os.getenv('BACKUP_HOUR', 2))
    BACKUP_MINUTE = int(os.getenv('BACKUP_MINUTE', 0))

    # SECURITY: Session Cookie protections
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Logging Configuration
    LOG_FILE = os.path.join(LOG_DIR, 'repair_shop.log')
    LOG_LEVEL = logging.INFO
    LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    
    # Optional: External logging aggregation (e.g. Logstash/Drain)
    LOG_AGGREGATION_URI = os.getenv('LOG_AGGREGATION_URI')

    # Flask-Limiter Configuration
    # Use Redis for production-ready rate limiting
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    
    # Enforce secure cookies in production by default (overridable for LAN/HTTP usage)
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'

    # SECURITY: Fail-fast checks performed at load time to ensure production safety
    if os.getenv('FLASK_CONFIG') == 'production':
        if os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production') == 'dev-secret-key-change-in-production':
            raise ValueError("CRITICAL SECURITY ERROR: SECRET_KEY must be set in production.")

        if os.getenv('ENCRYPTION_KEY', '39iJ2h3vR5uY8_a1zX-9kL0mN2pQ4rS6tU8vW0xY2zA=') == '39iJ2h3vR5uY8_a1zX-9kL0mN2pQ4rS6tU8vW0xY2zA=':
            raise ValueError("CRITICAL SECURITY ERROR: ENCRYPTION_KEY must be set in production.")

        # Ensure database is not running without a password in production
        if not os.getenv('DB_PASSWORD') and not os.getenv('DATABASE_URL'):
            logging.warning("SECURITY: DB_PASSWORD is empty. Ensure PostgreSQL is using peer auth or local trust.")

        if Config.SQLALCHEMY_DATABASE_URI and 'sqlite' in Config.SQLALCHEMY_DATABASE_URI:
            logging.warning("Running production environment on a fallback SQLite engine configuration.")

class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    # PostgreSQL is recommended for tests to support to_char() and other PG-specific functions
    SQLALCHEMY_DATABASE_URI = os.getenv('TEST_DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        t_user = os.getenv('DB_USER', 'postgres')
        t_host = os.getenv('DB_HOST', 'localhost')
        t_name = os.getenv('TEST_DB_NAME', 'repair_shop_test')
        # Construct dynamically to avoid hardcoded sensitive patterns
        SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg://{t_user}@{t_host}/{t_name}"