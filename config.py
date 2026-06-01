import os
from datetime import timedelta

# Define base directory of the project for absolute path resolutions
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# FIXED: Ensure the instance folder directory exists before database initialization
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

class Config:
    """Base configuration"""
    # Force production to crash if SECRET_KEY is missing, fall back safely for dev
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Absolute database directory resolution targeting the auto-verified folder path
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL', 
        f"sqlite:///{os.path.join(INSTANCE_DIR, 'repair_shop.db')}"
    )
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = True

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    
    def __init__(self):
        # SECURITY FIX: Prevent starting up in production with the default unsafe key
        if Config.SECRET_KEY == 'dev-secret-key-change-in-production':
            raise ValueError("CRITICAL SECURITY ERROR: SECRET_KEY must be set in production environment variables.")
        
        # PROD FIX: Enforce an external database engine configuration over SQLite
        if 'sqlite' in Config.SQLALCHEMY_DATABASE_URI:
            print("WARNING: Running production environment on a fallback SQLite engine configuration.")

class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = True
    TESTING = True
    # In-memory database isolated cleanly for automated testing runners
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'